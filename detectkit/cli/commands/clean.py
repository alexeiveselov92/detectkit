"""
Implementation of 'dtk clean' command.

Removes internal data that no longer matches the project's YAML configs —
the rows left behind when an analyst edits metrics on production. Two modes:

* ``--select`` (drift mode): for metrics that still exist, delete detection
  results whose ``detector_id`` is no longer produced by the config (a
  detector param/seasonality changed, or the detector was removed) and
  alert-state rows whose ``alert_config_id`` is no longer produced (an
  alerting block changed or was removed). Datapoints are NOT touched — they
  are keyed only by (metric, timestamp) and never orphaned by a param edit;
  use ``--full-refresh`` to reload those.

* ``--orphaned-metrics`` (GC mode): delete ALL rows, across every internal
  table, for metric names present in the database but no longer defined by
  any YAML in the project (renamed or deleted metric).

Both modes default to a dry-run that only reports what would be deleted;
pass ``--execute`` to actually delete. Selector semantics match ``dtk run``.
"""

from __future__ import annotations

from pathlib import Path

import click

from detectkit.cli._output import echo_done, echo_error, echo_noop, echo_tree
from detectkit.cli.commands.run import find_project_root, select_metrics
from detectkit.config.metric_config import MetricConfig
from detectkit.config.profile import ProfilesConfig
from detectkit.config.validator import validate_project_metrics
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.detectors.factory import DetectorFactory
from detectkit.orchestration.task_manager._types import make_alert_config_id


def run_clean(
    select: str | None,
    orphaned_metrics: bool,
    execute: bool,
    yes: bool,
    profile: str | None,
):
    """Prune stale internal data that no longer matches the project configs.

    Args:
        select: Metric selector (drift mode) — same semantics as ``dtk run``.
        orphaned_metrics: GC mode — purge metrics no longer present in the project.
        execute: Actually delete (default: dry-run, only report).
        yes: Skip the confirmation prompt in GC mode.
        profile: Profile name to use (defaults to project's default_profile).
    """
    if bool(select) == bool(orphaned_metrics):
        click.echo(
            click.style(
                "Error: choose exactly one of --select or --orphaned-metrics.",
                fg="red",
                bold=True,
            )
        )
        return

    project_root = find_project_root()
    if not project_root:
        click.echo(click.style("Error: Not in a detectkit project directory!", fg="red", bold=True))
        click.echo("Run 'dtk init <project_name>' to create a new project.")
        return

    click.echo(f"Project root: {project_root}")

    internal_manager = _create_internal_manager(project_root, profile)
    if internal_manager is None:
        return

    if not execute:
        click.echo(
            click.style("DRY-RUN — nothing will be deleted. Use --execute to apply.", fg="cyan")
        )
    click.echo()

    if select:
        _clean_drift(internal_manager, select, project_root, execute)
    else:
        _clean_orphaned_metrics(internal_manager, project_root, execute, yes)


# ── modes ──────────────────────────────────────────────────────────────────


def _clean_drift(
    internal_manager: InternalTablesManager,
    select: str,
    project_root: Path,
    execute: bool,
) -> None:
    """Prune detector/alert data whose hash is no longer produced by the config."""
    try:
        metrics = select_metrics(select, project_root)
    except ValueError as e:
        click.echo(click.style(f"Error: {e}", fg="red", bold=True))
        return

    if not metrics:
        click.echo(click.style(f"No metrics found matching selector: {select}", fg="yellow"))
        return

    click.echo(f"Found {len(metrics)} metric(s) to inspect")
    click.echo()

    total_det_groups = 0
    total_alert_rows = 0

    verb = "deleting" if execute else "would delete"

    for _, config in metrics:
        metric_name = config.name
        try:
            valid_detectors = _valid_detector_ids(config)
            valid_alerts = _valid_alert_config_ids(config)
            db_detectors = internal_manager.list_detector_ids(metric_name)
            db_alerts = internal_manager.list_alert_config_ids(metric_name)
        except Exception as e:
            echo_error(metric_name, f"error inspecting: {e}")
            continue

        orphan_detectors = {
            det_id: count for det_id, count in db_detectors.items() if det_id not in valid_detectors
        }
        orphan_alerts = [a for a in db_alerts if a not in valid_alerts]

        if not orphan_detectors and not orphan_alerts:
            echo_noop(metric_name, "nothing stale")
            continue

        children = [
            f"detector {det_id}: {verb} {count:,} detection row(s)"
            for det_id, count in sorted(orphan_detectors.items())
        ] + [
            f"alert_config {alert_id}: {verb} stale alert state"
            for alert_id in sorted(orphan_alerts)
        ]

        # An empty valid set means EVERY stored row is "orphaned" — usually a
        # config mid-edit, not an intent to wipe the metric. Flag it loudly.
        warnings = []
        if orphan_detectors and not valid_detectors:
            warnings.append("config defines no detectors — ALL detections below would be removed")
        if orphan_alerts and not valid_alerts:
            warnings.append("config defines no alerting — ALL alert states below would be removed")

        echo_tree(metric_name, children, warnings=warnings)

        if execute:
            for det_id in orphan_detectors:
                internal_manager.delete_detections(
                    metric_name=metric_name, detector_id=det_id, mutations_sync=True
                )
            for alert_id in orphan_alerts:
                internal_manager.delete_alert_state(metric_name, alert_id)

        total_det_groups += len(orphan_detectors)
        total_alert_rows += len(orphan_alerts)

    verb_done = "Removed" if execute else "Would remove"
    echo_done(
        f"{verb_done} {total_det_groups} detector group(s) "
        f"and {total_alert_rows} alert-state row(s)."
    )
    if not execute and (total_det_groups or total_alert_rows):
        click.echo("Re-run with --execute to apply.")


