"""Project resolution + a long-lived read-only context for the MCP server.

An MCP client (a desktop app, an IDE extension, a cloud agent) launches
``dtk mcp`` with **no working directory guarantee** — its config passes an
absolute command + args, never a ``cwd``. So project discovery cannot rely on
``Path.cwd()`` alone the way every other ``dtk`` command does; see
:func:`resolve_project_dir`.

:class:`McpContext` is built once at server startup (mirroring ``dtk run``'s
build order in ``cli/commands/run.py`` — project config → metric selection →
``profiles.yml`` → database manager → :class:`InternalTablesManager`) and then
read by every tool call for the life of the process. Two read-only-specific
deviations from that build order:

- **No** ``internal_manager.ensure_tables()`` call — a read-only server must
  never create schema/DDL. Table presence is probed once
  (:data:`McpContext.tables_ready`) so tools can fail with a clear "no data
  yet" message instead of a raw driver error. The database manager itself is
  built with ``ensure_locations=False`` (:meth:`ProfileConfig.create_manager`)
  so even *connecting* can't create a database/schema — every backend
  constructor otherwise does that as a side effect. For a file-backed DuckDB
  profile that forces a read-only attach, and a missing state file (no
  ``dtk run`` yet) then fails to attach at all; that one specific failure is
  caught and degraded into a manager-unavailable :class:`McpContext`
  (``internal=None``, ``tables_ready=False``) instead of a hard startup
  error — see :func:`_is_duckdb_missing_state_file`.
- **Session scoping.** The server's ``--select`` selector is not just a
  default — every tool that takes a metric name refuses one outside this set
  (:meth:`McpContext.require_metric`), and ``list_metrics``/
  ``get_project_status`` intersect their own selector against it. This is a
  deliberate access-control boundary: whoever launches the server (an
  operator, an MCP client config) decides which metrics an agent may read,
  independent of what a full ``dtk run --select "*"`` would touch.

A single :class:`threading.Lock` (``McpContext.lock``) serializes every
DB-touching tool call, mirroring ``detectkit/ui/server.py``'s ``db_lock``
rationale: the underlying manager holds one connection.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from pathlib import Path

from detectkit.cli.commands.run import select_metrics
from detectkit.config.metric_config import MetricConfig
from detectkit.config.profile import ProfileConfig, ProfilesConfig
from detectkit.config.project_config import ProjectConfig
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.database.tables import TABLE_DATAPOINTS
from detectkit.mcp.errors import McpProjectError

_PROJECT_MARKER = "detectkit_project.yml"
_ENV_PROJECT_DIR = "DETECTKIT_PROJECT_DIR"
_MAX_UPWARD_LEVELS = 10


def _search_upward(start: Path) -> Path | None:
    """Walk *start* and its parents (up to :data:`_MAX_UPWARD_LEVELS`) for the marker file."""
    current = start
    for _ in range(_MAX_UPWARD_LEVELS):
        if (current / _PROJECT_MARKER).exists():
            return current
        if current.parent == current:
            break
        current = current.parent
    return None


def resolve_project_dir(project_dir_flag: str | None) -> Path:
    """Resolve the project root, in order: ``--project-dir`` -> ``$DETECTKIT_PROJECT_DIR`` -> cwd.

    Each mechanism searches upward from its starting directory for
    ``detectkit_project.yml`` (so pointing at a subdirectory of the project
    still resolves). Raises :class:`McpProjectError` naming all three
    mechanisms when none resolves — the MCP client passes no ``cwd``, so a
    silent cwd-only fallback would leave the server unable to find the
    project with no actionable error.
    """
    if project_dir_flag:
        start = Path(project_dir_flag).expanduser().resolve()
        found = _search_upward(start)
        if found is None:
            raise McpProjectError(
                f"--project-dir {project_dir_flag!r} is not a detectkit project "
                f"(no {_PROJECT_MARKER} found searching upward from {start})."
            )
        return found

    env_dir = os.environ.get(_ENV_PROJECT_DIR)
    if env_dir:
        start = Path(env_dir).expanduser().resolve()
        found = _search_upward(start)
        if found is None:
            raise McpProjectError(
                f"${_ENV_PROJECT_DIR}={env_dir!r} is not a detectkit project "
                f"(no {_PROJECT_MARKER} found searching upward from {start})."
            )
        return found

    found = _search_upward(Path.cwd())
    if found is None:
        raise McpProjectError(
            "Could not find a detectkit project. Tried, in order: "
            "1) the --project-dir flag (not given), "
            f"2) the ${_ENV_PROJECT_DIR} environment variable (not set), "
            f"3) searching upward from the current directory ({Path.cwd()}) for "
            f"{_PROJECT_MARKER}. Pass --project-dir, set ${_ENV_PROJECT_DIR}, or "
            "launch the server with a cwd inside a detectkit project."
        )
    return found


def _tables_ready(internal: InternalTablesManager) -> bool:
    """Whether the internal tables already exist (never created here — read-only)."""
    manager = internal._manager  # noqa: SLF001 - same access pattern as tests/other callers
    try:
        return manager.table_exists(TABLE_DATAPOINTS, schema=manager.internal_location)
    except Exception:  # noqa: BLE001 - a probe failure reads as "not ready", not a crash
        return False


def _resolve_duckdb_path(profile_config: ProfileConfig, project_root: Path) -> ProfileConfig:
    """Absolutize a DuckDB profile's relative ``path`` against *project_root*.

    FINDING B: an MCP client launches ``dtk mcp`` with **no cwd guarantee**
    (see the module docstring) — a relative ``path`` resolved the ordinary
    way (against ``Path.cwd()``, e.g. via a bare ``open()``/``duckdb.connect``)
    would land wherever the launcher happened to start the process, and could
    even *create* a stray state file there. Every other project-relative path
    in detectkit (metrics/, incidents/, …) is resolved against the project
    root, so a relative DuckDB ``path`` should be too. ``":memory:"`` and an
    already-absolute path pass through unchanged. Returns a **copy**
    (``model_copy``) — the original ``ProfileConfig``/``ProfilesConfig`` is
    shared state (e.g. reused by ``get_server_info``) and must not be mutated.
    """
    if profile_config.type != "duckdb" or not profile_config.path:
        return profile_config
    if profile_config.path == ":memory:":
        return profile_config
    raw_path = Path(profile_config.path)
    if raw_path.is_absolute():
        return profile_config
    return profile_config.model_copy(update={"path": str((project_root / raw_path).resolve())})


def _is_duckdb_missing_state_file(profile_config: ProfileConfig, exc: Exception) -> bool:
    """Narrow match for DuckDB's "no such file, read-only attach" failure.

    FINDING A: this is the ONE expected failure mode of probing a
    file-backed DuckDB profile with ``ensure_locations=False`` (which forces
    a read-only connect — see :class:`~detectkit.database.duckdb_manager.DuckDBDatabaseManager`)
    before the state file exists, e.g. before the project's first
    ``dtk run``. Matched narrowly on both the profile type *and* the
    exception's own "does not exist" wording (DuckDB raises the same
    ``IOException`` type for other I/O failures against an *existing* file —
    permissions, corruption — which must still propagate as a real error,
    not be silently read as "no data yet"). Any other construction failure
    (unsupported type, missing driver, bad credentials for a server backend,
    …) is never swallowed here.
    """
    if profile_config.type != "duckdb":
        return False
    try:
        import duckdb  # noqa: PLC0415 - optional dep, mirrors DuckDBDatabaseManager's own lazy import
    except ImportError:
        return False
    return isinstance(exc, duckdb.IOException) and "does not exist" in str(exc)


@dataclass
class McpContext:
    """Everything a tool call needs, built once at server startup.

    ``internal`` is ``None`` only in the degraded manager-unavailable state
    (see the module docstring) — every DB-touching tool calls
    :meth:`require_internal` instead of touching ``self.internal`` directly,
    which both raises the friendly "no data yet" error in that state and
    narrows ``InternalTablesManager | None`` to a concrete manager for the
    caller (a plain ``ctx.internal`` access has no such guarantee, which is
    why no tool does that).
    """

    project_root: Path
    project_config: ProjectConfig
    profiles_config: ProfilesConfig
    internal: InternalTablesManager | None
    profile_name: str | None
    selector: str
    metrics_by_name: dict[str, tuple[Path, MetricConfig]]
    tables_ready: bool
    lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def metric_names(self) -> set[str]:
        return set(self.metrics_by_name)

    def require_metric(self, name: str) -> tuple[Path, MetricConfig]:
        """The ``(path, config)`` for *name*, or a clear error outside the session scope."""
        entry = self.metrics_by_name.get(name)
        if entry is not None:
            return entry
        known = sorted(self.metric_names)
        if known:
            shown = ", ".join(known[:20]) + (", …" if len(known) > 20 else "")
            detail = f"Known metrics: [{shown}]"
        else:
            detail = "No metrics matched at startup."
        raise McpProjectError(
            f"Metric {name!r} is not in this server's selected scope "
            f"({self.selector!r}). {detail}"
        )

    def require_internal(self) -> InternalTablesManager:
        """Return the internal-tables manager, or raise a clear "no data yet" error.

        Covers two distinct causes, both surfaced with the same friendly
        message (a tool caller shouldn't need to know which): the internal
        tables exist in a reachable database but are simply empty (no
        ``dtk run`` yet), or the state database/file itself isn't reachable
        or hasn't been created at all (e.g. a DuckDB profile pointing at a
        file `dtk run` hasn't written to — see :func:`build_context`'s
        manager-unavailable degrade). Combining the check and the return
        value in one call lets every DB-touching tool get a properly typed,
        non-``None`` manager back instead of a separate check plus a
        ``ctx.internal`` access mypy can't narrow on its own.
        """
        if self.internal is not None and self.tables_ready:
            return self.internal
        if self.internal is None:
            reason = "the state database is not reachable or hasn't been created yet"
        else:
            reason = "the internal tables don't exist"
        raise McpProjectError(
            f"No data yet — {reason}. This is a read-only server (it "
            "never runs DDL); run `dtk run` for this project first, "
            "then restart `dtk mcp`."
        )


def build_context(
    *,
    project_dir: str | None,
    selector: str,
    profile: str | None,
) -> McpContext:
    """Resolve the project and build the long-lived, read-only :class:`McpContext`.

    Mirrors ``run_command``'s build order (project config -> select metrics ->
    profiles.yml -> database manager -> :class:`InternalTablesManager`) but
    never calls ``ensure_tables()`` — a read-only server must not create
    schema. The manager itself is built with ``ensure_locations=False`` (see
    the module docstring), so connecting can't create a database/schema
    either. Every failure is wrapped as :class:`McpProjectError` with a clear
    message (the CLI maps it to a friendly exit) — **except** the one
    expected "no DuckDB state file yet" shape, which degrades to a
    manager-unavailable context instead (see
    :func:`_is_duckdb_missing_state_file`).
    """
    project_root = resolve_project_dir(project_dir)

    project_config_path = project_root / "detectkit_project.yml"
    try:
        project_config = ProjectConfig.from_yaml_file(project_config_path)
    except Exception as exc:
        raise McpProjectError(f"Error loading {project_config_path}: {exc}") from exc

    try:
        selected = select_metrics(selector, project_root)
    except ValueError as exc:
        raise McpProjectError(f"Error in selector {selector!r}: {exc}") from exc

    metrics_by_name = {config.name: (path, config) for path, config in selected}

    profiles_path = project_root / "profiles.yml"
    if not profiles_path.exists():
        raise McpProjectError(f"profiles.yml not found (expected at {profiles_path})")
    try:
        profiles_config = ProfilesConfig.from_yaml(profiles_path)
    except Exception as exc:
        raise McpProjectError(f"Error loading profiles.yml: {exc}") from exc

    try:
        profile_config = profiles_config.get_profile(profile)
    except Exception as exc:
        raise McpProjectError(f"Error resolving profile {profile!r}: {exc}") from exc

    # FINDING B — resolve a relative DuckDB `path` against the project root
    # before it ever reaches the manager constructor.
    profile_config = _resolve_duckdb_path(profile_config, project_root)

    # FINDING A — never let a read-only server run DDL (or, for DuckDB,
    # create the state file itself) merely by connecting.
    try:
        db_manager = profile_config.create_manager(ensure_locations=False)
    except Exception as exc:
        if _is_duckdb_missing_state_file(profile_config, exc):
            # Expected first-run shape for a file-backed DuckDB profile: no
            # `dtk run` has ever executed against it, so the state file
            # doesn't exist. Every DB-touching tool already gates on
            # `require_tables()`, so degrading here surfaces the same
            # friendly "no data yet" error on first use instead of a hard
            # failure at server startup.
            return McpContext(
                project_root=project_root,
                project_config=project_config,
                profiles_config=profiles_config,
                internal=None,
                profile_name=profile,
                selector=selector,
                metrics_by_name=metrics_by_name,
                tables_ready=False,
            )
        raise McpProjectError(f"Error creating database manager: {exc}") from exc

    internal = InternalTablesManager(db_manager)

    return McpContext(
        project_root=project_root,
        project_config=project_config,
        profiles_config=profiles_config,
        internal=internal,
        profile_name=profile,
        selector=selector,
        metrics_by_name=metrics_by_name,
        tables_ready=_tables_ready(internal),
    )
