"""Shared CLI output helpers so every command renders in one house style.

Mirrors the load → detect → alert pipeline's tree look (``┌─ / │ / └─``) used by
``dtk run`` so the maintenance commands (``dtk clean``, ``dtk unlock``) match it
instead of each inventing its own formatting.

House conventions:
- A metric *with* something to report is a tree: a cyan-bold ``┌─ <name>``
  header followed by one child line per item (``│   `` for all but the last,
  ``└─ `` for the last).
- A metric with *nothing* to do is a single ``•`` line.
- A per-metric error is a red ``✗`` line (to stderr).
- The final summary is a cyan-bold ``Done. …`` line.
"""

from __future__ import annotations

from collections.abc import Callable

import click

# Autotune-engine stage name → display title for the streamed run-log tree.
# Most stages render as ``stage.upper()``; only the two underscored names need a
# space so the header reads cleanly (``DETECTOR SELECT`` / ``GRID SEARCH``).
AUTOTUNE_STAGE_TITLES = {
    "labels": "LABELS",
    "seasonality": "SEASONALITY",
    "detector_select": "DETECTOR SELECT",
    "grid_search": "GRID SEARCH",
    "window": "WINDOW",
}


def echo_block(
    title: str,
    children: list[str],
    *,
    warnings: list[str] | None = None,
    echo: Callable[[str], None] = click.echo,
) -> None:
    """Print a cyan-bold ``┌─ title`` header with ``│``/``└─`` child lines.

    The injectable core of the house tree style (``dtk run``'s load/detect/alert
    blocks): ``warnings`` render as yellow ``│`` continuation lines above the
    children, the last child gets the ``└─`` elbow. ``echo`` defaults to
    ``click.echo`` but can be any line sink, so the tune server can stream the
    same blocks through its own output callback. ``children`` must be non-empty.
    """
    echo(click.style(f"  ┌─ {title}", fg="cyan", bold=True))
    for warning in warnings or []:
        echo(click.style(f"  │   ⚠ {warning}", fg="yellow", bold=True))
    last = len(children) - 1
    for i, child in enumerate(children):
        prefix = "  └─ " if i == last else "  │   "
        echo(f"{prefix}{child}")


def echo_tree(name: str, children: list[str], *, warnings: list[str] | None = None) -> None:
    """Print a ``┌─ name`` header with ``│``/``└─`` child lines.

    ``warnings`` (if any) are rendered as yellow ``│`` continuation lines above
    the children. ``children`` must be non-empty (a metric with no items should
    use :func:`echo_noop` instead). Thin wrapper over :func:`echo_block` (the
    CLI-default ``click.echo`` sink).
    """
    echo_block(name, children, warnings=warnings)


class StageLogRenderer:
    """Stream ``(stage, line)`` engine progress as the run-log tree.

    Opens a cyan-bold ``┌─ TITLE`` header the first time each stage appears and
    prints every subsequent line for that stage as a ``│   `` child — the same
    look as ``dtk run``'s load/detect/alert blocks. ``titles`` maps an engine
    stage name to its display title (unmapped names fall back to ``upper()``);
    ``echo`` is injectable so one renderer drives both the CLI (``click.echo``)
    and the ``dtk tune`` server (its own output callback). Build a fresh renderer
    per run so the first stage re-opens its header.
    """

    def __init__(
        self,
        *,
        titles: dict[str, str] | None = None,
        echo: Callable[[str], None] = click.echo,
    ) -> None:
        self._open: str | None = None
        self._titles = titles or {}
        self._echo = echo

    def __call__(self, stage: str, line: str) -> None:
        if self._open != stage:
            title = self._titles.get(stage, stage.upper())
            self._echo(click.style(f"  ┌─ {title}", fg="cyan", bold=True))
            self._open = stage
        self._echo(f"  │   {line}")


def echo_noop(name: str, reason: str) -> None:
    """A metric with nothing to do — a single ``•`` line."""
    click.echo(f"  • {name}: {reason}")


def echo_error(name: str, message: str) -> None:
    """A per-metric failure — a red ``✗`` line on stderr."""
    click.echo(click.style(f"  ✗ {name}: {message}", fg="red"), err=True)


def echo_done(summary: str) -> None:
    """The closing ``Done. …`` summary (cyan, bold), preceded by a blank line."""
    click.echo()
    click.echo(click.style(f"Done. {summary}", fg="cyan", bold=True))
