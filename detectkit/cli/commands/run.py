"""
Implementation of 'dtk run' command.

Executes metric processing pipeline.
"""

import contextlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import click

from detectkit.cli._output import echo_noop
from detectkit.config.metric_config import MetricConfig, resolve_source_profile
from detectkit.config.profile import ProfilesConfig
from detectkit.config.project_config import ProjectConfig
from detectkit.config.validator import (
    discover_metric_files,
    is_discoverable_metric_file,
    validate_metric_uniqueness,
)
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.orchestration.error_dispatch import dispatch_project_error_alert
from detectkit.orchestration.task_manager import PipelineStep, TaskManager, TaskStatus
from detectkit.utils.datetime_utils import now_utc_naive

# Wall-clock format for the --json summary's started_at/finished_at fields.
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def run_command(
    select: str,
    exclude: str | None,
    steps: str,
    from_date: str | None,
    to_date: str | None,
    full_refresh: bool,
    force: bool,
    profile: str | None,
    report_path: str | None = None,
    json_output: bool = False,
) -> int:
    """
    Execute metric processing pipeline.

    Args:
        select: Metric selector (name, path, or tag)
        exclude: Metrics to exclude (name, path, or tag)
        steps: Comma-separated pipeline steps
        from_date: Start date string
        to_date: End date string
        full_refresh: Delete and reload all data
        force: Ignore task locks
        profile: Profile name to use
        report_path: When not None, emit an HTML report per metric after its
            run. "" → default location (reports/<metric>.html); a directory →
            <dir>/<metric>.html; a .html path → that file.
        json_output: When True, emit a machine-readable JSON run summary on
            the real stdout and reroute every human-readable line (this
            command's own plus everything the pipeline echoes downstream) to
            stderr instead.

    Returns:
        The process exit code: 0 on success, 1 if a startup step failed, the
        selector matched no metrics, any metric failed, or the run aborted.
    """
    # Parsing failures raise click.BadParameter (a usage error) regardless of
    # --json — they happen before there is a run to summarize.
    step_list = parse_steps(steps)
    from_dt = parse_date(from_date) if from_date else None
    to_dt = parse_date(to_date) if to_date else None

    started_at = now_utc_naive()
    summary = _new_summary(select, exclude, step_list, started_at)

    if not json_output:
        rc = _run_impl(
            select=select,
            exclude=exclude,
            step_list=step_list,
            from_dt=from_dt,
            to_dt=to_dt,
            full_refresh=full_refresh,
            force=force,
            profile=profile,
            report_path=report_path,
            summary=summary,
        )
        _finish_summary(summary, started_at, rc)
        return rc

    # click.echo resolves sys.stdout dynamically (it looks it up on every
    # call), so redirecting stdout to stderr for the duration of the run
    # reroutes every click.echo the pipeline makes — not just this module's —
    # leaving the real stdout free for the one JSON document below.
    rc = 1
    caught: BaseException | None = None
    with contextlib.redirect_stdout(sys.stderr):
        try:
            rc = _run_impl(
                select=select,
                exclude=exclude,
                step_list=step_list,
                from_dt=from_dt,
                to_dt=to_dt,
                full_refresh=full_refresh,
                force=force,
                profile=profile,
                report_path=report_path,
                summary=summary,
            )
        except BaseException as exc:
            # A consumer parsing stdout must get the one JSON document even
            # when the run dies unexpectedly (including Ctrl+C) — emit it
            # first, then let the exception propagate for the usual traceback.
            caught = exc
            if not summary["error"]:
                summary["error"] = f"{type(exc).__name__}: {exc}"
    _finish_summary(summary, started_at, rc)
    click.echo(json.dumps(summary))
    if caught is not None:
        raise caught
    return rc


