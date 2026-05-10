"""Public ``TaskManager`` facade composed from per-step mixins."""

from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any

import click
import numpy as np

from detectkit.alerting.channels.base import AlertData
from detectkit.config.metric_config import MetricConfig
from detectkit.orchestration.task_manager._alert_step import _AlertStepMixin
from detectkit.orchestration.task_manager._detect_step import _DetectStepMixin
from detectkit.orchestration.task_manager._load_step import _LoadStepMixin
from detectkit.orchestration.task_manager._types import PipelineStep, TaskStatus
from detectkit.utils.datetime_utils import now_utc_naive


class TaskManager(_LoadStepMixin, _DetectStepMixin, _AlertStepMixin):
    """Drives the load → detect → alert pipeline for a single metric.

    Each step lives in its own mixin module; this class only orchestrates
    them, manages the run-level lock, and aggregates the final result
    dict that the CLI consumes.
    """

    def run_metric(
        self,
        config: MetricConfig,
        steps: list[PipelineStep] | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        full_refresh: bool = False,
        force: bool = False,
        metric_file_path: str | None = None,
    ) -> dict[str, Any]:
        """Execute the requested pipeline steps for *config*."""
        steps = steps or [
            PipelineStep.LOAD,
            PipelineStep.DETECT,
            PipelineStep.ALERT,
        ]
        metric_name = config.name

        result: dict[str, Any] = {
            "status": TaskStatus.SUCCESS,
            "steps_completed": [],
            "datapoints_loaded": 0,
            "anomalies_detected": 0,
            "alerts_sent": 0,
            "error": None,
            "abort_run": False,
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
                    load_result = self._run_load_step(config, from_date, to_date, full_refresh)
                    result["datapoints_loaded"] = load_result["points_loaded"]
                    result["steps_completed"].append(PipelineStep.LOAD)

                if PipelineStep.DETECT in steps:
                    click.echo()
                    click.echo(click.style("  ┌─ DETECT", fg="cyan", bold=True))
                    detect_result = self._run_detect_step(config, from_date, to_date, full_refresh)
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
                    status = "completed" if result["status"] == TaskStatus.SUCCESS else "failed"
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

            # Project-level error alert: at most once per run. After it fires,
            # signal the CLI to abort the remaining metrics — if e.g. the DB
            # is down, processing them won't change anything.
            if self._maybe_send_error_alert(metric_name, exc):
                result["abort_run"] = True

        return result

    def _maybe_send_error_alert(self, metric_name: str, exc: BaseException) -> bool:
        """Dispatch the project-level error alert, if configured.

        Returns ``True`` when an alert was actually attempted (meaning the
        caller should abort the rest of the run). ``False`` when alerting
        is disabled, already sent in this run, or the dispatch itself
        failed — in those cases the run continues normally.
        """
        cfg = getattr(self.project_config, "error_alerting", None)
        if not cfg or not cfg.enabled:
            return False
        if self._error_alert_sent_in_run:
            # Already alerted in this run — suppress and abort.
            return True
        if not cfg.channels:
            return False

        try:
            channels = self._create_alert_channels(cfg.channels)
            if not channels:
                click.echo(
                    click.style(
                        "  │ Project error_alerting enabled but no valid "
                        "channels resolved — skipping.",
                        fg="yellow",
                    ),
                    err=True,
                )
                return False

            alert_data = AlertData(
                metric_name=metric_name,
                timestamp=np.datetime64(now_utc_naive(), "ms"),
                timezone=cfg.timezone or "UTC",
                value=None,
                confidence_lower=None,
                confidence_upper=None,
                detector_name="pipeline",
                detector_params="",
                direction="none",
                severity=0.0,
                detection_metadata={"reason": "pipeline_error"},
                consecutive_count=0,
                is_error=True,
                error_type=type(exc).__name__,
                error_message=str(exc),
                description=None,
                mentions=cfg.mentions,
            )

            click.echo(
                click.style(
                    f"  │ ⚠ Project error alert → sending to " f"{len(channels)} channel(s)...",
                    fg="yellow",
                    bold=True,
                )
            )
            sent = 0
            for channel in channels:
                channel_name = channel.__class__.__name__
                try:
                    if channel.send(alert_data, template=cfg.template):
                        sent += 1
                        mark = click.style("✓", fg="green")
                    else:
                        mark = click.style("✗", fg="red")
                    click.echo(f"  │   {mark} {channel_name}")
                except Exception as channel_exc:
                    click.echo(
                        click.style(
                            f"  │   ✗ {channel_name}: "
                            f"{type(channel_exc).__name__}: {channel_exc}",
                            fg="red",
                        ),
                        err=True,
                    )

            click.echo(
                click.style(
                    "  │ Aborting remaining metrics for this run.",
                    fg="yellow",
                )
            )
            self._error_alert_sent_in_run = True
            return True
        except Exception as dispatch_exc:
            # Never let alert dispatch crash the run.
            click.echo(
                click.style(
                    f"  │ Failed to dispatch project error alert: "
                    f"{type(dispatch_exc).__name__}: {dispatch_exc}",
                    fg="red",
                ),
                err=True,
            )
            return False

    def __repr__(self) -> str:
        return f"TaskManager(db={self.db_manager.__class__.__name__})"
