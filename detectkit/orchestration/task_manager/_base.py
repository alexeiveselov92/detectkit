"""Shared state and helper methods for the TaskManager mixins."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from detectkit.alerting.channels.base import BaseAlertChannel
from detectkit.alerting.channels.factory import AlertChannelFactory
from detectkit.alerting.orchestrator import (
    DetectionRecord,
    _direction_from_metadata,
    _parse_detection_metadata,
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

    def _load_recent_detections(
        self,
        metric_name: str,
        last_point: datetime,
        num_points: int,
    ) -> List[DetectionRecord]:
        """Build :class:`DetectionRecord` rows for the last *num_points* timestamps."""
        results = self.internal.get_recent_detections(
            metric_name=metric_name,
            last_point=last_point,
            num_points=num_points,
        )
        if not results:
            return []

        records: List[DetectionRecord] = []
        for row in results:
            is_anomaly = any(row["is_anomaly_flags"])
            anomaly_indices = [
                i for i, flag in enumerate(row["is_anomaly_flags"]) if flag
            ]

            direction = "none"
            severity = 0.0
            confidence_lower = None
            confidence_upper = None
            detector_name = "unknown"
            detector_id = "unknown"
            detector_params = "{}"
            metadata: dict = {}

            metadata_list = (
                row.get("detection_metadata_list")
                or [None] * len(row["detector_ids"])
            )

            # Always read the first detector's CI so recovery messages
            # display the *current* confidence interval, not a stale one.
            if row["confidence_lowers"] and row["confidence_uppers"]:
                confidence_lower = row["confidence_lowers"][0]
                confidence_upper = row["confidence_uppers"][0]
            if row["detector_names"]:
                detector_name = row["detector_names"][0]
                detector_id = row["detector_ids"][0]
                detector_params = row["detector_params_list"][0]

            if is_anomaly and anomaly_indices:
                first_idx = anomaly_indices[0]
                detector_name = row["detector_names"][first_idx]
                detector_id = row["detector_ids"][first_idx]
                detector_params = row["detector_params_list"][first_idx]
                confidence_lower = row["confidence_lowers"][first_idx]
                confidence_upper = row["confidence_uppers"][first_idx]

                metadata = _parse_detection_metadata(metadata_list[first_idx])
                direction = _direction_from_metadata(metadata, True)
                try:
                    severity = float(metadata.get("severity", 0.0) or 0.0)
                except (TypeError, ValueError):
                    severity = 0.0

            records.append(
                DetectionRecord(
                    timestamp=row["timestamp"],
                    detector_name=detector_name,
                    detector_id=detector_id,
                    detector_params=detector_params,
                    value=row["value"],
                    is_anomaly=is_anomaly,
                    confidence_lower=confidence_lower,
                    confidence_upper=confidence_upper,
                    direction=direction,
                    severity=severity,
                    detection_metadata=metadata,
                )
            )

        # Caller wants chronological order; the SQL returns DESC.
        return list(reversed(records))

    def _create_alert_channels(
        self, channel_names: List[str]
    ) -> List[BaseAlertChannel]:
        """Resolve channel names against the loaded profiles config."""
        if not self.profiles_config:
            return []

        channels: List[BaseAlertChannel] = []
        for channel_name in channel_names:
            try:
                channel_config = self.profiles_config.get_alert_channel_config(
                    channel_name
                )
                channels.append(
                    AlertChannelFactory.create_from_config(channel_config)
                )
            except (ValueError, KeyError, ImportError, TypeError) as exc:
                # Config-level problems (missing channel, bad type, missing
                # driver, wrong constructor args) — skip this channel but
                # keep going so a single typo doesn't kill the whole run.
                print(
                    f"Warning: Failed to create channel '{channel_name}': "
                    f"{type(exc).__name__}: {exc}"
                )

        return channels

    def get_metric_status(self, metric_name: str) -> Optional[Dict]:
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