def _new_summary(
    select: str,
    exclude: str | None,
    step_list: list[PipelineStep],
    started_at: datetime,
) -> dict[str, Any]:
    """The mutable JSON-summary collector, seeded with the run's static inputs."""
    return {
        "schema_version": 1,
        "command": "run",
        "project": None,
        "selector": select,
        "exclude": exclude,
        "steps": [s.value for s in step_list],
        "started_at": started_at.strftime(_TIMESTAMP_FORMAT),
        "finished_at": None,
        "duration_seconds": None,
        "status": "success",
        "error": None,
        "aborted": False,
        "metrics": [],
        "totals": {
            "metrics": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "datapoints_loaded": 0,
            "anomalies_detected": 0,
            "alerts_sent": 0,
        },
        "exit_code": 0,
    }


def _status_str(status: Any) -> str:
    """Normalize a ``TaskStatus`` (or an already-plain string) to its plain string value.

    ``TaskManager.run_metric`` reports status via the ``TaskStatus`` str-enum;
    ``process_metric``'s own synthesized failure dict uses a plain string. Both
    must render identically in the JSON summary.
    """
    return status.value if isinstance(status, TaskStatus) else str(status)


def _skipped_metric_entry(name: str) -> dict[str, Any]:
    """A JSON-summary entry for a metric the run did not process.

    Shaped exactly like a processed metric's entry (the key set is part of the
    ``schema_version: 1`` contract) with every counter at zero and no error —
    a skip is a deliberate outcome, not a failure.
    """
    return {
        "name": name,
        "status": "skipped",
        "steps_completed": [],
        "datapoints_loaded": 0,
        "anomalies_detected": 0,
        "alerts_sent": 0,
        "error": None,
    }


def _refresh_disabled_registry(
    internal_manager: InternalTablesManager,
    project_config: ProjectConfig,
    disabled_metrics: list[tuple[Path, MetricConfig]],
) -> None:
    """Refresh ``_dtk_metrics`` for the metrics this run skipped.

    ``_dtk_metrics`` is the informational mirror of each metric's config and
    carries an ``enabled`` column, so a skipped metric must still refresh its
    row — otherwise the registry (and any dashboard built on it) would keep
    reporting a just-disabled metric as enabled forever. This is the *only*
    database write a disabled metric gets: no lock, no datapoints, no
    detections, no alerts. Informational, so a failure here is a warning and
    never the run's exit code.
    """
    table_override = None
    if project_config is not None and hasattr(project_config, "tables"):
        table_override = project_config.tables.metrics

    for metric_path, config in disabled_metrics:
        try:
            internal_manager.upsert_metric_config(
                metric_config=config,
                file_path=str(metric_path),
                table_name_override=table_override,
            )
        except Exception as exc:  # never fail a run over the informational mirror
            click.echo(
                click.style(
                    f"  │ Registry refresh skipped for {config.name}: {exc}",
                    fg="yellow",
                )
            )


def _finish_summary(summary: dict[str, Any], started_at: datetime, rc: int) -> None:
    """Fill in totals, timing and the final status, keyed off the per-metric entries."""
    finished_at = now_utc_naive()
    summary["finished_at"] = finished_at.strftime(_TIMESTAMP_FORMAT)
    summary["duration_seconds"] = round((finished_at - started_at).total_seconds(), 1)

    metrics = summary["metrics"]
    totals = summary["totals"]
    totals["metrics"] = len(metrics)
    totals["succeeded"] = sum(1 for m in metrics if m["status"] == "success")
    totals["failed"] = sum(1 for m in metrics if m["status"] == "failed")
    totals["skipped"] = sum(1 for m in metrics if m["status"] == "skipped")
    totals["datapoints_loaded"] = sum(m["datapoints_loaded"] for m in metrics)
    totals["anomalies_detected"] = sum(m["anomalies_detected"] for m in metrics)
    totals["alerts_sent"] = sum(m["alerts_sent"] for m in metrics)

    if summary["error"] is not None and not metrics:
        # Died before/at startup — no metric was ever processed.
        summary["status"] = "error"
    elif summary["aborted"] or totals["failed"] or summary["error"] is not None:
        # An error recorded mid-run (e.g. an exception after some metrics
        # already succeeded) is a failed run, never a "success" with an error.
        summary["status"] = "failed"
    else:
        summary["status"] = "success"
    summary["exit_code"] = rc


