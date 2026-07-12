"""Tests for hybrid source-profile mode: a metric's SQL runs against a SOURCE
database profile while all ``_dtk_*`` state stays in the STATE database.

Covers:
- ``resolve_source_profile`` precedence (metric -> project -> None).
- The TaskManager source-manager pool: single construction per profile
  name, reuse of ``db_manager`` when the resolved source equals the active
  state profile, detect/alert-only runs never touching a source manager,
  and a failed construction being cached (not retried) and wrapped.
- The LOAD step wiring: the pooled source manager reaches ``MetricLoader``
  while ``save_datapoints`` always goes through ``self.internal`` (state).
- ``SourceDatabaseError`` wraps only the source query failure — a state
  (``save_datapoints``) failure is never wrapped.
- ``dtk run``'s fail-fast validation: an unknown ``source_profile`` exits 1
  before any pipeline work (no TaskManager construction).
- An end-to-end run against two real, on-disk DuckDB files: the metric's SQL
  reads the SOURCE file and the datapoints land in the STATE file, which
  never touches the source.
"""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest

from detectkit.config.metric_config import MetricConfig, resolve_source_profile
from detectkit.loaders.errors import SourceDatabaseError
from detectkit.orchestration.task_manager import PipelineStep, TaskManager, TaskStatus

# ── resolve_source_profile precedence ────────────────────────────────────────


class TestResolveSourceProfile:
    def test_metric_wins_over_project(self):
        assert resolve_source_profile("warehouse", "lake") == "warehouse"

    def test_falls_back_to_project(self):
        assert resolve_source_profile(None, "lake") == "lake"

    def test_none_when_neither_set(self):
        assert resolve_source_profile(None, None) is None

    def test_any_non_none_metric_value_wins_even_empty(self):
        """The field is a plain optional string with no zero-value
        special-casing (unlike loading_delay): any non-None metric value —
        even "" — wins outright; rejecting a nonsense name is the run-time
        fail-fast profile check's job."""
        assert resolve_source_profile("warehouse", None) == "warehouse"
        assert resolve_source_profile("", "lake") == ""


# ── the TaskManager source-manager pool ──────────────────────────────────────


class _CountingProfiles:
    """Minimal ``ProfilesConfig`` stand-in that counts ``create_manager`` calls
    and can be told to fail for specific profile names."""

    def __init__(self, fail_names: set[str] | None = None):
        self.managers: dict[str, Mock] = {}
        self.fail_names = fail_names or set()
        self.calls: list[str] = []

    def create_manager(self, profile_name: str) -> Mock:
        self.calls.append(profile_name)
        if profile_name in self.fail_names:
            raise ConnectionError(f"cannot reach '{profile_name}'")
        return self.managers.setdefault(profile_name, Mock(name=f"manager-{profile_name}"))


def _metric(name: str = "m", source_profile: str | None = None) -> MetricConfig:
    return MetricConfig(
        name=name,
        interval="1min",
        query="SELECT 1 AS timestamp, 1 AS value",
        loading_start_time="2024-01-01 00:00:00",
        source_profile=source_profile,
    )


