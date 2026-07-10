"""Tests for the local tuning server (dtk tune, server mode)."""

import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from detectkit.config.metric_config import MetricConfig
from detectkit.tuning.server import build_tune_server

_METRIC_YAML = """name: orders
interval: 1h
query: "SELECT timestamp, value FROM t"
detectors:
  - type: mad
    params: {threshold: 3.0, window_size: 100}
alerting:
  - enabled: true
    channels: [slack_alerts]
    consecutive_anomalies: 3
"""


def _project(tmp_path: Path) -> Path:
    (tmp_path / "metrics").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "metrics" / "orders.yml"
    path.write_text(_METRIC_YAML, encoding="utf-8")
    return path


def _payload() -> dict:
    return {
        "metric": "orders",
        "project": None,
        "description": None,
        "interval_seconds": 3600,
        "period": {"start": 0, "end": 3600000},
        "points": [{"t": 0, "v": 1.0}, {"t": 3600000, "v": 2.0}],
        "seasonality": [{}, {}],
        "seasonality_columns": [],
        "detector": {
            "type": "mad",
            "threshold": 3.0,
            "windowSize": 100,
            "minSamples": 30,
            "inputType": "values",
            "smoothing": "none",
            "smoothingAlpha": 0.3,
            "smoothingWindow": 10,
            "windowWeights": "none",
            "halfLife": None,
            "detrend": "none",
            "seasonalityComponents": None,
            "minSamplesPerGroup": 10,
        },
        "consecutive_anomalies": 3,
        "save_url": None,
    }


def _serve(server):
    th = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.05), daemon=True)
    th.start()
    return th


