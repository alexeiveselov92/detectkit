"""Implementation of 'dtk mcp' — the read-only Model Context Protocol server.

Isolated from the load/detect/alert pipeline: this module imports only
``click`` at load time. Everything else — :mod:`detectkit.mcp.server` and the
optional ``mcp`` SDK it lazily guards — is imported inside :func:`run_mcp`'s
body, so `import detectkit.cli.commands.mcp` never pulls in the SDK either.
"""

from __future__ import annotations

import click


def run_mcp(*, project_dir: str | None, select: str, profile: str | None) -> None:
    """Resolve the project and serve the read-only MCP server over stdio.

    Args:
        project_dir: Explicit project directory (searched upward for
            ``detectkit_project.yml``). Falls back to ``$DETECTKIT_PROJECT_DIR``,
            then to searching upward from the current directory.
        select: Selector scoping which metrics the server exposes.
        profile: Profile name to use (defaults to the project's
            ``default_profile``).
    """
    from detectkit.mcp.errors import McpError
    from detectkit.mcp.server import run_server

    try:
        run_server(project_dir=project_dir, selector=select, profile=profile)
    except McpError as exc:
        raise click.ClickException(str(exc)) from exc
