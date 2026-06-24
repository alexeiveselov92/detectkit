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

import json
import secrets
import threading
import webbrowser
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from detectkit.tuning.config_writer import AppliedConfig, apply_tuned_config
from detectkit.tuning.html import render_tune_html

_MAX_BODY = 5_000_000  # generous cap on the posted config payload


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
        if parse_qs(urlparse(self.path).query).get("token", [""])[0] != srv.token:
            self.send_error(403, "bad token")
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > _MAX_BODY:
            self.send_error(413, "empty or too large")
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
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
        resp = json.dumps({"saved": str(applied.saved), "archived": str(applied.archived)}).encode(
            "utf-8"
        )
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)
        # stop serving (from this worker thread) so the command can continue
        threading.Thread(target=srv.shutdown, daemon=True).start()


def build_tune_server(
    *,
    payload: dict[str, Any],
    original_path: Path,
    project_root: Path,
) -> tuple[_TuneServer, str]:
    """Construct (without running) the tuning server; return ``(server, page_url)``.

    The bound port is known only after construction, so the ``save_url`` (carrying
    the one-shot token) is injected into the payload here, right before the HTML
    is rendered.
    """
    server = _TuneServer(("127.0.0.1", 0), _Handler)
    token = secrets.token_urlsafe(16)
    port = int(server.server_address[1])
    server.token = token
    server.original_path = original_path
    server.project_root = project_root
    payload_with_url = {**payload, "save_url": f"http://127.0.0.1:{port}/apply?token={token}"}
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
) -> AppliedConfig | None:
    """Serve the tuner until the user applies (returns the result) or cancels (None)."""
    server, url = build_tune_server(
        payload=payload,
        original_path=original_path,
        project_root=project_root,
    )
    if on_ready is not None:
        on_ready(url)
    echo(f"  Tuner: {url}")
    echo("  Turn the knobs in the browser, then click Apply to metric (Ctrl-C to cancel).")
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
    return server.applied
