"""Local browser tuning server for ``dtk tune``.

A pure-stdlib localhost server: it serves the interactive tuning page and, when
the user clicks **Apply to metric**, validates + archives + writes the tuned
config (``config_writer.apply_tuned_config``) and stops — so the command can
report what changed and exit. Bound to 127.0.0.1 with a one-shot token; nothing
is exposed off the machine, and nothing is written until the user explicitly
applies. An invalid config returns 400 and keeps serving so the user can fix the
knobs and retry.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import threading
import webbrowser
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from detectkit.autotune.labels import parse_incident_labels, versioned_labels_path
from detectkit.tuning.config_writer import AppliedConfig, apply_tuned_config
from detectkit.tuning.html import render_tune_html

_MAX_BODY = 5_000_000  # generous cap on the posted config payload


@contextlib.contextmanager
def _quiet_stderr() -> Iterator[None]:
    """Silence OS-level stderr for the duration of the block.

    ``webbrowser.open`` shells out to ``xdg-open``, which prints a wall of
    "browser not found" lines to stderr on a headless / WSL box. The launch is
    best-effort (we already print the URL), so swallow that noise.
    """
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


class _TuneServer(ThreadingHTTPServer):
    """Localhost server holding the per-run state the handler reads/writes."""

    # Don't block interpreter exit on in-flight request threads (we stop after a
    # single apply anyway).
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(address, handler)
        self.token: str = ""
        self.html: str = ""
        self.original_path: Path = Path(".")
        self.project_root: Path = Path(".")
        self.applied: AppliedConfig | None = None
        # Labeler write-back state (the synced incident labeler in the page).
        self.metric: str = ""
        self.incidents_dir: Path = Path(".")
        self.interval_seconds: int = 1


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # silence default stderr logging
        return

    def _srv(self) -> _TuneServer:
        return cast(_TuneServer, self.server)

    def do_GET(self) -> None:
        body = self._srv().html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        srv = self._srv()
        parsed = urlparse(self.path)
        if parse_qs(parsed.query).get("token", [""])[0] != srv.token:
            self.send_error(403, "bad token")
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > _MAX_BODY:
            self.send_error(413, "empty or too large")
            return
        body = self.rfile.read(length)
        # /labels is repeatable (save incidents, keep tuning); /apply is terminal.
        if parsed.path == "/labels":
            self._handle_labels(srv, body)
        else:
            self._handle_apply(srv, body)

    def _reply_json(self, payload: dict[str, str]) -> None:
        resp = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def _handle_apply(self, srv: _TuneServer, body: bytes) -> None:
        try:
            payload = json.loads(body.decode("utf-8"))
            detector = payload.get("detector") or {}
            consecutive = payload.get("consecutive_anomalies")
            applied = apply_tuned_config(
                original_path=srv.original_path,
                project_root=srv.project_root,
                detector_type=str(detector.get("type", "")),
                detector_params=dict(detector.get("params") or {}),
                consecutive_anomalies=None if consecutive is None else int(consecutive),
            )
        except Exception as exc:
            # Keep serving so the user can fix the knobs and retry.
            self.send_error(400, f"invalid config: {exc}")
            return
        srv.applied = applied
        self._reply_json({"saved": str(applied.saved), "archived": str(applied.archived)})
        # stop serving (from this worker thread) so the command can continue
        threading.Thread(target=srv.shutdown, daemon=True).start()

    def _handle_labels(self, srv: _TuneServer, body: bytes) -> None:
        """Validate + write the marked incidents to incidents/<metric>/; keep serving."""
        try:
            import yaml as _yaml

            payload = json.loads(body.decode("utf-8"))
            yaml_text = str(payload.get("yaml", ""))
            raw = _yaml.safe_load(yaml_text)
            # validate against the canonical schema before writing anything
            parse_incident_labels(
                raw, interval_seconds=srv.interval_seconds, metric_name=srv.metric
            )
            srv.incidents_dir.mkdir(parents=True, exist_ok=True)
            out = versioned_labels_path(srv.incidents_dir, srv.metric, str(payload.get("name", "")))
            out.write_text(yaml_text, encoding="utf-8")
        except Exception as exc:
            # Keep serving so the user can fix the labels and retry.
            self.send_error(400, f"invalid labels: {exc}")
            return
        # No shutdown: labels save repeatedly while the user keeps tuning.
        self._reply_json({"saved": str(out)})


def build_tune_server(
    *,
    payload: dict[str, Any],
    original_path: Path,
    project_root: Path,
    metric_name: str = "",
    incidents_dir: Path | None = None,
    interval_seconds: int = 1,
) -> tuple[_TuneServer, str]:
    """Construct (without running) the tuning server; return ``(server, page_url)``.

    The bound port is known only after construction, so the ``save_url`` (Apply)
    and ``labels_save_url`` (Save incidents) — each carrying the one-shot token —
    are injected into the payload here, right before the HTML is rendered.
    ``incidents_dir`` is where **Save incidents** writes versioned labels files.
    """
    server = _TuneServer(("127.0.0.1", 0), _Handler)
    token = secrets.token_urlsafe(16)
    port = int(server.server_address[1])
    server.token = token
    server.original_path = original_path
    server.project_root = project_root
    server.metric = metric_name
    server.incidents_dir = incidents_dir if incidents_dir is not None else project_root
    server.interval_seconds = interval_seconds
    payload_with_url = {
        **payload,
        "save_url": f"http://127.0.0.1:{port}/apply?token={token}",
        "labels_save_url": f"http://127.0.0.1:{port}/labels?token={token}",
    }
    server.html = render_tune_html(payload_with_url)
    return server, f"http://127.0.0.1:{port}/?token={token}"


def serve_tuner(
    *,
    payload: dict[str, Any],
    original_path: Path,
    project_root: Path,
    open_browser: bool = True,
    echo: Callable[[str], None] = print,
    on_ready: Callable[[str], None] | None = None,
    metric_name: str = "",
    incidents_dir: Path | None = None,
    interval_seconds: int = 1,
) -> AppliedConfig | None:
    """Serve the tuner until the user applies (returns the result) or cancels (None)."""
    server, url = build_tune_server(
        payload=payload,
        original_path=original_path,
        project_root=project_root,
        metric_name=metric_name,
        incidents_dir=incidents_dir,
        interval_seconds=interval_seconds,
    )
    if on_ready is not None:
        on_ready(url)
    echo(f"  Tuner: {url}")
    echo(
        "  Open the URL above if no browser opens. Turn the knobs, then click Apply (Ctrl-C to cancel)."
    )
    if open_browser:
        try:
            with _quiet_stderr():
                webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        return None
    finally:
        server.server_close()
    return server.applied
