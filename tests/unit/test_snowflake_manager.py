"""Real-engine unit tests for the Snowflake source-only backend.

Like ``test_duckdb_manager.py`` (real in-process engine, no Docker), the live
behavior here runs against `fakesnow <https://github.com/tekumara/fakesnow>`_ —
a DuckDB-backed in-process fake of ``snowflake.connector`` — patched in with
``fakesnow.patch()``. The connect-kwargs / auth / column-fold seams are exercised
directly (no connection needed); only the end-to-end query + hybrid-load paths
need the fake engine.
"""

from __future__ import annotations

from datetime import datetime

import pytest

pytest.importorskip("snowflake.connector")
pytest.importorskip("fakesnow")

import fakesnow  # noqa: E402
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from detectkit.database.snowflake_manager import SnowflakeSourceManager  # noqa: E402


def _write_pem(tmp_path, passphrase: bytes | None = None):
    """Generate an RSA key, write its PEM to ``tmp_path``, return (path, key)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    enc = (
        serialization.BestAvailableEncryption(passphrase)
        if passphrase is not None
        else serialization.NoEncryption()
    )
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, enc)
    path = tmp_path / "key.pem"
    path.write_bytes(pem)
    return str(path), key


# ── _connect_kwargs seam (no connection) ─────────────────────────────────────


class TestConnectKwargs:
    def _mgr(self, **kwargs) -> SnowflakeSourceManager:
        """Build a manager without connecting (skip __init__'s connect)."""
        mgr = SnowflakeSourceManager.__new__(SnowflakeSourceManager)
        defaults = {
            "account": "acct",
            "user": "usr",
            "password": None,
            "private_key_path": None,
            "private_key_passphrase": None,
            "warehouse": None,
            "database": None,
            "schema": None,
            "role": None,
            "settings": {},
        }
        defaults.update(kwargs)
        for name, value in defaults.items():
            setattr(mgr, f"_{name}", value)
        return mgr

    def test_timezone_pinned_utc_by_default(self):
        kw = self._mgr(password="pw")._connect_kwargs()
        assert kw["session_parameters"] == {"TIMEZONE": "UTC"}
        assert kw["account"] == "acct"
        assert kw["user"] == "usr"

    def test_settings_override_timezone(self):
        kw = self._mgr(
            password="pw",
            settings={"TIMEZONE": "America/New_York", "QUERY_TAG": "dtk"},
        )._connect_kwargs()
        # settings wins on key collision.
        assert kw["session_parameters"]["TIMEZONE"] == "America/New_York"
        assert kw["session_parameters"]["QUERY_TAG"] == "dtk"

    def test_optional_fields_only_when_set(self):
        kw = self._mgr(password="pw")._connect_kwargs()
        for absent in ("warehouse", "database", "schema", "role"):
            assert absent not in kw

    def test_optional_fields_included_when_set(self):
        kw = self._mgr(
            password="pw", warehouse="WH", database="DB", schema="PUBLIC", role="R"
        )._connect_kwargs()
        assert kw["warehouse"] == "WH"
        assert kw["database"] == "DB"
        assert kw["schema"] == "PUBLIC"
        assert kw["role"] == "R"

    def test_password_auth_passes_password(self):
        kw = self._mgr(password="secret")._connect_kwargs()
        assert kw["password"] == "secret"
        assert "private_key" not in kw

    def test_keypair_auth_unencrypted(self, tmp_path):
        path, _ = _write_pem(tmp_path)
        kw = self._mgr(private_key_path=path)._connect_kwargs()
        assert "password" not in kw
        der = kw["private_key"]
        assert isinstance(der, bytes)
        # Prove the DER bytes are a valid, loadable key.
        serialization.load_der_private_key(der, password=None)

    def test_keypair_auth_passphrase_encrypted(self, tmp_path):
        path, _ = _write_pem(tmp_path, passphrase=b"topsecret")
        kw = self._mgr(private_key_path=path, private_key_passphrase="topsecret")._connect_kwargs()
        assert "password" not in kw
        der = kw["private_key"]
        assert isinstance(der, bytes)
        serialization.load_der_private_key(der, password=None)


# ── column-fold rule as a unit ───────────────────────────────────────────────


class TestFoldColumn:
    def test_uppercase_folds_to_lower(self):
        assert SnowflakeSourceManager._fold_column("TIMESTAMP") == "timestamp"

    def test_mixed_case_preserved(self):
        assert SnowflakeSourceManager._fold_column("MixedCase") == "MixedCase"

    def test_lowercase_preserved(self):
        assert SnowflakeSourceManager._fold_column("value") == "value"


# ── live behavior under fakesnow ─────────────────────────────────────────────


class TestLiveUnderFakesnow:
    def test_query_returns_lowercase_keyed_rows(self):
        with fakesnow.patch():
            mgr = SnowflakeSourceManager(
                account="test",
                user="tester",
                password="pw",
                database="DB",
                schema="PUBLIC",
            )
            try:
                mgr.execute_query("CREATE TABLE events (ts TIMESTAMP, value DOUBLE)")
                mgr.execute_query(
                    "INSERT INTO events VALUES "
                    "('2024-01-01 00:00:00', 1.0), ('2024-01-01 00:01:00', 2.0)"
                )
                rows = mgr.execute_query("SELECT ts, value FROM events ORDER BY ts")
                # Snowflake uppercases unquoted columns; the manager folds them.
                assert [set(r.keys()) for r in rows] == [{"ts", "value"}, {"ts", "value"}]
                assert rows[0]["value"] == 1.0
                assert rows[1]["value"] == 2.0
                assert rows[0]["ts"] == datetime(2024, 1, 1, 0, 0)
            finally:
                mgr.close()
                mgr.close()  # idempotent

    def test_create_manager_refusal_is_source_only(self):
        """Smoke: a snowflake profile is refused as STATE (deep version lives
        in test_profile.py)."""
        from detectkit.config.profile import ProfileConfig

        profile = ProfileConfig(type="snowflake", account="a", user="u", password="p")
        with pytest.raises(ValueError, match="source-only"):
            profile.create_manager()


# ── hybrid end-to-end: Snowflake source -> DuckDB state ──────────────────────
# Mirrors TestHybridEndToEndDuckDB: the metric's SQL runs on the (fake)
# Snowflake source and the datapoints land in a real DuckDB state file.

import importlib.util  # noqa: E402

_HAS_DUCKDB = importlib.util.find_spec("duckdb") is not None
_needs_duckdb = pytest.mark.skipif(not _HAS_DUCKDB, reason="duckdb is not installed")


class _OneManagerProfiles:
    """Minimal ``ProfilesConfig`` stand-in returning one pre-built source
    manager, so seeding and loading share the same fakesnow connection."""

    def __init__(self, profile_name: str, manager: SnowflakeSourceManager):
        self._profile_name = profile_name
        self._manager = manager

    def create_source_manager(self, profile_name: str) -> SnowflakeSourceManager:
        assert profile_name == self._profile_name
        return self._manager


@_needs_duckdb
class TestHybridEndToEndSnowflake:
    def test_load_step_reads_snowflake_writes_duckdb_state(self, tmp_path):
        from detectkit.config.metric_config import MetricConfig
        from detectkit.config.profile import ProfileConfig
        from detectkit.database.duckdb_manager import DuckDBDatabaseManager
        from detectkit.database.internal_tables import InternalTablesManager
        from detectkit.orchestration.task_manager import TaskManager

        with fakesnow.patch():
            # Build the REAL source manager through the REAL profile seam.
            profile = ProfileConfig(
                type="snowflake",
                account="test",
                user="tester",
                password="pw",
                database="DB",
                schema="PUBLIC",
            )
            source_manager = profile.create_source_manager()
            assert isinstance(source_manager, SnowflakeSourceManager)

            # Seed an events table through that same manager/connection.
            source_manager.execute_query("CREATE TABLE events (ts TIMESTAMP, value DOUBLE)")
            source_manager.execute_query(
                "INSERT INTO events VALUES "
                "('2024-01-01 00:00:00', 1.0), "
                "('2024-01-01 00:01:00', 2.0), "
                "('2024-01-01 00:02:00', 3.0)"
            )

            state_manager = DuckDBDatabaseManager(path=str(tmp_path / "state.duckdb"))
            internal = InternalTablesManager(state_manager)
            internal.ensure_tables()

            try:
                config = MetricConfig(
                    name="hybrid_metric",
                    interval="1min",
                    query=(
                        "SELECT ts AS timestamp, value AS value FROM events "
                        "WHERE ts >= '{{ dtk_start_time }}' AND ts < '{{ dtk_end_time }}'"
                    ),
                    loading_start_time="2024-01-01 00:00:00",
                    source_profile="warehouse",
                )

                tm = TaskManager(
                    internal_manager=internal,
                    db_manager=state_manager,
                    profiles_config=_OneManagerProfiles("warehouse", source_manager),
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

                last_ts = internal.get_last_datapoint_timestamp("hybrid_metric")
                assert last_ts == datetime(2024, 1, 1, 0, 2)
            finally:
                source_manager.close()
                state_manager.close()
