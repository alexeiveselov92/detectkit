"""Metrics-metadata mixin: ``_dtk_metrics`` upserts.

The ``_dtk_metrics`` table is informational (used by analyst dashboards),
not by the library logic itself. We refresh it on every ``dtk run`` via
DELETE+INSERT to guarantee uniqueness on ``metric_name``.
"""

from __future__ import annotations

from datetime import datetime as _datetime

import numpy as np

from detectkit.database.internal_tables._base import _InternalTablesBase
from detectkit.database.tables import TABLE_METRICS
from detectkit.utils.datetime_utils import now_utc_naive
from detectkit.utils.json_utils import json_dumps_sorted


class _MetricsMixin(_InternalTablesBase):
    def upsert_metric_config(
        self,
        metric_config,  # MetricConfig — typed loosely to avoid a circular import
        file_path: str,
        table_name_override: str | None = None,
    ) -> int:
        """Refresh metadata for *metric_config* in ``_dtk_metrics``."""
        table_name = table_name_override or TABLE_METRICS
        full_table_name = self._manager.get_full_table_name(table_name, use_internal=True)

        loading_start_time_dt = None
        if metric_config.loading_start_time:
            try:
                loading_start_time_dt = _datetime.strptime(
                    metric_config.loading_start_time, "%Y-%m-%d %H:%M:%S"
                )  # naive UTC, by config convention
            except (ValueError, AttributeError):
                loading_start_time_dt = None

        first_alerting = metric_config.alerting[0] if metric_config.alerting else None
        is_alert_enabled = 1 if first_alerting and first_alerting.enabled else 0
        timezone_str = first_alerting.timezone if first_alerting else None
        direction = first_alerting.direction if first_alerting else None
        consecutive_anomalies = first_alerting.consecutive_anomalies if first_alerting else 3
        no_data_alert = 1 if first_alerting and first_alerting.no_data_alert else 0
        min_detectors = first_alerting.min_detectors if first_alerting else 1

        now = now_utc_naive()
        data = {
            "metric_name": np.array([metric_config.name]),
            "description": np.array([getattr(metric_config, "description", None)]),
            "path": np.array([file_path]),
            "interval": np.array([str(metric_config.interval)]),
            "loading_start_time": (
                np.array([loading_start_time_dt], dtype="datetime64[ms]")
                if loading_start_time_dt
                else np.array([None])
            ),
            "loading_batch_size": np.array([metric_config.loading_batch_size], dtype=np.uint32),
            "is_alert_enabled": np.array([is_alert_enabled], dtype=np.uint8),
            "timezone": np.array([timezone_str]),
            "direction": np.array([direction]),
            "consecutive_anomalies": np.array([consecutive_anomalies], dtype=np.uint32),
            "no_data_alert": np.array([no_data_alert], dtype=np.uint8),
            "min_detectors": np.array([min_detectors], dtype=np.uint32),
            "tags": np.array([json_dumps_sorted(metric_config.tags or [])]),
            "enabled": np.array([1 if metric_config.enabled else 0], dtype=np.uint8),
            "created_at": np.array([now], dtype="datetime64[ms]"),
            "updated_at": np.array([now], dtype="datetime64[ms]"),
        }

        return self._manager.upsert_record(
            table_name=full_table_name,
            key_columns={"metric_name": metric_config.name},
            data=data,
        )
