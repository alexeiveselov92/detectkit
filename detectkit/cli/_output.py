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

import click


def echo_tree(name: str, children: list[str], *, warnings: list[str] | None = None) -> None:
    """Print a ``┌─ name`` header with ``│``/``└─`` child lines.

    ``warnings`` (if any) are rendered as yellow ``│`` continuation lines above
    the children. ``children`` must be non-empty (a metric with no items should
    use :func:`echo_noop` instead).
    """
    click.echo(click.style(f"  ┌─ {name}", fg="cyan", bold=True))
    for warning in warnings or []:
        click.echo(click.style(f"  │   ⚠ {warning}", fg="yellow", bold=True))
    last = len(children) - 1
    for i, child in enumerate(children):
        prefix = "  └─ " if i == last else "  │   "
        click.echo(f"{prefix}{child}")


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
