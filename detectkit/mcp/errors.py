"""Typed errors for the MCP (Model Context Protocol) server layer.

Kept separate — mirroring :mod:`detectkit.semantic.errors` — so the server and
its tools surface failures with clear, actionable messages (mapped to a
friendly CLI exit, or to a tool-call error the MCP client renders) instead of
leaking pydantic / driver / SDK internals.
"""

from __future__ import annotations


class McpError(Exception):
    """Base class for every MCP-server failure."""


class McpProjectError(McpError):
    """The project couldn't be resolved/loaded, or a tool request was invalid.

    Covers: no ``detectkit_project.yml`` found by any of the three resolution
    mechanisms, a broken ``profiles.yml``/metric config, an unknown metric name
    / window preset / malformed timestamp, and "no data yet" (tables not
    created because no ``dtk run`` has executed).
    """


class McpDependencyMissing(McpError):
    """The optional ``[mcp]`` extra (the ``mcp`` SDK package) is not installed."""
