"""Tests for ``dtk init-claude`` — Claude context scaffolding.

Covers: fresh creation, idempotent re-runs, marker-based injection into an
existing CLAUDE.md (append + in-place refresh) with user content preserved,
and that the packaged rules/skill are materialized.
"""

from pathlib import Path

from click.testing import CliRunner

from detectkit import __version__
from detectkit.cli.commands.init_claude import _BLOCK_RE, run_init_claude
from detectkit.cli.main import cli

RULE_FILES = {
    "overview.md",
    "cli.md",
    "project.md",
    "metrics.md",
    "detectors.md",
    "alerting.md",
}
SKILL_FILE = ".claude/skills/dtk-new-metric/SKILL.md"
SETUP_SKILL_FILE = ".claude/skills/dtk-setup-project/SKILL.md"
FEEDBACK_SKILL_FILE = ".claude/skills/dtk-feedback/SKILL.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class TestFreshScaffold:
    def test_creates_all_artifacts(self, tmp_path):
        run_init_claude(str(tmp_path))

        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        text = _read(claude_md)
        # Exactly one managed block, carrying the installed version.
        assert text.count("<!-- BEGIN detectkit") == 1
        assert text.count("<!-- END detectkit -->") == 1
        assert f"v{__version__}" in text
        assert _BLOCK_RE.search(text) is not None

        rules_dir = tmp_path / ".claude" / "rules" / "detectkit"
        assert {p.name for p in rules_dir.glob("*.md")} == RULE_FILES

        skill = tmp_path / SKILL_FILE
        assert skill.exists()
        assert "name: dtk-new-metric" in _read(skill)

        setup_skill = tmp_path / SETUP_SKILL_FILE
        assert setup_skill.exists()
        assert "name: dtk-setup-project" in _read(setup_skill)

        feedback_skill = tmp_path / FEEDBACK_SKILL_FILE
        assert feedback_skill.exists()
        assert "name: dtk-feedback" in _read(feedback_skill)

    def test_block_points_to_rules_and_skill(self, tmp_path):
        run_init_claude(str(tmp_path))
        text = _read(tmp_path / "CLAUDE.md")
        assert ".claude/rules/detectkit/" in text
        assert "dtk-new-metric" in text
        assert "dtk-setup-project" in text
        assert "dtk-feedback" in text


class TestIdempotency:
    def test_rerun_changes_nothing(self, tmp_path):
        run_init_claude(str(tmp_path))
        before = {p: _read(p) for p in tmp_path.rglob("*") if p.is_file()}

        run_init_claude(str(tmp_path))
        after = {p: _read(p) for p in tmp_path.rglob("*") if p.is_file()}

        assert before.keys() == after.keys()
        assert before == after


class TestInjectionIntoExistingFile:
    def test_appends_block_and_preserves_user_content(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text("# My rules\n\nAlways write tests.\n", encoding="utf-8")

        run_init_claude(str(tmp_path))
        text = _read(claude_md)

        assert "# My rules" in text
        assert "Always write tests." in text
        assert text.count("<!-- BEGIN detectkit") == 1
        assert text.count("<!-- END detectkit -->") == 1

    def test_refreshes_stale_block_in_place(self, tmp_path):
        claude_md = tmp_path / "CLAUDE.md"
        claude_md.write_text(
            "# Top\n\nmine above.\n\n"
            "<!-- BEGIN detectkit v0.0.1 (managed by `dtk init-claude` — do not "
            "edit between these markers) -->\n"
            "OLD STALE CONTENT\n"
            "<!-- END detectkit -->\n\n"
            "mine below.\n",
            encoding="utf-8",
        )

        run_init_claude(str(tmp_path))
        text = _read(claude_md)

        # User content on both sides preserved; stale body gone; single block.
        assert "mine above." in text
        assert "mine below." in text
        assert "OLD STALE CONTENT" not in text
        assert text.count("<!-- BEGIN detectkit") == 1
        assert text.count("<!-- END detectkit -->") == 1
        assert f"v{__version__}" in text


class TestCliWiring:
    def test_init_claude_command_runs(self, tmp_path):
        runner = CliRunner()
        result = runner.invoke(cli, ["init-claude", "--target-dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "CLAUDE.md").exists()
        assert (tmp_path / SKILL_FILE).exists()
