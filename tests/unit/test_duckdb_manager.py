"""Real-engine unit tests for the DuckDB backend.

Unlike ``test_sql_managers.py`` (mock-based, for PostgreSQL/MySQL), these
tests run against a real in-process DuckDB instance — DuckDB has no server to
mock against, and the whole point of :mod:`detectkit.database.duckdb_manager`
is the DB-API adapter that makes the shared ``%(name)s``/cursor-based flow
work against DuckDB's ``$name``/qmark, autocommit-by-default Python API. Each
test gets its own on-disk file under ``tmp_path`` (or ``:memory:`` where the
scenario calls for it).
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

duckdb = pytest.importorskip("duckdb")

from detectkit.database.duckdb_manager import DuckDBDatabaseManager  # noqa: E402
from detectkit.database.internal_tables.manager import InternalTablesManager  # noqa: E402
from detectkit.database.tables import (  # noqa: E402
    TABLE_DATAPOINTS,
    TABLE_DETECTIONS,
    TABLE_TASKS,
    get_datapoints_table_model,
    get_tasks_table_model,
)


def _db_path(tmp_path) -> str:
    return str(tmp_path / "dtk.duckdb")


def _make_manager(tmp_path, **kwargs) -> DuckDBDatabaseManager:
    return DuckDBDatabaseManager(path=_db_path(tmp_path), **kwargs)


def _datapoints_row(
    metric_name: str = "cpu",
    ts: str = "2024-01-01T00:00:00",
    value: float = 1.0,
    created_at: str = "2024-01-01T00:00:00",
) -> dict[str, np.ndarray]:
    return {
        "metric_name": np.array([metric_name]),
        "timestamp": np.array([np.datetime64(ts, "ms")]),
        "value": np.array([value]),
        "seasonality_data": np.array(["{}"]),
        "interval_seconds": np.array([60], dtype=np.int32),
        "seasonality_columns": np.array(["hour"]),
        "created_at": np.array([np.datetime64(created_at, "ms")]),
    }


class TestConstruction:
    def test_empty_path_raises_value_error(self):
        with pytest.raises(ValueError):
            DuckDBDatabaseManager(path="")

    def test_memory_path_works(self):
        mgr = DuckDBDatabaseManager(path=":memory:")
        try:
            assert mgr.execute_query("SELECT 1 AS x") == [{"x": 1}]
        finally:
            mgr.close()

    def test_locations_default_to_detectkit_and_main(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            assert mgr.internal_location == "detectkit"
            assert mgr.data_location == "main"
        finally:
            mgr.close()


class TestEnsureLocations:
    def test_creates_internal_schema_but_not_main(self, tmp_path):
        mgr = _make_manager(tmp_path, data_schema="main")
        try:
            schemas = {
                row["schema_name"]
                for row in mgr.execute_query("SELECT schema_name FROM information_schema.schemata")
            }
            assert "detectkit" in schemas
            assert "main" in schemas  # always present, never explicitly created
        finally:
            mgr.close()

    def test_creates_both_schemas_when_distinct(self, tmp_path):
        mgr = _make_manager(tmp_path, internal_schema="dtk_internal", data_schema="dtk_data")
        try:
            schemas = {
                row["schema_name"]
                for row in mgr.execute_query("SELECT schema_name FROM information_schema.schemata")
            }
            assert {"dtk_internal", "dtk_data"} <= schemas
        finally:
            mgr.close()


class TestCreateTableAndExists:
    def test_create_table_enforces_primary_key(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
            mgr.create_table(full, get_datapoints_table_model())
            # A duplicate PK insert must now be rejected at the constraint level.
            with pytest.raises(duckdb.Error):
                mgr.execute_query(
                    f"INSERT INTO {full} "
                    "(metric_name, timestamp, value, seasonality_data, "
                    "interval_seconds, seasonality_columns, created_at) VALUES "
                    "('cpu', TIMESTAMP '2024-01-01', 1.0, '{}', 60, 'hour', "
                    "TIMESTAMP '2024-01-01'), "
                    "('cpu', TIMESTAMP '2024-01-01', 2.0, '{}', 60, 'hour', "
                    "TIMESTAMP '2024-01-01')"
                )
        finally:
            mgr.close()

    def test_table_exists_checks_both_locations_and_explicit_schema(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
            assert mgr.table_exists(TABLE_DATAPOINTS) is False
            mgr.create_table(full, get_datapoints_table_model())
            assert mgr.table_exists(TABLE_DATAPOINTS) is True
            assert mgr.table_exists(TABLE_DATAPOINTS, schema="detectkit") is True
            assert mgr.table_exists(TABLE_DATAPOINTS, schema="main") is False
        finally:
            mgr.close()


class TestGetLastTimestamp:
    def test_empty_table_returns_none(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
            mgr.create_table(full, get_datapoints_table_model())
            assert mgr.get_last_timestamp(full, "cpu") is None
        finally:
            mgr.close()

    def test_returns_max_timestamp_for_metric(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
            mgr.create_table(full, get_datapoints_table_model())
            mgr.insert_batch(full, _datapoints_row(ts="2024-01-01T00:00:00"))
            mgr.insert_batch(full, _datapoints_row(ts="2024-01-01T00:10:00"))
            assert mgr.get_last_timestamp(full, "cpu") == datetime(2024, 1, 1, 0, 10, 0)
        finally:
            mgr.close()


class TestInsertBatchConflicts:
    def test_ignore_dedups_on_primary_key(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
            mgr.create_table(full, get_datapoints_table_model())
            mgr.insert_batch(full, _datapoints_row(), conflict_strategy="ignore")
            mgr.insert_batch(full, _datapoints_row(), conflict_strategy="ignore")
            rows = mgr.execute_query(f"SELECT count(*) AS n FROM {full}")
            assert rows[0]["n"] == 1
        finally:
            mgr.close()

    def test_version_aware_last_writer_wins_older_does_not_overwrite(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
            mgr.create_table(full, get_datapoints_table_model())
            mgr.insert_batch(
                full,
                _datapoints_row(value=1.0, created_at="2024-06-01T00:00:00"),
                conflict_strategy="ignore",
            )
            mgr.insert_batch(
                full,
                _datapoints_row(value=999.0, created_at="2024-01-01T00:00:00"),
                conflict_strategy="ignore",
            )
            rows = mgr.execute_query(f"SELECT value FROM {full}")
            assert rows[0]["value"] == 1.0
        finally:
            mgr.close()

    def test_version_aware_last_writer_wins_newer_overwrites(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
            mgr.create_table(full, get_datapoints_table_model())
            mgr.insert_batch(
                full,
                _datapoints_row(value=1.0, created_at="2024-06-01T00:00:00"),
                conflict_strategy="ignore",
            )
            mgr.insert_batch(
                full,
                _datapoints_row(value=42.0, created_at="2024-12-01T00:00:00"),
                conflict_strategy="ignore",
            )
            rows = mgr.execute_query(f"SELECT value FROM {full}")
            assert rows[0]["value"] == 42.0
        finally:
            mgr.close()

    def test_equal_version_counts_as_newer_and_overwrites(self, tmp_path):
        # Mirrors ReplacingMergeTree: `<=` in the WHERE guard means an
        # incoming row with an *equal* version still wins.
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
            mgr.create_table(full, get_datapoints_table_model())
            mgr.insert_batch(
                full,
                _datapoints_row(value=1.0, created_at="2024-06-01T00:00:00"),
                conflict_strategy="ignore",
            )
            mgr.insert_batch(
                full,
                _datapoints_row(value=7.0, created_at="2024-06-01T00:00:00"),
                conflict_strategy="ignore",
            )
            rows = mgr.execute_query(f"SELECT value FROM {full}")
            assert rows[0]["value"] == 7.0
        finally:
            mgr.close()


class TestCoerce:
    def test_nan_value_becomes_null(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
            mgr.create_table(full, get_datapoints_table_model())
            mgr.insert_batch(full, _datapoints_row(value=float("nan")))
            rows = mgr.execute_query(f"SELECT value FROM {full}")
            assert rows[0]["value"] is None
        finally:
            mgr.close()

    def test_nat_timestamp_coerces_to_none(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            assert mgr._coerce(np.datetime64("NaT")) is None
        finally:
            mgr.close()

    def test_numpy_scalar_coercions(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            out = mgr._coerce(np.datetime64("2024-03-04T05:06:07", "ms"))
            assert out == datetime(2024, 3, 4, 5, 6, 7)
            assert out.tzinfo is None
            assert mgr._coerce(np.int32(7)) == 7
            assert isinstance(mgr._coerce(np.int32(7)), int)
            assert mgr._coerce(np.bool_(True)) is True
            assert mgr._coerce(np.float64("nan")) is None
        finally:
            mgr.close()


class TestUpsertRecordAndTaskStatus:
    def test_upsert_record_replaces_in_place(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_TASKS, use_internal=True)
            mgr.create_table(full, get_tasks_table_model())
            mgr.upsert_task_status("cpu", "load", "load", "running", timeout_seconds=10)
            mgr.upsert_task_status("cpu", "load", "load", "completed", timeout_seconds=10)
            rows = mgr.execute_query(f"SELECT status FROM {full} WHERE metric_name = 'cpu'")
            assert len(rows) == 1
            assert rows[0]["status"] == "completed"
        finally:
            mgr.close()

    def test_upsert_task_status_does_not_duplicate_pk(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_TASKS, use_internal=True)
            mgr.create_table(full, get_tasks_table_model())
            for _ in range(3):
                mgr.upsert_task_status("cpu", "load", "load", "running", timeout_seconds=10)
            rows = mgr.execute_query(f"SELECT count(*) AS n FROM {full}")
            assert rows[0]["n"] == 1
        finally:
            mgr.close()


class TestDeleteRows:
    def test_delete_rows_returns_real_deleted_count(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
            mgr.create_table(full, get_datapoints_table_model())
            mgr.insert_batch(full, _datapoints_row(ts="2024-01-01T00:00:00"))
            mgr.insert_batch(full, _datapoints_row(ts="2024-01-01T00:10:00"))
            mgr.insert_batch(full, _datapoints_row(ts="2024-01-01T00:20:00"))
            n = mgr.delete_rows(full, "metric_name = %(m)s", {"m": "cpu"})
            assert n == 3
            remaining = mgr.execute_query(f"SELECT count(*) AS n FROM {full}")
            assert remaining[0]["n"] == 0
        finally:
            mgr.close()

    def test_delete_rows_no_match_returns_zero(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
            mgr.create_table(full, get_datapoints_table_model())
            n = mgr.delete_rows(full, "metric_name = %(m)s", {"m": "nonexistent"})
            assert n == 0
        finally:
            mgr.close()


class TestRollback:
    def test_failed_statement_rolls_back_and_leaves_prior_state(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_TASKS, use_internal=True)
            mgr.create_table(full, get_tasks_table_model())
            mgr.upsert_task_status("cpu", "load", "load", "running", timeout_seconds=10)

            with pytest.raises(duckdb.Error):
                with mgr._conn.cursor() as cur:
                    # Missing required NOT NULL columns -> constraint failure.
                    cur.execute(f"INSERT INTO {full} (metric_name) VALUES ('broken')")
                mgr._conn.commit()
            mgr._conn.rollback()

            rows = mgr.execute_query(f"SELECT metric_name, status FROM {full}")
            assert rows == [{"metric_name": "cpu", "status": "running"}]
        finally:
            mgr.close()

    def test_insert_batch_conflict_strategy_fail_rolls_back_whole_batch(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
            mgr.create_table(full, get_datapoints_table_model())
            mgr.insert_batch(full, _datapoints_row(ts="2024-01-01T00:00:00"))
            with pytest.raises(duckdb.Error):
                # Duplicate PK under conflict_strategy="fail" -> constraint error.
                mgr.insert_batch(
                    full, _datapoints_row(ts="2024-01-01T00:00:00"), conflict_strategy="fail"
                )
            rows = mgr.execute_query(f"SELECT count(*) AS n FROM {full}")
            assert rows[0]["n"] == 1
        finally:
            mgr.close()


class TestPlaceholderTranslation:
    def test_pyformat_params_round_trip(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            rows = mgr.execute_query("SELECT %(a)s AS a, %(b)s AS b", {"a": 5, "b": "hello"})
            assert rows == [{"a": 5, "b": "hello"}]
        finally:
            mgr.close()

    def test_pyformat_repeated_param_in_where_clause(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            full = mgr.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
            mgr.create_table(full, get_datapoints_table_model())
            mgr.insert_batch(full, _datapoints_row(metric_name="cpu"))
            mgr.insert_batch(full, _datapoints_row(metric_name="mem", ts="2024-01-01T00:01:00"))
            rows = mgr.execute_query(
                f"SELECT metric_name FROM {full} WHERE metric_name = %(m)s", {"m": "cpu"}
            )
            assert rows == [{"metric_name": "cpu"}]
        finally:
            mgr.close()


class TestReadOnly:
    def test_read_only_connect_can_select_from_existing_file(self, tmp_path):
        path = _db_path(tmp_path)
        mgr = DuckDBDatabaseManager(path=path)
        full = mgr.get_full_table_name(TABLE_DATAPOINTS, use_internal=True)
        mgr.create_table(full, get_datapoints_table_model())
        mgr.insert_batch(full, _datapoints_row())
        mgr.close()

        reader = DuckDBDatabaseManager(path=path, read_only=True)
        try:
            rows = reader.execute_query(f"SELECT value FROM {full}")
            assert rows == [{"value": 1.0}]
            with pytest.raises(duckdb.Error):
                reader.execute_query(f"INSERT INTO {full} DEFAULT VALUES")
        finally:
            reader.close()


class TestInternalTablesManagerSmoke:
    def test_ensure_tables_then_datapoints_and_detections_round_trip(self, tmp_path):
        mgr = _make_manager(tmp_path)
        try:
            itm = InternalTablesManager(mgr)
            itm.ensure_tables()

            assert mgr.table_exists(TABLE_DATAPOINTS, schema=mgr.internal_location)
            assert mgr.table_exists(TABLE_DETECTIONS, schema=mgr.internal_location)
            assert mgr.table_exists(TABLE_TASKS, schema=mgr.internal_location)

            timestamps = np.array(
                [
                    np.datetime64("2024-01-01T00:00:00", "ms"),
                    np.datetime64("2024-01-01T00:10:00", "ms"),
                ]
            )
            itm.save_datapoints(
                "cpu",
                {
                    "timestamp": timestamps,
                    "value": np.array([1.0, 2.0]),
                    "seasonality_data": np.array(["{}", "{}"], dtype=object),
                },
                600,
                ["hour"],
            )
            loaded = itm.load_datapoints("cpu")
            assert list(loaded["value"]) == [1.0, 2.0]
            assert loaded["seasonality_columns"] == ["hour"]

            itm.save_detections(
                "cpu",
                "det1",
                "MADDetector",
                {
                    "timestamp": timestamps,
                    "is_anomaly": np.array([False, True]),
                    "confidence_lower": np.array([0.0, 0.0]),
                    "confidence_upper": np.array([10.0, 10.0]),
                    "value": np.array([1.0, 2.0]),
                    "processed_value": np.array([1.0, 2.0]),
                    "detection_metadata": np.array(["{}", "{}"], dtype=object),
                },
                "{}",
            )
            detections = itm.load_detections("cpu")
            assert len(detections) == 2
            assert detections[1]["is_anomaly"] is True

            assert itm.get_last_datapoint_timestamp("cpu") == datetime(2024, 1, 1, 0, 10, 0)
            assert itm.get_last_detection_timestamp("cpu", "det1") == datetime(2024, 1, 1, 0, 10, 0)

            # The alert step's quorum fetch — its ``timestamp IN %(timestamps)s``
            # query binds a tuple as a DuckDB LIST parameter, which only parses
            # on duckdb >= 1.1 (the reason for the pyproject floor). Exercise it
            # end-to-end so a floor regression fails loudly here.
            recent = itm.get_recent_detections(
                "cpu", last_point=datetime(2024, 1, 1, 0, 10, 0), num_points=2
            )
            assert len(recent) == 2
            # Newest timestamp first; its single detector row was the anomaly.
            assert recent[0]["is_anomaly_flags"] == [True]
            assert recent[1]["is_anomaly_flags"] == [False]
        finally:
            mgr.close()


# ── MotherDuck (`md:` paths) — connect-seam tests, no cloud round trip ────────
# The real MotherDuck attach needs the `motherduck` extension + network + a
# token (covered by the env-gated tests/integration/test_motherduck.py); what
# is unit-testable is the connect seam: how `md:` paths change the config dict
# and the strict-probe read-only forcing.


class _FakeRaw:
    """Minimal stand-in for duckdb.DuckDBPyConnection (connect seam only)."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class TestMotherDuckConnectSeam:
    def _capture_connect(self, monkeypatch) -> dict:
        import detectkit.database.duckdb_manager as mod

        captured: dict = {}

        def fake_connect(path, read_only=False, config=None):
            captured.update(path=path, read_only=read_only, config=config)
            return _FakeRaw()

        monkeypatch.setattr(mod.duckdb, "connect", fake_connect)
        return captured

    def test_token_threaded_into_config_for_md_path(self, monkeypatch):
        captured = self._capture_connect(monkeypatch)
        DuckDBDatabaseManager(
            path="md:analytics", motherduck_token="tok-123", ensure_locations=False
        )
        assert captured["path"] == "md:analytics"
        assert captured["config"]["motherduck_token"] == "tok-123"

    def test_settings_win_over_token_field_on_collision(self, monkeypatch):
        captured = self._capture_connect(monkeypatch)
        DuckDBDatabaseManager(
            path="md:analytics",
            motherduck_token="from-field",
            settings={"motherduck_token": "from-settings"},
            ensure_locations=False,
        )
        assert captured["config"]["motherduck_token"] == "from-settings"

    def test_token_ignored_for_local_paths(self, monkeypatch, tmp_path):
        captured = self._capture_connect(monkeypatch)
        DuckDBDatabaseManager(
            path=str(tmp_path / "x.duckdb"),
            motherduck_token="tok-123",
            ensure_locations=False,
        )
        assert "motherduck_token" not in (captured["config"] or {})

    def test_strict_probe_does_not_force_read_only_for_md(self, monkeypatch):
        """MotherDuck has no read-only attach, and there is no local file a
        connect could create — the ensure_locations=False probe must not
        force read_only for md: paths (it still runs no DDL)."""
        captured = self._capture_connect(monkeypatch)
        DuckDBDatabaseManager(path="md:analytics", ensure_locations=False)
        assert captured["read_only"] is False

    def test_strict_probe_still_forces_read_only_for_local_files(self, monkeypatch, tmp_path):
        captured = self._capture_connect(monkeypatch)
        DuckDBDatabaseManager(path=str(tmp_path / "x.duckdb"), ensure_locations=False)
        assert captured["read_only"] is True

    def test_explicit_read_only_on_md_passes_through(self, monkeypatch):
        """Deliberate semantics: an explicit read_only=True on an md: path is
        passed through (MotherDuck rejects it loudly at connect) rather than
        silently dropped — silently opening read-write when the user asked
        for a read-only guarantee would be worse. Docs say: leave it unset."""
        captured = self._capture_connect(monkeypatch)
        DuckDBDatabaseManager(path="md:analytics", read_only=True)
        assert captured["read_only"] is True