def _clean_orphaned_metrics(
    internal_manager: InternalTablesManager,
    project_root: Path,
    execute: bool,
    yes: bool,
) -> None:
    """Purge all data for metrics present in the DB but absent from the project."""
    try:
        project_metrics = validate_project_metrics(project_root)
        project_names = {config.name for _, config in project_metrics}
    except FileNotFoundError:
        # No metrics/ directory at all — every DB metric is technically orphaned.
        project_names = set()
    except ValueError as e:
        # Duplicates / parse errors: we can't trust the project set, so refuse
        # to delete anything rather than risk purging valid metrics.
        click.echo(
            click.style(
                f"Error: cannot determine project metrics ({e}). "
                "Fix the configs first; aborting to avoid deleting valid data.",
                fg="red",
                bold=True,
            )
        )
        return

    db_names = internal_manager.list_known_metric_names()
    orphans = sorted(db_names - project_names)

    if not orphans:
        click.echo(click.style("No orphaned metrics — database matches the project.", fg="green"))
        return

    click.echo(f"Found {len(orphans)} metric(s) in the database with no YAML in the project:")
    click.echo()
    for name in orphans:
        try:
            counts = internal_manager.count_metric_rows(name)
        except Exception as e:
            echo_error(name, f"error counting rows: {e}")
            continue
        children = [f"{table}: {count:,} row(s)" for table, count in counts.items() if count]
        echo_tree(name, children or ["(no rows)"])

    if not execute:
        click.echo()
        click.echo("Re-run with --execute to purge these metrics.")
        return

    # Guard: an empty project set means --execute would wipe EVERYTHING. Almost
    # always a wrong directory / empty project, so demand explicit --yes.
    if not project_names and not yes:
        click.echo()
        click.echo(
            click.style(
                "Refusing to purge: the project defines no metrics, so this would "
                "delete ALL data. Re-run with --yes if that is really intended.",
                fg="red",
                bold=True,
            )
        )
        return

    if not yes:
        click.echo()
        if not click.confirm(
            click.style(f"Permanently delete all data for {len(orphans)} metric(s)?", fg="yellow")
        ):
            click.echo("Aborted.")
            return

    purged = 0
    for name in orphans:
        try:
            internal_manager.purge_metric(name)
            purged += 1
        except Exception as e:
            echo_error(name, f"error purging: {e}")

    echo_done(f"Purged {purged} of {len(orphans)} orphaned metric(s).")


# ── helpers ──────────────────────────────────────────────────────────────────


def _valid_detector_ids(config: MetricConfig) -> set[str]:
    """Detector IDs the current config produces.

    Mirrors the DETECT step exactly (DetectorFactory + the same seasonality
    injection) so the computed ``detector_id`` matches what the pipeline
    writes — anything in the DB not in this set is stale.
    """
    return {
        DetectorFactory.detector_id_for_config(detector_config)
        for detector_config in config.detectors or []
    }


def _valid_alert_config_ids(config: MetricConfig) -> set[str]:
    """Alert-config IDs the current config produces (enabled or not).

    Disabled blocks keep their hash, so a temporarily-disabled alert is NOT
    treated as orphaned; only removed or functionally-changed blocks are.
    """
    return {make_alert_config_id(c) for c in (config.alerting or [])}


def _create_internal_manager(
    project_root: Path, profile: str | None
) -> InternalTablesManager | None:
    """Load profiles.yml and build an InternalTablesManager, or report and return None."""
    profiles_path = project_root / "profiles.yml"
    if not profiles_path.exists():
        click.echo(click.style("Error: profiles.yml not found!", fg="red", bold=True))
        click.echo(f"Expected at: {profiles_path}")
        return None

    try:
        profiles_config = ProfilesConfig.from_yaml(profiles_path)
    except Exception as e:
        click.echo(click.style(f"Error loading profiles.yml: {e}", fg="red", bold=True))
        return None

    try:
        db_manager = profiles_config.create_manager(profile)
    except Exception as e:
        click.echo(click.style(f"Error creating database manager: {e}", fg="red", bold=True))
        return None

    return InternalTablesManager(db_manager)