class TestSourceManagerPool:
    def test_two_metrics_sharing_source_profile_build_once(self):
        profiles = _CountingProfiles()
        tm = TaskManager(
            internal_manager=Mock(),
            db_manager=Mock(),
            profiles_config=profiles,
            project_config=None,
            state_profile_name="state",
        )

        mgr_a, name_a = tm._resolve_source_manager(_metric("a", "warehouse"))
        mgr_b, name_b = tm._resolve_source_manager(_metric("b", "warehouse"))

        assert name_a == name_b == "warehouse"
        assert mgr_a is mgr_b
        assert profiles.calls == ["warehouse"]

    def test_source_equal_to_state_profile_reuses_db_manager(self):
        profiles = _CountingProfiles()
        state_db = Mock()
        tm = TaskManager(
            internal_manager=Mock(),
            db_manager=state_db,
            profiles_config=profiles,
            project_config=None,
            state_profile_name="prod",
        )

        mgr, name = tm._resolve_source_manager(_metric("a", "prod"))

        assert mgr is state_db
        assert name is None
        assert profiles.calls == []

    def test_no_source_profile_reuses_db_manager(self):
        profiles = _CountingProfiles()
        state_db = Mock()
        tm = TaskManager(
            internal_manager=Mock(),
            db_manager=state_db,
            profiles_config=profiles,
            project_config=None,
            state_profile_name="prod",
        )

        mgr, name = tm._resolve_source_manager(_metric("a", None))

        assert mgr is state_db
        assert name is None
        assert profiles.calls == []

    def test_detect_alert_only_never_constructs_source_manager(self):
        profiles = _CountingProfiles()
        internal = Mock()
        internal.acquire_lock.return_value = True
        tm = TaskManager(
            internal_manager=internal,
            db_manager=Mock(),
            profiles_config=profiles,
            project_config=None,
            state_profile_name="prod",
        )
        tm._run_detect_step = Mock(return_value={"anomalies_count": 0})
        tm._run_alert_step = Mock(return_value={"alerts_sent": 0})

        result = tm.run_metric(
            _metric("a", "warehouse"),
            steps=[PipelineStep.DETECT, PipelineStep.ALERT],
        )

        assert result["status"] == TaskStatus.SUCCESS
        assert profiles.calls == []

    def test_failed_construction_is_cached_and_wrapped(self):
        profiles = _CountingProfiles(fail_names={"warehouse"})
        tm = TaskManager(
            internal_manager=Mock(),
            db_manager=Mock(),
            profiles_config=profiles,
            project_config=None,
            state_profile_name="prod",
        )

        with pytest.raises(SourceDatabaseError) as exc_a:
            tm._resolve_source_manager(_metric("a", "warehouse"))
        with pytest.raises(SourceDatabaseError) as exc_b:
            tm._resolve_source_manager(_metric("b", "warehouse"))

        # create_manager was attempted exactly once — the failure is cached,
        # not retried for the second metric.
        assert profiles.calls == ["warehouse"]
        assert exc_a.value.profile_name == "warehouse"
        assert exc_b.value.profile_name == "warehouse"
        assert "source database (profile 'warehouse')" in str(exc_a.value)

    def test_no_profiles_config_raises_wrapped_error(self):
        """A hybrid source_profile with no profiles_config to resolve it
        against fails clearly instead of an AttributeError."""
        tm = TaskManager(
            internal_manager=Mock(),
            db_manager=Mock(),
            profiles_config=None,
            project_config=None,
            state_profile_name="prod",
        )

        with pytest.raises(SourceDatabaseError):
            tm._resolve_source_manager(_metric("a", "warehouse"))


# ── LOAD step wiring ──────────────────────────────────────────────────────────


