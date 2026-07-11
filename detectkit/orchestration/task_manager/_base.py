"""Shared state and helper methods for the TaskManager mixins."""

from __future__ import annotations

from datetime import datetime

from detectkit.alerting.channels.base import BaseAlertChannel
from detectkit.alerting.channels.factory import AlertChannelFactory
from detectkit.alerting.orchestrator import DetectionRecord, hydrate_detection_records
from detectkit.config.metric_config import (
    MetricConfig,
    resolve_grid_phase_seconds,
    resolve_loading_delay_seconds,
)
from detectkit.database.internal_tables import InternalTablesManager


class _TaskManagerBase:
    """Holds collaborators shared across every pipeline step mixin."""

    def __init__(
        self,
        internal_manager: InternalTablesManager,
        db_manager,  # BaseDatabaseManager — typed loosely to avoid an import cycle
        profiles_config=None,
        project_config=None,
    ):
        self.internal = internal_manager
        self.db_manager = db_manager
        self.profiles_config = profiles_config
        self.project_config = project_config
        # In-process flag: dispatch project-level error alert at most once
        # per run. Abort propagation is signalled via result["abort_run"].
        self._error_alert_sent_in_run = False

    def _loading_delay_seconds(self, config: MetricConfig) -> int:
        """Effective data-maturity delay for *config* (metric → project → 0).

        One resolution seam for the load step's end bound and the alert
        step's no-data expectation, so the two can't drift apart.
        """
        return resolve_loading_delay_seconds(
            config.loading_delay,
            getattr(self.project_config, "loading_delay", None),
        )

    def _grid_phase_seconds(self, config: MetricConfig) -> int:
        """Phase of *config*'s interval grid on the epoch clock (metric-derived).

        The loader anchors the stored grid on ``loading_start_time``; the alert
        step's exact-timestamp no-data lookup must floor to the same phase, so
        this one seam feeds the orchestrator's ``get_last_complete_point`` — the
        mirror of ``_loading_delay_seconds`` for the grid phase (issue #114).
        """
        return resolve_grid_phase_seconds(
            config.loading_start_time,
            config.get_interval().seconds,
        )

    def _load_recent_detections(
        self,
        metric_name: str,
        last_point: datetime,
        num_points: int,
    ) -> list[DetectionRecord]:
        """Build :class:`DetectionRecord` rows for the last *num_points* timestamps.

        Emits one record *per detector per timestamp* so the orchestrator can
        evaluate multi-detector consensus (``min_detectors``). Collapsing
        detectors into a single record breaks ``min_detectors >= 2`` because
        ``should_alert`` counts records, not flags.
        """
        results = self.internal.get_recent_detections(
            metric_name=metric_name,
            last_point=last_point,
            num_points=num_points,
        )
        if not results:
            return []

        return hydrate_detection_records(results)

    def _create_alert_channels(self, channel_names: list[str]) -> list[BaseAlertChannel]:
        """Resolve channel names against the loaded profiles config."""
        if not self.profiles_config:
            return []

        channels: list[BaseAlertChannel] = []
        for channel_name in channel_names:
            try:
                channel_config = self.profiles_config.get_alert_channel_config(channel_name)
                channels.append(AlertChannelFactory.create_from_config(channel_config))
            except (ValueError, KeyError, ImportError, TypeError) as exc:
                # Config-level problems (missing channel, bad type, missing
                # driver, wrong constructor args) — skip this channel but
                # keep going so a single typo doesn't kill the whole run.
                print(
                    f"Warning: Failed to create channel '{channel_name}': "
                    f"{type(exc).__name__}: {exc}"
                )

        return channels

    def get_metric_status(self, metric_name: str) -> dict | None:
        """Quick health snapshot for *metric_name*."""
        # NOTE: check_lock requires (metric_name, detector_id, process_type);
        # this convenience wrapper uses the pipeline lock that run_metric takes.
        lock_info = self.internal.check_lock(metric_name, "pipeline", "pipeline")
        last_timestamp = self.internal.get_last_datapoint_timestamp(metric_name)
        return {
            "metric_name": metric_name,
            "is_locked": lock_info is not None,
            "locked_by": lock_info.get("locked_by") if lock_info else None,
            "locked_at": lock_info.get("locked_at") if lock_info else None,
            "last_datapoint": last_timestamp,
        }
