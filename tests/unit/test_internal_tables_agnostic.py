"""Backend-agnosticism guard for the InternalTablesManager mixins.

The ``_dtk_*`` semantics layer must not emit ClickHouse-only SQL through
``execute_query`` — every backend-specific operation has to go through a
generic manager method (``delete_rows``, ``upsert_record``, ``insert_batch``,
``final_modifier`` …). This test drives every mixin method through a fake
manager that raises if it ever sees ClickHouse-only syntax, so a future
regression (re-introducing ``ALTER TABLE ... DELETE``, ``FINAL``, ``count()``
without ``*``, or ``SETTINGS mutations_sync``) fails loudly here rather than
silently breaking PostgreSQL/MySQL.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import numpy as np

from detectkit.database.internal_tables import InternalTablesManager
from detectkit.database.manager import BaseDatabaseManager

# ClickHouse-only constructs that must never reach a generic backend via SQL.
_BANNED = [
    re.compile(r"\bALTER\s+TABLE\b", re.IGNORECASE),
    re.compile(r"\bFINAL\b", re.IGNORECASE),
    re.compile(r"\bmutations_sync\b", re.IGNORECASE),
    re.compile(r"\bSETTINGS\b", re.IGNORECASE),
    re.compile(r"count\(\s*\)"),  # ClickHouse count() with no argument
    re.compile(r"\bsystem\.tables\b", re.IGNORECASE),
]


def _assert_portable(sql: str) -> None:
    for pattern in _BANNED:
        if pattern.search(sql):
            raise AssertionError(
                f"ClickHouse-only SQL reached the backend: {pattern.pattern!r}\n{sql}"
            )


class PortableFakeManager(BaseDatabaseManager):
    """A generic backend that rejects ClickHouse-only SQL.

    Reads return empty results (the mixins handle empties gracefully); writes,
    deletes and upserts are recorded so they can be asserted. ``final_modifier``
    inherits the base default of ``""``.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute_query(self, query: str, params: dict[str, Any] | None = None) -> list[dict]:
        _assert_portable(query)
        self.calls.append("execute_query")
        return []

    def create_table(self, table_name, table_model, if_not_exists: bool = True) -> None:
        self.calls.append("create_table")

    def table_exists(self, table_name: str, schema: str | None = None) -> bool:
        self.calls.append("table_exists")
        return True  # pretend tables exist so ensure_tables() is a no-op path

    def insert_batch(self, table_name, data, conflict_strategy: str = "ignore") -> int:
        self.calls.append("insert_batch")
        return len(next(iter(data.values()))) if data else 0

    def get_last_timestamp(self, table_name, metric_name, timestamp_column: str = "timestamp"):
        self.calls.append("get_last_timestamp")
        return None

    def upsert_task_status(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append("upsert_task_status")

    def upsert_record(self, table_name, key_columns, data) -> int:
        self.calls.append("upsert_record")
        return 1

    def delete_rows(self, table_name, where_clause, params=None, sync: bool = False) -> int:
        # The generic delete primitive receives only a WHERE predicate, never
        # ClickHouse mutation syntax.
        _assert_portable(f"DELETE FROM {table_name} WHERE {where_clause}")
        self.calls.append("delete_rows")
        return 0

    @property
    def internal_location(self) -> str:
        return "dtk"

    @property
    def data_location(self) -> str:
        return "public"

    def close(self) -> None:
        pass


def _empty_detection_batch() -> dict[str, np.ndarray]:
    z = np.array([], dtype=np.float64)
    return {
        "timestamp": np.array([], dtype="datetime64[ms]"),
        "is_anomaly": np.array([], dtype=bool),
        "confidence_lower": z,
        "confidence_upper": z,
        "value": z,
        "processed_value": z,
        "detection_metadata": np.array([], dtype=object),
    }


def test_every_mixin_method_is_backend_agnostic():
    mgr = PortableFakeManager()
    it = InternalTablesManager(mgr)
    now = datetime(2024, 1, 1, 12, 0, 0)

    # schema
    it.ensure_tables()

    # datapoints
    it.save_datapoints(
        "cpu",
        {
            "timestamp": np.array([np.datetime64("2024-01-01T00:00:00", "ms")]),
            "value": np.array([1.0]),
            "seasonality_data": np.array(["{}"], dtype=object),
        },
        interval_seconds=60,
        seasonality_columns=["hour"],
    )
    it.load_datapoints("cpu", from_timestamp=now, to_timestamp=now)
    it.get_last_datapoint_timestamp("cpu")
    it.get_value_at("cpu", now)
    it.delete_datapoints("cpu", from_timestamp=now)

    # detections
    it.save_detections("cpu", "det1", "MADDetector", _empty_detection_batch(), "{}")
    it.get_last_detection_timestamp("cpu", "det1")
    it.list_detector_ids("cpu")
    it.load_detections("cpu", detector_id="det1", from_timestamp=now, to_timestamp=now)
    it.delete_detections("cpu", detector_id="det1", mutations_sync=True)
    it.get_recent_detections("cpu", last_point=now, num_points=3)

    # alert states
    it.get_alert_state("cpu", "cfg1")
    it.upsert_alert_state("cpu", "cfg1", last_alert_sent=now, increment_count=True)
    it.list_alert_config_ids("cpu")
    it.update_alert_timestamp("cpu", "cfg1", now)
    it.update_recovery_timestamp("cpu", "cfg1", now)
    it.delete_alert_state("cpu", "cfg1")

    # tasks
    it.acquire_lock("cpu", "load", "load")
    it.check_lock("cpu", "load", "load")
    it.release_lock("cpu", "load", "load", status="completed")

    # autotune runs
    it.save_autotune_run(
        metric_name="cpu",
        run_id="r1",
        training_period_start=now,
        training_period_end=now,
        interval_seconds=60,
        labels={"intervals": [], "points": []},
        mode="supervised",
        scoring_metric="mcc",
        score=0.5,
        chosen_seasonality=["hour"],
        chosen_detector_type="mad",
        chosen_detector_params={"threshold": 3.0},
        winning_detector_id="d1",
        candidate_detector_ids=["d1", "d2"],
        decision_log=[],
        generated_config_path="metrics/cpu__tuned_ab12cd.yml",
        generated_config_text="name: cpu__tuned_ab12cd\n",
        status="success",
    )
    it.get_autotune_runs("cpu")
    it.get_last_autotune_run("cpu")

    # maintenance
    it.list_known_metric_names()
    it.count_metric_rows("cpu")
    it.purge_metric("cpu")

    # The delete path must go through delete_rows, not raw execute_query SQL.
    assert "delete_rows" in mgr.calls
    assert "upsert_record" in mgr.calls
