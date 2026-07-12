"""FastMCP server wiring for ``dtk mcp`` — a READ-ONLY window over a detectkit project.

Isolation: nothing in the load/detect/alert pipeline imports this module (or
anything under :mod:`detectkit.mcp`). The ``mcp`` SDK import is **guarded** —
:func:`_fastmcp_class` imports it lazily, inside a function, and raises
:class:`~detectkit.mcp.errors.McpDependencyMissing` with an actionable message
when the optional ``[mcp]`` extra isn't installed (mirroring
``detectkit.semantic.query_gen._sqlglot``'s lazy-sqlglot pattern for the
``[osi]`` extra). This module itself can always be imported — only *building*
or *running* the server needs the SDK. Pin: ``mcp>=1.27,<2`` (SDK v2 renames
``FastMCP`` to ``MCPServer`` — a migration point, not a drop-in).

**The 10 tools** (registered by :func:`build_server`) are thin closures over
the plain functions in :mod:`detectkit.mcp.tools` — see that module's
docstring for the session-scope and read-only-exclusion contract shared by
all of them. Every tool call is serialized by ``McpContext.lock`` (one DB
connection, mirroring ``detectkit/ui/server.py``'s ``db_lock``).

**Excluded by design** — this server contains zero write paths: applying a
tuned config (``dtk tune``'s ``/apply``), the ``dtk ui`` metric-file CRUD,
job/subprocess spawning, writing incident labels (``dtk tune``'s
``/labels``), any ``save_*``/``delete_*`` internal-table call, and
``ensure_tables()`` (DDL). A tool that would need data that isn't there yet
returns a clear "no data yet — run `dtk run` first" error instead of
creating it.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from detectkit.mcp import tools as _tools
from detectkit.mcp.context import McpContext, build_context
from detectkit.mcp.errors import McpDependencyMissing

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _fastmcp_class() -> type[FastMCP]:
    """Import :class:`FastMCP` lazily, raising a friendly error when the SDK is absent."""
    try:
        from mcp.server.fastmcp import FastMCP  # noqa: PLC0415
    except ImportError as exc:
        raise McpDependencyMissing(
            "MCP server needs the mcp package — install the extra: " "pip install 'detectkit[mcp]'"
        ) from exc
    return FastMCP


def build_server(ctx: McpContext) -> FastMCP:
    """Build a :class:`FastMCP` server with the 10 read-only tools bound to *ctx*.

    Raises :class:`~detectkit.mcp.errors.McpDependencyMissing` if the ``mcp``
    SDK isn't installed.
    """
    fastmcp_cls = _fastmcp_class()
    mcp_server = fastmcp_cls(
        name="detectkit",
        instructions=(
            "Read-only access to a detectkit monitoring project: metric "
            "configs, loaded datapoints, detector results, replayed alert "
            "history, autotune runs and labeled incidents. Nothing here "
            "writes to the database or the filesystem — to change a metric's "
            "config, tune a detector, or run the pipeline, use `dtk tune` / "
            "`dtk run` / `dtk ui` directly."
        ),
    )

    @mcp_server.tool()
    def list_metrics(selector: str = "*") -> dict[str, Any]:
        """List the project's metrics (name, location, tags, detectors, alert rule).

        ``selector`` uses the same syntax as every ``dtk`` CLI command:
        ``"*"`` (default, every metric in this server's scope), a bare metric
        ``name``, a glob path like ``"critical/*.yml"``, or ``"tag:<tag>"``.
        Results are always intersected with the server's own startup
        ``--select`` scope — a selector can narrow that scope but never
        escape it. Returns each metric's name, its directory/file under
        ``metrics/``, tags, enabled flag, interval (seconds), configured
        detector types, and a one-line alert-rule summary.
        """
        return _tools.list_metrics(ctx, selector)

    @mcp_server.tool()
    def get_metric(name: str) -> dict[str, Any]:
        """Get one metric's full config: description, loading, detectors, alerting, SQL.

        Includes: description, tags, interval, loading params (start time,
        batch size, resolved data-maturity delay, resolved hybrid-mode
        ``source_profile`` NAME), seasonality columns, every detector's type
        + params, every alerting block (channels listed by NAME only — never
        channel connection details/secrets, which live in ``profiles.yml``
        and this tool never reads), ``ai_context``, and the metric's SQL text
        (inline or read from ``query_file``). Raises if ``name`` isn't in
        this server's session scope.
        """
        return _tools.get_metric(ctx, name)

    @mcp_server.tool()
    def get_metric_status(name: str, window: str = "7d") -> dict[str, Any]:
        """Get one metric's live health: freshness, points, anomaly rate, alerts, quality.

        The same row ``dtk ui``'s overview table shows, computed by replaying
        alerts from stored detections (not by reading last-writer-wins alert
        state) over ``window`` — one of ``24h``, ``7d`` (default), ``30d``,
        ``90d``, ``all``. Includes last-datapoint lag, whether the pipeline
        lock is currently held, point/anomaly counts, per-day alert
        frequency, stale-detector-generation count, and (when
        ``incidents/<metric>/`` has labels) recall/false-alert-rate quality
        stats. Every timestamp is ISO-8601 UTC.
        """
        return _tools.get_metric_status(ctx, name, window)

    @mcp_server.tool()
    def get_project_status(
        window: str = "7d", selector: str = "*", limit: int = 50
    ) -> dict[str, Any]:
        """Get the ``get_metric_status`` row for every metric matching ``selector``.

        Bounded like ``dtk ui``'s overview: computing every metric's row is
        expensive (it reads and replays detections), so results are capped at
        ``limit`` (default 50, hard cap 200) even though ``total_metrics``
        reports the full matched count. Raise ``limit`` — up to the cap — to
        see more; there is no further pagination. ``selector`` semantics and
        session-scope intersection match ``list_metrics``.
        """
        return _tools.get_project_status(ctx, window, selector, limit)

    @mcp_server.tool()
    def query_datapoints(
        metric: str,
        from_ts: str | None = None,
        to_ts: str | None = None,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Raw loaded values for a metric: ``{timestamp, value}`` rows, newest first.

        ``from_ts``/``to_ts`` are ISO-8601 UTC (``2026-07-01T00:00:00Z``);
        both are inclusive and default to the ``limit``-sized window ending
        at the metric's last datapoint. ``limit`` defaults to 1000, hard cap
        5000 — for a longer span, page by moving ``to_ts`` backward. ``value``
        is ``null`` for a gap-filled missing point. A wide ``from_ts`` is
        clamped to the newest ``limit`` grid points before fetching (the
        response is capped to that many anyway, so nothing wider is ever
        returned) — for a longer span, page by moving ``to_ts`` backward
        instead of widening ``from_ts``.
        """
        return _tools.query_datapoints(ctx, metric, from_ts, to_ts, limit)

    @mcp_server.tool()
    def query_detections(
        metric: str,
        detector_id: str | None = None,
        from_ts: str | None = None,
        to_ts: str | None = None,
        anomalies_only: bool = False,
        limit: int = 1000,
    ) -> dict[str, Any]:
        """Per-detector results for a metric: value, confidence band, anomaly flag; newest first.

        ``detector_id`` restricts to one detector generation (see
        ``get_metric_status``'s ``stale_detectors`` / ``list_metrics``'
        detector types to find one) — omitted, every stored generation is
        returned, which can include superseded configs after a retune.
        ``anomalies_only=true`` filters to flagged points. ``from_ts``/
        ``to_ts``/``limit`` match ``query_datapoints`` (limit default 1000,
        hard cap 5000), including the same wide-``from_ts`` clamp — **except**
        when ``anomalies_only=true``: a wide range combined with
        ``anomalies_only`` scans the full requested span before filtering,
        since anomalies can be sparse enough that clamping to the newest
        ``limit`` grid points first would miss ones further back.
        """
        return _tools.query_detections(
            ctx, metric, detector_id, from_ts, to_ts, anomalies_only, limit
        )

    @mcp_server.tool()
    def replay_alerts(
        metric: str, from_ts: str | None = None, to_ts: str | None = None
    ) -> dict[str, Any]:
        """Reconstruct the anomaly/recovery/no-data alert timeline a period actually fired.

        Uses the same pure replay engine ``dtk run --report`` and ``dtk ui``
        use — it re-walks the real decision logic (quorum, consecutive/
        fraction rule, cooldown, recovery) over stored detections, **not**
        ``_dtk_alert_states`` (last-writer-wins state, not an event log). No
        dispatch happens; this never sends a notification. ``from_ts``/
        ``to_ts`` are ISO-8601 UTC and default to the metric's usual report
        window when omitted. Each event carries ``kind`` (anomaly/recovery/
        no_data), ``direction``, ``value``, the confidence bounds, and —
        when resolved — the anomaly's ``onset`` and whether the streak length
        is a lower bound (``streak_capped``).
        """
        return _tools.replay_alerts(ctx, metric, from_ts, to_ts)

    @mcp_server.tool()
    def get_autotune_history(
        metric: str, limit: int = 5, include_decision_log: bool = False
    ) -> dict[str, Any]:
        """List past ``dtk autotune`` runs for a metric, newest first.

        Each entry: run id/timestamp/status/mode/scoring metric/score, the
        chosen detector type + params + seasonality, and the winning
        ``detector_id``. ``limit`` defaults to 5 (hard cap 50).
        ``include_decision_log=true`` also returns the full per-stage
        decision log (seasonality search, detector selection, grid search,
        window selection) — large, so it's opt-in.
        """
        return _tools.get_autotune_history(ctx, metric, limit, include_decision_log)

    @mcp_server.tool()
    def get_incidents(metric: str) -> dict[str, Any]:
        """Get the ground-truth incidents labeled for a metric via `dtk tune` (Label mode).

        Reads the newest versioned file under ``incidents/<metric>/`` (the
        same store ``dtk autotune`` auto-discovers) and returns each interval/
        point as ``{start, end, label}`` (a point is a degenerate span with
        ``start == end``). Returns an empty list when the metric has never
        been labeled — this is normal, not an error.
        """
        return _tools.get_incidents(ctx, metric)

    @mcp_server.tool()
    def get_server_info() -> dict[str, Any]:
        """Get this server's identity: detectkit version, project, profile/backend, scope.

        Includes ``read_only: true`` (always) and ``tables_ready`` (whether
        the internal tables exist yet — false before the first ``dtk run``).
        Useful as a first call to confirm which project/profile/selector
        scope this server session is bound to.
        """
        return _tools.get_server_info(ctx)

    return mcp_server


def run_server(*, project_dir: str | None, selector: str, profile: str | None) -> None:
    """Resolve the project, build the server, and serve it over stdio until EOF/Ctrl-C.

    Echoes exactly one startup line to **stderr** (stdout is reserved for the
    MCP protocol itself once the server starts). Raises
    :class:`~detectkit.mcp.errors.McpError` on any resolution/build failure —
    the CLI command maps that to a clean exit.

    FINDING D: the ``mcp`` SDK is probed **first**, before any project/DB
    work — ``dtk mcp`` run without the ``[mcp]`` extra installed should fail
    instantly with the install hint, not after resolving the project and
    opening a database connection only to discard it.
    """
    _fastmcp_class()  # raises McpDependencyMissing early when the [mcp] extra is absent
    ctx = build_context(project_dir=project_dir, selector=selector, profile=profile)
    server = build_server(ctx)
    print(
        f"detectkit MCP server: project={ctx.project_config.name!r} "
        f"root={ctx.project_root} select={selector!r} "
        f"profile={(ctx.profile_name or ctx.profiles_config.default_profile)!r} "
        f"metrics={len(ctx.metric_names)} tables_ready={ctx.tables_ready} "
        "read_only=true",
        file=sys.stderr,
    )
    server.run()
