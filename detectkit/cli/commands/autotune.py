"""Implementation of ``dtk autotune`` — automatic detector configuration.

For each selected metric, loads its datapoints, optionally reads labeled
incidents, runs the autotune engine (seasonality → detector → grid search →
window), then: persists the run to ``_dtk_autotune_runs``, writes an annotated
tuned config, persists the winning detector's detections (so it is inspectable
and reusable), and prunes superseded autotune winners from prior runs.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import click
import numpy as np

from detectkit.autotune import (
    AutoTuneError,
    ScoringMetric,
    TuneSettings,
    compute_run_id,
    emit_tuned_config,
    parse_labels_file,
    render_labeler_html,
    run_autotune_engine,
)
from detectkit.autotune.labels import GroundTruth, IncidentLabels, parse_incident_labels
from detectkit.cli._output import echo_done, echo_error, echo_noop
from detectkit.cli.commands.run import find_project_root, parse_date, select_metrics
from detectkit.config.metric_config import AutoTuneConfig, MetricConfig
from detectkit.config.profile import ProfilesConfig
from detectkit.config.project_config import ProjectConfig
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.detectors.base import DetectionResult
from detectkit.detectors.factory import DetectorFactory
from detectkit.utils.json_utils import json_dumps_sorted

# Cap the scored training span when the user doesn't pin max_history, so tuning
# stays responsive on very long histories (recent data is the most relevant).
_DEFAULT_TRAIN_CAP = 50_000

_STAGE_TITLES = {
    "labels": "LABELS",
    "seasonality": "SEASONALITY",
    "detector_select": "DETECTOR SELECT",
    "grid_search": "GRID SEARCH",
    "window": "WINDOW",
}


class _StageRenderer:
    """Streams engine progress as the run-log tree (header per stage + │ lines)."""

    def __init__(self) -> None:
        self._open: str | None = None

    def __call__(self, stage: str, line: str) -> None:
        if self._open != stage:
            title = _STAGE_TITLES.get(stage, stage.upper())
            click.echo(click.style(f"  ┌─ {title}", fg="cyan", bold=True))
            self._open = stage
        click.echo(f"  │   {line}")


def _results_to_batch(results: list[DetectionResult]) -> dict[str, np.ndarray]:
    """Convert detect() output into the ``save_detections`` batch shape."""

    def _f(value: float | None) -> float:
        return float("nan") if value is None else float(value)

    return {
        "timestamp": np.array([r.timestamp for r in results], dtype="datetime64[ms]"),
        "is_anomaly": np.array([bool(r.is_anomaly) for r in results], dtype=bool),
        "confidence_lower": np.array([_f(r.confidence_lower) for r in results], dtype=np.float64),
        "confidence_upper": np.array([_f(r.confidence_upper) for r in results], dtype=np.float64),
        "value": np.array([_f(r.value) for r in results], dtype=np.float64),
        "processed_value": np.array([_f(r.processed_value) for r in results], dtype=np.float64),
        "detection_metadata": np.array(
            [json_dumps_sorted(r.detection_metadata or {}) for r in results], dtype=object
        ),
    }


def _resolve_scoring(scoring_override: str | None, autotune_cfg: AutoTuneConfig) -> ScoringMetric:
    value = scoring_override or autotune_cfg.scoring_metric or ScoringMetric.MCC.value
    try:
        return ScoringMetric(value)
    except ValueError as exc:
        allowed = ", ".join(m.value for m in ScoringMetric)
        raise click.BadParameter(f"Invalid scoring metric '{value}'. Allowed: {allowed}") from exc


def _resolve_labels(
    *,
    metric_name: str,
    interval_seconds: int,
    incidents_path: str | None,
    autotune_cfg: AutoTuneConfig,
    project_root: Path,
) -> tuple[IncidentLabels, str]:
    """Resolve labels by precedence.

    ``--incidents`` flag > config ``labels_file`` > config inline ``incidents`` >
    interactive prompt > none (unsupervised).
    """
    path = incidents_path or autotune_cfg.labels_file
    if path:
        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = project_root / file_path
        labels = parse_labels_file(
            file_path, interval_seconds=interval_seconds, metric_name=metric_name
        )
        return labels, f"file {file_path}"

    if autotune_cfg.incidents:
        labels = parse_incident_labels(
            {"incidents": autotune_cfg.incidents, "timezone": autotune_cfg.incidents_timezone},
            interval_seconds=interval_seconds,
            metric_name=metric_name,
        )
        n = len(autotune_cfg.incidents)
        return labels, f"inline config ({n} incident{'s' if n != 1 else ''})"

    if sys.stdin.isatty():
        return _prompt_labels(interval_seconds=interval_seconds), "interactive"

    return IncidentLabels([], []), "none (unsupervised)"


def _prompt_labels(*, interval_seconds: int) -> IncidentLabels:
    """Collect incident windows interactively (blank start ends the loop)."""
    if not click.confirm(
        "  No incident labels provided. Enter them now? (No → unsupervised tuning)",
        default=False,
    ):
        return IncidentLabels([], [])
    incidents: list[dict[str, str]] = []
    while True:
        start = click.prompt(
            "    incident start (YYYY-MM-DD[ HH:MM:SS], blank to finish)",
            default="",
            show_default=False,
        )
        if not start.strip():
            break
        end = click.prompt(
            "    incident end (blank → treat start as a point)", default="", show_default=False
        )
        incidents.append({"start": start, "end": end} if end.strip() else {"at": start})
    return parse_incident_labels({"incidents": incidents}, interval_seconds=interval_seconds)


def _build_settings(*, scoring: ScoringMetric, autotune_cfg: AutoTuneConfig) -> TuneSettings:
    return TuneSettings(
        metric=scoring,
        beta=autotune_cfg.beta,
        fold_count=autotune_cfg.folds,
        allowed_detector_types=autotune_cfg.detector_types,
        allowed_seasonality=autotune_cfg.seasonality_candidates,
        force_seasonality=autotune_cfg.force_seasonality,
        fixed_params=dict(autotune_cfg.fixed_params),
        max_history=autotune_cfg.max_history,
    )


def _cap_history(data: dict[str, np.ndarray], max_history: int | None) -> dict[str, np.ndarray]:
    """Keep the most recent ``max_history`` (or default-cap) points."""
    n = len(data["timestamp"])
    cap = max_history if max_history is not None else _DEFAULT_TRAIN_CAP
    if n <= cap:
        return data
    return {
        "timestamp": data["timestamp"][-cap:],
        "value": data["value"][-cap:],
        "seasonality_data": data["seasonality_data"][-cap:],
        "seasonality_columns": data["seasonality_columns"],
    }


def _load_project(
    profile: str | None,
) -> tuple[Path, ProjectConfig, InternalTablesManager, Any] | None:
    """Bootstrap project root, configs, DB manager and internal tables."""
    project_root = find_project_root()
    if not project_root:
        click.echo(click.style("Error: Not in a detectkit project directory!", fg="red", bold=True))
        click.echo("Run 'dtk init <project_name>' to create a new project.")
        return None

    try:
        project_config = ProjectConfig.from_yaml_file(project_root / "detectkit_project.yml")
    except Exception as exc:
        click.echo(click.style(f"Error loading detectkit_project.yml: {exc}", fg="red", bold=True))
        return None

    profiles_path = project_root / "profiles.yml"
    if not profiles_path.exists():
        click.echo(click.style("Error: profiles.yml not found!", fg="red", bold=True))
        return None
    try:
        profiles_config = ProfilesConfig.from_yaml(profiles_path)
        db_manager = profiles_config.create_manager(profile)
        internal_manager = InternalTablesManager(db_manager)
        internal_manager.ensure_tables()
    except Exception as exc:
        click.echo(click.style(f"Error connecting to the database: {exc}", fg="red", bold=True))
        return None

    return project_root, project_config, internal_manager, db_manager


def run_autotune(
    *,
    select: str,
    incidents_path: str | None,
    label: bool,
    scoring_override: str | None,
    from_date: str | None,
    to_date: str | None,
    profile: str | None,
    force: bool,
    dry_run: bool,
) -> None:
    """Auto-tune each selected metric's detector configuration."""
    from_dt = parse_date(from_date) if from_date else None
    to_dt = parse_date(to_date) if to_date else None

    loaded = _load_project(profile)
    if loaded is None:
        return
    project_root, _project_config, internal_manager, _db_manager = loaded

    try:
        metrics = select_metrics(select, project_root)
    except ValueError as exc:
        click.echo(click.style(f"Error: {exc}", fg="red", bold=True))
        return
    if not metrics:
        click.echo(click.style(f"No metrics found matching selector: {select}", fg="yellow"))
        return

    click.echo(f"Found {len(metrics)} metric(s) to tune")
    succeeded = 0
    for metric_path, config in metrics:
        ok = _tune_one(
            metric_path=metric_path,
            config=config,
            project_root=project_root,
            internal_manager=internal_manager,
            incidents_path=incidents_path,
            label=label,
            scoring_override=scoring_override,
            from_dt=from_dt,
            to_dt=to_dt,
            force=force,
            dry_run=dry_run,
        )
        if ok:
            succeeded += 1

    echo_done(f"Tuned {len(metrics)} metric(s), {succeeded} succeeded.")


