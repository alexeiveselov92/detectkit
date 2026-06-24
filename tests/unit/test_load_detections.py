"""Tests for the detections range reader (``load_detections``).

Mirrors the datapoints range reader (``load_datapoints``). Uses a fake
``BaseDatabaseManager`` that captures the SQL + params handed to
``execute_query`` and returns canned rows, so the test can assert column
mapping, WHERE-clause construction (detector filter + half-open range), and
that ``final_modifier`` is included in the emitted SQL.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np

from detectkit.database.internal_tables import InternalTablesManager
from detectkit.database.manager import BaseDatabaseManager
from detectkit.database.tables import TABLE_DETECTIONS


class FakeManager(BaseDatabaseManager):
    """Records the last query/params and returns canned ``execute_query`` rows.

    ``final_modifier`` is overridden to a non-empty value so the test can assert
    the reader appends it after the table name (the ClickHouse ``FINAL`` path).
    """

    def __init__(self, rows: list[dict] | None = None) -> None:
        self._rows = rows or []
        self.last_query: str | None = None
        self.last_params: dict[str, Any] | None = None

    def execute_query(self, query: str, params: dict[str, Any] | None = None) -> list[dict]:
        self.last_query = query
        self.last_params = params
        return self._rows

    # --- unused abstract surface -------------------------------------------
    def create_table(self, table_name, table_model, if_not_exists: bool = True) -> None:
        pass

    def table_exists(self, table_name: str, schema: str | None = None) -> bool:
        return True

    def insert_batch(self, table_name, data, conflict_strategy: str = "ignore") -> int:
        return 0

    def get_last_timestamp(self, table_name, metric_name, timestamp_column: str = "timestamp"):
        return None

    def upsert_task_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    def upsert_record(self, table_name, key_columns, data) -> int:
        return 1

    def delete_rows(self, table_name, where_clause, params=None, sync: bool = False) -> int:
        return 0

    @property
    def final_modifier(self) -> str:
        return " FINAL"

    @property
    def internal_location(self) -> str:
        return "detectk_internal"

    @property
    def data_location(self) -> str:
        return "public"

    def close(self) -> None:
        pass


def _canned_rows() -> list[dict]:
    return [
        {
            "timestamp": datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
            "detector_id": "mad_abc",
            "detector_name": "MADDetector",
            "is_anomaly": np.bool_(False),
            "confidence_lower": 0.4,
            "confidence_upper": 0.6,
            "value": 0.5,
            "processed_value": 0.5,
            "detector_params": '{"threshold": 3.0}',
            "detection_metadata": '{"severity": 0.0}',
        },
        {
            "timestamp": datetime(2024, 1, 1, 0, 10, tzinfo=timezone.utc),
            "detector_id": "mad_abc",
            "detector_name": "MADDetector",
            "is_anomaly": 1,  # truthy non-bool -> coerced to True
            "confidence_lower": None,  # Nullable passes through unchanged
            "confidence_upper": None,
            "value": None,
            "processed_value": None,
            "detector_params": '{"threshold": 3.0}',
            "detection_metadata": '{"severity": 0.9, "direction": "above"}',
        },
    ]


def _reader(rows: list[dict] | None = None) -> tuple[InternalTablesManager, FakeManager]:
    mgr = FakeManager(rows)
    return InternalTablesManager(mgr), mgr


class TestColumnMapping:
    def test_maps_columns_to_flat_dicts(self) -> None:
        it, _ = _reader(_canned_rows())

        result = it.load_detections("cpu_usage")

        assert len(result) == 2
        first, second = result

        # timestamp normalised to naive UTC
        assert first["timestamp"] == datetime(2024, 1, 1, 0, 0)
        assert first["timestamp"].tzinfo is None
        assert second["timestamp"] == datetime(2024, 1, 1, 0, 10)

        assert first["detector_id"] == "mad_abc"
        assert first["detector_name"] == "MADDetector"
        assert first["detector_params"] == '{"threshold": 3.0}'
        assert first["detection_metadata"] == '{"severity": 0.0}'

        # is_anomaly coerced to Python bool
        assert first["is_anomaly"] is False
        assert second["is_anomaly"] is True

        # numeric Nullable columns pass through unchanged (None stays None)
        assert first["confidence_lower"] == 0.4
        assert first["confidence_upper"] == 0.6
        assert first["value"] == 0.5
        assert first["processed_value"] == 0.5
        assert second["confidence_lower"] is None
        assert second["confidence_upper"] is None
        assert second["value"] is None
        assert second["processed_value"] is None

    def test_empty_result_returns_empty_list(self) -> None:
        it, _ = _reader([])
        assert it.load_detections("cpu_usage") == []


class TestQueryConstruction:
    def test_resolves_table_and_includes_final_modifier(self) -> None:
        it, mgr = _reader()

        it.load_detections("cpu_usage")

        sql = mgr.last_query or ""
        assert f"detectk_internal.{TABLE_DETECTIONS} FINAL" in sql
        # base filter + ordering always present
        assert "metric_name = %(metric_name)s" in sql
        assert "ORDER BY timestamp, detector_id" in sql
        assert mgr.last_params == {"metric_name": "cpu_usage"}

    def test_no_detector_or_range_filter_by_default(self) -> None:
        it, mgr = _reader()

        it.load_detections("cpu_usage")

        sql = mgr.last_query or ""
        assert "detector_id = %(detector_id)s" not in sql
        assert "%(from_timestamp)s" not in sql
        assert "%(to_timestamp)s" not in sql

    def test_detector_id_filter_adds_where_clause(self) -> None:
        it, mgr = _reader()

        it.load_detections("cpu_usage", detector_id="mad_abc")

        sql = mgr.last_query or ""
        assert "detector_id = %(detector_id)s" in sql
        assert mgr.last_params is not None
        assert mgr.last_params["detector_id"] == "mad_abc"

    def test_from_to_build_half_open_bounds(self) -> None:
        it, mgr = _reader()
        frm = datetime(2024, 1, 1)
        to = datetime(2024, 1, 2)

        it.load_detections("cpu_usage", from_timestamp=frm, to_timestamp=to)

        sql = mgr.last_query or ""
        # half-open: inclusive lower, exclusive upper
        assert "timestamp >= %(from_timestamp)s" in sql
        assert "timestamp < %(to_timestamp)s" in sql
        assert "timestamp <= %(to_timestamp)s" not in sql
        assert mgr.last_params is not None
        assert mgr.last_params["from_timestamp"] == frm
        assert mgr.last_params["to_timestamp"] == to

    def test_all_filters_combine(self) -> None:
        it, mgr = _reader()
        frm = datetime(2024, 1, 1)
        to = datetime(2024, 1, 2)

        it.load_detections(
            "cpu_usage", detector_id="mad_abc", from_timestamp=frm, to_timestamp=to
        )

        assert mgr.last_params == {
            "metric_name": "cpu_usage",
            "detector_id": "mad_abc",
            "from_timestamp": frm,
            "to_timestamp": to,
        }
