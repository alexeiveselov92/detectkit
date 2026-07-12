"""Read-only Model Context Protocol (MCP) server for detectkit.

An **isolated, additive** layer — mirroring ``detectkit/semantic/``'s design:
nothing in the load/detect/alert pipeline imports it, so it can never affect
a running project. It powers only the ``dtk mcp`` command
(:mod:`detectkit.cli.commands.mcp`), which exposes a project's metrics,
loaded data, detector results, replayed alert history, autotune runs and
labeled incidents to an MCP client (an IDE assistant, a desktop app, a cloud
agent) over stdio.

The ``mcp`` SDK (the ``[mcp]`` extra, ``pip install 'detectkit[mcp]'``) is a
guarded, lazy import — see :mod:`detectkit.mcp.server` — so this package (and
every module in it) imports cleanly even when the extra isn't installed;
only building/running the actual server needs it.

Module map:

- ``errors.py`` — :class:`McpError` / :class:`McpProjectError` /
  :class:`McpDependencyMissing`.
- ``context.py`` — project resolution (``--project-dir`` ->
  ``$DETECTKIT_PROJECT_DIR`` -> cwd search) and the long-lived
  :class:`McpContext` (mirrors ``dtk run``'s build order, minus
  ``ensure_tables()`` — read-only never runs DDL).
- ``serialize.py`` — ISO-8601 / numpy-free JSON conversion helpers shared by
  every tool.
- ``tools.py`` — the 10 read-only tool implementations, as plain functions
  (no SDK dependency; directly unit-testable).
- ``server.py`` — the guarded ``FastMCP`` wiring + ``dtk mcp``'s entry point
  (:func:`~detectkit.mcp.server.run_server`).

See :mod:`detectkit.mcp.tools` for the full tool list and the read-only
exclusion contract (no config/label writes, no pipeline runs, no DDL).
"""

from __future__ import annotations

from detectkit.mcp.context import McpContext, build_context, resolve_project_dir
from detectkit.mcp.errors import McpDependencyMissing, McpError, McpProjectError

__all__ = [
    "McpContext",
    "McpDependencyMissing",
    "McpError",
    "McpProjectError",
    "build_context",
    "resolve_project_dir",
]