def _run_impl(
    *,
    select: str,
    exclude: str | None,
    step_list: list[PipelineStep],
    from_dt: datetime | None,
    to_dt: datetime | None,
    full_refresh: bool,
    force: bool,
    profile: str | None,
    report_path: str | None,
    summary: dict[str, Any],
) -> int:
    """Run the pipeline for the selected metrics, mutating *summary* as it goes.

    Returns the process exit code (0 success, 1 failure) — the actual work
    behind :func:`run_command`, factored out so the JSON-summary wrapper can
    redirect stdout around exactly this call.
    """
    # Find project root and load config
    project_root = find_project_root()
    if not project_root:
        click.echo(
            click.style(
                "Error: Not in a detectkit project directory!",
                fg="red",
                bold=True,
            )
        )
        click.echo("Run 'dtk init <project_name>' to create a new project.")
        summary["error"] = "Not in a detectkit project directory"
        return 1

    click.echo(f"Project root: {project_root}")

    # Load project config
    project_config_path = project_root / "detectkit_project.yml"
    try:
        project_config = ProjectConfig.from_yaml_file(project_config_path)
    except Exception as e:
        click.echo(
            click.style(
                f"Error loading detectkit_project.yml: {e}",
                fg="red",
                bold=True,
            )
        )
        summary["error"] = f"Error loading detectkit_project.yml: {e}"
        return 1

    summary["project"] = getattr(project_config, "name", None)

    # Select metrics based on selector
    # Returns list of (path, config) tuples with uniqueness validation
    try:
        metrics = select_metrics(select, project_root)
    except ValueError as e:
        click.echo(
            click.style(
                f"Error: {e}",
                fg="red",
                bold=True,
            )
        )
        summary["error"] = f"Error: {e}"
        return 1

    # Exclude metrics if specified
    if exclude:
        try:
            excluded_metrics = select_metrics(exclude, project_root)
            excluded_names = {config.name for _, config in excluded_metrics}
            metrics = [
                (path, config) for path, config in metrics if config.name not in excluded_names
            ]

            if excluded_metrics:
                click.echo(f"Excluded {len(excluded_metrics)} metric(s) matching: {exclude}")
        except ValueError as e:
            click.echo(
                click.style(
                    f"Error in exclusion selector: {e}",
                    fg="red",
                    bold=True,
                )
            )
            summary["error"] = f"Error in exclusion selector: {e}"
            return 1

    if not metrics:
        click.echo(
            click.style(
                f"No metrics found matching selector: {select}",
                fg="yellow",
            )
        )
        summary["error"] = f"No metrics found matching selector: {select}"
        return 1

    # `enabled: false` takes the metric out of the pipeline entirely — no load,
    # no detect, no alert, no lock. The skip happens HERE, in the runner, not in
    # discovery/`select_metrics`, for two reasons: (1) observability — a disabled
    # metric stays visible as one `•` line in the log and a `skipped` entry in
    # the --json summary instead of silently vanishing; (2) every other command
    # shares `select_metrics`, and they must keep seeing it — `dtk tune`/`dtk ui`
    # are exactly how you inspect a disabled metric to decide its fate, and its
    # `_dtk_*` rows must not read as orphaned to `dtk clean --orphaned-metrics`.
    # A skip is a config choice, never a failure: it does not affect the exit
    # code (a run whose every selected metric is disabled still exits 0).
    disabled_metrics = [(path, cfg) for path, cfg in metrics if not cfg.enabled]
    if disabled_metrics:
        metrics = [(path, cfg) for path, cfg in metrics if cfg.enabled]
        for _path, disabled_config in disabled_metrics:
            echo_noop(disabled_config.name, "disabled in config (enabled: false) — skipped")
            summary["metrics"].append(_skipped_metric_entry(disabled_config.name))

    click.echo(f"Found {len(metrics)} metric(s) to process")
    click.echo()

    # Load profiles.yml
    profiles_path = project_root / "profiles.yml"
    if not profiles_path.exists():
        click.echo(
            click.style(
                "Error: profiles.yml not found!",
                fg="red",
                bold=True,
            )
        )
        click.echo(f"Expected at: {profiles_path}")
        summary["error"] = "profiles.yml not found"
        return 1

    try:
        profiles_config = ProfilesConfig.from_yaml(profiles_path)
    except Exception as e:
        click.echo(
            click.style(
                f"Error loading profiles.yml: {e}",
                fg="red",
                bold=True,
            )
        )
        summary["error"] = f"Error loading profiles.yml: {e}"
        return 1

    # Fail-fast: every selected metric's RESOLVED source_profile (hybrid
    # mode) must name a real profile. This is a cheap name check — no
    # connections opened — so a typo'd source_profile fails the whole run
    # up front instead of surfacing deep inside whichever metric's LOAD step
    # happens to hit it first. Disabled metrics are already out of `metrics`,
    # so a typo in one of them can't fail a run that would never have used it.
    source_profile_error = _validate_source_profiles(metrics, project_config, profiles_config)
    if source_profile_error:
        # A config typo, not an outage: exit 1 without paging error_alerting,
        # consistent with the sibling config-error paths (bad selector,
        # unparseable profiles.yml). The error alert channel is reserved for
        # DB-down / DDL / runtime failures.
        click.echo(click.style(f"Error: {source_profile_error}", fg="red", bold=True))
        summary["error"] = f"Error: {source_profile_error}"
        return 1

    # Fail-fast: the STATE profile must be a state-capable type. Like the
    # source_profile check above this is a config error, not an outage —
    # exit 1 without paging error_alerting (create_manager would raise the
    # same refusal, but through the path that fires the error alert).
    state_type_error = _validate_state_profile_type(profiles_config, profile)
    if state_type_error:
        click.echo(click.style(f"Error: {state_type_error}", fg="red", bold=True))
        summary["error"] = f"Error: {state_type_error}"
        return 1

    # Create database manager
    try:
        db_manager = profiles_config.create_manager(profile)
    except Exception as e:
        click.echo(
            click.style(
                f"Error creating database manager: {e}",
                fg="red",
                bold=True,
            )
        )
        # Profiles are loaded → channels can be resolved → fire the
        # project-level error alert before bailing. Otherwise a dead DB
        # silently kills the entire run with no notification.
        dispatch_project_error_alert(
            profiles_config=profiles_config,
            project_config=project_config,
            metric_name="<startup>",
            exc=e,
        )
        summary["error"] = f"Error creating database manager: {e}"
        return 1

    # Create internal tables manager
    internal_manager = InternalTablesManager(db_manager)

    # Initialize internal tables if needed
    try:
        internal_manager.ensure_tables()
    except Exception as e:
        click.echo(
            click.style(
                f"Error initializing internal tables: {e}",
                fg="red",
                bold=True,
            )
        )
        dispatch_project_error_alert(
            profiles_config=profiles_config,
            project_config=project_config,
            metric_name="<startup>",
            exc=e,
        )
        summary["error"] = f"Error initializing internal tables: {e}"
        return 1

    # Disabled metrics run no pipeline step, but their config mirror stays
    # truthful so `_dtk_metrics.enabled` reflects the YAML that was just read.
    if disabled_metrics:
        _refresh_disabled_registry(internal_manager, project_config, disabled_metrics)

    # The active STATE profile's actual name (mirrors ProfilesConfig.get_profile's
    # own None -> default_profile resolution) — lets the task manager recognize
    # a metric's source_profile that happens to name the state profile itself,
    # and reuse db_manager instead of opening a duplicate connection.
    state_profile_name: str | None
    if profile is not None:
        state_profile_name = profile
    else:
        state_profile_name = getattr(profiles_config, "default_profile", None)

    # Create task manager
    task_manager = TaskManager(
        internal_manager=internal_manager,
        db_manager=db_manager,
        profiles_config=profiles_config,
        project_config=project_config,
        state_profile_name=state_profile_name,
    )

    try:
        # Process each metric
        for index, (metric_path, config) in enumerate(metrics):
            result = process_metric(
                metric_path=metric_path,
                config=config,
                project_root=project_root,
                task_manager=task_manager,
                steps=step_list,
                from_date=from_dt,
                to_date=to_dt,
                full_refresh=full_refresh,
                force=force,
            )
            summary["metrics"].append(
                {
                    "name": config.name,
                    "status": _status_str(result["status"]),
                    "steps_completed": [s.value for s in result["steps_completed"]],
                    "datapoints_loaded": result["datapoints_loaded"],
                    "anomalies_detected": result["anomalies_detected"],
                    "alerts_sent": result["alerts_sent"],
                    "error": result["error"],
                }
            )

            # Project-level error alert was dispatched — stop processing the
            # rest of the metrics. The DB / source is presumed unreachable;
            # subsequent metrics would all fail with the same error.
            if result.get("abort_run"):
                click.echo(
                    click.style(
                        "✗ Aborting run after project error alert. " "Remaining metrics skipped.",
                        fg="red",
                        bold=True,
                    )
                )
                summary["aborted"] = True
                for _, skipped_config in metrics[index + 1 :]:
                    summary["metrics"].append(
                        {
                            "name": skipped_config.name,
                            "status": "skipped",
                            "steps_completed": [],
                            "datapoints_loaded": 0,
                            "anomalies_detected": 0,
                            "alerts_sent": 0,
                            "error": None,
                        }
                    )
                break

            # Optional: emit a self-contained HTML report from the freshly-persisted
            # internal tables (values + bands + anomalies + replayed alerts).
            if report_path is not None:
                try:
                    emit_metric_report(
                        config=config,
                        project_root=project_root,
                        internal_manager=internal_manager,
                        report_path=report_path,
                        project_name=getattr(project_config, "name", None),
                        project_loading_delay=getattr(project_config, "loading_delay", None),
                        from_dt=from_dt,
                        to_dt=to_dt,
                    )
                except Exception as report_error:  # never fail the run on a report
                    click.echo(click.style(f"  │ Report skipped: {report_error}", fg="yellow"))

        failed = any(m["status"] == "failed" for m in summary["metrics"])
        return 1 if (failed or summary["aborted"]) else 0
    finally:
        # Close every pooled hybrid-mode SOURCE manager (never db_manager
        # itself — this function owns that connection's lifecycle, and it
        # was never explicitly closed here either, before or after hybrid
        # mode existed). Duck-typed lookup: a test double standing in for
        # TaskManager need not implement it.
        close_sources = getattr(task_manager, "close_sources", None)
        if close_sources is not None:
            close_sources()


