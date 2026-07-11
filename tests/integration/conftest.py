"""Integration-test fixtures.

Spins up real ClickHouse, PostgreSQL, MySQL, and MariaDB servers in Docker (via
``testcontainers``) so the database layer is exercised end-to-end against every
supported backend. The whole module is skipped when ``testcontainers`` or Docker
is unavailable, which keeps ``pytest -m "not integration"`` working in
environments without Docker. Each per-backend container fixture additionally
``importorskip``s its own ``testcontainers`` submodule, so a backend whose extra
is not installed is skipped individually rather than failing the suite.

The ``internal_tables`` fixture is parametrized over the four backends, so every
``test_*_e2e`` assertion runs against ClickHouse, PostgreSQL, MySQL, and MariaDB.
MariaDB reuses ``testcontainers``' ``MySqlContainer`` (the official ``mariadb``
image accepts the same ``MYSQL_*`` env vars) rather than a dedicated
``MariaDbContainer`` class.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator

import pytest

# All tests in tests/integration/** are flagged as integration so the
# main CI job (``-m "not integration"``) skips them by default.
pytestmark = pytest.mark.integration

pytest.importorskip("testcontainers", reason="install the 'integration' extra to run these tests")


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


# ── per-backend containers (session-scoped, started lazily) ──────────────────


@pytest.fixture(scope="session")
def clickhouse_container() -> Iterator:
    cc = pytest.importorskip("testcontainers.clickhouse")
    container = cc.ClickHouseContainer("clickhouse/clickhouse-server:24.3")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def postgres_container() -> Iterator:
    pc = pytest.importorskip("testcontainers.postgres")
    container = pc.PostgresContainer("postgres:16")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def mysql_container() -> Iterator:
    mc = pytest.importorskip("testcontainers.mysql")
    # Connect as root so the manager may CREATE DATABASE for its locations.
    container = mc.MySqlContainer("mysql:8.0", username="root", password="testpwd")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def mariadb_container() -> Iterator:
    mc = pytest.importorskip("testcontainers.mysql")
    # No dedicated MariaDbContainer class in testcontainers; the official
    # `mariadb` image accepts the same MYSQL_* env vars, so MySqlContainer
    # works unmodified against it.
    container = mc.MySqlContainer("mariadb:11.4", username="root", password="testpwd")
    container.start()
    try:
        yield container
    finally:
        container.stop()


# ── parametrized manager / internal-tables fixtures ──────────────────────────


@pytest.fixture(params=["clickhouse", "postgres", "mysql", "mariadb"])
def db_manager(request):
    """A fresh database manager per backend (parametrized)."""
    backend = request.param
    container = request.getfixturevalue(f"{backend}_container")
    host = container.get_container_host_ip()

    if backend == "clickhouse":
        from detectkit.database.clickhouse_manager import ClickHouseDatabaseManager

        manager = ClickHouseDatabaseManager(
            host=host,
            port=int(container.get_exposed_port(9000)),
            user=container.username,
            password=container.password,
            internal_database="detectkit_internal_it",
            data_database="detectkit_data_it",
        )
    elif backend == "postgres":
        from detectkit.database.postgres_manager import PostgresDatabaseManager

        manager = PostgresDatabaseManager(
            host=host,
            port=int(container.get_exposed_port(5432)),
            user=container.username,
            password=container.password,
            database=container.dbname,
            internal_schema="detectkit_internal_it",
            data_schema="detectkit_data_it",
        )
    else:  # mysql / mariadb — same manager, same container port (3306)
        from detectkit.database.mysql_manager import MySQLDatabaseManager

        manager = MySQLDatabaseManager(
            host=host,
            port=int(container.get_exposed_port(3306)),
            user=container.username,
            password=container.password,
            internal_database="detectkit_internal_it",
            data_database="detectkit_data_it",
        )

    try:
        yield manager
    finally:
        manager.close()


@pytest.fixture()
def internal_tables(db_manager):
    """Provision the ``_dtk_*`` tables on the active backend for the test."""
    from detectkit.database.internal_tables import InternalTablesManager

    internal = InternalTablesManager(db_manager)
    internal.ensure_tables()
    return internal