def _tune_one(
    *,
    metric_path: Path,
    config: MetricConfig,
    project_root: Path,
    internal_manager: InternalTablesManager,
    incidents_path: str | None,
    label: bool,
    scoring_override: str | None,
    from_dt: datetime | None,
    to_dt: datetime | None,
    force: bool,
    dry_run: bool,
) -> bool:
    """Tune one metric end to end; return True on success."""
    name = config.name
    autotune_cfg = config.autotune or AutoTuneConfig()
    if not autotune_cfg.enabled:
        echo_noop(name, "autotune disabled in config")
        return False

    interval_seconds = config.get_interval().seconds

    # Load already-loaded datapoints (autotune does not re-query the source).
    data = internal_manager.load_datapoints(name, from_timestamp=from_dt, to_timestamp=to_dt)
    if len(data["timestamp"]) == 0:
        echo_noop(name, "no datapoints — run `dtk run --select " + name + " --steps load` first")
        return False

    # --label: emit the HTML labeler and stop (offline; no DB writes).
    if label:
        html = render_labeler_html(name, data)
        out = project_root / "metrics" / f"{metric_path.stem}__labeler.html"
        out.write_text(html, encoding="utf-8")
        click.echo(click.style(f"Processing metric: {name}", fg="cyan", bold=True))
        click.echo(f"  Wrote labeler: {out.relative_to(project_root)}")
        click.echo("  Open it, mark incidents, export, then re-run with --incidents")
        return True

    click.echo(click.style(f"Tuning metric: {name}", fg="cyan", bold=True))
    click.echo(f"  Config file: {metric_path.relative_to(project_root)}")

    if not force and not internal_manager.acquire_lock(name, "pipeline", "pipeline"):
        echo_error(name, "locked by another run (use --force or `dtk unlock`)")
        return False

    try:
        data = _cap_history(data, autotune_cfg.max_history)
        click.echo(
            f"  Training span: {len(data['timestamp']):,} points " f"(interval {interval_seconds}s)"
        )

        scoring = _resolve_scoring(scoring_override, autotune_cfg)
        labels, label_source = _resolve_labels(
            metric_name=name,
            interval_seconds=interval_seconds,
            incidents_path=incidents_path,
            autotune_cfg=autotune_cfg,
            project_root=project_root,
        )
        ground_truth = labels.to_ground_truth(data["timestamp"], interval_seconds)
        click.echo(f"  Labels: {label_source}")

        settings = _build_settings(scoring=scoring, autotune_cfg=autotune_cfg)
        result = run_autotune_engine(
            metric_name=name,
            data=data,
            ground_truth=ground_truth,
            interval_seconds=interval_seconds,
            settings=settings,
            on_stage=_StageRenderer(),
        )

        run_id = compute_run_id(result)
        out_path, config_text, _ = emit_tuned_config(
            original_config=config,
            original_path=metric_path,
            result=result,
            project_root=project_root,
            run_id=run_id,
        )

        _finalize(
            internal_manager=internal_manager,
            name=name,
            data=data,
            result=result,
            run_id=run_id,
            out_path=out_path,
            config_text=config_text,
            labels=labels,
            ground_truth=ground_truth,
            dry_run=dry_run,
            project_root=project_root,
        )
        internal_manager.release_lock(name, "pipeline", "pipeline", status="completed")
        return True

    except (AutoTuneError, ValueError, FileNotFoundError) as exc:
        internal_manager.release_lock(
            name, "pipeline", "pipeline", status="failed", error_message=str(exc)
        )
        if not dry_run:
            _save_failed_run(internal_manager, name, interval_seconds, scoring_override, str(exc))
        echo_error(name, str(exc))
        return False
    except Exception as exc:  # noqa: BLE001 — never leave a held lock behind
        internal_manager.release_lock(
            name, "pipeline", "pipeline", status="failed", error_message=str(exc)
        )
        echo_error(name, f"unexpected error: {exc}")
        return False


