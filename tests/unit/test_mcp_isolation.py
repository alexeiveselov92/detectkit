"""Isolation guarantees for the MCP server layer (mirrors ``test_osi.py``'s pattern).

Two properties are load-bearing:

(a) Nothing in the load/detect/alert pipeline (or the plain CLI entry point)
    imports :mod:`detectkit.mcp` — so a project that never runs `dtk mcp`
    pays zero cost, and the optional ``mcp`` SDK dependency can never leak
    into a core pipeline run.
(b) :mod:`detectkit.mcp.server` itself imports cleanly even when the ``mcp``
    SDK isn't installed — only *building*/*running* the actual server needs
    it, and doing so without the SDK raises a friendly, actionable error
    instead of a raw ``ImportError``.
"""

from __future__ import annotations

import subprocess
import sys

import pytest


def _mask_mcp_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block any import of the ``mcp`` SDK, whether or not it's already cached.

    Masks every already-imported ``mcp``/``mcp.*`` module *and* the specific
    dotted names :func:`~detectkit.mcp.server._fastmcp_class` imports, so the
    test doesn't depend on whether some earlier test happened to import the
    real SDK first (a bare ``sys.modules`` scan alone would find nothing to
    mask on a fresh process where ``mcp`` was never touched yet).
    """
    for name in list(sys.modules):
        if name == "mcp" or name.startswith("mcp."):
            monkeypatch.setitem(sys.modules, name, None)
    for name in ("mcp", "mcp.server", "mcp.server.fastmcp"):
        monkeypatch.setitem(sys.modules, name, None)


def _fresh_import_never_pulls_in_mcp(module_name: str) -> None:
    """Probe in a SUBPROCESS: a genuinely fresh interpreter imports
    *module_name* and asserts ``detectkit.mcp`` never lands in ``sys.modules``.

    Deliberately NOT an in-process purge-and-reimport: deleting
    ``detectkit.orchestration``/``detectkit.loaders`` entries from
    ``sys.modules`` splits module identity for the rest of the session —
    later tests ``patch()`` into the re-imported module object while their
    already-bound references execute the old one, so the mock silently never
    applies (this exact interaction broke two hybrid-mode tests).
    """
    code = (
        "import importlib, sys; "
        f"importlib.import_module({module_name!r}); "
        "leaked = [m for m in sys.modules if m == 'detectkit.mcp' "
        "or m.startswith('detectkit.mcp.')]; "
        "print(leaked); "
        "sys.exit(1 if leaked else 0)"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, (
        f"importing {module_name} pulled in detectkit.mcp: "
        f"{result.stdout.strip()} {result.stderr.strip()}"
    )


class TestPipelineNeverImportsMcp:
    def test_orchestration_does_not_import_mcp(self) -> None:
        _fresh_import_never_pulls_in_mcp("detectkit.orchestration")

    def test_loaders_does_not_import_mcp(self) -> None:
        _fresh_import_never_pulls_in_mcp("detectkit.loaders")

    def test_cli_main_does_not_import_mcp(self) -> None:
        _fresh_import_never_pulls_in_mcp("detectkit.cli.main")


class TestGuardedSdkImport:
    def test_server_module_imports_even_with_sdk_masked(self) -> None:
        # Subprocess probe (same no-purge rationale as above): a fresh
        # interpreter with the mcp SDK blocked must still import the server
        # module — the module-level code never touches the SDK.
        code = (
            "import sys; "
            "sys.modules['mcp'] = None; sys.modules['mcp.server'] = None; "
            "sys.modules['mcp.server.fastmcp'] = None; "
            "import detectkit.mcp.server as s; "
            "assert hasattr(s, 'build_server') and hasattr(s, 'run_server')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr.strip()

    def test_build_server_raises_friendly_error_without_sdk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from detectkit.mcp.errors import McpDependencyMissing
        from detectkit.mcp.server import _fastmcp_class

        _mask_mcp_sdk(monkeypatch)

        with pytest.raises(McpDependencyMissing, match=r"pip install 'detectkit\[mcp\]'"):
            _fastmcp_class()

    def test_dependency_missing_message_names_the_extra(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from detectkit.mcp.errors import McpDependencyMissing
        from detectkit.mcp.server import _fastmcp_class

        _mask_mcp_sdk(monkeypatch)

        with pytest.raises(McpDependencyMissing) as excinfo:
            _fastmcp_class()
        assert "mcp" in str(excinfo.value)
        assert "detectkit[mcp]" in str(excinfo.value)