def _validate_source_profiles(
    metrics: list[tuple[Path, MetricConfig]],
    project_config: ProjectConfig,
    profiles_config: ProfilesConfig,
) -> str | None:
    """Cheap, connection-free check that every metric's RESOLVED
    ``source_profile`` (hybrid mode) names a real profile.

    Returns an error message naming every offending metric, or ``None`` when
    every resolved name is either unset (no hybrid override) or a known
    profile. Runs before any database manager is built.
    """
    project_source_profile = getattr(project_config, "source_profile", None)
    known_profiles = getattr(profiles_config, "profiles", {}) or {}
    unknown: dict[str, str] = {}
    for _, config in metrics:
        name = resolve_source_profile(
            getattr(config, "source_profile", None), project_source_profile
        )
        if name is not None and name not in known_profiles:
            unknown[config.name] = name
    if not unknown:
        return None
    details = ", ".join(f"{m} -> '{p}'" for m, p in sorted(unknown.items()))
    available = ", ".join(sorted(known_profiles.keys()))
    return (
        f"Unknown source_profile referenced by metric(s): {details}. "
        f"Available profiles: {available}"
    )


def _validate_state_profile_type(
    profiles_config: ProfilesConfig, profile_name: str | None
) -> str | None:
    """Cheap, connection-free check that the STATE profile is state-capable.

    A source-only profile type (e.g. ``snowflake``) pointed at by
    ``--profile``/``default_profile`` is a config error, not an outage, so it
    must exit 1 *without* paging ``error_alerting`` — same spirit as the
    source_profile name check above. An unknown/unset profile name returns
    ``None`` here so the existing ``create_manager`` path reports it exactly
    as before. Duck-typed via ``getattr`` like ``_validate_source_profiles``,
    so test doubles need not model the full ProfilesConfig surface.
    """
    known_profiles = getattr(profiles_config, "profiles", {}) or {}
    name = profile_name or getattr(profiles_config, "default_profile", None)
    profile_config = known_profiles.get(name) if name else None
    if profile_config is None or not getattr(profile_config, "is_source_only", False):
        return None
    state_types = ", ".join(sorted(profile_config.STATE_TYPES))
    return (
        f"Profile type '{profile_config.type}' is source-only: it can serve "
        f"as a metric/project 'source_profile' (hybrid mode), but it cannot "
        f"hold detectkit state. Point --profile/default_profile at one of: "
        f"{state_types}."
    )


