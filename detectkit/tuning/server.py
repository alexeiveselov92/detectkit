"""Local browser tuning server for ``dtk tune``.

A pure-stdlib localhost server: it serves the interactive tuning page and, when
the user clicks **Apply to metric**, validates + archives + writes the tuned
config (``config_writer.apply_tuned_config``) and stops — so the command can
report what changed and exit. Bound to 127.0.0.1 with a one-shot token; nothing
is exposed off the machine, and nothing is written until the user explicitly
applies. An invalid config returns 400 and keeps serving so the user can fix the
knobs and retry.

Two further POST endpoints are **repeatable** (they keep serving rather than
shutting down): ``/labels`` writes the marked incidents to ``incidents/<metric>/``,
and ``/autotune`` runs the full server-side autotune engine over the metric's
history (using the incidents the user has marked as ground truth) and returns the
winning config so the page can re-seed every knob — the **Autotune** mode of the
cockpit. Autotune here is purely advisory: it computes + re-seeds, it does NOT
persist a run, emit a ``__tuned_<id>.yml`` or write detections (so ``dtk tune``
stays lock-free); the user reviews the band and clicks **Apply** to write it back,
and the next ``dtk run`` is the source of truth.
"""

from __future__ import annotations

import contextlib
import json
import os
import secrets
import threading
import webbrowser
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import parse_qs, urlparse

from detectkit.autotune.labels import parse_incident_labels, versioned_labels_path
from detectkit.core.interval import Interval
from detectkit.tuning.config_writer import AppliedConfig, TunedDetector, apply_tuned_config
from detectkit.tuning.html import render_tune_html

if TYPE_CHECKING:
    from detectkit.config.metric_config import MetricConfig
    from detectkit.database.internal_tables import InternalTablesManager

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
        # Where the server-side Autotune mode streams its run-log (the LABELS →
        # SEASONALITY → … → RESULT blocks). Defaults to plain ``print`` so a bare
        # server still works; ``serve_tuner`` swaps in the command's ``click.echo``
        # so the terminal log matches the rest of the CLI's house style.
        self.echo: Callable[[str], None] = print
        # Labeler write-back state (the synced incident labeler in the page).
        self.metric: str = ""
        self.incidents_dir: Path = Path(".")
        self.interval_seconds: int = 1
        # Server-side autotune state (the Autotune mode): the config + a DB handle
        # to reload the metric's history. None when autotune isn't wired in (e.g. a
        # bare server in a test); /autotune then returns 400.
        self.metric_config: MetricConfig | None = None
        self.internal_manager: InternalTablesManager | None = None
        # Serialize /autotune: the DB manager holds a single connection, and the
        # engine is heavy — one run at a time (e.g. two browser tabs) keeps both safe.
        self.autotune_lock = threading.Lock()


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
            self._reply_error(403, "bad token")
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0 or length > _MAX_BODY:
            self._reply_error(413, "empty or too large")
            return
        body = self.rfile.read(length)
        # /labels and /autotune are repeatable (keep tuning); /apply is terminal.
        if parsed.path == "/labels":
            self._handle_labels(srv, body)
        elif parsed.path == "/autotune":
            self._handle_autotune(srv, body)
        else:
            self._handle_apply(srv, body)

    def _reply_json(self, payload: dict[str, Any]) -> None:
        resp = json.dumps(payload, default=_json_default).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def _reply_error(self, code: int, detail: str) -> None:
        """Error response with the detail in the UTF-8 body, not the status line.

        ``BaseHTTPRequestHandler.send_error`` writes the message into the HTTP
        status line, which is latin-1 only — an exception text carrying a unicode
        dash/``≈`` (pydantic validation, an autotune decision message, the
        no-datapoints hint) would crash the response with a ``UnicodeEncodeError``
        instead of returning a clean error. Keep the status line's default reason
        phrase (ASCII) and carry the detail in the body, which the page reads via
        ``r.text()``.
        """
        body = detail.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_apply(self, srv: _TuneServer, body: bytes) -> None:
        try:
            payload = json.loads(body.decode("utf-8"))
            consecutive = payload.get("consecutive_anomalies")
            # Fraction rule (issue #101): the page always posts both keys (a
            # value to set, null to remove); a legacy page posts neither, which
            # leaves the metric's existing pair untouched.
            window_update: tuple[str | None, float | None] | None = None
            if "anomaly_window" in payload or "min_anomaly_share" in payload:
                raw_window = payload.get("anomaly_window")
                raw_share = payload.get("min_anomaly_share")
                window_update = (
                    None if raw_window is None else str(raw_window),
                    None if raw_share is None else float(raw_share),
                )
            applied = apply_tuned_config(
                original_path=srv.original_path,
                project_root=srv.project_root,
                detectors=_parse_tuned_detectors(payload),
                consecutive_anomalies=None if consecutive is None else int(consecutive),
                anomaly_window_update=window_update,
            )
        except Exception as exc:
            # Keep serving so the user can fix the knobs and retry.
            self._reply_error(400, f"invalid config: {exc}")
            return
        srv.applied = applied
        self._reply_json(
            {
                "saved": str(applied.saved),
                "archived": str(applied.archived),
                "updated": list(applied.updated),
                "preserved": list(applied.preserved),
            }
        )
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
            self._reply_error(400, f"invalid labels: {exc}")
            return
        # No shutdown: labels save repeatedly while the user keeps tuning.
        self._reply_json({"saved": str(out)})

    def _handle_autotune(self, srv: _TuneServer, body: bytes) -> None:
        """Run the autotune engine server-side; return the winning config to re-seed.

        Reloads the metric's full (capped) history from the DB and uses the
        incidents the page POSTs (the same labels YAML as **Save incidents**) as
        ground truth, so labeling in the cockpit and autotuning share one set with
        no file round-trip. Advisory only — nothing is persisted; the user reviews
        the re-seeded band and clicks **Apply** to write it back. Repeatable: keeps
        serving so the user can relabel and re-run. An error returns 400.
        """
        try:
            with srv.autotune_lock:
                result = _run_autotune(srv, body)
        except Exception as exc:  # noqa: BLE001 — surface as a 400, keep serving
            import click

            srv.echo(click.style(f"  ✗ Autotune failed: {exc}", fg="red"))
            self._reply_error(400, f"autotune failed: {exc}")
            return
        self._reply_json(result)


