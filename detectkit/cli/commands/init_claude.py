"""
Implementation of ``dtk init-claude``.

Scaffolds Claude Code context into the folder that holds detectkit project(s),
so an AI assistant can natively help the user operate detectkit — work with
metrics, detectors, alerts and the ``dtk`` CLI.

It writes three things into the target directory:

- ``CLAUDE.md`` — created if absent, otherwise a managed detectkit block is
  injected/refreshed between HTML-comment markers (existing content is kept).
- ``.claude/rules/detectkit/`` — the reference docs the assistant reads on
  demand (overview, cli, project, metrics, detectors, alerting).
- ``.claude/skills/`` — user-facing skills (``dtk-new-metric``).

The source of truth for all of the above lives in ``detectkit/cli/assets/claude``
and ships with the package, so re-running this command after upgrading detectkit
refreshes the context to match the installed version. The operation is
idempotent: re-running with no upstream change reports everything unchanged.
"""

from __future__ import annotations

import re
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

import click

from detectkit import __version__
from detectkit.cli._output import echo_done, echo_tree

# Region in CLAUDE.md owned by this command. The BEGIN marker carries the
# detectkit version (informational); the regex below matches any version so a
# refresh replaces the whole region in place rather than appending a duplicate.
_BEGIN = (
    f"<!-- BEGIN detectkit v{__version__} "
    "(managed by `dtk init-claude` — do not edit between these markers) -->"
)
_END = "<!-- END detectkit -->"
_BLOCK_RE = re.compile(r"<!-- BEGIN detectkit.*?-->.*?<!-- END detectkit -->", re.DOTALL)

# New CLAUDE.md preamble (only used when the file does not exist yet).
_NEW_FILE_HEADER = (
    "# Project guidance for Claude\n\n"
    "This file gives Claude Code context about this workspace. Add your own\n"
    "notes anywhere outside the detectkit block below.\n"
)


def _assets_root() -> Traversable:
    """Return the packaged ``assets/claude`` directory as a Traversable."""
    return files("detectkit.cli").joinpath("assets", "claude")


def _render_block(section_text: str) -> str:
    """Wrap the packaged CLAUDE section in the managed markers."""
    return f"{_BEGIN}\n{section_text.strip()}\n{_END}"


def _write_if_changed(target: Path, content: str) -> str:
    """Write ``content`` to ``target``; return 'created' | 'updated' | 'unchanged'."""
    if target.exists():
        if target.read_text(encoding="utf-8") == content:
            return "unchanged"
        status = "updated"
    else:
        status = "created"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return status


def _inject_claude_md(target_dir: Path, section_text: str) -> str:
    """Create or refresh the managed detectkit block in ``CLAUDE.md``.

    Returns the status of the *block* ('created' | 'updated' | 'unchanged').
    Any user content outside the markers is preserved verbatim.
    """
    claude_md = target_dir / "CLAUDE.md"
    block = _render_block(section_text)

    if not claude_md.exists():
        claude_md.write_text(f"{_NEW_FILE_HEADER}\n{block}\n", encoding="utf-8")
        return "created"

    original = claude_md.read_text(encoding="utf-8")
    if _BLOCK_RE.search(original):
        updated = _BLOCK_RE.sub(lambda _m: block, original, count=1)
        status = "updated"
    else:
        sep = "" if original.endswith("\n\n") else ("\n" if original.endswith("\n") else "\n\n")
        updated = f"{original}{sep}{block}\n"
        status = "added"

    if updated == original:
        return "unchanged"
    claude_md.write_text(updated, encoding="utf-8")
    return status


def _copy_tree(src: Traversable, dst: Path, results: list[tuple[str, str]], _rel: str = "") -> None:
    """Recursively materialize a packaged Traversable tree under ``dst``.

    ``results`` accumulates ``(relative_path, status)`` for reporting (relative
    to the copy root), where status is 'created' | 'updated' | 'unchanged'.
    """
    dst.mkdir(parents=True, exist_ok=True)
    for child in sorted(src.iterdir(), key=lambda c: c.name):
        target = dst / child.name
        rel = f"{_rel}{child.name}"
        if child.is_dir():
            _copy_tree(child, target, results, f"{rel}/")
        else:
            status = _write_if_changed(target, child.read_text(encoding="utf-8"))
            results.append((rel, status))


def _summarize(results: list[tuple[str, str]]) -> str:
    counts: dict[str, int] = {}
    for _name, status in results:
        counts[status] = counts.get(status, 0) + 1
    return ", ".join(f"{n} {status}" for status, n in counts.items())


def run_init_claude(target_dir: str):
    """Generate Claude context (CLAUDE.md + .claude/rules + skills) in ``target_dir``."""
    target_path = Path(target_dir).resolve()
    target_path.mkdir(parents=True, exist_ok=True)

    assets = _assets_root()
    section_text = assets.joinpath("CLAUDE.section.md").read_text(encoding="utf-8")

    click.echo(f"Target: {target_path}")
    click.echo()

    # 1) CLAUDE.md
    claude_status = _inject_claude_md(target_path, section_text)
    echo_tree("CLAUDE.md", [f"detectkit section {claude_status}"])

    # 2) .claude/rules/detectkit/
    rule_results: list[tuple[str, str]] = []
    _copy_tree(
        assets.joinpath("rules"),
        target_path / ".claude" / "rules" / "detectkit",
        rule_results,
    )
    echo_tree(
        ".claude/rules/detectkit/",
        [f"{name} ({status})" for name, status in rule_results],
    )

    # 3) .claude/skills/
    skill_results: list[tuple[str, str]] = []
    _copy_tree(
        assets.joinpath("skills"),
        target_path / ".claude" / "skills",
        skill_results,
    )
    echo_tree(
        ".claude/skills/",
        [f"{name} ({status})" for name, status in skill_results],
    )

    all_results = [("CLAUDE.md", claude_status), *rule_results, *skill_results]
    echo_done(f"Claude context ready for detectkit v{__version__} ({_summarize(all_results)}).")
    click.echo()
    click.echo("Open this folder in Claude Code and ask it to help with your metrics,")
    click.echo("or run the `dtk-new-metric` skill to scaffold one.")