def _post(url_base, token, body):
    req = urllib.request.Request(
        f"{url_base}/apply?token={token}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=5)


def _post_path(url_base, path, token, body):
    req = urllib.request.Request(
        f"{url_base}{path}?token={token}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    return urllib.request.urlopen(req, timeout=5)


_LABELS_YAML = (
    "metric: orders\ntimezone: UTC\n"
    'incidents:\n  - {start: "1970-01-01 00:00:00", end: "1970-01-01 01:00:00"}\n'
)


def test_save_url_injected_into_page(tmp_path):
    server, url = build_tune_server(
        payload=_payload(), original_path=_project(tmp_path), project_root=tmp_path
    )
    try:
        assert "/apply?token=" in server.html  # save_url baked into the served page
        assert "__DTK_TUNE__" in server.html
    finally:
        server.server_close()


def test_server_applies_valid_config(tmp_path):
    path = _project(tmp_path)
    server, url = build_tune_server(payload=_payload(), original_path=path, project_root=tmp_path)
    th = _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        body = {
            "detector": {"type": "zscore", "params": {"threshold": 2.0, "window_size": 150}},
            "consecutive_anomalies": 4,
        }
        r = _post(base, token, body)
        assert r.status == 200
        th.join(timeout=5)  # server stops itself after a successful apply
        assert server.applied is not None
        assert server.applied.saved == path
        assert server.applied.archived.exists()
        cfg = MetricConfig.from_yaml_file(path)
        assert cfg.detectors[0].type == "zscore"
        assert cfg.detectors[0].params["window_size"] == 150
        assert cfg.alerting[0].consecutive_anomalies == 4
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        server.server_close()


_MULTI_METRIC_YAML = """name: orders
interval: 1h
query: "SELECT timestamp, value FROM t"
detectors:
  - type: mad
    params: {threshold: 3.0, window_size: 100}
  - type: manual_bounds
    params: {lower_bound: 1}
alerting:
  - channels: [slack_alerts]
    min_detectors: 2
    consecutive_anomalies: 2
"""


def test_server_merges_and_preserves_other_detectors(tmp_path):
    """The new detectors-list Apply payload rewrites only the tuned slot and keeps
    the metric's other detector (the manual_bounds floor) verbatim — so a
    min_detectors: 2 quorum isn't silently disabled (the reported bug)."""
    (tmp_path / "metrics").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "metrics" / "orders.yml"
    path.write_text(_MULTI_METRIC_YAML, encoding="utf-8")
    server, url = build_tune_server(payload=_payload(), original_path=path, project_root=tmp_path)
    th = _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        body = {
            "detectors": [
                {"index": 0, "type": "zscore", "params": {"threshold": 2.0, "window_size": 150}}
            ],
            "consecutive_anomalies": 2,
        }
        r = _post(base, token, body)
        assert r.status == 200
        resp = json.loads(r.read())
        assert resp["updated"] == ["zscore"]
        assert resp["preserved"] == ["manual_bounds"]
        th.join(timeout=5)
        cfg = MetricConfig.from_yaml_file(path)
        assert [d.type for d in cfg.detectors] == ["zscore", "manual_bounds"]
        assert cfg.detectors[1].params == {"lower_bound": 1}  # floor preserved verbatim
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        server.server_close()


def test_server_rejects_bad_token(tmp_path):
    path = _project(tmp_path)
    before = path.read_text()
    server, url = build_tune_server(payload=_payload(), original_path=path, project_root=tmp_path)
    _serve(server)
    try:
        base = url.split("/?")[0]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post(base, "WRONG", {"detector": {"type": "mad", "params": {"threshold": 3.0}}})
        assert ei.value.code == 403
        assert server.applied is None
        assert path.read_text() == before
    finally:
        server.shutdown()
        server.server_close()


def test_server_rejects_invalid_config(tmp_path):
    path = _project(tmp_path)
    before = path.read_text()
    server, url = build_tune_server(payload=_payload(), original_path=path, project_root=tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post(base, token, {"detector": {"type": "mad", "params": {"threshold": -1.0}}})
        assert ei.value.code == 400
        assert server.applied is None
        # nothing written, no archive — and the server keeps serving for a retry
        assert path.read_text() == before
        assert not (tmp_path / "metrics" / ".history").exists()
    finally:
        server.shutdown()
        server.server_close()


def _labels_server(tmp_path):
    inc_dir = tmp_path / "incidents" / "orders"
    server, url = build_tune_server(
        payload=_payload(),
        original_path=_project(tmp_path),
        project_root=tmp_path,
        metric_name="orders",
        incidents_dir=inc_dir,
        interval_seconds=3600,
    )
    return server, url, inc_dir


def test_labels_save_url_injected_into_page(tmp_path):
    server, _url, _inc = _labels_server(tmp_path)
    try:
        assert "/labels?token=" in server.html  # Save-incidents endpoint baked in
    finally:
        server.server_close()


def test_server_saves_labels_and_keeps_serving(tmp_path):
    server, url, inc_dir = _labels_server(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        r = _post_path(base, "/labels", token, {"name": "", "yaml": _LABELS_YAML})
        assert r.status == 200
        saved = json.loads(r.read())["saved"]
        assert Path(saved).exists()
        files = sorted(inc_dir.glob("*.yml"))
        assert len(files) == 1 and files[0].name.startswith("orders-")
        # /labels is repeatable: apply was never triggered and a 2nd save works.
        assert server.applied is None
        r2 = _post_path(base, "/labels", token, {"name": "second", "yaml": _LABELS_YAML})
        assert r2.status == 200
        assert any(f.name.startswith("orders-second-") for f in inc_dir.glob("*.yml"))
        assert len(list(inc_dir.glob("*.yml"))) == 2
    finally:
        server.shutdown()
        server.server_close()


def test_server_rejects_invalid_labels_and_keeps_serving(tmp_path):
    server, url, inc_dir = _labels_server(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post_path(base, "/labels", token, {"yaml": "metric: orders\nincidents: not-a-list\n"})
        assert ei.value.code == 400
        assert not list(inc_dir.glob("*.yml")) if inc_dir.exists() else True
        # still serving — a valid save now works
        r = _post_path(base, "/labels", token, {"yaml": _LABELS_YAML})
        assert r.status == 200
    finally:
        server.shutdown()
        server.server_close()


def test_labels_rejects_bad_token(tmp_path):
    server, url, inc_dir = _labels_server(tmp_path)
    _serve(server)
    try:
        base = url.split("/?")[0]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post_path(base, "/labels", "WRONG", {"yaml": _LABELS_YAML})
        assert ei.value.code == 403
        assert not inc_dir.exists() or not list(inc_dir.glob("*.yml"))
    finally:
        server.shutdown()
        server.server_close()


# ── server-side autotune (the Autotune mode) ──────────────────────────────────

_AUTOTUNE_METRIC_YAML = """name: orders
interval: 1h
query: "SELECT timestamp, value FROM t"
detectors:
  - type: mad
    params: {threshold: 3.0, window_size: 50}
alerting:
  - enabled: true
    channels: [slack_alerts]
    consecutive_anomalies: 3
autotune:
  folds: 3
"""


class _StubManager:
    """Minimal stand-in for InternalTablesManager — only load_datapoints is used.

    Honors ``from_timestamp`` / ``to_timestamp`` with the real half-open ``[from,
    to)`` semantics so a test can assert the server constrains the load to the
    shown window.
    """

    def __init__(self, data: dict) -> None:
        self._data = data

    def load_datapoints(self, metric_name, from_timestamp=None, to_timestamp=None):  # noqa: ARG002
        if from_timestamp is None and to_timestamp is None:
            return self._data
        import numpy as np

        ts = self._data["timestamp"]
        mask = np.ones(len(ts), dtype=bool)
        if from_timestamp is not None:
            mask &= ts >= np.datetime64(from_timestamp, "ms")
        if to_timestamp is not None:
            mask &= ts < np.datetime64(to_timestamp, "ms")
        return {
            "timestamp": ts[mask],
            "value": self._data["value"][mask],
            "seasonality_data": self._data["seasonality_data"][mask],
            "seasonality_columns": self._data["seasonality_columns"],
        }


def _series(n: int = 600) -> dict:
    import numpy as np

    rng = np.random.RandomState(3)
    ts = np.array(
        [np.datetime64("2026-01-01T00:00:00", "ms") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[ms]",
    )
    vals = (100 + rng.normal(0, 3, n)).astype(np.float64)
    for i in (200, 201, 400):
        if i < n:
            vals[i] += 60.0
    return {
        "timestamp": ts,
        "value": vals,
        "seasonality_data": np.array(["{}"] * n, dtype=object),
        "seasonality_columns": [],
    }


def _autotune_server(tmp_path: Path):
    (tmp_path / "metrics").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "metrics" / "orders.yml"
    path.write_text(_AUTOTUNE_METRIC_YAML, encoding="utf-8")
    config = MetricConfig.from_yaml_file(path)
    server, url = build_tune_server(
        payload=_payload(),
        original_path=path,
        project_root=tmp_path,
        metric_name="orders",
        incidents_dir=tmp_path / "incidents" / "orders",
        interval_seconds=3600,
        metric_config=config,
        internal_manager=_StubManager(_series()),
    )
    return server, url, path


def test_autotune_url_injected_into_page(tmp_path):
    server, _url, _path = _autotune_server(tmp_path)
    try:
        assert "/autotune?token=" in server.html  # Autotune endpoint baked in
    finally:
        server.server_close()


def test_autotune_returns_winner_and_keeps_serving(tmp_path):
    server, url, _path = _autotune_server(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        # Unsupervised (no incidents) — still returns a winning windowed detector.
        r = _post_path(base, "/autotune", token, {"yaml": "metric: orders\nincidents: []\n"})
        assert r.status == 200
        res = json.loads(r.read())
        assert res["detector"]["type"] in {"mad", "zscore", "iqr", "autoreg"}
        assert isinstance(res["detector"]["threshold"], int | float)
        assert isinstance(res["detector"]["windowSize"], int)
        assert res["mode"] == "unsupervised"
        assert res["n_candidates"] >= 1
        assert isinstance(res["decision_log"], list) and res["decision_log"]
        # Repeatable + advisory: never triggers apply, nothing written.
        assert server.applied is None
        r2 = _post_path(base, "/autotune", token, {"yaml": "metric: orders\nincidents: []\n"})
        assert r2.status == 200
    finally:
        server.shutdown()
        server.server_close()


def test_autotune_streams_structured_run_log(tmp_path):
    """The Autotune mode streams a blocked run-log through ``server.echo`` — a
    cyan banner, the engine's LABELS/SEASONALITY/.../RESULT blocks (the same
    house style as ``dtk run`` / ``dtk autotune``) — so a user watching the
    terminal beside the cockpit sees what each Run-autotune click computes. The
    per-candidate under-fill warning flood never reaches that log."""
    server, url, _path = _autotune_server(tmp_path)
    lines: list[str] = []
    server.echo = lines.append  # capture the streamed run-log
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        # echo happens synchronously before the JSON reply, so the lines are all
        # captured by the time the POST returns.
        r = _post_path(base, "/autotune", token, {"yaml": "metric: orders\nincidents: []\n"})
        assert r.status == 200
        blob = "\n".join(lines)
        assert "Autotune (cockpit): orders" in blob  # the banner
        assert "┌─ LABELS" in blob  # first engine stage block
        assert "┌─ RESULT" in blob  # closing block
        assert "Winner:" in blob
        assert "falls back to global" not in blob  # no warning flood in the log
    finally:
        server.shutdown()
        server.server_close()


def test_autotune_honors_shown_window(tmp_path):
    """The page posts the shown 'Points shown' window; the server must tune on
    exactly that slice, not the full history — otherwise the search optimizes a
    different series than the cockpit shows and scores recall/FDR on."""
    import numpy as np

    server, url, _path = _autotune_server(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        # No window → full history (all 600 points).
        r_full = _post_path(base, "/autotune", token, {"yaml": "metric: orders\nincidents: []\n"})
        assert json.loads(r_full.read())["n_points"] == 600
        # Shown window = the most-recent 400 points (indices 200..599). `_series` is
        # deterministic, so these timestamps match the server's stub series exactly.
        ts = _series()["timestamp"]
        win = {
            "start": int(ts[200].astype("datetime64[ms]").astype(np.int64)),
            "end": int(ts[599].astype("datetime64[ms]").astype(np.int64)),
        }
        r_win = _post_path(
            base,
            "/autotune",
            token,
            {"yaml": "metric: orders\nincidents: []\n", "window": win},
        )
        assert json.loads(r_win.read())["n_points"] == 400  # exactly the shown window
    finally:
        server.shutdown()
        server.server_close()


def test_autotune_window_maps_ms_to_load_bounds():
    from datetime import datetime

    from detectkit.tuning.server import _autotune_window

    f, t, desc = _autotune_window({"start": 0, "end": 3_600_000}, 3600)
    assert desc == "the selected window"
    assert f == datetime(1970, 1, 1)
    # half-open [from, to): the upper bound is pushed one interval past the last
    # shown point (end 01:00 + 1h interval) so that point stays included.
    assert t == datetime(1970, 1, 1, 2)
    # Absent / malformed / reversed windows fall back to the full history.
    assert _autotune_window(None, 3600) == (None, None, "the full history")
    assert _autotune_window({"start": 5, "end": 1}, 3600)[2] == "the full history"
    assert _autotune_window({"start": "x", "end": 1}, 3600)[2] == "the full history"


def test_autotune_supervised_picks_consecutive(tmp_path):
    server, url, _path = _autotune_server(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        # index 200/201 → 2026-01-09 08:00/09:00 (i hours after 2026-01-01T00:00).
        labels = (
            "metric: orders\ntimezone: UTC\n"
            'incidents:\n  - {start: "2026-01-09 08:00:00", end: "2026-01-09 09:00:00"}\n'
        )
        r = _post_path(base, "/autotune", token, {"yaml": labels})
        assert r.status == 200
        res = json.loads(r.read())
        assert res["mode"] == "supervised"
        assert isinstance(res["consecutive_anomalies"], int)
    finally:
        server.shutdown()
        server.server_close()


def test_autotune_rejects_bad_scoring_and_keeps_serving(tmp_path):
    # A bad `scoring` override in the POST body must surface as 400 (it threads into
    # resolve_scoring) and leave the server serving for a valid retry.
    server, url, _path = _autotune_server(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post_path(
                base,
                "/autotune",
                token,
                {"yaml": "metric: orders\nincidents: []\n", "scoring": "nonsense"},
            )
        assert ei.value.code == 400
        r = _post_path(base, "/autotune", token, {"yaml": "metric: orders\nincidents: []\n"})
        assert r.status == 200
    finally:
        server.shutdown()
        server.server_close()


def test_autotune_rejects_when_no_datapoints(tmp_path):
    # Manager returns an empty series (e.g. datapoints were cleaned) → friendly 400.
    import numpy as np

    (tmp_path / "metrics").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "metrics" / "orders.yml"
    path.write_text(_AUTOTUNE_METRIC_YAML, encoding="utf-8")
    empty = {
        "timestamp": np.array([], dtype="datetime64[ms]"),
        "value": np.array([], dtype="float64"),
        "seasonality_data": np.array([], dtype=object),
        "seasonality_columns": [],
    }
    server, url = build_tune_server(
        payload=_payload(),
        original_path=path,
        project_root=tmp_path,
        metric_name="orders",
        interval_seconds=3600,
        metric_config=MetricConfig.from_yaml_file(path),
        internal_manager=_StubManager(empty),
    )
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post_path(base, "/autotune", token, {"yaml": "metric: orders\nincidents: []\n"})
        assert ei.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_json_default_serializes_numpy_and_rejects_unknown():
    # The /autotune reply serializes the decision log / CV folds, which can carry
    # numpy scalars — lock all three branches of the JSON fallback directly.
    import numpy as np

    from detectkit.tuning.server import _json_default

    assert _json_default(np.int64(3)) == 3
    assert isinstance(_json_default(np.int64(3)), int)
    assert _json_default(np.float64(1.5)) == 1.5
    assert _json_default(np.array([1, 2])) == [1, 2]
    with pytest.raises(TypeError):
        _json_default(object())


def test_autotune_unavailable_without_config(tmp_path):
    # The plain labels server carries no metric_config/internal_manager → 400.
    server, url, _inc = _labels_server(tmp_path)
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post_path(base, "/autotune", token, {"yaml": "metric: orders\nincidents: []\n"})
        assert ei.value.code == 400
    finally:
        server.shutdown()
        server.server_close()


def test_autotune_rejects_when_disabled(tmp_path):
    (tmp_path / "metrics").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "metrics" / "orders.yml"
    path.write_text(
        _AUTOTUNE_METRIC_YAML.replace("autotune:\n  folds: 3\n", "autotune:\n  enabled: false\n"),
        encoding="utf-8",
    )
    server, url = build_tune_server(
        payload=_payload(),
        original_path=path,
        project_root=tmp_path,
        metric_name="orders",
        interval_seconds=3600,
        metric_config=MetricConfig.from_yaml_file(path),
        internal_manager=_StubManager(_series(200)),
    )
    _serve(server)
    try:
        base, token = url.split("/?")[0], url.split("token=")[1]
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post_path(base, "/autotune", token, {"yaml": "metric: orders\nincidents: []\n"})
        assert ei.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
