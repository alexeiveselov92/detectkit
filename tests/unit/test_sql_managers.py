"""Unit tests for the PostgreSQL and MySQL backends.

These are mock-based: the DB-API connection is faked so the tests run without a
real database or the psycopg2/pymysql drivers installed. They assert the SQL the
managers generate (DDL with enforced PK, version-aware upserts, plain DELETE)
and the numpy → driver value coercion. End-to-end behaviour against real servers
is covered by the testcontainers integration suite.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

import detectkit.database.mysql_manager as mysql_mod
import detectkit.database.postgres_manager as pg_mod
from detectkit.database.tables import (
    TABLE_DATAPOINTS,
    TABLE_TASKS,
    get_datapoints_table_model,
    get_tasks_table_model,
)


class FakeCursor:
    def __init__(self, conn: FakeConn) -> None:
        self.conn = conn

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    @property
    def description(self):
        return self.conn.next_description

    @property
    def rowcount(self) -> int:
        return self.conn.next_rowcount

    def execute(self, sql: str, params=None) -> None:
        self.conn.executed.append((sql, params))

    def executemany(self, sql: str, seq) -> None:
        rows = list(seq)
        self.conn.executed.append((sql, rows))
        self.conn.next_rowcount = len(rows)

    def fetchall(self):
        return self.conn.next_result


class FakeConn:
    def __init__(self) -> None:
        self.executed: list[tuple] = []
        self.next_description = None
        self.next_result: list[tuple] = []
        self.next_rowcount = 0
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        pass

    # convenience: SQL of the last executed statement
    @property
    def last_sql(self) -> str:
        return self.executed[-1][0]


def _make_manager(backend: str, monkeypatch):
    conn = FakeConn()
    if backend == "postgres":
        monkeypatch.setattr(pg_mod, "PSYCOPG2_AVAILABLE", True)
        monkeypatch.setattr(pg_mod.PostgresDatabaseManager, "_connect", lambda self: conn)
        monkeypatch.setattr(pg_mod.PostgresDatabaseManager, "_ensure_locations", lambda self: None)
        mgr = pg_mod.PostgresDatabaseManager(
            database="db", internal_schema="dtk", data_schema="public"
        )
    else:
        # "mariadb" is the same MySQLDatabaseManager with vendor detection
        # forced on, since _connect (where detection normally runs) is stubbed.
        monkeypatch.setattr(mysql_mod, "PYMYSQL_AVAILABLE", True)
        monkeypatch.setattr(mysql_mod.MySQLDatabaseManager, "_connect", lambda self: conn)
        monkeypatch.setattr(mysql_mod.MySQLDatabaseManager, "_ensure_locations", lambda self: None)
        mgr = mysql_mod.MySQLDatabaseManager(internal_database="dtk", data_database="analytics")
        if backend == "mariadb":
            mgr._is_mariadb = True
    return mgr, conn


@pytest.fixture(params=["postgres", "mysql", "mariadb"])
def backend(request):
    return request.param


@pytest.fixture
def mgr_conn(backend, monkeypatch):
    mgr, conn = _make_manager(backend, monkeypatch)
    return mgr, conn, backend


class TestDDL:
    def test_create_table_emits_pk_and_no_clickhouse_engine(self, mgr_conn):
        mgr, conn, backend = mgr_conn
        q = mgr._IDENT_QUOTE
        mgr.create_table(f"dtk.{TABLE_DATAPOINTS}", get_datapoints_table_model())
        ddl = conn.last_sql
        assert f"PRIMARY KEY ({q}metric_name{q}, {q}timestamp{q})" in ddl
        assert "ENGINE" not in ddl and "ReplacingMergeTree" not in ddl and "ORDER BY" not in ddl
        # version/PK metadata is recorded for the insert path
        assert mgr._table_meta[TABLE_DATAPOINTS] == (
            ["metric_name", "timestamp"],
            "created_at",
        )

    def test_type_mapping_per_dialect(self, mgr_conn):
        mgr, conn, backend = mgr_conn
        q = mgr._IDENT_QUOTE
        mgr.create_table(f"dtk.{TABLE_DATAPOINTS}", get_datapoints_table_model())
        ddl = conn.last_sql
        if backend == "postgres":
            assert f"{q}metric_name{q} TEXT NOT NULL" in ddl
            assert f"{q}timestamp{q} TIMESTAMP(3) NOT NULL" in ddl
            assert f"{q}value{q} DOUBLE PRECISION" in ddl
            assert f"{q}interval_seconds{q} INTEGER NOT NULL" in ddl
        else:
            # MySQL: PK String must be VARCHAR (TEXT can't be PK-indexed); the
            # JSON/text columns stay TEXT.
            assert f"{q}metric_name{q} VARCHAR(255) NOT NULL" in ddl
            assert f"{q}seasonality_data{q} TEXT NOT NULL" in ddl
            assert f"{q}timestamp{q} DATETIME(3) NOT NULL" in ddl
            assert f"{q}value{q} DOUBLE" in ddl

    def test_reserved_word_column_is_quoted(self, mgr_conn):
        # `interval` is a reserved word on MySQL; it must be quoted in the DDL.
        from detectkit.database.tables import TABLE_METRICS, get_metrics_table_model

        mgr, conn, _ = mgr_conn
        q = mgr._IDENT_QUOTE
        mgr.create_table(f"dtk.{TABLE_METRICS}", get_metrics_table_model())
        assert f"{q}interval{q} " in conn.last_sql

    def test_nullable_value_column_has_no_not_null(self, mgr_conn):
        mgr, conn, _ = mgr_conn
        q = mgr._IDENT_QUOTE
        mgr.create_table(f"dtk.{TABLE_DATAPOINTS}", get_datapoints_table_model())
        ddl = conn.last_sql
        # value is Nullable(Float64) -> no NOT NULL
        value_line = next(
            line for line in ddl.splitlines() if line.strip().startswith(f"{q}value{q} ")
        )
        assert "NOT NULL" not in value_line


class TestInsertConflict:
    def test_versioned_ignore_is_last_writer_wins_upsert(self, mgr_conn):
        mgr, conn, backend = mgr_conn
        mgr.create_table(f"dtk.{TABLE_DATAPOINTS}", get_datapoints_table_model())
        full = f"dtk.{TABLE_DATAPOINTS}"
        data = {
            "metric_name": np.array(["cpu"]),
            "timestamp": np.array([np.datetime64("2024-01-01T00:00:00", "ms")]),
            "value": np.array([1.0]),
            "seasonality_data": np.array(["{}"]),
            "interval_seconds": np.array([60], dtype=np.int32),
            "seasonality_columns": np.array(["hour"]),
            "created_at": np.array([np.datetime64("2024-01-01T00:00:00", "ms")]),
        }
        mgr.insert_batch(full, data, conflict_strategy="ignore")
        sql = conn.last_sql
        q = mgr._IDENT_QUOTE
        if backend == "postgres":
            assert f"ON CONFLICT ({q}metric_name{q}, {q}timestamp{q}) DO UPDATE SET" in sql
            assert f"WHERE _dtk_datapoints.{q}created_at{q} <= EXCLUDED.{q}created_at{q}" in sql
        elif backend == "mariadb":
            # MariaDB has no row-alias upsert: no "AS new", VALUES() instead.
            assert "ON DUPLICATE KEY UPDATE" in sql
            assert "AS new" not in sql
            assert f"VALUES({q}created_at{q})" in sql
            assert f"IF(VALUES({q}created_at{q}) >= {q}_dtk_datapoints{q}.{q}created_at{q}" in sql
        else:
            assert "AS new ON DUPLICATE KEY UPDATE" in sql
            assert f"IF(new.{q}created_at{q} >= {q}_dtk_datapoints{q}.{q}created_at{q}" in sql
        assert conn.commits >= 1

    def test_insert_coerces_nan_to_none(self, mgr_conn):
        mgr, conn, _ = mgr_conn
        mgr.create_table(f"dtk.{TABLE_DATAPOINTS}", get_datapoints_table_model())
        data = {
            "metric_name": np.array(["cpu"]),
            "timestamp": np.array([np.datetime64("2024-01-01T00:00:00", "ms")]),
            "value": np.array([np.nan]),
            "seasonality_data": np.array(["{}"]),
            "interval_seconds": np.array([60], dtype=np.int32),
            "seasonality_columns": np.array(["hour"]),
            "created_at": np.array([np.datetime64("2024-01-01T00:00:00", "ms")]),
        }
        mgr.insert_batch(f"dtk.{TABLE_DATAPOINTS}", data, conflict_strategy="ignore")
        rows = conn.executed[-1][1]
        # the value cell (index 2) was NaN -> None
        assert rows[0][2] is None


class TestDeleteAndUpsert:
    def test_delete_rows_uses_plain_delete(self, mgr_conn):
        mgr, conn, _ = mgr_conn
        conn.next_rowcount = 3
        n = mgr.delete_rows("dtk._dtk_datapoints", "metric_name = %(m)s", {"m": "cpu"}, sync=True)
        sql = conn.last_sql
        assert sql.startswith("DELETE FROM dtk._dtk_datapoints WHERE")
        assert "ALTER TABLE" not in sql and "mutations_sync" not in sql
        assert n == 3

    def test_upsert_record_deletes_then_inserts(self, mgr_conn):
        mgr, conn, _ = mgr_conn
        mgr.create_table(f"dtk.{TABLE_TASKS}", get_tasks_table_model())
        conn.executed.clear()
        conn.commits = 0
        mgr.upsert_task_status("cpu", "load", "load", "running", timeout_seconds=10)
        kinds = [sql.split()[0] for sql, _ in conn.executed]
        assert kinds[0] == "DELETE"
        assert kinds[1] == "INSERT"
        # delete + insert committed together, once (atomic)
        assert conn.commits == 1

    def test_get_last_timestamp_null_is_none(self, mgr_conn):
        mgr, conn, _ = mgr_conn
        conn.next_description = [("last_ts",)]
        conn.next_result = [(None,)]
        assert mgr.get_last_timestamp("dtk._dtk_datapoints", "cpu") is None

    def test_get_last_timestamp_returns_value(self, mgr_conn):
        mgr, conn, _ = mgr_conn
        dt = datetime(2024, 1, 1, 12, 0, 0)
        conn.next_description = [("last_ts",)]
        conn.next_result = [(dt,)]
        assert mgr.get_last_timestamp("dtk._dtk_datapoints", "cpu") == dt


class TestCoerce:
    def test_numpy_datetime_to_naive_utc(self, mgr_conn):
        mgr, _, _ = mgr_conn
        out = mgr._coerce(np.datetime64("2024-03-04T05:06:07", "ms"))
        assert out == datetime(2024, 3, 4, 5, 6, 7)
        assert out.tzinfo is None

    def test_scalar_conversions(self, mgr_conn):
        mgr, _, _ = mgr_conn
        assert mgr._coerce(np.int32(7)) == 7 and isinstance(mgr._coerce(np.int32(7)), int)
        assert mgr._coerce(np.bool_(True)) is True
        assert mgr._coerce(np.float64("nan")) is None
        assert mgr._coerce(None) is None
        assert mgr._coerce("text") == "text"


class _VersionFakeCursor:
    """Answers ``SELECT VERSION()`` with a fixed row, for `_detect_mariadb`."""

    def __init__(self, version_row: tuple | None) -> None:
        self._version_row = version_row

    def __enter__(self) -> _VersionFakeCursor:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False

    def execute(self, sql: str, params=None) -> None:
        pass

    def fetchone(self):
        return self._version_row


class _VersionFakeConn:
    def __init__(self, version_row: tuple | None) -> None:
        self._version_row = version_row

    def cursor(self) -> _VersionFakeCursor:
        return _VersionFakeCursor(self._version_row)


class _RaisingConn:
    """A connection whose ``cursor()`` blows up, exercising the fallback path."""

    def cursor(self):
        raise RuntimeError("connection lost")


class TestMariaDbDetection:
    def test_mariadb_version_string_detected(self):
        conn = _VersionFakeConn(("11.4.2-MariaDB-log",))
        assert mysql_mod.MySQLDatabaseManager._detect_mariadb(conn) is True

    def test_stock_mysql_version_string_is_not_mariadb(self):
        conn = _VersionFakeConn(("8.0.36",))
        assert mysql_mod.MySQLDatabaseManager._detect_mariadb(conn) is False

    def test_query_failure_defaults_to_false(self):
        assert mysql_mod.MySQLDatabaseManager._detect_mariadb(_RaisingConn()) is False
