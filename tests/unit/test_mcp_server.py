"""Tests for the MCP server's tool implementations and (optionally) the SDK wiring.

Gated at module level with ``pytest.importorskip`` for both optional
dependencies the fixtures need (``duckdb`` for a real backend, ``mcp`` for the
SDK-level end-to-end check) — mirrors ``tests/unit/test_duckdb_manager.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

duckdb = pytest.importorskip("duckdb")

from detectkit.cli.commands.run import select_metrics  # noqa: E402
from detectkit.config.profile import ProfileConfig, ProfilesConfig  # noqa: E402
from detectkit.config.project_config import ProjectConfig  # noqa: E402
from detectkit.database.duckdb_manager import DuckDBDatabaseManager  # noqa: E402
from detectkit.database.internal_tables import InternalTablesManager  # noqa: E402
from detectkit.mcp import tools  # noqa: E402
from detectkit.mcp.context import McpContext, build_context  # noqa: E402
from detectkit.mcp.errors import McpProjectError  # noqa: E402
from detectkit.mcp.serialize import clamp_limit  # noqa: E402

_INTERVAL_SECONDS = 600


def _write_metric(metrics_dir: Path, name: str, **overrides: Any) -> Path:
    body: dict[str, Any] = {
        "name": name,
        "description": overrides.pop("description", f"{name} description"),
        "tags": overrides.pop("tags", ["critical"]),
        "interval": overrides.pop("interval", _INTERVAL_SECONDS),
        "query": overrides.pop("query", "SELECT timestamp, value FROM x"),
        "seasonality_columns": overrides.pop("seasonality_columns", []),
        "detectors": overrides.pop("detectors", [{"type": "mad", "params": {"threshold": 3.0}}]),
        "alerting": overrides.pop(
            "alerting",
            [{"channels": ["slack_alerts"], "min_detectors": 1, "consecutive_anomalies": 1}],
        ),
    }
    body.update(overrides)
    path = metrics_dir / f"{name}.yml"
    path.write_text(yaml.safe_dump(body, sort_keys=False))
    return path


def _seed_series(
    internal: InternalTablesManager,
    metric_name: str,
    *,
    n: int = 12,
    interval_seconds: int = _INTERVAL_SECONDS,
    anomaly_idx: int | None = 8,
    detector_id: str = "det1",
) -> np.ndarray:
    """Seed a simple linear series (+ one flagged anomaly) via the internal API."""
    base = np.datetime64("2026-01-01T00:00:00", "ms")
    timestamps = (base + np.arange(n) * np.timedelta64(interval_seconds, "s")).astype(
        "datetime64[ms]"
    )
    values = np.array([10.0 + i for i in range(n)], dtype=np.float64)
    if anomaly_idx is not None:
        values[anomaly_idx] = 999.0

    internal.save_datapoints(
        metric_name,
        {
            "timestamp": timestamps,
            "value": values,
            "seasonality_data": np.array(["{}"] * n, dtype=object),
        },
        interval_seconds,
        [],
    )

    is_anomaly = np.zeros(n, dtype=bool)
    metadata = np.array(["{}"] * n, dtype=object)
    if anomaly_idx is not None:
        is_anomaly[anomaly_idx] = True
        metadata[anomaly_idx] = json.dumps({"direction": "above", "severity": 5.0})

    internal.save_detections(
        metric_name,
        detector_id,
        "MADDetector",
        {
            "timestamp": timestamps,
            "is_anomaly": is_anomaly,
            "confidence_lower": values - 5.0,
            "confidence_upper": values + 5.0,
            "value": values,
            "processed_value": values,
            "detection_metadata": metadata,
        },
        "{}",
    )
    return timestamps


@pytest.fixture
def project(tmp_path: Path) -> McpContext:
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (tmp_path / "detectkit_project.yml").write_text("name: test_project\n")

    _write_metric(metrics_dir, "api_errors")
    _write_metric(metrics_dir, "other_metric", tags=["misc"])

    selected = select_metrics("*", tmp_path)
    metrics_by_name = {config.name: (path, config) for path, config in selected}

    project_config = ProjectConfig(name="test_project", default_profile="dev")
    profiles_config = ProfilesConfig(
        profiles={
            "dev": ProfileConfig(type="duckdb", path=":memory:"),
        },
        default_profile="dev",
    )
    # A secret that must never leak through get_metric() — channel configs
    # live only in profiles.yml's alert_channels, which no tool reads.
    profiles_config.alert_channels["slack_alerts"] = {
        "webhook_url": "https://hooks.example/T00/SECRET-TOKEN-XYZ"
    }

    db_manager = DuckDBDatabaseManager(path=":memory:")
    internal = InternalTablesManager(db_manager)
    internal.ensure_tables()  # the fixture may write; the tools under test never do

    _seed_series(internal, "api_errors")

    ctx = McpContext(
        project_root=tmp_path,
        project_config=project_config,
        profiles_config=profiles_config,
        internal=internal,
        profile_name=None,
        selector="*",
        metrics_by_name=metrics_by_name,
        tables_ready=True,
    )
    yield ctx
    db_manager.close()


def _assert_json_safe(value: Any) -> str:
    """json.dumps must succeed — the tool-boundary contract (no numpy, no NaN floats)."""
    return json.dumps(value)


class TestListMetrics:
    def test_lists_every_metric_in_scope(self, project: McpContext) -> None:
        result = tools.list_metrics(project, "*")
        _assert_json_safe(result)
        assert result["count"] == 2
        names = {m["name"] for m in result["metrics"]}
        assert names == {"api_errors", "other_metric"}

    def test_tag_selector(self, project: McpContext) -> None:
        result = tools.list_metrics(project, "tag:critical")
        assert [m["name"] for m in result["metrics"]] == ["api_errors"]

    def test_name_selector(self, project: McpContext) -> None:
        result = tools.list_metrics(project, "other_metric")
        assert [m["name"] for m in result["metrics"]] == ["other_metric"]

    def test_selector_outside_session_scope_is_excluded(self, project: McpContext) -> None:
        # A metric that select_metrics finds but isn't in this server's scope
        # must never surface, even when explicitly named by selector.
        project.metrics_by_name.pop("other_metric")
        result = tools.list_metrics(project, "other_metric")
        assert result["metrics"] == []


class TestGetMetric:
    def test_shape_and_no_secret_leak(self, project: McpContext) -> None:
        result = tools.get_metric(project, "api_errors")
        dumped = _assert_json_safe(result)
        assert result["name"] == "api_errors"
        assert result["interval_seconds"] == _INTERVAL_SECONDS
        assert result["alerting"][0]["channels"] == ["slack_alerts"]
        assert "SELECT" in (result["sql"] or "")
        assert "SECRET-TOKEN" not in dumped
        assert "webhook_url" not in dumped

    def test_unknown_metric_raises(self, project: McpContext) -> None:
        with pytest.raises(McpProjectError):
            tools.get_metric(project, "does_not_exist")


class TestGetMetricStatus:
    def test_shape_and_iso_timestamps(self, project: McpContext) -> None:
        result = tools.get_metric_status(project, "api_errors", "all")
        _assert_json_safe(result)
        assert result["points"] == 12
        assert result["last_point"].endswith("Z")
        assert result["alerts"]["last_ts"] is None or result["alerts"]["last_ts"].endswith("Z")

    def test_unknown_window_raises(self, project: McpContext) -> None:
        with pytest.raises(McpProjectError):
            tools.get_metric_status(project, "api_errors", "bogus")

    def test_no_data_yet_raises_friendly_error(self, project: McpContext) -> None:
        project.tables_ready = False
        with pytest.raises(McpProjectError, match="dtk run"):
            tools.get_metric_status(project, "api_errors", "all")


class TestGetProjectStatus:
    def test_reports_total_and_caps_returned(self, project: McpContext) -> None:
        result = tools.get_project_status(project, "all", "*", 1)
        _assert_json_safe(result)
        assert result["total_metrics"] == 2
        assert result["returned"] == 1
        assert len(result["metrics"]) == 1


class TestQueryDatapoints:
    def test_newest_first_and_limit(self, project: McpContext) -> None:
        result = tools.query_datapoints(project, "api_errors", limit=3)
        _assert_json_safe(result)
        assert result["count"] == 3
        ts = [p["timestamp"] for p in result["points"]]
        assert ts == sorted(ts, reverse=True)

    def test_unknown_metric_raises(self, project: McpContext) -> None:
        with pytest.raises(McpProjectError):
            tools.query_datapoints(project, "nope")


class TestQueryDetections:
    def test_anomalies_only_filter(self, project: McpContext) -> None:
        result = tools.query_detections(project, "api_errors", anomalies_only=True)
        _assert_json_safe(result)
        assert result["count"] == 1
        assert result["detections"][0]["is_anomaly"] is True

    def test_detector_id_filter(self, project: McpContext) -> None:
        result = tools.query_detections(project, "api_errors", detector_id="det1")
        assert result["count"] == 12
        assert all(d["detector_id"] == "det1" for d in result["detections"])

    def test_limit_is_enforced(self, project: McpContext) -> None:
        result = tools.query_detections(project, "api_errors", limit=2)
        assert result["count"] == 2


class TestClampLimit:
    def test_clamps_to_hard_cap(self) -> None:
        assert clamp_limit(999_999, default=1000, hard_cap=5000) == 5000

    def test_non_positive_falls_back_to_default(self) -> None:
        assert clamp_limit(0, default=1000, hard_cap=5000) == 1000
        assert clamp_limit(-5, default=1000, hard_cap=5000) == 1000

    def test_within_range_passes_through(self) -> None:
        assert clamp_limit(42, default=1000, hard_cap=5000) == 42


class TestReplayAlerts:
    def test_returns_seeded_anomaly_event(self, project: McpContext) -> None:
        result = tools.replay_alerts(project, "api_errors")
        _assert_json_safe(result)
        anomaly_events = [e for e in result["events"] if e["kind"] == "anomaly"]
        assert len(anomaly_events) >= 1
        assert anomaly_events[0]["direction"] == "up"
        assert anomaly_events[0]["timestamp"].endswith("Z")


class TestGetAutotuneHistory:
    def test_lists_runs_newest_first_and_hides_decision_log_by_default(
        self, project: McpContext
    ) -> None:
        project.internal.save_autotune_run(
            metric_name="api_errors",
            run_id="run-1",
            training_period_start=None,
            training_period_end=None,
            interval_seconds=_INTERVAL_SECONDS,
            labels=None,
            mode="unsupervised",
            scoring_metric="mcc",
            score=0.5,
            chosen_seasonality=None,
            chosen_detector_type="mad",
            chosen_detector_params={"threshold": 3.0},
            winning_detector_id="det1",
            candidate_detector_ids=["det1"],
            decision_log=[{"stage": "seasonality", "note": "skipped"}],
            generated_config_path=None,
            generated_config_text="",
            status="success",
        )
        result = tools.get_autotune_history(project, "api_errors")
        _assert_json_safe(result)
        assert result["count"] == 1
        assert result["runs"][0]["run_id"] == "run-1"
        assert "decision_log" not in result["runs"][0]

        with_log = tools.get_autotune_history(project, "api_errors", include_decision_log=True)
        assert with_log["runs"][0]["decision_log"] == [{"stage": "seasonality", "note": "skipped"}]

    def test_limit_hard_cap(self) -> None:
        assert clamp_limit(999, default=5, hard_cap=50) == 50


class TestGetIncidents:
    def test_no_labels_returns_empty(self, project: McpContext) -> None:
        result = tools.get_incidents(project, "api_errors")
        _assert_json_safe(result)
        assert result == {
            "metric": "api_errors",
            "labels_file": None,
            "count": 0,
            "incidents": [],
        }

    def test_reads_newest_labels_file(self, project: McpContext) -> None:
        incidents_dir = project.project_root / "incidents" / "api_errors"
        incidents_dir.mkdir(parents=True)
        (incidents_dir / "api_errors-20260101000000.yml").write_text(
            yaml.safe_dump(
                {
                    "metric": "api_errors",
                    "incidents": [{"start": "2026-01-01 04:00:00", "end": "2026-01-01 04:00:00"}],
                }
            )
        )
        result = tools.get_incidents(project, "api_errors")
        _assert_json_safe(result)
        assert result["count"] == 1
        assert result["labels_file"] is not None


class TestGetServerInfo:
    def test_shape(self, project: McpContext) -> None:
        result = tools.get_server_info(project)
        _assert_json_safe(result)
        assert result["read_only"] is True
        assert result["backend_type"] == "duckdb"
        assert result["metric_count"] == 2
        assert result["tables_ready"] is True


class TestSessionScope:
    def test_metric_outside_scope_is_refused(self, project: McpContext) -> None:
        project.metrics_by_name.pop("other_metric")
        with pytest.raises(McpProjectError):
            tools.get_metric(project, "other_metric")


def _write_project(tmp_path: Path, *, duckdb_path: str) -> None:
    """Write a minimal on-disk project: config + one metric + a duckdb profile.

    Used by the ``build_context``-level tests below (FINDING A/B), which
    exercise the real project/profile-resolution path — unlike the
    ``project`` fixture above, which constructs an :class:`McpContext`
    directly and never calls ``build_context``.
    """
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    (tmp_path / "detectkit_project.yml").write_text("name: test_project\ndefault_profile: dev\n")
    _write_metric(metrics_dir, "api_errors")
    (tmp_path / "profiles.yml").write_text(
        yaml.safe_dump(
            {
                "profiles": {"dev": {"type": "duckdb", "path": duckdb_path}},
                "default_profile": "dev",
            }
        )
    )


class TestEnsureLocationsFalse:
    """FINDING A: ``ensure_locations=False`` must skip every backend's DDL-on-connect.

    Mock-level, mirroring the dispatch-is-mocked style in
    ``tests/unit/test_profile.py`` / ``tests/unit/test_sql_managers.py`` —
    kept here per the MCP-server review's instruction not to edit those
    files.
    """

    def test_clickhouse_skips_database_creation(self, monkeypatch) -> None:
        import detectkit.database.clickhouse_manager as ch_mod

        executed: list[str] = []

        class FakeClient:
            def __init__(self, **kwargs: Any) -> None:
                pass

            def execute(self, query: str, *a: Any, **kw: Any) -> list[Any]:
                executed.append(query)
                return []

        monkeypatch.setattr(ch_mod, "CLICKHOUSE_AVAILABLE", True)
        monkeypatch.setattr(ch_mod, "Client", FakeClient)

        profile = ProfileConfig(
            type="clickhouse",
            host="localhost",
            port=9000,
            internal_database="dtk_internal",
            data_database="dtk_data",
        )

        manager = profile.create_manager(ensure_locations=False)
        assert isinstance(manager, ch_mod.ClickHouseDatabaseManager)
        assert executed == []  # no `CREATE DATABASE` statements ran

        profile.create_manager(ensure_locations=True)
        assert executed == [
            "CREATE DATABASE IF NOT EXISTS dtk_internal",
            "CREATE DATABASE IF NOT EXISTS dtk_data",
        ]

    def test_postgres_skips_ensure_locations(self, monkeypatch) -> None:
        import detectkit.database.postgres_manager as pg_mod

        calls: list[str] = []
        monkeypatch.setattr(pg_mod, "PSYCOPG2_AVAILABLE", True)
        monkeypatch.setattr(pg_mod.PostgresDatabaseManager, "_connect", lambda self: object())
        monkeypatch.setattr(
            pg_mod.PostgresDatabaseManager,
            "_ensure_locations",
            lambda self: calls.append("ensure_locations"),
        )

        profile = ProfileConfig(
            type="postgres",
            host="localhost",
            port=5432,
            database="dtk",
            internal_schema="dtk_internal",
            data_schema="public",
        )

        profile.create_manager(ensure_locations=False)
        assert calls == []

        profile.create_manager(ensure_locations=True)
        assert calls == ["ensure_locations"]

    def test_mysql_skips_ensure_locations(self, monkeypatch) -> None:
        import detectkit.database.mysql_manager as mysql_mod

        calls: list[str] = []
        monkeypatch.setattr(mysql_mod, "PYMYSQL_AVAILABLE", True)
        monkeypatch.setattr(mysql_mod.MySQLDatabaseManager, "_connect", lambda self: object())
        monkeypatch.setattr(
            mysql_mod.MySQLDatabaseManager,
            "_ensure_locations",
            lambda self: calls.append("ensure_locations"),
        )

        profile = ProfileConfig(
            type="mysql",
            host="localhost",
            port=3306,
            internal_database="dtk_internal",
            data_database="dtk_data",
        )

        profile.create_manager(ensure_locations=False)
        assert calls == []

        profile.create_manager(ensure_locations=True)
        assert calls == ["ensure_locations"]

    def test_duckdb_missing_file_raises_and_creates_no_file(self, tmp_path: Path) -> None:
        path = tmp_path / "missing.duckdb"
        assert not path.exists()

        with pytest.raises(duckdb.IOException):
            DuckDBDatabaseManager(path=str(path), ensure_locations=False)

        assert not path.exists()  # the whole point: the probe never creates it

    def test_duckdb_forces_read_only_even_when_read_only_false(self, tmp_path: Path) -> None:
        path = tmp_path / "state.duckdb"
        # Create the file for real first (ensure_locations=True), so the
        # probe below hits "attach succeeds" rather than "file missing".
        DuckDBDatabaseManager(path=str(path), internal_schema="dtk_internal").close()

        probe = DuckDBDatabaseManager(
            path=str(path),
            internal_schema="dtk_internal",
            read_only=False,  # explicitly requesting read-write ...
            ensure_locations=False,  # ... is overridden by the strict probe
        )
        try:
            assert probe._read_only is True
        finally:
            probe.close()

    def test_duckdb_memory_is_exempt_from_forced_read_only(self) -> None:
        # ":memory:" has no file to protect, and DuckDB rejects a read-only
        # in-memory connection outright — forcing it there would break
        # rather than protect, so it must NOT be forced.
        manager = DuckDBDatabaseManager(path=":memory:", ensure_locations=False)
        try:
            assert manager._read_only is False
            assert manager.execute_query("SELECT 1 AS x") == [{"x": 1}]
        finally:
            manager.close()


class TestBuildContextDuckdbMissingFile:
    """FINDING A: a read-only server must never create the DuckDB state file."""

    def test_degrades_gracefully_with_no_file_created(self, tmp_path: Path) -> None:
        state_path = tmp_path / "state.duckdb"
        _write_project(tmp_path, duckdb_path=str(state_path))
        assert not state_path.exists()

        ctx = build_context(project_dir=str(tmp_path), selector="*", profile=None)

        # (a) no file gets created — the whole point.
        assert not state_path.exists()
        assert ctx.internal is None
        assert ctx.tables_ready is False

        # (b) every DB-touching tool surfaces the friendly "no data yet" error.
        with pytest.raises(McpProjectError, match="dtk run"):
            tools.get_metric_status(ctx, "api_errors", "7d")
        with pytest.raises(McpProjectError, match="dtk run"):
            tools.query_datapoints(ctx, "api_errors")
        with pytest.raises(McpProjectError, match="dtk run"):
            tools.get_project_status(ctx)

        # Still no file after those calls either.
        assert not state_path.exists()

        # Tools that don't touch the database still work normally.
        listed = tools.list_metrics(ctx, "*")
        assert listed["count"] == 1
        info = tools.get_server_info(ctx)
        assert info["tables_ready"] is False
        assert info["backend_type"] == "duckdb"

    def test_real_construction_errors_are_not_swallowed(self, tmp_path: Path) -> None:
        """A genuinely bad profile (unsupported type) must still raise, not degrade."""
        metrics_dir = tmp_path / "metrics"
        metrics_dir.mkdir()
        (tmp_path / "detectkit_project.yml").write_text(
            "name: test_project\ndefault_profile: dev\n"
        )
        _write_metric(metrics_dir, "api_errors")
        (tmp_path / "profiles.yml").write_text(
            yaml.safe_dump(
                {
                    "profiles": {"dev": {"type": "postgres", "host": "localhost", "port": 5432}},
                    "default_profile": "dev",
                }
            )
        )

        with pytest.raises(McpProjectError):
            build_context(project_dir=str(tmp_path), selector="*", profile=None)


class TestResolveRelativeDuckdbPath:
    """FINDING B: a relative DuckDB ``path`` resolves against the PROJECT root, not cwd."""

    def test_relative_path_resolves_under_project_root_not_cwd(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        state_path = tmp_path / "state.duckdb"
        # Pre-create the state file for real so this test isolates FINDING B
        # (path resolution) from FINDING A (the missing-file degrade).
        DuckDBDatabaseManager(path=str(state_path)).close()

        _write_project(tmp_path, duckdb_path="state.duckdb")  # relative

        elsewhere = tmp_path.parent / f"{tmp_path.name}-elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        ctx = build_context(project_dir=str(tmp_path), selector="*", profile=None)
        try:
            assert ctx.internal is not None
            resolved_path = ctx.internal._manager._path  # noqa: SLF001 - same access as context.py
            assert Path(resolved_path) == state_path.resolve()
            # FINDING A, incidentally: no stray file next to the launcher's cwd.
            assert not (elsewhere / "state.duckdb").exists()
        finally:
            if ctx.internal is not None:
                ctx.internal._manager.close()  # noqa: SLF001


class TestQueryDatapointsClamp:
    """FINDING C: a wide ``from_ts`` must not materialize more than ``limit`` needs."""

    def test_wide_from_ts_is_clamped_before_fetch(self, project: McpContext, monkeypatch) -> None:
        calls: list[tuple[Any, Any]] = []
        original = project.internal.load_datapoints

        def spy(metric_name: str, start: Any, end: Any) -> Any:
            calls.append((start, end))
            return original(metric_name, start, end)

        monkeypatch.setattr(project.internal, "load_datapoints", spy)

        result = tools.query_datapoints(
            project, "api_errors", from_ts="2000-01-01T00:00:00Z", limit=3
        )

        assert len(calls) == 1
        clamped_start, _ = calls[0]
        # The series starts in 2026 — an unclamped fetch would have reached
        # all the way back to 2000.
        assert clamped_start.year >= 2025

        # Clamping must not change *which* points come back.
        unclamped = tools.query_datapoints(project, "api_errors", limit=3)
        assert result["points"] == unclamped["points"]


class TestQueryDetectionsClamp:
    """FINDING C: same clamp for detections, except when ``anomalies_only=True``."""

    def test_wide_from_ts_is_clamped_when_not_anomalies_only(
        self, project: McpContext, monkeypatch
    ) -> None:
        calls: list[tuple[Any, Any]] = []
        original = project.internal.load_detections

        def spy(metric_name: str, detector_id: str | None, start: Any, end: Any) -> Any:
            calls.append((start, end))
            return original(metric_name, detector_id, start, end)

        monkeypatch.setattr(project.internal, "load_detections", spy)

        result = tools.query_detections(
            project,
            "api_errors",
            from_ts="2000-01-01T00:00:00Z",
            limit=3,
            anomalies_only=False,
        )

        assert len(calls) == 1
        clamped_start, _ = calls[0]
        assert clamped_start.year >= 2025

        unclamped = tools.query_detections(project, "api_errors", limit=3, anomalies_only=False)
        assert result["detections"] == unclamped["detections"]

    def test_wide_from_ts_stays_unclamped_when_anomalies_only(
        self, project: McpContext, monkeypatch
    ) -> None:
        calls: list[tuple[Any, Any]] = []
        original = project.internal.load_detections

        def spy(metric_name: str, detector_id: str | None, start: Any, end: Any) -> Any:
            calls.append((start, end))
            return original(metric_name, detector_id, start, end)

        monkeypatch.setattr(project.internal, "load_detections", spy)

        result = tools.query_detections(
            project,
            "api_errors",
            from_ts="2000-01-01T00:00:00Z",
            limit=1,
            anomalies_only=True,
        )

        assert len(calls) == 1
        wide_start, _ = calls[0]
        assert wide_start.year == 2000  # NOT clamped — the documented exception
        assert result["count"] == 1
        assert result["detections"][0]["is_anomaly"] is True


class TestSdkEndToEnd:
    """One in-process SDK-level smoke test; skips gracefully if the API differs."""

    def test_list_metrics_through_a_real_client_session(self, project: McpContext) -> None:
        pytest.importorskip("mcp")
        try:
            import anyio
            from mcp.shared.memory import create_connected_server_and_client_session
        except ImportError:
            pytest.skip("mcp.shared.memory in-process client API not available")

        from detectkit.mcp.server import build_server

        server = build_server(project)

        async def _run() -> Any:
            async with create_connected_server_and_client_session(server) as client:
                result = await client.call_tool("list_metrics", {"selector": "*"})
                return result

        result = anyio.run(_run)
        assert result.isError is not True
        payload = result.structuredContent or {}
        # Either the tool's own dict shape, or wrapped — accept both.
        count = payload.get("count", payload.get("result", {}).get("count"))
        assert count == 2
