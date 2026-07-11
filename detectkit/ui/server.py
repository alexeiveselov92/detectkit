"""Local browser server for ``dtk ui`` — the project-level monitoring cockpit.

A pure-stdlib localhost server, mirroring ``detectkit/tuning/server.py``'s
shape: bound to ``127.0.0.1`` with a one-shot token, serving the cockpit shell
plus a small JSON/HTML API. Unlike the tune server it never self-shuts-down —
it runs until Ctrl-C — and the token is checked on **every** route (GET and
POST), since this page stays open and polls in the background rather than
ending after one write.

The server itself never runs the pipeline in-process and takes no pipeline
lock: ``POST /api/run`` / ``/api/autotune`` / ``/api/unlock`` spawn the real
``dtk`` CLI as a subprocess (tracked by :class:`detectkit.ui.jobs.JobManager`),
exactly as if typed at a terminal — spawned processes take their own lock. A
single ``db_lock`` serializes every DB-touching route (the DB manager holds one
connection, same reason the tune server serializes ``/autotune``); it is never
held while a subprocess runs.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import secrets
import sys
import threading
import webbrowser
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qs, unquote, urlparse

from detectkit import __version__
from detectkit.reporting import build_report_payload, render_report_html
from detectkit.ui.html import render_ui_html
from detectkit.ui.jobs import JobManager
from detectkit.ui.metric_files import (
    create_metric_file,
    delete_metric_file,
    text_digest,
    update_metric_file,
)
from detectkit.ui.overview import (
    ALL_WINDOW_PRESETS,
    WINDOW_PRESETS,
    build_metric_row,
    build_overview_payload,
)
from detectkit.ui.overview import resolve_metric_location as _resolve_metric_location
from detectkit.utils.datetime_utils import now_utc_naive

if TYPE_CHECKING:
    from detectkit.config.metric_config import MetricConfig
    from detectkit.config.project_config import ProjectConfig
    from detectkit.database.internal_tables import InternalTablesManager

_MAX_BODY = 1_000_000
_VALID_STEPS = {"load", "detect", "alert"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?: \d{2}:\d{2}:\d{2})?$")
_TUNER_URL_RE = re.compile(r"Tuner:\s*(\S+)")
_DEFAULT_TUNE_URL_TIMEOUT = 90.0


@contextlib.contextmanager
def _quiet_stderr() -> Iterator[None]:
    """Silence OS-level stderr for the duration of the block (see tuning/server.py)."""
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
    except OSError:
        yield
        return
    saved = os.dup(2)
    try:
        os.dup2(devnull, 2)
        yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)
        os.close(devnull)


class _UiServer(ThreadingHTTPServer):
    """Localhost server holding the per-session state the handler reads/writes."""

    # Don't block interpreter exit on in-flight request threads.
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(address, handler)
        self.token: str = ""
        self.html: str = ""
        self.project_config: ProjectConfig | None = None
        self.project_root: Path = Path(".")
        self.metrics: list[tuple[Path, MetricConfig]] = []
        self.internal_manager: InternalTablesManager | None = None
        self.initial_window: str = "30d"
        self.profile: str | None = None
        self.echo: Callable[[str], None] = print
        self.tune_url_timeout: float = _DEFAULT_TUNE_URL_TIMEOUT
        self.jobs = JobManager()
        # The DB manager holds a single connection — serialize every route that
        # touches it. Never held while a subprocess runs (spawning is
        # fire-and-forget; polling its output doesn't touch the DB).
        self.db_lock = threading.Lock()

    def handle_error(self, request: Any, client_address: Any) -> None:
        """Keep the terminal clean: a client dropping its socket is routine.

        The stdlib default dumps a full traceback for every handler-thread
        exception — on Ctrl-C (or a browser aborting a slow request) that
        floods the terminal with BrokenPipe walls. Client disconnects are
        swallowed; anything else is echoed as one compact line.
        """
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        self.echo(f"  [ui] request error: {type(exc).__name__}: {exc}")


def _find_metric(metrics: list[tuple[Path, MetricConfig]], name: str) -> MetricConfig | None:
    for _path, config in metrics:
        if config.name == name:
            return config
    return None


def _find_metric_entry(
    metrics: list[tuple[Path, MetricConfig]], name: str
) -> tuple[Path, MetricConfig] | None:
    """The ``(path, config)`` entry for *name* — the CRUD routes' lookup seam."""
    return next(((p, c) for p, c in metrics if c.name == name), None)


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _pipeline_argv(
    *,
    select: str,
    steps: list[str],
    from_date: str | None,
    to_date: str | None,
    full_refresh: bool,
    force: bool,
    profile: str | None,
) -> list[str]:
    """``dtk run`` argv for the given options. Module-level so tests can monkeypatch it."""
    argv = [
        sys.executable,
        "-m",
        "detectkit.cli.main",
        "run",
        "--select",
        select,
        "--steps",
        ",".join(steps),
    ]
    if from_date:
        argv += ["--from", from_date]
    if to_date:
        argv += ["--to", to_date]
    if full_refresh:
        argv.append("--full-refresh")
    if force:
        argv.append("--force")
    if profile:
        argv += ["--profile", profile]
    return argv


