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
