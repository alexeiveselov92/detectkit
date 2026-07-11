"""Tests for CLI exit codes and `dtk run --json` (issue: every failure exited 0).

Covers:
- click wiring (CliRunner): startup failures exit non-zero, usage errors exit 2.
- `run_command` unit-level: per-metric outcomes drive the returned exit code,
  and an aborted run marks the remaining metrics "skipped".
- `--json`: the emitted document matches the frozen schema and carries all
  human-readable output on stderr, leaving stdout as exactly one JSON document
  (even for a startup error).
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from detectkit.cli.commands import run as run_module
from detectkit.cli.main import cli
from detectkit.orchestration.task_manager import PipelineStep, TaskStatus

# ── fakes for the run_command unit-level / --json tests ─────────────────────


class FakeProfilesConfig:
    """Stand-in for ``ProfilesConfig`` — never touches profiles.yml for real."""

    @classmethod
    def from_yaml(cls, path: Path) -> FakeProfilesConfig:
        return cls()

    def create_manager(self, profile: str | None) -> object:
        return object()


class FakeInternalTablesManager:
    """Stand-in for ``InternalTablesManager`` — no DB, ``ensure_tables`` is a no-op."""

    def __init__(self, db_manager: object) -> None:
        self.db_manager = db_manager

    def ensure_tables(self) -> None:
        pass


def _fake_task_manager_class(results: list[dict]):
    """Build a ``TaskManager`` stand-in whose ``run_metric`` yields *results* in order."""
    queue = list(results)

    class _FakeTaskManager:
        def __init__(self, **kwargs: object) -> None:
            pass

        def run_metric(self, **kwargs: object) -> dict:
            return queue.pop(0)

    return _FakeTaskManager


def _success_result() -> dict:
    return {
        "status": TaskStatus.SUCCESS,
        "error": None,
        "steps_completed": [PipelineStep.LOAD, PipelineStep.DETECT, PipelineStep.ALERT],
        "datapoints_loaded": 10,
        "anomalies_detected": 2,
        "alerts_sent": 1,
        "abort_run": False,
    }


def _failed_result() -> dict:
    return {
        "status": TaskStatus.FAILED,
        "error": "RuntimeError: boom",
        "steps_completed": [],
        "datapoints_loaded": 0,
        "anomalies_detected": 0,
        "alerts_sent": 0,
        "abort_run": False,
    }


def _abort_result() -> dict:
    return {
        "status": TaskStatus.FAILED,
        "error": "ConnectionError: db down",
        "steps_completed": [],
        "datapoints_loaded": 0,
        "anomalies_detected": 0,
        "alerts_sent": 0,
        "abort_run": True,
    }


def _build_project(tmp_path: Path, metric_names: list[str]) -> Path:
    """A minimal on-disk project: detectkit_project.yml, profiles.yml, metrics/*.yml."""
    (tmp_path / "detectkit_project.yml").write_text("name: demo_project\ndefault_profile: dev\n")
    (tmp_path / "profiles.yml").write_text("profiles: {}\n")  # never actually parsed (mocked)
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    for name in metric_names:
        (metrics_dir / f"{name}.yml").write_text(
            f'name: {name}\ninterval: 1min\nquery: "SELECT 1"\n'
        )
    return tmp_path


def _patch_fakes(monkeypatch, root: Path, task_manager_results: list[dict]) -> None:
    monkeypatch.setattr(run_module, "find_project_root", lambda: root)
    monkeypatch.setattr(run_module, "ProfilesConfig", FakeProfilesConfig)
    monkeypatch.setattr(run_module, "InternalTablesManager", FakeInternalTablesManager)
    monkeypatch.setattr(run_module, "TaskManager", _fake_task_manager_class(task_manager_results))


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


# ── click wiring (CliRunner) ─────────────────────────────────────────────────


class TestCliExitCodes:
    def test_run_not_a_project_exits_1(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["run", "--select", "x"])
        assert result.exit_code == 1

    def test_clean_not_a_project_exits_1(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["clean", "--select", "x"])
        assert result.exit_code == 1

    def test_autotune_not_a_project_exits_1(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["autotune", "--select", "x"])
        assert result.exit_code == 1

    def test_clean_neither_flag_exits_2(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["clean"])
        assert result.exit_code == 2

    def test_clean_both_flags_exits_2(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["clean", "--select", "x", "--orphaned-metrics"])
        assert result.exit_code == 2


# ── run_command unit-level (no DB, TaskManager stubbed) ─────────────────────


class TestRunCommandExitCodes:
    def test_success_returns_zero(self, tmp_path, monkeypatch):
        root = _build_project(tmp_path, ["metric_a"])
        _patch_fakes(monkeypatch, root, [_success_result()])
        assert _run() == 0

    def test_failed_metric_returns_one(self, tmp_path, monkeypatch):
        root = _build_project(tmp_path, ["metric_a"])
        _patch_fakes(monkeypatch, root, [_failed_result()])
        assert _run() == 1

    def test_abort_marks_remaining_metrics_skipped(self, tmp_path, monkeypatch, capsys):
        root = _build_project(tmp_path, ["metric_a", "metric_b"])
        # Only one result queued: metric_b must never reach run_metric once the
        # first metric aborts the run.
        _patch_fakes(monkeypatch, root, [_abort_result()])
        rc = _run(json_output=True)
        payload = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert payload["aborted"] is True
        assert [m["name"] for m in payload["metrics"]] == ["metric_a", "metric_b"]
        assert payload["metrics"][0]["status"] == "failed"
        assert payload["metrics"][1]["status"] == "skipped"
        assert payload["totals"]["skipped"] == 1
        assert payload["totals"]["failed"] == 1

    def test_no_metrics_matched_returns_one(self, tmp_path, monkeypatch):
        root = _build_project(tmp_path, [])
        _patch_fakes(monkeypatch, root, [])
        assert _run(select="nope") == 1


# ── --json ────────────────────────────────────────────────────────────────


class TestJsonSummary:
    def test_success_json_shape_and_stdout_isolation(self, tmp_path, monkeypatch, capsys):
        root = _build_project(tmp_path, ["metric_a"])
        _patch_fakes(monkeypatch, root, [_success_result()])

        rc = _run(json_output=True)
        captured = capsys.readouterr()

        # Human output (echoed "Project root: ...", etc.) landed on stderr.
        assert "Project root" in captured.err
        assert "Project root" not in captured.out

        # stdout is exactly one JSON document — nothing else.
        lines = captured.out.strip("\n").splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])

        assert rc == 0
        assert payload["schema_version"] == 1
        assert payload["command"] == "run"
        assert payload["project"] == "demo_project"
        assert payload["selector"] == "*"
        assert payload["exclude"] is None
        assert payload["steps"] == ["load", "detect", "alert"]
        assert payload["status"] == "success"
        assert payload["error"] is None
        assert payload["aborted"] is False
        assert payload["exit_code"] == 0
        assert payload["totals"] == {
            "metrics": 1,
            "succeeded": 1,
            "failed": 0,
            "skipped": 0,
            "datapoints_loaded": 10,
            "anomalies_detected": 2,
            "alerts_sent": 1,
        }
        metric0 = payload["metrics"][0]
        assert metric0["name"] == "metric_a"
        assert metric0["status"] == "success"
        assert metric0["steps_completed"] == ["load", "detect", "alert"]
        assert metric0["error"] is None
        assert set(metric0.keys()) == {
            "name",
            "status",
            "steps_completed",
            "datapoints_loaded",
            "anomalies_detected",
            "alerts_sent",
            "error",
        }

    def test_failed_metric_json_status_and_exit_code(self, tmp_path, monkeypatch, capsys):
        root = _build_project(tmp_path, ["metric_a"])
        _patch_fakes(monkeypatch, root, [_failed_result()])

        rc = _run(json_output=True)
        payload = json.loads(capsys.readouterr().out)
        assert rc == 1
        assert payload["status"] == "failed"
        assert payload["exit_code"] == 1
        assert payload["metrics"][0]["status"] == "failed"
        assert payload["metrics"][0]["error"] == "RuntimeError: boom"

    def test_startup_error_emits_valid_json(self, monkeypatch, capsys):
        monkeypatch.setattr(run_module, "find_project_root", lambda: None)

        rc = _run(json_output=True)
        captured = capsys.readouterr()
        lines = captured.out.strip("\n").splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])

        assert rc == 1
        assert payload["status"] == "error"
        assert payload["error"] is not None
        assert payload["metrics"] == []
        assert payload["totals"] == {
            "metrics": 0,
            "succeeded": 0,
            "failed": 0,
            "skipped": 0,
            "datapoints_loaded": 0,
            "anomalies_detected": 0,
            "alerts_sent": 0,
        }
        assert payload["exit_code"] == 1