def _resolve_report_path(report_path: str, project_root: Path, metric_name: str) -> Path:
    """Map the ``--report`` value to a concrete output file for a metric.

    "" → ``<project>/reports/<metric>.html``; a ``.html`` path → that file;
    anything else → ``<dir>/<metric>.html``.
    """
    if report_path == "":
        return project_root / "reports" / f"{metric_name}.html"
    candidate = Path(report_path)
    if candidate.suffix.lower() == ".html":
        return candidate
    return candidate / f"{metric_name}.html"


def emit_metric_report(
    *,
    config: MetricConfig,
    project_root: Path,
    internal_manager: InternalTablesManager,
    report_path: str,
    project_name: str | None,
    from_dt: datetime | None,
    to_dt: datetime | None,
    project_loading_delay: str | int | None = None,
) -> None:
    """Build and write the HTML report for one metric (best-effort)."""
    from detectkit.reporting import build_report_payload, render_report_html
    from detectkit.utils.datetime_utils import now_utc_naive

    payload = build_report_payload(
        metric_config=config,
        internal=internal_manager,
        start=from_dt,
        end=to_dt,
        project_name=project_name,
        generated_at=now_utc_naive().strftime("%Y-%m-%d %H:%M UTC"),
        project_loading_delay=project_loading_delay,
    )
    if not payload["points"]:
        click.echo("  │ Report: no datapoints in window, skipped")
        return

    out = _resolve_report_path(report_path, project_root, config.name)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report_html(payload), encoding="utf-8")
    try:
        shown = out.relative_to(project_root)
    except ValueError:
        shown = out
    click.echo(
        click.style(
            f"  │ Report → {shown}  "
            f"({payload['summary']['anomalies']} anomalies, "
            f"{payload['summary']['alerts']} alerts)",
            fg="cyan",
        )
    )