def _parse_tuned_detectors(payload: dict[str, Any]) -> list[TunedDetector]:
    """Build the tuned-detector list from an Apply POST.

    The cockpit posts ``detectors: [{index, type, params}, ...]`` — one entry per
    detector the user actually tuned (the auto-seeded one plus any it edited via the
    picker); every other detector in the metric is preserved verbatim by the writer.
    Falls back to the legacy single ``detector`` object (index 0) so an older page
    still applies. Raises ``ValueError`` on a payload with neither.
    """
    raw = payload.get("detectors")
    if isinstance(raw, list) and raw:
        out: list[TunedDetector] = []
        for d in raw:
            if not isinstance(d, dict):
                continue
            idx = d.get("index")
            out.append(
                TunedDetector(
                    type=str(d.get("type", "")),
                    params=dict(d.get("params") or {}),
                    index=int(idx) if isinstance(idx, int) and not isinstance(idx, bool) else None,
                )
            )
        if out:
            return out
    detector = payload.get("detector")
    if isinstance(detector, dict):
        return [
            TunedDetector(
                type=str(detector.get("type", "")),
                params=dict(detector.get("params") or {}),
                index=0,
            )
        ]
    raise ValueError("no detector in the apply request")


def _json_default(o: Any) -> Any:
    """JSON fallback so an autotune reply with numpy scalars/arrays serializes.

    The decision log / CV folds can carry ``np.int64``/``np.float64`` (only the
    latter is a ``float`` subclass, so ints would otherwise raise). Invoked by
    ``json.dumps`` only for otherwise-unserializable values, so the hot /apply +
    /labels replies (plain ``str`` dicts) never import numpy.
    """
    import numpy as np

    if isinstance(o, np.generic):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def _run_autotune(srv: _TuneServer, body: bytes) -> dict[str, Any]:
    """Run the autotune engine for the **Autotune** mode; return the re-seed payload.

    Reloads the metric's full history, projects the POSTed incidents as ground
    truth, runs the shared engine, and shapes the winner into the same camelCase
    detector seed the controls were first seeded from (``seed_detector_params``),
    plus a decision log / score summary for the panel. Raises on any problem; the
    handler turns that into a 400 and keeps serving.

    Side effect: streams a structured run-log to ``srv.echo`` — a cyan banner,
    then the engine's ``LABELS → SEASONALITY → DETECTOR SELECT → GRID SEARCH →
    WINDOW`` blocks (the **same** ``StageLogRenderer`` the ``dtk autotune`` command
    uses), then a ``RESULT`` block — so a user watching the terminal beside the
    cockpit sees what each Run-autotune click is computing, in the same blocked
    format as ``dtk run``'s load/detect/alert log.
    """
    import yaml as _yaml

    from detectkit.autotune.runner import autotune_from_data
    from detectkit.cli._output import AUTOTUNE_STAGE_TITLES, StageLogRenderer
    from detectkit.config.metric_config import AutoTuneConfig
    from detectkit.tuning.payload import seed_detector_params

    echo = srv.echo
    config = srv.metric_config
    internal = srv.internal_manager
    if config is None or internal is None:
        raise RuntimeError("autotune is unavailable for this session")
    autotune_cfg = config.autotune or AutoTuneConfig()
    if not autotune_cfg.enabled:
        raise RuntimeError("autotune is disabled in this metric's config (autotune.enabled: false)")

    request = json.loads(body.decode("utf-8")) if body else {}
    raw = _yaml.safe_load(str(request.get("yaml", ""))) if request.get("yaml") else None
    scoring = request.get("scoring") or None
    labels = parse_incident_labels(
        raw, interval_seconds=srv.interval_seconds, metric_name=srv.metric
    )

    # Tune on exactly the window the cockpit is showing (the 'Points shown' trim),
    # not the full history — otherwise the search optimizes a different series than
    # the one the user sees and scores recall/FDR on. The page posts its current
    # window; an absent window (older page / static) falls back to full history.
    from_dt, to_dt, window_desc = _autotune_window(request.get("window"), srv.interval_seconds)
    data = internal.load_datapoints(srv.metric, from_timestamp=from_dt, to_timestamp=to_dt)
    n_all = int(len(data["timestamp"]))
    if n_all == 0:
        raise RuntimeError(
            f"no datapoints for {srv.metric} in {window_desc} — "
            f"run `dtk run --select {srv.metric} --steps load` first, or widen the window"
        )

    _echo_autotune_banner(
        echo=echo,
        metric=srv.metric,
        n_points=n_all,
        interval_seconds=srv.interval_seconds,
        labels=labels,
        scoring=scoring,
        autotune_cfg=autotune_cfg,
        window_desc=window_desc,
    )

    result = autotune_from_data(
        metric_name=srv.metric,
        data=data,
        labels=labels,
        interval_seconds=srv.interval_seconds,
        autotune_cfg=autotune_cfg,
        scoring_override=scoring,
        on_stage=StageLogRenderer(titles=AUTOTUNE_STAGE_TITLES, echo=echo),
    )

    params = result.chosen_detector_params
    _echo_autotune_result(echo=echo, result=result)
    return {
        "detector": seed_detector_params(result.chosen_detector_type, params),
        "consecutive_anomalies": result.consecutive_anomalies,
        # Fraction rule (issue #101): pre-resolved to grid points for the page
        # (the worker sweeps in points), same floor-div as AlertConditions.
        "anomaly_window_points": (
            max(1, Interval(result.anomaly_window).seconds // srv.interval_seconds)
            if result.anomaly_window is not None
            else None
        ),
        "min_anomaly_share": result.min_anomaly_share,
        "seasonality": result.chosen_seasonality,
        "score": result.score,
        "scoring_metric": result.scoring_metric,
        "mode": result.mode,
        "n_points": result.n_points,
        "n_candidates": len(result.candidate_detector_ids),
        "labels_summary": result.labels_summary,
        "cv_per_fold": result.cv_per_fold,
        "decision_log": result.decision_log,
        "winner": (
            f"{result.chosen_detector_type}"
            f"(threshold={params.get('threshold')}, window_size={params.get('window_size')})"
        ),
    }


def _autotune_window(
    window: Any, interval_seconds: int
) -> tuple[datetime | None, datetime | None, str]:
    """Map the cockpit's current ``{start, end}`` ms window to load bounds.

    The page posts the **shown** window (after the 'Points shown' trim) so the
    engine tunes on exactly what the user sees. Returns ``(from_dt, to_dt,
    label)``; an absent or malformed window falls back to ``(None, None, "the
    full history")``. ``load_datapoints`` is half-open ``[from, to)``, so the
    upper bound is pushed one interval past the last shown point to keep it
    inclusive (mirroring ``build_tune_payload``).
    """
    if not isinstance(window, dict):
        return None, None, "the full history"
    try:
        start_ms = int(window["start"])
        end_ms = int(window["end"])
    except (KeyError, TypeError, ValueError):
        return None, None, "the full history"
    if end_ms < start_ms:
        return None, None, "the full history"
    epoch = datetime(1970, 1, 1)
    from_dt = epoch + timedelta(milliseconds=start_ms)
    to_dt = epoch + timedelta(milliseconds=end_ms) + timedelta(seconds=interval_seconds)
    return from_dt, to_dt, "the selected window"


def _echo_autotune_banner(
    *,
    echo: Callable[[str], None],
    metric: str,
    n_points: int,
    interval_seconds: int,
    labels: Any,
    scoring: str | None,
    autotune_cfg: Any,
    window_desc: str = "the full history",
) -> None:
    """Announce a server-side autotune run with the same cyan header the CLI prints.

    Mirrors the ``dtk autotune`` command's ``Tuning metric: …`` preamble so the
    cockpit's terminal log opens the same way: which metric, how much of which
    window, the ground truth (supervised vs unsupervised) and the scoring metric.
    """
    import click

    n_gt = len(labels.intervals) + len(labels.points)
    gt_desc = (
        f"{n_gt} marked incident(s) as ground truth (supervised)"
        if n_gt
        else "no marked incidents → unsupervised"
    )
    echo("")
    echo(click.style(f"Autotune (cockpit): {metric}", fg="cyan", bold=True))
    echo(
        f"  Series: {n_points:,} point(s) in {window_desc} "
        f"(interval {interval_seconds}s) · {gt_desc}"
    )
    echo(f"  Scoring: {scoring or autotune_cfg.scoring_metric or 'mcc'}")


def _echo_autotune_result(*, echo: Callable[[str], None], result: Any) -> None:
    """Render the closing ``RESULT`` block (winner + CV folds + the re-seed note)."""
    from detectkit.cli._output import echo_block

    params = result.chosen_detector_params
    folds = " ".join(f"{f:.2f}" for f in result.cv_per_fold) or "—"
    season_line = f"Seasonality: {result.chosen_seasonality or 'none'}  |  CV folds: {folds}"
    if result.consecutive_anomalies is not None:
        season_line += f"  |  consecutive_anomalies={result.consecutive_anomalies}"
    if result.anomaly_window is not None:
        season_line += (
            f"  |  anomaly_window={result.anomaly_window} "
            f"× min_anomaly_share={result.min_anomaly_share}"
        )
    echo_block(
        "RESULT",
        [
            f"Winner: {result.chosen_detector_type}"
            f"(threshold={params.get('threshold')}, window_size={params.get('window_size')})  "
            f"{result.scoring_metric}={result.score:.3f}",
            season_line,
            f"Evaluated {len(result.candidate_detector_ids)} candidate(s) — re-seeded the cockpit. "
            "Review the band, then click Apply to write it into the metric YAML.",
        ],
        echo=echo,
    )


def build_tune_server(
    *,
    payload: dict[str, Any],
    original_path: Path,
    project_root: Path,
    metric_name: str = "",
    incidents_dir: Path | None = None,
    interval_seconds: int = 1,
    metric_config: MetricConfig | None = None,
    internal_manager: InternalTablesManager | None = None,
) -> tuple[_TuneServer, str]:
    """Construct (without running) the tuning server; return ``(server, page_url)``.

    The bound port is known only after construction, so the ``save_url`` (Apply),
    ``labels_save_url`` (Save incidents) and ``autotune_url`` (server-side Autotune)
    — each carrying the one-shot token — are injected into the payload here, right
    before the HTML is rendered. ``incidents_dir`` is where **Save incidents** writes
    versioned labels files. ``metric_config`` + ``internal_manager`` enable the
    **Autotune** mode (reload history + run the engine); omit them (e.g. a static
    preview) and ``/autotune`` returns 400.
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
    server.metric_config = metric_config
    server.internal_manager = internal_manager
    payload_with_url = {
        **payload,
        "save_url": f"http://127.0.0.1:{port}/apply?token={token}",
        "labels_save_url": f"http://127.0.0.1:{port}/labels?token={token}",
        "autotune_url": f"http://127.0.0.1:{port}/autotune?token={token}",
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
    metric_config: MetricConfig | None = None,
    internal_manager: InternalTablesManager | None = None,
) -> AppliedConfig | None:
    """Serve the tuner until the user applies (returns the result) or cancels (None)."""
    server, url = build_tune_server(
        payload=payload,
        original_path=original_path,
        project_root=project_root,
        metric_name=metric_name,
        incidents_dir=incidents_dir,
        interval_seconds=interval_seconds,
        metric_config=metric_config,
        internal_manager=internal_manager,
    )
    # Stream the server-side Autotune mode's run-log through the command's echo
    # (``click.echo``) so the terminal blocks match the rest of the CLI.
    server.echo = echo
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