def _finalize(
    *,
    internal_manager: InternalTablesManager,
    name: str,
    data: dict[str, np.ndarray],
    result: Any,
    run_id: str,
    out_path: Path,
    config_text: str,
    labels: IncidentLabels,
    ground_truth: GroundTruth,
    dry_run: bool,
    project_root: Path,
) -> None:
    """Persist run + winner detections + tuned config, prune prior winners, render RESULT."""
    folds = " ".join(f"{f:.2f}" for f in result.cv_per_fold) or "—"
    children = [
        f"Winner: {result.chosen_detector_type}"
        f"(threshold={result.chosen_detector_params.get('threshold')}, "
        f"window_size={result.chosen_detector_params.get('window_size')})  "
        f"{result.scoring_metric}={result.score:.3f}",
        f"Seasonality: {result.chosen_seasonality or 'none'}  |  CV folds: {folds}",
    ]

    if dry_run:
        children.append("dry-run: no config written, no detections persisted")
        click.echo(click.style("  ┌─ RESULT", fg="cyan", bold=True))
        for i, child in enumerate(children):
            click.echo(f"  {'└─' if i == len(children) - 1 else '│  '} {child}")
        return

    # Persist the run record (the audit trail).
    labels_json = {
        "intervals": [
            {"start": iv.start.isoformat(), "end": iv.end.isoformat()} for iv in labels.intervals
        ],
        "points": [{"at": p.at.isoformat()} for p in labels.points],
    }
    internal_manager.save_autotune_run(
        metric_name=name,
        run_id=run_id,
        training_period_start=result.training_start,
        training_period_end=result.training_end,
        interval_seconds=result.interval_seconds,
        labels=labels_json,
        mode=result.mode,
        scoring_metric=result.scoring_metric,
        score=result.score,
        chosen_seasonality=result.chosen_seasonality,
        chosen_detector_type=result.chosen_detector_type,
        chosen_detector_params=result.chosen_detector_params,
        winning_detector_id=result.winning_detector_id,
        candidate_detector_ids=result.candidate_detector_ids,
        decision_log=result.decision_log,
        generated_config_path=str(out_path.relative_to(project_root)),
        generated_config_text=config_text,
        status="success",
    )

    # Prune superseded autotune winners for this metric (keep only the current best).
    pruned = _prune_prior_winners(internal_manager, name, result.winning_detector_id)

    # Persist the winning detector's detections (inspectable + reusable by `dtk run`).
    winner = next(c for c in result.candidates if c["detector_id"] == result.winning_detector_id)
    detector = DetectorFactory.create(winner["detector_type"], winner["params"])
    batch = _results_to_batch(detector.detect(data))
    internal_manager.save_detections(
        name,
        result.winning_detector_id,
        detector.__class__.__name__,
        batch,
        detector.get_detector_params(),
    )

    # Write the annotated tuned config.
    out_path.write_text(config_text, encoding="utf-8")

    children.append(f"Wrote {out_path.relative_to(project_root)}  (run_id={run_id})")
    children.append(
        f"Evaluated {len(result.candidate_detector_ids)} candidate(s); "
        f"persisted winner, pruned {pruned} superseded run(s)"
    )
    children.append(f"Re-run with: dtk run --select {name}__tuned_{run_id}")
    click.echo(click.style("  ┌─ RESULT", fg="cyan", bold=True))
    for i, child in enumerate(children):
        click.echo(f"  {'└─' if i == len(children) - 1 else '│  '} {child}")


