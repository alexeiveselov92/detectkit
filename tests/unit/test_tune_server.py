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
