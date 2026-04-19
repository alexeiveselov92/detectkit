"""Public ``TaskManager`` facade composed from per-step mixins."""

from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

import click

from detectkit.config.metric_config import MetricConfig
from detectkit.orchestration.task_manager._alert_step import _AlertStepMixin
from detectkit.orchestration.task_manager._detect_step import _DetectStepMixin
from detectkit.orchestration.task_manager._load_step import _LoadStepMixin
from detectkit.orchestration.task_manager._types import PipelineStep, TaskStatus


class TaskManager(_LoadStepMixin, _DetectStepMixin, _AlertStepMixin):
    """Drives the load → detect → alert pipeline for a single metric.

    Each step lives in its own mixin module; this class only orchestrates
    them, manages the run-level lock, and aggregates the final result
    dict that the CLI consumes.
    """

    def run_metric(
        self,
        config: MetricConfig,
        steps: Optional[List[PipelineStep]] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        full_refresh: bool = False,
        force: bool = False,
        metric_file_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute the requested pipeline steps for *config*."""
        steps = steps or [
            PipelineStep.LOAD,
            PipelineStep.DETECT,
            PipelineStep.ALERT,
        ]
        metric_name = config.name

        result: Dict[str, Any] = {
            "status": TaskStatus.SUCCESS,
            "steps_completed": [],
            "datapoints_loaded": 0,
            "anomalies_detected": 0,
            "alerts_sent": 0,
            "error": None,
        }

        try:
            if metric_file_path:
                metrics_table_name = None
                if self.project_config and hasattr(self.project_config, "tables"):
                    metrics_table_name = self.project_config.tables.metrics
                self.internal.upsert_metric_config(
                    metric_config=config,
                    file_path=metric_file_path,
                    table_name_override=metrics_table_name,
                )

            if not force:
                # TODO: surface the timeout via ProjectConfig.
                lock_acquired = self.internal.acquire_lock(
                    metric_name=metric_name,
                    detector_id="pipeline",
                    process_type="pipeline",
                    timeout_seconds=3600,
                )
                if not lock_acquired:
                    raise RuntimeError(
                        f"Failed to acquire lock for metric '{metric_name}'. "
                        "Another task is running. Use --force to override."
                    )

            try:
                if PipelineStep.LOAD in steps:
                    load_result = self._run_load_step(
                        config, from_date, to_date, full_refresh
                    )
                    result["datapoints_loaded"] = load_result["points_loaded"]
                    result["steps_completed"].append(PipelineStep.LOAD)

                if PipelineStep.DETECT in steps:
                    click.echo()
                    click.echo(click.style("  ┌─ DETECT", fg="cyan", bold=True))
                    detect_result = self._run_detect_step(
                        config, from_date, to_date, full_refresh
                    )
                    result["anomalies_detected"] = detect_result["anomalies_count"]
                    result["steps_completed"].append(PipelineStep.DETECT)

                if PipelineStep.ALERT in steps:
                    click.echo()
                    click.echo(click.style("  ┌─ ALERT", fg="cyan", bold=True))
                    alert_result = self._run_alert_step(config)
                    result["alerts_sent"] = alert_result["alerts_sent"]
                    result["steps_completed"].append(PipelineStep.ALERT)

            finally:
                if not force:
                    status = (
                        "completed"
                        if result["status"] == TaskStatus.SUCCESS
                        else "failed"
                    )
                    self.internal.release_lock(
                        metric_name=metric_name,
                        detector_id="pipeline",
                        process_type="pipeline",
                        status=status,
                        error_message=result.get("error"),
                    )

        except Exception as exc:
            # Surface the failure with type + message so the CLI/log shows
            # which class of error happened (DB connection, validation,
            # channel HTTP, etc.) without having to grep the traceback.
            result["status"] = TaskStatus.FAILED
            result["error"] = f"{type(exc).__name__}: {exc}"
            click.echo(
                click.style(
                    f"  ✗ Pipeline failed for '{metric_name}': {result['error']}",
                    fg="red",
                ),
                err=True,
            )
            click.echo(traceback.format_exc(), err=True)

        return result

    def __repr__(self) -> str:
        return f"TaskManager(db={self.db_manager.__class__.__name__})"