def _autotune_argv(
    *, select: str, from_date: str | None, to_date: str | None, profile: str | None
) -> list[str]:
    """``dtk autotune`` argv. Module-level so tests can monkeypatch it."""
    argv = [sys.executable, "-m", "detectkit.cli.main", "autotune", "--select", select]
    if from_date:
        argv += ["--from", from_date]
    if to_date:
        argv += ["--to", to_date]
    if profile:
        argv += ["--profile", profile]
    return argv


def _unlock_argv(*, select: str, profile: str | None) -> list[str]:
    """``dtk unlock`` argv. Module-level so tests can monkeypatch it."""
    argv = [sys.executable, "-m", "detectkit.cli.main", "unlock", "--select", select]
    if profile:
        argv += ["--profile", profile]
    return argv


def _tune_argv(*, metric: str, profile: str | None) -> list[str]:
    """``dtk tune`` argv (server mode, no browser). Module-level so tests can monkeypatch it."""
    argv = [sys.executable, "-m", "detectkit.cli.main", "tune", "--select", metric, "--no-open"]
    if profile:
        argv += ["--profile", profile]
    return argv


def _validate_select(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 200:
        raise ValueError("'select' must be a non-empty string (max 200 chars)")
    return value


def _validate_date(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ValueError(f"'{field}' must match YYYY-MM-DD or YYYY-MM-DD HH:MM:SS")
    return value


def _validate_steps(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ValueError("'steps' must be a non-empty list")
    steps = [str(s) for s in value]
    bad = [s for s in steps if s not in _VALID_STEPS]
    if bad:
        raise ValueError(f"invalid steps: {bad}; choose from {sorted(_VALID_STEPS)}")
    return steps


def _report_window(window: str) -> tuple[datetime | None, datetime | None]:
    """Map a window preset to ``build_report_payload``'s ``(start, end)``.

    ``end`` is always ``None`` (the builder resolves it to the last
    datapoint); ``"all"`` also leaves ``start`` at ``None`` so the builder
    falls back to its own default recent-points window (the report is a
    detail view, not the overview's bounded-history stats).
    """
    if window == "all":
        return None, None
    days = WINDOW_PRESETS.get(window)
    if days is None:
        raise ValueError(f"unknown window preset: {window!r}")
    return now_utc_naive() - timedelta(days=days), None


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # silence default stderr logging
        return

    def _srv(self) -> _UiServer:
        return cast(_UiServer, self.server)

    def _authorized(self, srv: _UiServer) -> bool:
        query = parse_qs(urlparse(self.path).query)
        return query.get("token", [""])[0] == srv.token

    def do_GET(self) -> None:
        srv = self._srv()
        if not self._authorized(srv):
            self._reply_error(403, "bad token")
            return
        try:
            self._route_get(srv)
        except Exception as exc:  # noqa: BLE001 — never crash the server on bad input
            self._reply_error(400, str(exc))

    def do_POST(self) -> None:
        srv = self._srv()
        if not self._authorized(srv):
            self._reply_error(403, "bad token")
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > _MAX_BODY:
            self._reply_error(413, "request body too large")
            return
        body = self.rfile.read(length) if length > 0 else b""
        try:
            self._route_post(srv, body)
        except Exception as exc:  # noqa: BLE001 — 400 and keep serving
            self._reply_error(400, str(exc))

    # ── routing ──────────────────────────────────────────────────────────

    def _route_get(self, srv: _UiServer) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)

        if path == "/":
            self._reply_html(srv.html)
            return
        if path == "/api/overview":
            window = query.get("window", [srv.initial_window])[0]
            self._handle_overview(srv, window)
            return
        if path.startswith("/api/stats/"):
            name = unquote(path[len("/api/stats/") :])
            window = query.get("window", [srv.initial_window])[0]
            self._handle_metric_stats(srv, name, window)
            return
        if path.startswith("/metric/"):
            name = unquote(path[len("/metric/") :])
            window = query.get("window", [srv.initial_window])[0]
            self._handle_metric_report(srv, name, window)
            return
        if path == "/api/jobs":
            self._reply_json({"jobs": srv.jobs.list_snapshots()})
            return
        if path.startswith("/api/job/"):
            job_id = path[len("/api/job/") :]
            offset = _parse_int(query.get("offset", ["0"])[0], default=0)
            self._handle_job_status(srv, job_id, offset)
            return
        if path == "/api/metrics":
            self._reply_json({"metrics": metric_entries(srv.project_root, srv.metrics)})
            return
        if path.startswith("/api/metric-source/"):
            name = unquote(path[len("/api/metric-source/") :])
            self._handle_metric_source(srv, name)
            return
        self._reply_error(404, "not found")

    def _route_post(self, srv: _UiServer, body: bytes) -> None:
        path = urlparse(self.path).path
        if path == "/api/run":
            self._handle_run(srv, body)
        elif path == "/api/autotune":
            self._handle_autotune(srv, body)
        elif path == "/api/unlock":
            self._handle_unlock(srv, body)
        elif path == "/api/tune":
            self._handle_tune(srv, body)
        elif path.startswith("/api/job/") and path.endswith("/stop"):
            job_id = path[len("/api/job/") : -len("/stop")].rstrip("/")
            self._handle_stop(srv, job_id)
        elif path == "/api/metric-create":
            self._handle_metric_create(srv, body)
        elif path.startswith("/api/metric/") and path.endswith("/update"):
            name = unquote(path[len("/api/metric/") : -len("/update")].rstrip("/"))
            self._handle_metric_update(srv, name, body)
        elif path.startswith("/api/metric/") and path.endswith("/delete"):
            name = unquote(path[len("/api/metric/") : -len("/delete")].rstrip("/"))
            self._handle_metric_delete(srv, name, body)
        else:
            self._reply_error(404, "not found")

    # ── GET handlers ─────────────────────────────────────────────────────

    def _handle_overview(self, srv: _UiServer, window: str) -> None:
        if window not in ALL_WINDOW_PRESETS:
            self._reply_error(400, f"unknown window preset: {window!r}")
            return
        assert srv.project_config is not None and srv.internal_manager is not None
        with srv.db_lock:
            payload = build_overview_payload(
                project_config=srv.project_config,
                project_root=srv.project_root,
                metrics=srv.metrics,
                internal=srv.internal_manager,
                window_preset=window,
            )
        self._reply_json(payload)

    def _handle_metric_stats(self, srv: _UiServer, name: str, window: str) -> None:
        """One metric's overview row — the page loads stats incrementally.

        Small per-metric requests keep every HTTP exchange short (no browser
        abort on a project whose combined stats take minutes) and let the page
        fill in progressively; a failing metric degrades to its row's
        ``error`` field without sinking the rest.
        """
        entry = next(((p, c) for p, c in srv.metrics if c.name == name), None)
        if entry is None:
            self._reply_error(404, f"unknown metric: {name}")
            return
        metric_path, config = entry
        assert srv.project_config is not None and srv.internal_manager is not None
        with srv.db_lock:
            row = build_metric_row(
                project_config=srv.project_config,
                project_root=srv.project_root,
                metric_path=metric_path,
                config=config,
                internal=srv.internal_manager,
                window_preset=window,
            )
        self._reply_json(row)

    def _handle_metric_report(self, srv: _UiServer, name: str, window: str) -> None:
        config = _find_metric(srv.metrics, name)
        if config is None:
            self._reply_error(404, f"unknown metric: {name}")
            return
        start, end = _report_window(window)
        assert srv.internal_manager is not None
        with srv.db_lock:
            payload = build_report_payload(
                metric_config=config,
                internal=srv.internal_manager,
                start=start,
                end=end,
                project_name=getattr(srv.project_config, "name", None),
                generated_at=now_utc_naive().strftime("%Y-%m-%d %H:%M UTC"),
                project_loading_delay=getattr(srv.project_config, "loading_delay", None),
            )
        self._reply_html(render_report_html(payload))

    def _handle_job_status(self, srv: _UiServer, job_id: str, offset: int) -> None:
        job = srv.jobs.get(job_id)
        if job is None:
            self._reply_error(404, f"unknown job: {job_id}")
            return
        self._reply_json(srv.jobs.snapshot(job, offset))

    def _handle_metric_source(self, srv: _UiServer, name: str) -> None:
        """The raw YAML text of one metric's file, for the editor overlay.

        Runs under ``db_lock`` like the mutation routes — the update handler
        overwrites the same file in place (a plain truncate-and-write), so an
        unserialized read could hand the editor a torn half-written file. The
        ``digest`` is the optimistic-concurrency token the editor echoes back
        on save (see ``update_metric_file``).
        """
        with srv.db_lock:
            entry = _find_metric_entry(srv.metrics, name)
            if entry is None:
                self._reply_error(404, f"unknown metric: {name}")
                return
            mpath = _abs_metric_path(srv, entry[0])
            text = mpath.read_text(encoding="utf-8")
        dir_str, file_str = _resolve_metric_location(
            mpath, srv.project_root, srv.project_root / "metrics"
        )
        self._reply_json(
            {
                "name": name,
                "dir": dir_str,
                "file": file_str,
                "text": text,
                "digest": text_digest(text),
            }
        )

    # ── POST handlers ────────────────────────────────────────────────────

    def _handle_run(self, srv: _UiServer, body: bytes) -> None:
        payload = _load_json(body)
        select = _validate_select(payload.get("select"))
        steps = _validate_steps(payload.get("steps") or ["load", "detect", "alert"])
        from_date = _validate_date(payload.get("from"), "from")
        to_date = _validate_date(payload.get("to"), "to")
        full_refresh = bool(payload.get("full_refresh", False))
        force = bool(payload.get("force", False))
        argv = _pipeline_argv(
            select=select,
            steps=steps,
            from_date=from_date,
            to_date=to_date,
            full_refresh=full_refresh,
            force=force,
            profile=srv.profile,
        )
        job = srv.jobs.spawn_pipeline(
            "run", f"run --select {select}", argv, cwd=srv.project_root, env=_subprocess_env()
        )
        if job is None:
            self._reply_error(400, "a pipeline job is already running")
            return
        self._reply_json({"job_id": job.id})

    def _handle_autotune(self, srv: _UiServer, body: bytes) -> None:
        payload = _load_json(body)
        select = _validate_select(payload.get("select"))
        from_date = _validate_date(payload.get("from"), "from")
        to_date = _validate_date(payload.get("to"), "to")
        argv = _autotune_argv(
            select=select, from_date=from_date, to_date=to_date, profile=srv.profile
        )
        job = srv.jobs.spawn_pipeline(
            "autotune",
            f"autotune --select {select}",
            argv,
            cwd=srv.project_root,
            env=_subprocess_env(),
        )
        if job is None:
            self._reply_error(400, "a pipeline job is already running")
            return
        self._reply_json({"job_id": job.id})

    def _handle_unlock(self, srv: _UiServer, body: bytes) -> None:
        payload = _load_json(body)
        select = _validate_select(payload.get("select"))
        argv = _unlock_argv(select=select, profile=srv.profile)
        job = srv.jobs.spawn_pipeline(
            "unlock", f"unlock --select {select}", argv, cwd=srv.project_root, env=_subprocess_env()
        )
        if job is None:
            self._reply_error(400, "a pipeline job is already running")
            return
        self._reply_json({"job_id": job.id})

    def _handle_tune(self, srv: _UiServer, body: bytes) -> None:
        payload = _load_json(body)
        metric = payload.get("metric")
        if not isinstance(metric, str) or not metric.strip():
            self._reply_error(400, "'metric' must be a non-empty string")
            return
        if _find_metric(srv.metrics, metric) is None:
            self._reply_error(400, f"unknown metric: {metric}")
            return
        # Concurrent tune jobs are allowed across DIFFERENT metrics (each takes
        # no pipeline lock) — but a second tuner for the SAME metric would race
        # the first on Apply (each writes the whole metric YAML from its own
        # startup snapshot, silently dropping the other's changes). Reuse the
        # live session instead: hand back its URL so a re-click simply reopens
        # the existing cockpit tab.
        existing = srv.jobs.running_tune_for(metric)
        if existing is not None:
            with existing.lock:
                existing_url = existing.url
            if existing_url:
                self._reply_json({"job_id": existing.id, "url": existing_url})
            else:
                self._reply_error(400, f"a tuner for {metric} is already starting")
            return
        argv = _tune_argv(metric=metric, profile=srv.profile)
        job = srv.jobs.spawn(
            "tune",
            f"tune --select {metric}",
            argv,
            cwd=srv.project_root,
            env=_subprocess_env(),
            metric=metric,
        )
        line = srv.jobs.wait_for_line(job, lambda ln: "Tuner:" in ln, srv.tune_url_timeout)
        if line is None:
            srv.jobs.stop(job.id)
            tail = "\n".join(srv.jobs.snapshot(job, 0)["lines"][-20:])
            self._reply_error(400, f"tuner did not start in time — output:\n{tail}")
            return
        match = _TUNER_URL_RE.search(line)
        url = match.group(1) if match else line.strip()
        srv.jobs.set_url(job, url)
        self._reply_json({"job_id": job.id, "url": url})

    def _handle_stop(self, srv: _UiServer, job_id: str) -> None:
        if not srv.jobs.stop(job_id):
            self._reply_error(400, f"no running job: {job_id}")
            return
        self._reply_json({"ok": True})

    # ── metric file CRUD (see detectkit/ui/metric_files.py) ─────────────────
    #
    # File mutations don't touch the database, but they replace the in-memory
    # `srv.metrics` list every DB route reads — so they run under `db_lock`
    # too, which also serializes two concurrent editor saves. The list is
    # rebuilt and reassigned atomically; in-flight readers keep the old list.

    def _handle_metric_create(self, srv: _UiServer, body: bytes) -> None:
        """Create ``metrics/[<folder>/]<name>.yml`` from raw YAML text.

        The new metric joins this session's list even when it wouldn't match
        the ``--select`` the server was started with — the user just created
        it here and expects to see it.
        """
        payload = _load_json(body)
        text = _validate_yaml_text(payload.get("text"))
        folder = payload.get("folder")
        if folder is None:
            folder = ""
        elif not isinstance(folder, str):
            raise ValueError("'folder' must be a string")
        with srv.db_lock:
            written = create_metric_file(project_root=srv.project_root, text=text, folder=folder)
            srv.metrics = sorted(
                [*srv.metrics, (written.path, written.config)], key=lambda item: str(item[0])
            )
        srv.echo(f"  [ui] created metric '{written.config.name}' ({written.path})")
        self._reply_json(
            {
                "name": written.config.name,
                "file": str(written.path),
                "metrics": metric_entries(srv.project_root, srv.metrics),
            }
        )

    def _handle_metric_update(self, srv: _UiServer, name: str, body: bytes) -> None:
        """Overwrite one metric's YAML (archiving the previous version first).

        The existence lookup and tune-session guard run **inside** ``db_lock``,
        atomically with the write — checked outside, two concurrent requests
        for the same metric would both pass and the loser would hit a raw
        ``FileNotFoundError`` instead of the clean 404/400. The optional
        ``digest`` (from ``GET /api/metric-source``) makes a stale editor —
        one opened before a ``dtk tune`` Apply or another tab's save — fail
        loudly instead of silently clobbering the newer config.
        """
        payload = _load_json(body)
        text = _validate_yaml_text(payload.get("text"))
        digest = payload.get("digest")
        if digest is not None and not isinstance(digest, str):
            raise ValueError("'digest' must be a string")
        with srv.db_lock:
            entry = _find_metric_entry(srv.metrics, name)
            if entry is None:
                self._reply_error(404, f"unknown metric: {name}")
                return
            if srv.jobs.running_tune_for(name) is not None:
                self._reply_error(
                    400,
                    f"a tuner for {name} is running — Apply or close it first "
                    "(its Apply would overwrite this edit)",
                )
                return
            mpath = _abs_metric_path(srv, entry[0])
            written = update_metric_file(
                project_root=srv.project_root, path=mpath, text=text, expected_digest=digest
            )
            srv.metrics = [(p, written.config if c.name == name else c) for p, c in srv.metrics]
        renamed = written.config.name != name
        note = (
            f"renamed '{name}' → '{written.config.name}': rows under the old name stay "
            "in the _dtk_* tables until `dtk clean`"
            if renamed
            else None
        )
        srv.echo(f"  [ui] updated metric '{name}' ({written.path})")
        self._reply_json(
            {
                "name": written.config.name,
                "renamed_from": name if renamed else None,
                "archived": str(written.archived) if written.archived else None,
                "note": note,
                "metrics": metric_entries(srv.project_root, srv.metrics),
            }
        )

    def _handle_metric_delete(self, srv: _UiServer, name: str, body: bytes) -> None:
        """Delete one metric's YAML — requires the client to echo the name back.

        The ``confirm`` field is the server-side half of the UI's confirmation
        dialog: a request that doesn't carry the exact metric name is refused,
        so nothing can delete a metric with a bare POST by accident.
        """
        payload = _load_json(body)
        if payload.get("confirm") != name:
            self._reply_error(400, "confirmation mismatch: POST {'confirm': '<metric name>'}")
            return
        # Lookup + tune-guard inside the lock, atomically with the delete —
        # same reasoning as _handle_metric_update.
        with srv.db_lock:
            entry = _find_metric_entry(srv.metrics, name)
            if entry is None:
                self._reply_error(404, f"unknown metric: {name}")
                return
            if srv.jobs.running_tune_for(name) is not None:
                self._reply_error(
                    400,
                    f"a tuner for {name} is running — close it first "
                    "(its Apply would re-create the file)",
                )
                return
            mpath = _abs_metric_path(srv, entry[0])
            archived = delete_metric_file(project_root=srv.project_root, path=mpath)
            srv.metrics = [(p, c) for p, c in srv.metrics if c.name != name]
        srv.echo(f"  [ui] deleted metric '{name}' (archived at {archived})")
        self._reply_json(
            {
                "name": name,
                "archived": str(archived),
                "note": (
                    "the YAML file was archived and removed; rows in the _dtk_* tables "
                    "remain until `dtk clean`"
                ),
                "metrics": metric_entries(srv.project_root, srv.metrics),
            }
        )

    # ── response helpers ─────────────────────────────────────────────────

    def _reply_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reply_json(self, payload: dict[str, Any]) -> None:
        # allow_nan=False: a NaN leaking into a stat must fail loudly here (a
        # 400 with the message) — the default emits bare `NaN`, which is not
        # JSON and would die opaquely in the browser's JSON.parse instead.
        resp = json.dumps(payload, default=_json_default, allow_nan=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def _reply_error(self, code: int, detail: str) -> None:
        """Error response with the detail in the UTF-8 body, not the status line.

        Mirrors ``tuning/server.py``: the status line is latin-1 only, and an
        exception message can carry non-ASCII (e.g. an ``≈`` from a validation
        error), so the detail rides in the body instead. Errors other than the
        routine bad-token 403 are also echoed to the terminal — a page stuck on
        a failing request should be diagnosable without opening devtools.
        """
        if code >= 400 and code != 403:
            first_line = detail.splitlines()[0] if detail else ""
            self._srv().echo(f"  [ui] {code} {urlparse(self.path).path}: {first_line}")
        body = detail.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _parse_int(value: str, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _abs_metric_path(srv: _UiServer, path: Path) -> Path:
    """Session metric paths may be project-root-relative; resolve for file I/O."""
    return path if path.is_absolute() else srv.project_root / path


def _validate_yaml_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("'text' must be a non-empty string (the metric YAML)")
    return value


def _load_json(body: bytes) -> dict[str, Any]:
    if not body:
        return {}
    parsed = json.loads(body.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("request body must be a JSON object")
    return parsed


def _json_default(o: Any) -> Any:
    """JSON fallback for numpy scalars/arrays that might leak into a payload."""
    import numpy as np

    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def metric_entries(
    project_root: Path, metrics: list[tuple[Path, MetricConfig]]
) -> list[dict[str, Any]]:
    """The boot-shaped metric list entries — shared by ``GET /`` and ``GET /api/metrics``.

    The CRUD routes return this refreshed list after every mutation so the
    page re-syncs its session metric list in the same round trip.
    """
    metrics_dir = project_root / "metrics"
    entries = []
    for path, config in metrics:
        dir_str, file_str = _resolve_metric_location(path, project_root, metrics_dir)
        entries.append(
            {
                "name": config.name,
                "dir": dir_str,
                "file": file_str,
                "tags": list(config.tags) if config.tags else [],
                "interval_seconds": config.get_interval().seconds,
                "enabled": config.enabled,
            }
        )
    return entries


def _boot_payload(
    project_config: ProjectConfig,
    project_root: Path,
    metrics: list[tuple[Path, MetricConfig]],
    initial_window: str,
) -> dict[str, Any]:
    """The ``GET /`` shell payload: project + metric list, no stats, no URLs."""
    return {
        "project": project_config.name,
        "initial_window": initial_window,
        "version": __version__,
        "metrics": metric_entries(project_root, metrics),
        "generated_at": int(now_utc_naive().timestamp() * 1000),
    }


def build_ui_server(
    *,
    project_config: ProjectConfig,
    project_root: Path,
    metrics: list[tuple[Path, MetricConfig]],
    internal_manager: InternalTablesManager,
    initial_window: str,
    profile: str | None = None,
    echo: Callable[[str], None] = print,
    tune_url_timeout: float = _DEFAULT_TUNE_URL_TIMEOUT,
) -> tuple[_UiServer, str]:
    """Construct (without running) the UI server; return ``(server, page_url)``.

    No URLs are baked into the boot payload — the client reads ``token`` from
    ``location.search`` and builds every API URL itself, so the same served
    HTML works regardless of which port was bound.
    """
    if initial_window not in ALL_WINDOW_PRESETS:
        allowed = ", ".join(sorted(ALL_WINDOW_PRESETS))
        raise ValueError(f"Unknown window preset {initial_window!r}. Choose one of: {allowed}.")

    server = _UiServer(("127.0.0.1", 0), _Handler)
    token = secrets.token_urlsafe(16)
    port = int(server.server_address[1])
    server.token = token
    server.project_config = project_config
    server.project_root = project_root
    server.metrics = metrics
    server.internal_manager = internal_manager
    server.initial_window = initial_window
    server.profile = profile
    server.echo = echo
    server.tune_url_timeout = tune_url_timeout
    server.html = render_ui_html(
        _boot_payload(project_config, project_root, metrics, initial_window)
    )
    return server, f"http://127.0.0.1:{port}/?token={token}"


def serve_ui(
    *,
    project_config: ProjectConfig,
    project_root: Path,
    metrics: list[tuple[Path, MetricConfig]],
    internal_manager: InternalTablesManager,
    initial_window: str,
    profile: str | None = None,
    echo: Callable[[str], None] = print,
    open_browser: bool = True,
    tune_url_timeout: float = _DEFAULT_TUNE_URL_TIMEOUT,
) -> None:
    """Serve the cockpit until Ctrl-C. Every spawned job is stopped on exit."""
    server, url = build_ui_server(
        project_config=project_config,
        project_root=project_root,
        metrics=metrics,
        internal_manager=internal_manager,
        initial_window=initial_window,
        profile=profile,
        echo=echo,
        tune_url_timeout=tune_url_timeout,
    )
    echo(f"  UI: {url}")
    echo("  Open the URL above if no browser opens. Ctrl-C to stop.")
    if open_browser:
        try:
            with _quiet_stderr():
                webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        echo("")
        echo("  Stopping — terminating any jobs the UI spawned…")
    finally:
        server.jobs.shutdown()
        server.server_close()
        echo("  Stopped.")
