"""Alert-state mixin: ``_dtk_alert_states`` operations.

Each row tracks per-(metric, alert_config) state used by the alerting
orchestrator: the last sent alert/recovery timestamps and a running
counter. Reads use ``FINAL`` to collapse ReplacingMergeTree versions;
writes go through DELETE+INSERT so updates are immediately visible.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from detectkit.database.internal_tables._base import _InternalTablesBase
from detectkit.database.tables import TABLE_ALERT_STATES
from detectkit.utils.datetime_utils import now_utc_naive, to_naive_utc


class _AlertStatesMixin(_InternalTablesBase):
    def get_alert_state(
        self,
        metric_name: str,
        alert_config_id: str,
    ) -> dict:
        """Read the persisted alert state, defaulting to an empty record."""
        full_table_name = self._manager.get_full_table_name(TABLE_ALERT_STATES, use_internal=True)
        query = f"""
        SELECT last_alert_sent, last_recovery_sent, alert_count
        FROM {full_table_name}
        FINAL
        WHERE metric_name = %(metric_name)s
          AND alert_config_id = %(alert_config_id)s
        LIMIT 1
        """
        results = self._manager.execute_query(
            query,
            params={
                "metric_name": metric_name,
                "alert_config_id": alert_config_id,
            },
        )
        if not results:
            return {
                "last_alert_sent": None,
                "last_recovery_sent": None,
                "alert_count": 0,
            }

        row = results[0]
        return {
            "last_alert_sent": to_naive_utc(row.get("last_alert_sent")),
            "last_recovery_sent": to_naive_utc(row.get("last_recovery_sent")),
            "alert_count": row.get("alert_count", 0) or 0,
        }

    def upsert_alert_state(
        self,
        metric_name: str,
        alert_config_id: str,
        last_alert_sent: datetime | None = None,
        last_recovery_sent: datetime | None = None,
        increment_count: bool = False,
    ) -> None:
        """Write a new alert-state row, preserving fields not being updated."""
        full_table_name = self._manager.get_full_table_name(TABLE_ALERT_STATES, use_internal=True)

        existing = self.get_alert_state(metric_name, alert_config_id)
        new_last_alert = (
            to_naive_utc(last_alert_sent)
            if last_alert_sent is not None
            else existing["last_alert_sent"]
        )
        new_last_recovery = (
            to_naive_utc(last_recovery_sent)
            if last_recovery_sent is not None
            else existing["last_recovery_sent"]
        )
        new_alert_count = (
            existing["alert_count"] + 1 if increment_count else existing["alert_count"]
        )

        delete_query = f"""
        ALTER TABLE {full_table_name}
        DELETE WHERE metric_name = %(metric_name)s
          AND alert_config_id = %(alert_config_id)s
        SETTINGS mutations_sync = 1
        """
        self._manager.execute_query(
            delete_query,
            params={
                "metric_name": metric_name,
                "alert_config_id": alert_config_id,
            },
        )

        now = now_utc_naive()
        insert_data = {
            "metric_name": np.array([metric_name]),
            "alert_config_id": np.array([alert_config_id]),
            "last_alert_sent": (
                np.array([new_last_alert], dtype="datetime64[ms]")
                if new_last_alert
                else np.array([None])
            ),
            "last_recovery_sent": (
                np.array([new_last_recovery], dtype="datetime64[ms]")
                if new_last_recovery
                else np.array([None])
            ),
            "alert_count": np.array([new_alert_count], dtype=np.uint32),
            "updated_at": np.array([now], dtype="datetime64[ms]"),
        }
        self._manager.insert_batch(full_table_name, insert_data, conflict_strategy="ignore")

    def list_alert_config_ids(self, metric_name: str) -> list[str]:
        """Return every ``alert_config_id`` with stored state for a metric.

        Used by ``dtk clean`` to find alert-state rows left behind after an
        alerting block was removed or its functional params changed (see
        ``make_alert_config_id``).
        """
        full_table_name = self._manager.get_full_table_name(TABLE_ALERT_STATES, use_internal=True)
        query = f"""
        SELECT DISTINCT alert_config_id
        FROM {full_table_name}
        WHERE metric_name = %(metric_name)s
        """
        result = self._manager.execute_query(query, {"metric_name": metric_name})
        return [row["alert_config_id"] for row in result if row.get("alert_config_id")]

    def delete_alert_state(self, metric_name: str, alert_config_id: str) -> int:
        """Delete the alert-state row for a single ``(metric, alert_config)``."""
        full_table_name = self._manager.get_full_table_name(TABLE_ALERT_STATES, use_internal=True)
        query = f"""
        ALTER TABLE {full_table_name}
        DELETE WHERE metric_name = %(metric_name)s
          AND alert_config_id = %(alert_config_id)s
        SETTINGS mutations_sync = 1
        """
        self._manager.execute_query(
            query,
            params={"metric_name": metric_name, "alert_config_id": alert_config_id},
        )
        return 0

    def get_last_alert_timestamp(
        self,
        metric_name: str,
        alert_config_id: str,
    ) -> datetime | None:
        """Convenience accessor for ``alert_state['last_alert_sent']``."""
        return self.get_alert_state(metric_name, alert_config_id)["last_alert_sent"]

    def update_alert_timestamp(
        self,
        metric_name: str,
        alert_config_id: str,
        timestamp: datetime,
        increment_count: bool = True,
    ) -> int:
        self.upsert_alert_state(
            metric_name=metric_name,
            alert_config_id=alert_config_id,
            last_alert_sent=timestamp,
            increment_count=increment_count,
        )
        return 1

    def get_last_recovery_timestamp(
        self,
        metric_name: str,
        alert_config_id: str,
    ) -> datetime | None:
        """Convenience accessor for ``alert_state['last_recovery_sent']``."""
        return self.get_alert_state(metric_name, alert_config_id)["last_recovery_sent"]

    def update_recovery_timestamp(
        self,
        metric_name: str,
        alert_config_id: str,
        timestamp: datetime,
    ) -> int:
        self.upsert_alert_state(
            metric_name=metric_name,
            alert_config_id=alert_config_id,
            last_recovery_sent=timestamp,
        )
        return 1
