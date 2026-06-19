"""Public ``TaskManager`` facade composed from per-step mixins."""

from __future__ import annotations

import traceback
from datetime import datetime
from typing import Any

import click

from detectkit.config.metric_config import MetricConfig
from detectkit.orchestration.error_dispatch import dispatch_project_error_alert
from detectkit.orchestration.task_manager._alert_step import _AlertStepMixin
from detectkit.orchestration.task_manager._detect_step import _DetectStepMixin
from detectkit.orchestration.task_manager._load_step import _LoadStepMixin
from detectkit.orchestration.task_manager._types import PipelineStep, TaskStatus

# Age (seconds) after which a 'running' pipeline lock is considered stale and
# overridden — see acquire_lock. A run whose
# 'running' row is older than this is assumed to have died without releasing
# the lock (e.g. the database restarted mid-run).
PIPELINE_LOCK_TIMEOUT_SECONDS = 3600


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

            # Acquire the pipeline lock. A stale 'running' row (older than the
            # timeout) is auto-overridden inside acquire_lock; --force skips the
            # held-lock check but still takes ownership so the lock is released
            # on exit. Done outside the try/finally below so we never release a
            # lock held by another (still-active) process.
            lock_acquired = self.internal.acquire_lock(
                metric_name=metric_name,
                detector_id="pipeline",
                process_type="pipeline",
                timeout_seconds=PIPELINE_LOCK_TIMEOUT_SECONDS,
                force=force,
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

            except BaseException as exc:
                # Mark the failure BEFORE the finally block releases the
                # lock, so the _dtk_tasks row records status='failed' with
                # the error message (not a bogus 'completed'). BaseException
                # on purpose: Ctrl+C / SystemExit must also leave a 'failed'
                # row, then keep propagating past the outer handler.
                result["status"] = TaskStatus.FAILED
                result["error"] = f"{type(exc).__name__}: {exc}"
                raise

            finally:
                # Always release the lock we acquired — including forced runs,
                # so a --force run heals a previously stuck 'running' row
                # instead of leaving it behind.
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
            if not result.get("error"):
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
        is disabled — in that case the run continues normally. Within one
        TaskManager instance the alert fires at most once; subsequent
        failures still return ``True`` so the CLI keeps aborting.
        """
        cfg = getattr(self.project_config, "error_alerting", None)
        if not cfg or not cfg.enabled:
            return False
        if self._error_alert_sent_in_run:
            return True

        sent = dispatch_project_error_alert(
            profiles_config=self.profiles_config,
            project_config=self.project_config,
            metric_name=metric_name,
            exc=exc,
        )
        if sent:
            click.echo(
                click.style(
                    "  │ Aborting remaining metrics for this run.",
                    fg="yellow",
                )
            )
            self._error_alert_sent_in_run = True
        return sent

    def __repr__(self) -> str:
        return f"TaskManager(db={self.db_manager.__class__.__name__})"
