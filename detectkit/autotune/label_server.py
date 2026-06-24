"""Local browser labeler server for ``dtk autotune --label``.

A pure-stdlib localhost server: it serves the interactive labeler page and, when
the user clicks **Save & tune**, validates the labels, writes a versioned file
into ``incidents/<metric>/`` and stops — so the command can continue straight
into the tuning run. Bound to 127.0.0.1 with a one-shot token; nothing is exposed
off the machine, and nothing is written until the user explicitly saves.
"""

from __future__ import annotations

import json
import re
import secrets
import threading
import webbrowser
from collections.abc import Callable
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import numpy as np

from detectkit.autotune.html_labeler import render_labeler_html
from detectkit.autotune.labels import parse_incident_labels

_NAME_RE = re.compile(r"[^a-z0-9_-]+")
_MAX_BODY = 5_000_000  # generous cap on the posted labels payload


def _sanitize(name: str) -> str:
    """Filesystem-safe slug for a label-set name; falls back to ``incidents``."""
    slug = _NAME_RE.sub("-", name.strip().lower()).strip("-")
    return slug or "incidents"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class _LabelServer(ThreadingHTTPServer):
    """Localhost server holding the per-run state the handler reads/writes."""

    # Don't block process/interpreter exit on in-flight request threads (we stop
    # after a single save anyway); also avoids coverage's thread-tracing hanging
    # at exit on lingering handler threads.
    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(address, handler)
        self.token: str = ""
        self.html: str = ""
        self.metric: str = ""
        self.incidents_dir: Path = Path(".")
        self.interval_seconds: int = 1
        self.saved_path: Path | None = None


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args: Any) -> None:  # silence default stderr logging
        return

    def _srv(self) -> _LabelServer:
        return cast(_LabelServer, self.server)

    def do_GET(self) -> None:
        body = self._srv().html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        srv = self._srv()
        if parse_qs(urlparse(self.path).query).get("token", [""])[0] != srv.token:
            self.send_error(403, "bad token")
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > _MAX_BODY:
            self.send_error(413, "empty or too large")
            return
        try:
            import yaml as _yaml

            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            yaml_text = str(payload.get("yaml", ""))
            set_name = _sanitize(str(payload.get("name", "")))
            raw = _yaml.safe_load(yaml_text)
            # validate against the canonical schema before writing anything
            parse_incident_labels(
                raw, interval_seconds=srv.interval_seconds, metric_name=srv.metric
            )
            srv.incidents_dir.mkdir(parents=True, exist_ok=True)
            out = srv.incidents_dir / f"{set_name}-{_stamp()}.yml"
            out.write_text(yaml_text, encoding="utf-8")
            srv.saved_path = out
        except Exception as exc:
            self.send_error(400, f"invalid labels: {exc}")
            return
        resp = json.dumps({"saved": str(out)}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)
        # stop serving (from this worker thread) so the command can continue
        threading.Thread(target=srv.shutdown, daemon=True).start()


def build_label_server(
    *,
    metric_name: str,
    data: dict[str, np.ndarray],
    incidents_dir: Path,
    interval_seconds: int,
) -> tuple[_LabelServer, str]:
    """Construct (without running) the labeler server; return ``(server, page_url)``."""
    server = _LabelServer(("127.0.0.1", 0), _Handler)
    token = secrets.token_urlsafe(16)
    port = int(server.server_address[1])
    server.token = token
    server.metric = metric_name
    server.incidents_dir = incidents_dir
    server.interval_seconds = interval_seconds
    server.html = render_labeler_html(
        metric_name,
        data,
        save_url=f"http://127.0.0.1:{port}/save?token={token}",
        interval_seconds=interval_seconds,
    )
    return server, f"http://127.0.0.1:{port}/?token={token}"


def serve_labeler(
    *,
    metric_name: str,
    data: dict[str, np.ndarray],
    incidents_dir: Path,
    interval_seconds: int,
    open_browser: bool = True,
    echo: Callable[[str], None] = print,
    on_ready: Callable[[str], None] | None = None,
) -> Path | None:
    """Serve the labeler until the user saves (returns the file) or cancels (None)."""
    server, url = build_label_server(
        metric_name=metric_name,
        data=data,
        incidents_dir=incidents_dir,
        interval_seconds=interval_seconds,
    )
    if on_ready is not None:
        on_ready(url)
    echo(f"  Labeler: {url}")
    echo("  Mark incidents in the browser, then click Save & tune (Ctrl-C to cancel).")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        return None
    finally:
        server.server_close()
    return server.saved_path