def parse_steps(steps_str: str) -> list[PipelineStep]:
    """
    Parse comma-separated steps string.

    Args:
        steps_str: Comma-separated steps (e.g., "load,detect,alert")

    Returns:
        List of PipelineStep enums

    Example:
        >>> parse_steps("load,detect")
        [PipelineStep.LOAD, PipelineStep.DETECT]
    """
    step_map = {
        "load": PipelineStep.LOAD,
        "detect": PipelineStep.DETECT,
        "alert": PipelineStep.ALERT,
    }

    steps = []
    for step_str in steps_str.split(","):
        step_str = step_str.strip().lower()
        if step_str not in step_map:
            raise click.BadParameter(f"Invalid step: {step_str}. Valid steps: load, detect, alert")
        steps.append(step_map[step_str])

    return steps


def parse_date(date_str: str) -> datetime:
    """
    Parse date string to datetime.

    Supports formats:
    - YYYY-MM-DD
    - YYYY-MM-DD HH:MM:SS

    Args:
        date_str: Date string

    Returns:
        datetime object

    Raises:
        click.BadParameter: If date format is invalid
    """
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue

    raise click.BadParameter(
        f"Invalid date format: {date_str}. " f"Use YYYY-MM-DD or 'YYYY-MM-DD HH:MM:SS'"
    )


