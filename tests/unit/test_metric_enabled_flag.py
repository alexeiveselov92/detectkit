"""Tests for the metric-level ``enabled: false`` flag.

It used to be a silent no-op: a metric disabled in its YAML kept loading,
detecting and alerting (a real incident — rows written with a fresh
``created_at`` and an alert delivered hours after the flag was pushed), while
three places in the docs promised ``dtk run`` skipped it.

What is locked in here:

- ``dtk run`` skips a disabled metric entirely (``run_metric`` never called),
  says so on a visible log line, reports it as ``skipped`` in ``--json``, and
  keeps the exit code at 0 — a config choice is not a failure.
- the skip is total except for the informational ``_dtk_metrics`` mirror, which
  is still refreshed so its ``enabled`` column can't go stale.
- ``dtk autotune`` skips it too (an offline tune would persist detections for a
  retired metric), independently of the ``autotune.enabled`` switch.
- the skip lives in the RUNNER, not in discovery: ``select_metrics`` still
  returns disabled metrics (``dtk tune`` / ``dtk ui`` must open them) and
  ``dtk clean --orphaned-metrics`` must never treat their rows as orphaned.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from detectkit.cli.commands import autotune as autotune_module
from detectkit.cli.commands import clean as clean_cmd
from detectkit.cli.commands import run as run_module
from detectkit.config.metric_config import MetricConfig
from detectkit.orchestration.task_manager import PipelineStep, TaskStatus

# ── fakes ────────────────────────────────────────────────────────────────────


class FakeProfilesConfig:
    @classmethod
    def from_yaml(cls, path: Path) -> FakeProfilesConfig:
        return cls()

    def create_manager(self, profile: str | None) -> object:
        return object()


class FakeInternalTablesManager:
    """No DB. Records every ``_dtk_metrics`` refresh so the test can assert it."""

    instances: list[FakeInternalTablesManager] = []

    def __init__(self, db_manager: object) -> None:
        self.db_manager = db_manager
        self.upserts: list[tuple[str, bool]] = []
        FakeInternalTablesManager.instances.append(self)

    def ensure_tables(self) -> None:
        pass

    def upsert_metric_config(self, metric_config, file_path, table_name_override=None) -> int:
        self.upserts.append((metric_config.name, metric_config.enabled))
        return 1


class RecordingTaskManager:
    """Stand-in for ``TaskManager`` — records which metrics reached the pipeline."""

    calls: list[str] = []

    def __init__(self, **kwargs: object) -> None:
        pass

    def run_metric(self, **kwargs: object) -> dict:
        config = kwargs["config"]
        RecordingTaskManager.calls.append(config.name)
        return {
            "status": TaskStatus.SUCCESS,
            "error": None,
            "steps_completed": [PipelineStep.LOAD, PipelineStep.DETECT, PipelineStep.ALERT],
            "datapoints_loaded": 10,
            "anomalies_detected": 2,
            "alerts_sent": 1,
            "abort_run": False,
        }


def _write_metric(metrics_dir: Path, name: str, *, enabled: bool) -> None:
    body = f'name: {name}\ninterval: 1min\nquery: "SELECT 1"\n'
    if not enabled:
        body += "enabled: false\n"
    (metrics_dir / f"{name}.yml").write_text(body)


def _build_project(tmp_path: Path, metrics: dict[str, bool]) -> Path:
    (tmp_path / "detectkit_project.yml").write_text("name: demo_project\ndefault_profile: dev\n")
    (tmp_path / "profiles.yml").write_text("profiles: {}\n")  # never parsed (mocked)
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    for name, enabled in metrics.items():
        _write_metric(metrics_dir, name, enabled=enabled)
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_fakes():
    RecordingTaskManager.calls = []
    FakeInternalTablesManager.instances = []
    yield


def _patch_run(monkeypatch, root: Path) -> None:
    monkeypatch.setattr(run_module, "find_project_root", lambda: root)
    monkeypatch.setattr(run_module, "ProfilesConfig", FakeProfilesConfig)
    monkeypatch.setattr(run_module, "InternalTablesManager", FakeInternalTablesManager)
    monkeypatch.setattr(run_module, "TaskManager", RecordingTaskManager)


def _run(**overrides) -> int:
    kwargs = {
        "select": "*",
        "exclude": None,
        "steps": "load,detect,alert",
        "from_date": None,
        "to_date": None,
        "full_refresh": False,
        "force": False,
        "profile": None,
    }
    kwargs.update(overrides)
    return run_module.run_command(**kwargs)


# ── dtk run ──────────────────────────────────────────────────────────────────


class TestRunSkipsDisabledMetrics:
    def test_disabled_metric_never_reaches_the_pipeline(self, tmp_path, monkeypatch, capsys):
        root = _build_project(tmp_path, {"metric_off": False})
        _patch_run(monkeypatch, root)

        rc = _run(select="metric_off")
        out = capsys.readouterr().out

        # No load, no detect, no alert — the metric never reached run_metric.
        assert RecordingTaskManager.calls == []
        # A config choice, not a failure: schedulers must not page on it.
        assert rc == 0
        # And it is LOUD: the worst part of the bug was the silence.
        assert "metric_off: disabled in config (enabled: false)" in out
        assert "Found 0 metric(s) to process" in out

    def test_enabled_sibling_still_runs(self, tmp_path, monkeypatch):
        root = _build_project(tmp_path, {"metric_on": True, "metric_off": False})
        _patch_run(monkeypatch, root)

        assert _run() == 0
        assert RecordingTaskManager.calls == ["metric_on"]

    def test_json_summary_reports_skipped(self, tmp_path, monkeypatch, capsys):
        root = _build_project(tmp_path, {"metric_on": True, "metric_off": False})
        _patch_run(monkeypatch, root)

        rc = _run(json_output=True)
        payload = json.loads(capsys.readouterr().out)
        entries = {m["name"]: m for m in payload["metrics"]}

        assert rc == 0
        assert payload["status"] == "success"
        assert payload["exit_code"] == 0
        assert payload["aborted"] is False
        assert entries["metric_off"]["status"] == "skipped"
        assert entries["metric_off"]["error"] is None
        assert entries["metric_on"]["status"] == "success"
        assert payload["totals"]["skipped"] == 1
        assert payload["totals"]["succeeded"] == 1
        assert payload["totals"]["failed"] == 0
        assert payload["totals"]["metrics"] == 2
        # A skipped metric contributes nothing to the work counters.
        assert payload["totals"]["datapoints_loaded"] == 10
        # The entry shape is part of the schema_version: 1 contract.
        assert set(entries["metric_off"]) == set(entries["metric_on"])

    def test_every_metric_disabled_still_exits_zero(self, tmp_path, monkeypatch, capsys):
        root = _build_project(tmp_path, {"a_off": False, "b_off": False})
        _patch_run(monkeypatch, root)

        rc = _run(json_output=True)
        payload = json.loads(capsys.readouterr().out)

        assert rc == 0
        assert RecordingTaskManager.calls == []
        assert payload["totals"]["skipped"] == 2
        # NOT the "selector matched nothing" exit-1 path: the selector DID match.
        assert payload["error"] is None
        assert payload["status"] == "success"

    def test_unmatched_selector_still_exits_one(self, tmp_path, monkeypatch):
        """The disabled-skip must not swallow the matching-nothing failure."""
        root = _build_project(tmp_path, {"metric_off": False})
        _patch_run(monkeypatch, root)
        assert _run(select="does_not_exist") == 1

    def test_metrics_registry_stays_truthful(self, tmp_path, monkeypatch):
        """`_dtk_metrics` is the config mirror: its `enabled` column must follow."""
        root = _build_project(tmp_path, {"metric_off": False})
        _patch_run(monkeypatch, root)

        assert _run() == 0
        internal = FakeInternalTablesManager.instances[-1]
        assert internal.upserts == [("metric_off", False)]

    def test_registry_failure_never_fails_the_run(self, tmp_path, monkeypatch, capsys):
        root = _build_project(tmp_path, {"metric_off": False})
        _patch_run(monkeypatch, root)
        monkeypatch.setattr(
            FakeInternalTablesManager,
            "upsert_metric_config",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("registry down")),
        )

        assert _run() == 0
        assert "Registry refresh skipped for metric_off" in capsys.readouterr().out


# ── dtk autotune ─────────────────────────────────────────────────────────────


class TestAutotuneSkipsDisabledMetrics:
    def _config(self, *, enabled: bool) -> MetricConfig:
        return MetricConfig(
            name="metric_off",
            interval="1min",
            query="SELECT 1",
            enabled=enabled,
        )

    def test_disabled_metric_is_skipped_not_tuned(self, capsys):
        internal = MagicMock()
        status = autotune_module._tune_one(
            metric_path=Path("/proj/metrics/metric_off.yml"),
            config=self._config(enabled=False),
            project_root=Path("/proj"),
            internal_manager=internal,
            incidents_path=None,
            scoring_override=None,
            from_dt=None,
            to_dt=None,
            force=False,
            dry_run=False,
        )
        assert status == "skipped"
        # It never even read the datapoints, let alone took the pipeline lock.
        internal.load_datapoints.assert_not_called()
        internal.acquire_lock.assert_not_called()
        assert "metric disabled in config (enabled: false)" in capsys.readouterr().out

    def test_enabled_metric_is_not_short_circuited(self):
        """The new gate must not swallow a live metric (it fails later, on data)."""
        internal = MagicMock()
        internal.load_datapoints.return_value = {"timestamp": []}
        status = autotune_module._tune_one(
            metric_path=Path("/proj/metrics/metric_on.yml"),
            config=self._config(enabled=True),
            project_root=Path("/proj"),
            internal_manager=internal,
            incidents_path=None,
            scoring_override=None,
            from_dt=None,
            to_dt=None,
            force=False,
            dry_run=False,
        )
        assert status == "failed"  # "no datapoints", i.e. it got past the gate
        internal.load_datapoints.assert_called_once()


# ── the commands that must KEEP seeing a disabled metric ─────────────────────


class TestDiscoveryStillIncludesDisabledMetrics:
    def test_select_metrics_returns_disabled_metrics(self, tmp_path):
        """`dtk tune` / `dtk ui` / `dtk mcp` share this seam and must see them."""
        root = _build_project(tmp_path, {"metric_on": True, "metric_off": False})
        selected = {
            config.name: config.enabled for _path, config in run_module.select_metrics("*", root)
        }
        assert selected == {"metric_on": True, "metric_off": False}

    def test_disabled_metric_is_not_orphaned(self, tmp_path, monkeypatch, capsys):
        """`dtk clean --orphaned-metrics` must never purge a disabled metric's rows.

        It is still defined in YAML — only turned off. Purging it would delete
        the very history you disabled the metric to go and inspect.
        """
        root = _build_project(tmp_path, {"metric_off": False})
        internal = MagicMock()
        internal.list_known_metric_names.return_value = {"metric_off"}
        monkeypatch.setattr(clean_cmd, "find_project_root", lambda: root)
        monkeypatch.setattr(clean_cmd, "_create_internal_manager", lambda r, p: internal)

        rc = clean_cmd.run_clean(
            select=None, orphaned_metrics=True, execute=True, yes=True, profile=None
        )

        assert rc == 0
        internal.purge_metric.assert_not_called()
        assert "No orphaned metrics" in capsys.readouterr().out