class TestLoadStepUsesSourceManager:
    def test_pooled_manager_passed_to_loader_save_goes_to_internal(self, monkeypatch):
        profiles = _CountingProfiles()
        internal = Mock()
        internal.get_last_datapoint_timestamp.return_value = None
        state_db = Mock()
        tm = TaskManager(
            internal_manager=internal,
            db_manager=state_db,
            profiles_config=profiles,
            project_config=None,
            state_profile_name="prod",
        )
        config = _metric("a", "warehouse")

        captured: dict[str, object] = {}

        class _CapturingLoader:
            def __init__(self, config, db_manager, internal_manager, source_profile_name=None):
                captured["db_manager"] = db_manager
                captured["internal_manager"] = internal_manager
                captured["source_profile_name"] = source_profile_name

            def load_and_save(self, from_date, to_date):
                return 5

        monkeypatch.setattr(
            "detectkit.orchestration.task_manager._load_step.MetricLoader", _CapturingLoader
        )

        result = tm._run_load_step(
            config,
            from_date=datetime(2024, 1, 1, 0, 0),
            to_date=datetime(2024, 1, 1, 0, 10),
            full_refresh=False,
        )

        assert result["points_loaded"] == 5
        assert captured["source_profile_name"] == "warehouse"
        assert captured["db_manager"] is profiles.managers["warehouse"]
        assert captured["internal_manager"] is internal
        assert profiles.calls == ["warehouse"]

    def test_state_db_failure_not_wrapped_even_in_hybrid_mode(self):
        """save_datapoints() always writes to STATE, never the source
        connection — a failure there stays a plain exception."""
        profiles = _CountingProfiles()
        source_manager = Mock()
        source_manager.execute_query.return_value = [
            {"timestamp": datetime(2024, 1, 1, 0, 0), "value": 1.0},
        ]
        profiles.managers["warehouse"] = source_manager

        internal = Mock()
        internal.get_last_datapoint_timestamp.return_value = None
        internal.save_datapoints.side_effect = RuntimeError("state db down")

        tm = TaskManager(
            internal_manager=internal,
            db_manager=Mock(),
            profiles_config=profiles,
            project_config=None,
            state_profile_name="prod",
        )
        config = _metric("a", "warehouse")

        with pytest.raises(RuntimeError, match="state db down"):
            tm._run_load_step(
                config,
                from_date=datetime(2024, 1, 1, 0, 0),
                to_date=datetime(2024, 1, 1, 0, 1),
                full_refresh=False,
            )

        # The source query itself succeeded; only the state write failed.
        assert profiles.calls == ["warehouse"]

    def test_source_query_failure_wrapped(self):
        profiles = _CountingProfiles()
        source_manager = Mock()
        source_manager.execute_query.side_effect = ConnectionError("source unreachable")
        profiles.managers["warehouse"] = source_manager

        internal = Mock()
        internal.get_last_datapoint_timestamp.return_value = None

        tm = TaskManager(
            internal_manager=internal,
            db_manager=Mock(),
            profiles_config=profiles,
            project_config=None,
            state_profile_name="prod",
        )
        config = _metric("a", "warehouse")

        with pytest.raises(SourceDatabaseError) as exc_info:
            tm._run_load_step(
                config,
                from_date=datetime(2024, 1, 1, 0, 0),
                to_date=datetime(2024, 1, 1, 0, 1),
                full_refresh=False,
            )

        assert exc_info.value.profile_name == "warehouse"
        internal.save_datapoints.assert_not_called()


# ── error alert message leads with the source profile name ──────────────────


class TestErrorAlertRendersSourceProfileName:
    """``TaskManager._maybe_send_error_alert`` -> ``dispatch_project_error_alert``
    needs no structural change: ``AlertData.error_type`` already distinguishes
    a ``SourceDatabaseError``. This only verifies the MESSAGE leads with
    "source database (profile '<name>')" so a stakeholder reading the alert
    can tell source-down from state-down at a glance."""

    def test_message_leads_with_profile_name(self, monkeypatch):
        from detectkit.orchestration import error_dispatch

        captured: dict[str, object] = {}

        class _FakeChannel:
            def send(self, alert_data, template=None):
                captured["alert_data"] = alert_data
                return True

        class _FakeProfilesConfig:
            def get_alert_channel_config(self, name):
                return {"type": "webhook", "url": "https://example.invalid"}

        monkeypatch.setattr(
            error_dispatch.AlertChannelFactory,
            "create_from_config",
            lambda cfg: _FakeChannel(),
        )

        class _ErrorAlertingCfg:
            enabled = True
            channels = ["ops"]
            template = None
            mentions: list[str] = []
            timezone = None

        class _ProjectConfig:
            name = "demo"
            error_alerting = _ErrorAlertingCfg()

            def resolve_alert_help_url(self):
                return None

        exc = SourceDatabaseError("warehouse", ConnectionError("cannot reach 'warehouse'"))

        sent = error_dispatch.dispatch_project_error_alert(
            profiles_config=_FakeProfilesConfig(),
            project_config=_ProjectConfig(),
            metric_name="hybrid_metric",
            exc=exc,
        )

        assert sent is True
        alert_data = captured["alert_data"]
        assert alert_data.error_type == "SourceDatabaseError"
        assert alert_data.error_message.startswith("source database (profile 'warehouse')")
        assert "cannot reach 'warehouse'" in alert_data.error_message