def _prune_prior_winners(
    internal_manager: InternalTablesManager, name: str, current_winner: str
) -> int:
    """Delete detections of prior autotune winners that differ from the current one."""
    stored = internal_manager.list_detector_ids(name)
    pruned = 0
    seen: set[str] = set()
    for row in internal_manager.get_autotune_runs(name):
        prior = row.get("winning_detector_id")
        if not prior or prior == current_winner or prior in seen:
            continue
        seen.add(prior)
        if prior in stored:
            internal_manager.delete_detections(name, detector_id=prior, mutations_sync=True)
            pruned += 1
    return pruned


def _save_failed_run(
    internal_manager: InternalTablesManager,
    name: str,
    interval_seconds: int,
    scoring_override: str | None,
    error: str,
) -> None:
    """Best-effort failure row so the audit trail records the attempt."""
    try:
        internal_manager.save_autotune_run(
            metric_name=name,
            run_id="failed",
            training_period_start=None,
            training_period_end=None,
            interval_seconds=interval_seconds,
            labels={},
            mode="unknown",
            scoring_metric=scoring_override or ScoringMetric.MCC.value,
            score=None,
            chosen_seasonality=None,
            chosen_detector_type=None,
            chosen_detector_params={},
            winning_detector_id=None,
            candidate_detector_ids=[],
            decision_log=[],
            generated_config_path=None,
            generated_config_text="",
            status="failed",
            error_message=error,
        )
    except Exception:  # noqa: BLE001 — failure logging must never raise
        pass