def find_project_root() -> Path | None:
    """
    Find detectkit project root by looking for detectkit_project.yml.

    Searches current directory and parent directories.

    Returns:
        Path to project root or None if not found
    """
    current = Path.cwd()

    # Search up to 10 levels up
    for _ in range(10):
        if (current / "detectkit_project.yml").exists():
            return current

        if current.parent == current:
            # Reached filesystem root
            break

        current = current.parent

    return None


def select_metrics(selector: str, project_root: Path) -> list[tuple[Path, MetricConfig]]:
    """
    Select metrics based on selector and validate uniqueness.

    Selector types:
    - Metric name: "cpu_usage" (searches by 'name' field recursively in subdirectories)
    - Path pattern: "metrics/critical/*.yml" or "league/cpu_usage"
    - Tag: "tag:critical"

    For name selector:
    1. First tries filename-based search in root metrics/ directory
    2. If not found, searches recursively by 'name' field in all subdirectories

    Args:
        selector: Selector string
        project_root: Project root path

    Returns:
        List of (path, config) tuples for selected metrics

    Raises:
        ValueError: If duplicate metric names found or configs invalid
    """
    metrics_dir = project_root / "metrics"

    if not metrics_dir.exists():
        return []

    # Collect metric paths based on selector
    metric_paths: list[Path] = []

    # Tag selector
    if selector.startswith("tag:"):
        tag = selector[4:]
        metric_paths = find_metrics_by_tag(metrics_dir, tag)
    # Path pattern selector
    elif "*" in selector or "/" in selector:
        if selector == "*":
            # "all metrics" — search recursively so nested metrics are included
            # (mirrors validate_project_metrics); a plain glob of "metrics/*"
            # would only see the top level. Excludes the metrics/.history/ archive.
            metric_paths = discover_metric_files(metrics_dir)
        else:
            pattern = selector if selector.startswith("metrics/") else f"metrics/{selector}"
            # Keep only metric files: a bare glob also matches the `.gitkeep`
            # stub created by `dtk init`, any other non-YAML files, directories, and
            # the metrics/.history/ archive dtk tune writes (whose snapshots keep the
            # original name:) — all of which would crash the parser or collide on name.
            metric_paths = [
                p for p in project_root.glob(pattern) if is_discoverable_metric_file(p, metrics_dir)
            ]
    # Metric name selector
    else:
        # First try filename-based search in root (backward compatibility)
        metric_file = metrics_dir / f"{selector}.yml"
        if metric_file.exists():
            metric_paths = [metric_file]
        else:
            # Try with .yaml extension
            metric_file = metrics_dir / f"{selector}.yaml"
            if metric_file.exists():
                metric_paths = [metric_file]
            else:
                # Fall back to recursive search by 'name' field
                found_metric = find_metric_by_name(metrics_dir, selector)
                if found_metric:
                    metric_paths = [found_metric]

    if not metric_paths:
        return []

    # Validate uniqueness and load configs
    # This will raise ValueError if duplicate metric names found
    return validate_metric_uniqueness(metric_paths)


def find_metrics_by_tag(metrics_dir: Path, tag: str) -> list[Path]:
    """
    Find all metrics with specific tag.

    Args:
        metrics_dir: Metrics directory path
        tag: Tag to search for

    Returns:
        List of metric paths with this tag
    """
    import yaml

    matching_metrics = []

    # Live metric files only (excludes the metrics/.history/ archive).
    for metric_file in discover_metric_files(metrics_dir):
        try:
            with open(metric_file) as f:
                config = yaml.safe_load(f)

            if config and "tags" in config:
                if tag in config["tags"]:
                    matching_metrics.append(metric_file)
        except Exception as e:
            # Warn about unparseable files but continue searching
            click.echo(
                click.style(
                    f"Warning: Skipping {metric_file.relative_to(metrics_dir.parent)}: {e}",
                    fg="yellow",
                ),
                err=True,
            )
            continue

    return matching_metrics


