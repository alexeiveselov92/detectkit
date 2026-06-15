"""Tests for the shared CLI output helpers and the commands that use them
(`dtk unlock`, `dtk clean`) so they all render in the same tree style."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from detectkit.cli._output import echo_done, echo_error, echo_noop, echo_tree
from detectkit.cli.commands import unlock as unlock_cmd

# click.echo strips ANSI colour codes when the stream is not a TTY (as under
# capsys), so assertions can match the plain text directly.


class TestOutputHelpers:
    def test_tree_single_child_has_no_continuation(self, capsys):
        echo_tree("metric", ["only item"])
        out = capsys.readouterr().out
        assert out.splitlines() == ["  ┌─ metric", "  └─ only item"]

    def test_tree_multiple_children(self, capsys):
        echo_tree("metric", ["a", "b", "c"])
        assert capsys.readouterr().out.splitlines() == [
            "  ┌─ metric",
            "  │   a",
            "  │   b",
            "  └─ c",
        ]

    def test_tree_warnings_render_above_children(self, capsys):
        echo_tree("metric", ["item"], warnings=["careful"])
        assert capsys.readouterr().out.splitlines() == [
            "  ┌─ metric",
            "  │   ⚠ careful",
            "  └─ item",
        ]

    def test_noop(self, capsys):
        echo_noop("metric", "nothing stale")
        assert capsys.readouterr().out == "  • metric: nothing stale\n"

    def test_error_goes_to_stderr(self, capsys):
        echo_error("metric", "boom")
        cap = capsys.readouterr()
        assert "  ✗ metric: boom" in cap.err
        assert cap.out == ""

    def test_done_has_leading_blank_and_prefix(self, capsys):
        echo_done("All good.")
        out = capsys.readouterr().out
        assert out == "\nDone. All good.\n"


@pytest.fixture
def unlock_env(tmp_path, monkeypatch):
    """Patch unlock's project/profile/manager wiring; return the mock manager."""
    (tmp_path / "profiles.yml").write_text("profiles: {}\n")
    monkeypatch.setattr(unlock_cmd, "find_project_root", lambda: tmp_path)
    fake_profiles = MagicMock()
    fake_profiles.create_manager.return_value = MagicMock()
    monkeypatch.setattr(unlock_cmd, "ProfilesConfig", MagicMock(from_yaml=lambda p: fake_profiles))
    internal = MagicMock()
    monkeypatch.setattr(unlock_cmd, "InternalTablesManager", lambda dbm: internal)
    return internal


def _select_one(monkeypatch, name="cpu_usage"):
    cfg = SimpleNamespace(name=name)
    monkeypatch.setattr(unlock_cmd, "select_metrics", lambda s, root: [(Path("x.yml"), cfg)])


class TestUnlockOutput:
    def test_cleared_lock_uses_tree(self, capsys, monkeypatch, unlock_env):
        _select_one(monkeypatch)
        unlock_env.clear_lock.return_value = True
        unlock_cmd.run_unlock(select="cpu_usage", profile=None)
        out = capsys.readouterr().out
        assert "  ┌─ cpu_usage" in out
        assert "  └─ lock cleared" in out
        assert "Done. Cleared 1 lock(s) of 1 metric(s)." in out

    def test_no_lock_uses_bullet(self, capsys, monkeypatch, unlock_env):
        _select_one(monkeypatch)
        unlock_env.clear_lock.return_value = False
        unlock_cmd.run_unlock(select="cpu_usage", profile=None)
        out = capsys.readouterr().out
        assert "  • cpu_usage: no active lock" in out
        assert "Done. Cleared 0 lock(s) of 1 metric(s)." in out

    def test_error_uses_cross_on_stderr(self, capsys, monkeypatch, unlock_env):
        _select_one(monkeypatch)
        unlock_env.clear_lock.side_effect = RuntimeError("db down")
        unlock_cmd.run_unlock(select="cpu_usage", profile=None)
        cap = capsys.readouterr()
        assert "  ✗ cpu_usage: error clearing lock: db down" in cap.err
