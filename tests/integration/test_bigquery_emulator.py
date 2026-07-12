"""End-to-end checks against a real BigQuery emulator.

Runs the goccy/bigquery-emulator Docker image (multi-arch, actively
maintained) and talks to it through the **real** ``google-cloud-bigquery``
client via the profile's ``api_endpoint`` override — the exact no-GCP-account
path documented for users. Covers the eager connect probe, ``dataset`` →
``default_dataset`` resolution of unqualified table names, tz-aware UTC
TIMESTAMP results, and the hybrid load path into a DuckDB state file.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("google.cloud.bigquery")

from testcontainers.core.container import DockerContainer  # noqa: E402
from testcontainers.core.waiting_utils import wait_for_logs  # noqa: E402

from detectkit.config.profile import ProfileConfig  # noqa: E402
from detectkit.database.bigquery_manager import BigQuerySourceManager  # noqa: E402

_IMAGE = "ghcr.io/goccy/bigquery-emulator:latest"
_PROJECT = "test"
_DATASET = "src"


@pytest.fixture(scope="module")
def bigquery_endpoint() -> Iterator[str]:
    container = (
        DockerContainer(_IMAGE)
        .with_command(f"--project={_PROJECT} --dataset={_DATASET}")
        .with_exposed_ports(9050)
    )
    container.start()
    try:
        wait_for_logs(container, "listening", timeout=120)
        host = container.get_container_host_ip()
        port = container.get_exposed_port(9050)
        yield f"http://{host}:{port}"
    finally:
        container.stop()


@pytest.fixture(scope="module")
def source_manager(bigquery_endpoint: str) -> Iterator[BigQuerySourceManager]:
    """Build the manager through the REAL profile seam (probe included)."""
    profile = ProfileConfig(
        type="bigquery",
        project=_PROJECT,
        dataset=_DATASET,
        api_endpoint=bigquery_endpoint,
    )
    manager = profile.create_source_manager()
    assert isinstance(manager, BigQuerySourceManager)

    # Seed with dataset-QUALIFIED names: the emulator does not apply
    # default_dataset to DDL/DML (it fails them with a retried-for-minutes
    # jobInternalError). Reads below stay unqualified on purpose — they prove
    # `dataset` -> default_dataset resolution on the load-query path.
    manager.execute_query(f"CREATE TABLE {_DATASET}.events (ts TIMESTAMP, value FLOAT64)")
    manager.execute_query(
        f"INSERT INTO {_DATASET}.events (ts, value) VALUES "
        "(TIMESTAMP('2024-01-01 00:00:00'), 1.0), "
        "(TIMESTAMP('2024-01-01 00:01:00'), 2.0), "
        "(TIMESTAMP('2024-01-01 00:02:00'), 3.0)"
    )
    try:
        yield manager
    finally:
        manager.close()
        manager.close()  # idempotent


def test_query_returns_tz_aware_utc_rows(source_manager: BigQuerySourceManager):
    """TIMESTAMP columns come back tz-aware UTC; aliases keep their case
    (VALUE_UC discriminates against a Snowflake-style uppercase fold)."""
    rows = source_manager.execute_query(
        "SELECT ts AS timestamp, value AS value, value AS VALUE_UC FROM events ORDER BY ts"
    )
    assert [set(r.keys()) for r in rows] == [{"timestamp", "value", "VALUE_UC"}] * 3
    assert [r["value"] for r in rows] == [1.0, 2.0, 3.0]
    assert [r["VALUE_UC"] for r in rows] == [1.0, 2.0, 3.0]
    first = rows[0]["timestamp"]
    assert first.tzinfo is not None
    assert first.astimezone(timezone.utc).replace(tzinfo=None) == datetime(2024, 1, 1, 0, 0)


def test_hybrid_load_bigquery_source_duckdb_state(source_manager: BigQuerySourceManager, tmp_path):
    """The metric's SQL runs on the emulator; datapoints land in DuckDB state."""
    pytest.importorskip("duckdb")
    from detectkit.config.metric_config import MetricConfig
    from detectkit.database.duckdb_manager import DuckDBDatabaseManager
    from detectkit.database.internal_tables import InternalTablesManager
    from detectkit.orchestration.task_manager import TaskManager

    class _OneManagerProfiles:
        def create_source_manager(self, profile_name: str) -> BigQuerySourceManager:
            assert profile_name == "warehouse"
            return source_manager

    state_manager = DuckDBDatabaseManager(path=str(tmp_path / "state.duckdb"))
    internal = InternalTablesManager(state_manager)
    internal.ensure_tables()
    try:
        config = MetricConfig(
            name="hybrid_bq_metric",
            interval="1min",
            query=(
                "SELECT ts AS timestamp, value AS value FROM events "
                "WHERE ts >= TIMESTAMP('{{ dtk_start_time }}') "
                "AND ts < TIMESTAMP('{{ dtk_end_time }}')"
            ),
            loading_start_time="2024-01-01 00:00:00",
            source_profile="warehouse",
        )

        tm = TaskManager(
            internal_manager=internal,
            db_manager=state_manager,
            profiles_config=_OneManagerProfiles(),
            project_config=None,
            state_profile_name="state",
        )

        result = tm._run_load_step(
            config,
            from_date=datetime(2024, 1, 1, 0, 0),
            to_date=datetime(2024, 1, 1, 0, 3),
            full_refresh=False,
        )
        assert result["points_loaded"] == 3

        last_ts = internal.get_last_datapoint_timestamp("hybrid_bq_metric")
        assert last_ts == datetime(2024, 1, 1, 0, 2)
    finally:
        state_manager.close()
