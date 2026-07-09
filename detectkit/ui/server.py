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
from detectkit.ui.overview import ALL_WINDOW_PRESETS, WINDOW_PRESETS, build_overview_payload
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


def _find_metric(metrics: list[tuple[Path, MetricConfig]], name: str) -> MetricConfig | None:
    for _path, config in metrics:
        if config.name == name:
            return config
    return None


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
            )
        self._reply_html(render_report_html(payload))

    def _handle_job_status(self, srv: _UiServer, job_id: str, offset: int) -> None:
        job = srv.jobs.get(job_id)
        if job is None:
            self._reply_error(404, f"unknown job: {job_id}")
            return
        self._reply_json(srv.jobs.snapshot(job, offset))

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

    # ── response helpers ─────────────────────────────────────────────────

    def _reply_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _reply_json(self, payload: dict[str, Any]) -> None:
        resp = json.dumps(payload, default=_json_default).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def _reply_error(self, code: int, detail: str) -> None:
        """Error response with the detail in the UTF-8 body, not the status line.

        Mirrors ``tuning/server.py``: the status line is latin-1 only, and an
        exception message can carry non-ASCII (e.g. an ``≈`` from a validation
        error), so the detail rides in the body instead.
        """
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


def _boot_payload(
    project_config: ProjectConfig,
    project_root: Path,
    metrics: list[tuple[Path, MetricConfig]],
    initial_window: str,
) -> dict[str, Any]:
    """The ``GET /`` shell payload: project + metric list, no stats, no URLs."""
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
    return {
        "project": project_config.name,
        "initial_window": initial_window,
        "version": __version__,
        "metrics": entries,
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
        pass
    finally:
        server.jobs.shutdown()
        server.server_close()