# ── dtk run fail-fast validation ─────────────────────────────────────────────


class TestRunFailFastUnknownSourceProfile:
    def _build_project(self, tmp_path: Path) -> Path:
        (tmp_path / "detectkit_project.yml").write_text("name: demo\ndefault_profile: prod\n")
        (tmp_path / "profiles.yml").write_text(
            "profiles:\n"
            "  prod:\n"
            "    type: duckdb\n"
            "    path: ':memory:'\n"
            "default_profile: prod\n"
        )
        metrics_dir = tmp_path / "metrics"
        metrics_dir.mkdir()
        (metrics_dir / "a.yml").write_text(
            'name: a\ninterval: 1min\nquery: "SELECT 1"\nsource_profile: nonexistent\n'
        )
        return tmp_path

    def test_unknown_source_profile_exits_one_before_pipeline(self, tmp_path, monkeypatch):
        from detectkit.cli.commands import run as run_module

        root = self._build_project(tmp_path)
        monkeypatch.setattr(run_module, "find_project_root", lambda: root)

        def _must_not_construct(*args, **kwargs):
            raise AssertionError("TaskManager must not be built after a fail-fast error")

        monkeypatch.setattr(run_module, "TaskManager", _must_not_construct)

        rc = run_module.run_command(
            select="*",
            exclude=None,
            steps="load,detect,alert",
            from_date=None,
            to_date=None,
            full_refresh=False,
            force=False,
            profile=None,
        )

        assert rc == 1

    def test_known_source_profile_passes_validation(self, tmp_path, monkeypatch):
        """A resolvable source_profile does not trip the fail-fast check —
        this project reaches TaskManager construction (proven by the stub
        raising past that point instead of the validation itself)."""
        from detectkit.cli.commands import run as run_module

        (tmp_path / "detectkit_project.yml").write_text("name: demo\ndefault_profile: prod\n")
        (tmp_path / "profiles.yml").write_text(
            "profiles:\n"
            "  prod:\n"
            "    type: duckdb\n"
            "    path: ':memory:'\n"
            "  warehouse:\n"
            "    type: duckdb\n"
            "    path: ':memory:'\n"
            "default_profile: prod\n"
        )
        metrics_dir = tmp_path / "metrics"
        metrics_dir.mkdir()
        (metrics_dir / "a.yml").write_text(
            'name: a\ninterval: 1min\nquery: "SELECT 1"\nsource_profile: warehouse\n'
        )
        monkeypatch.setattr(run_module, "find_project_root", lambda: tmp_path)

        reached = {"task_manager_built": False}

        class _StubTaskManager:
            def __init__(self, **kwargs):
                reached["task_manager_built"] = True

            def run_metric(self, **kwargs):
                return {
                    "status": TaskStatus.SUCCESS,
                    "error": None,
                    "steps_completed": [],
                    "datapoints_loaded": 0,
                    "anomalies_detected": 0,
                    "alerts_sent": 0,
                    "abort_run": False,
                }

        monkeypatch.setattr(run_module, "TaskManager", _StubTaskManager)

        run_module.run_command(
            select="*",
            exclude=None,
            steps="load,detect,alert",
            from_date=None,
            to_date=None,
            full_refresh=False,
            force=False,
            profile=None,
        )

        assert reached["task_manager_built"] is True