def find_metric_by_name(metrics_dir: Path, name: str) -> Path | None:
    """
    Find metric by name field (searches recursively in subdirectories).

    Args:
        metrics_dir: Metrics directory path
        name: Metric name to search for (from 'name' field in YAML)

    Returns:
        Path to metric file if found, None otherwise
    """
    import yaml

    # Live metric files only (excludes the metrics/.history/ archive).
    for metric_file in discover_metric_files(metrics_dir):
        try:
            with open(metric_file) as f:
                config = yaml.safe_load(f)

            if config and config.get("name") == name:
                return metric_file
        except Exception as e:
            # Warn about unparseable files but continue searching
            click.echo(
                click.style(
                    f"Warning: Skipping {metric_file.relative_to(metrics_dir.parent)}: {e}",
                    fg="yellow",
                ),
                err=True,
            )
            continue

    return None


def process_metric(
    metric_path: Path,
    config: MetricConfig,
    project_root: Path,
    task_manager: TaskManager,
    steps: list[PipelineStep],
    from_date: datetime | None,
    to_date: datetime | None,
    full_refresh: bool,
    force: bool,
) -> dict[str, Any]:
    """
    Process a single metric.

    Args:
        metric_path: Path to metric YAML file
        config: Loaded and validated metric configuration
        project_root: Project root directory
        task_manager: Task manager instance
        steps: Pipeline steps to execute
        from_date: Start date
        to_date: End date
        full_refresh: Full refresh flag
        force: Force flag

    Returns:
        A result dict shaped like ``TaskManager.run_metric``'s (``status``,
        ``error``, ``steps_completed``, ``datapoints_loaded``,
        ``anomalies_detected``, ``alerts_sent``, ``abort_run``) — always
        populated, even when the call raises before returning one.
    """
    # Use config.name (not metric_path.stem) for consistency
    metric_name = config.name

    click.echo(click.style(f"Processing metric: {metric_name}", fg="cyan", bold=True))
    click.echo(f"  Config file: {metric_path.relative_to(project_root)}")
    click.echo(f"  Steps: {', '.join(s.value for s in steps)}")

    if from_date:
        click.echo(f"  From: {from_date}")
    if to_date:
        click.echo(f"  To: {to_date}")
    if full_refresh:
        click.echo(click.style("  Full refresh: YES", fg="yellow"))
    if force:
        click.echo(click.style("  Force: YES (ignoring locks)", fg="yellow"))

    click.echo()

    # Run pipeline
    try:
        # Log step headers
        if PipelineStep.LOAD in steps:
            click.echo()
            click.echo(click.style("  ┌─ LOAD", fg="cyan", bold=True))

        result = task_manager.run_metric(
            config=config,
            steps=steps,
            from_date=from_date,
            to_date=to_date,
            full_refresh=full_refresh,
            force=force,
            metric_file_path=str(metric_path),
        )

        # Display results - task_manager already printed details
        click.echo()
        if result["status"] == "success":
            click.echo(click.style("✓ Pipeline completed successfully", fg="green", bold=True))
        else:
            click.echo(
                click.style(
                    f"  ✗ Failed: {result['error']}",
                    fg="red",
                    bold=True,
                )
            )

    except Exception as e:
        click.echo(
            click.style(
                f"  ✗ Pipeline error: {e}",
                fg="red",
                bold=True,
            )
        )
        import traceback

        click.echo(traceback.format_exc())
        # run_metric normally always returns a result dict (it catches its own
        # exceptions internally); this branch only guards against something
        # raising before that call returns — e.g. building the pipeline lock
        # request — so `result` is never left unbound.
        result = {
            "status": "failed",
            "error": f"{type(e).__name__}: {e}",
            "steps_completed": [],
            "datapoints_loaded": 0,
            "anomalies_detected": 0,
            "alerts_sent": 0,
            "abort_run": False,
        }

    click.echo()
    return result
