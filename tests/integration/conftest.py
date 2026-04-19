"""Integration-test fixtures.

Spins up a real ClickHouse server in Docker (via ``testcontainers``) so
the suite can exercise the database layer end-to-end. The whole module
is skipped when ``testcontainers`` or Docker is unavailable, which keeps
``pytest -m "not integration"`` working in environments without Docker.
"""

from __future__ import annotations

import socket
from typing import Iterator

import pytest

# All tests in tests/integration/** are flagged as integration so the
# main CI job (``-m "not integration"``) skips them by default.
pytestmark = pytest.mark.integration

testcontainers = pytest.importorskip(
    "testcontainers.clickhouse",
    reason="install testcontainers[clickhouse] to run integration tests",
)


def _docker_available() -> bool:
    """Cheap probe: does the local docker socket accept connections?"""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(1.0)
            sock.connect("/var/run/docker.sock")
            return True
    except OSError:
        return False


if not _docker_available():  # pragma: no cover - environment dependent
    pytest.skip(
        "Docker daemon not reachable; skipping integration suite",
        allow_module_level=True,
    )


@pytest.fixture(scope="session")
def clickhouse_container() -> Iterator:
    """Run a single ClickHouse container for the whole session."""
    from testcontainers.clickhouse import ClickHouseContainer

    container = ClickHouseContainer("clickhouse/clickhouse-server:24.3")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture()
def clickhouse_manager(clickhouse_container):
    """Hand each test a fresh ``ClickHouseDatabaseManager`` instance."""
    from detectkit.database.clickhouse_manager import ClickHouseDatabaseManager

    manager = ClickHouseDatabaseManager(
        host=clickhouse_container.get_container_host_ip(),
        port=int(clickhouse_container.get_exposed_port(9000)),
        user=clickhouse_container.username,
        password=clickhouse_container.password,
        internal_database="detectkit_internal_it",
        data_database="detectkit_data_it",
    )
    try:
        yield manager
    finally:
        manager.close()


@pytest.fixture()
def internal_tables(clickhouse_manager):
    """Provision the ``_dtk_*`` tables for the test."""
    from detectkit.database.internal_tables import InternalTablesManager

    internal = InternalTablesManager(clickhouse_manager)
    internal.ensure_tables()
    return internal