# ── end-to-end with real DuckDB engines ──────────────────────────────────────
# Class-level skip, NOT a module-level importorskip: the mock-based hybrid
# tests above need no duckdb and must keep running on a bare `[dev]` install —
# only the real-engine e2e class below skips when the extra is missing.

_HAS_DUCKDB = importlib.util.find_spec("duckdb") is not None
_needs_duckdb = pytest.mark.skipif(not _HAS_DUCKDB, reason="duckdb is not installed")

if _HAS_DUCKDB:
    import duckdb

# Safe without the engine: the module's import guard defers to construction.
from detectkit.database.duckdb_manager import DuckDBDatabaseManager  # noqa: E402
from detectkit.database.internal_tables import InternalTablesManager  # noqa: E402


class _OneProfileProfilesConfig:
    """Minimal ``ProfilesConfig`` stand-in exposing exactly one named source
    profile, backed by a real, already-constructed manager."""

    def __init__(self, profile_name: str, manager: DuckDBDatabaseManager):
        self._profile_name = profile_name
        self._manager = manager

    def create_manager(self, profile_name: str) -> DuckDBDatabaseManager:
        assert profile_name == self._profile_name
        return self._manager


@_needs_duckdb
class TestHybridEndToEndDuckDB:
    def test_load_step_reads_source_writes_state_only(self, tmp_path):
        source_path = tmp_path / "source.duckdb"
        state_path = tmp_path / "state.duckdb"

        # Seed the SOURCE file with a little table the metric's SQL reads.
        seed_conn = duckdb.connect(str(source_path))
        seed_conn.execute("CREATE TABLE events (ts TIMESTAMP, value DOUBLE)")
        seed_conn.execute(
            "INSERT INTO events VALUES "
            "('2024-01-01 00:00:00', 1.0), "
            "('2024-01-01 00:01:00', 2.0), "
            "('2024-01-01 00:02:00', 3.0)"
        )
        seed_conn.close()

        source_manager = DuckDBDatabaseManager(path=str(source_path))
        state_manager = DuckDBDatabaseManager(path=str(state_path))
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
                profiles_config=_OneProfileProfilesConfig("warehouse", source_manager),
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

            # STATE file received the datapoints.
            last_ts = internal.get_last_datapoint_timestamp("hybrid_metric")
            assert last_ts == datetime(2024, 1, 1, 0, 2)

            # SOURCE file has no _dtk_* tables at all — only its own `events`.
            source_tables = {
                row["table_name"]
                for row in source_manager.execute_query(
                    "SELECT table_name FROM information_schema.tables"
                )
            }
            assert not any(t.startswith("_dtk_") for t in source_tables)
            assert "events" in source_tables
        finally:
            source_manager.close()
            state_manager.close()

    def test_source_profile_equal_to_state_reuses_connection(self, tmp_path):
        """A metric whose source_profile names the ACTIVE state profile must
        not open a second connection to the same file."""
        state_path = tmp_path / "state.duckdb"
        state_manager = DuckDBDatabaseManager(path=str(state_path))
        internal = InternalTablesManager(state_manager)
        internal.ensure_tables()

        class _BoomIfCalled:
            def create_manager(self, profile_name: str):
                raise AssertionError(
                    "create_manager must not be called when source == state profile"
                )

        try:
            config = MetricConfig(
                name="same_profile_metric",
                interval="1min",
                query="SELECT '2024-01-01 00:00:00'::TIMESTAMP AS timestamp, 1.0 AS value",
                loading_start_time="2024-01-01 00:00:00",
                source_profile="state",
            )

            tm = TaskManager(
                internal_manager=internal,
                db_manager=state_manager,
                profiles_config=_BoomIfCalled(),
                project_config=None,
                state_profile_name="state",
            )

            result = tm._run_load_step(
                config,
                from_date=datetime(2024, 1, 1, 0, 0),
                to_date=datetime(2024, 1, 1, 0, 1),
                full_refresh=False,
            )
            assert result["points_loaded"] == 1
        finally:
            state_manager.close()
