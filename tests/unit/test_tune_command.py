"""Tests for `dtk tune` command orchestration (run_tune) with a mocked manager."""

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from detectkit.cli.commands import tune as tune_cmd
from detectkit.config.metric_config import MetricConfig
from detectkit.tuning.config_writer import AppliedConfig

_METRIC_YAML = """name: orders
interval: 1h
query: "SELECT timestamp, value FROM t"
detectors:
  - type: mad
    params: {threshold: 3.0}
"""


class FakeInternal:
    def __init__(self, n=48, empty=False):
        if empty:
            n = 0
        ts = (
            np.datetime64("2026-01-01T00:00:00", "ms") + np.arange(n) * np.timedelta64(1, "h")
        ).astype("datetime64[ms]")
        self._data = {
            "timestamp": ts,
            "value": (100.0 + np.sin(np.arange(n) / 6.0)).astype(float),
            "seasonality_data": np.array([{} for _ in range(n)], dtype=object),
            "seasonality_columns": [],
        }

    def get_last_datapoint_timestamp(self, name):
        ts = self._data["timestamp"]
        return ts[-1].astype(datetime) if len(ts) else None

    def get_first_datapoint_timestamp(self, name):
        ts = self._data["timestamp"]
        return ts[0].astype(datetime) if len(ts) else None

    def load_datapoints(self, name, from_timestamp=None, to_timestamp=None):
        return self._data


def _setup(tmp_path: Path, monkeypatch, internal, metrics):
    (tmp_path / "metrics").mkdir(parents=True, exist_ok=True)
    project_config = SimpleNamespace(name="demo")
    monkeypatch.setattr(
        tune_cmd, "_load_project", lambda profile: (tmp_path, project_config, internal, None)
    )
    monkeypatch.setattr(tune_cmd, "select_metrics", lambda select, root: metrics)
    return tmp_path


def _metric_pair(tmp_path: Path, name="orders") -> tuple[Path, MetricConfig]:
    path = tmp_path / "metrics" / f"{name}.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_METRIC_YAML.replace("orders", name), encoding="utf-8")
    return path, MetricConfig.from_yaml_file(path)


def test_no_serve_writes_static_preview(tmp_path, monkeypatch):
    pair = _metric_pair(tmp_path)
    _setup(tmp_path, monkeypatch, FakeInternal(), [pair])
    ok = tune_cmd.run_tune(select="orders", no_serve=True)
    assert ok is True
    out = tmp_path / "metrics" / "orders__tuner.html"
    assert out.exists()
    assert "__DTK_TUNE__" in out.read_text()


def test_serve_applies_and_reports(tmp_path, monkeypatch):
    path, config = _metric_pair(tmp_path)
    _setup(tmp_path, monkeypatch, FakeInternal(), [(path, config)])
    archived = tmp_path / "metrics" / ".history" / "orders" / "orders-x.yml"
    captured = {}

    def fake_serve(**kwargs):
        captured.update(kwargs)
        return AppliedConfig(metric="orders", saved=path, archived=archived)

    monkeypatch.setattr(tune_cmd, "serve_tuner", fake_serve)
    ok = tune_cmd.run_tune(select="orders")
    assert ok is True
    # the command passed the metric's own YAML path + project root to the server
    assert captured["original_path"] == path
    assert captured["project_root"] == tmp_path
    assert captured["payload"]["metric"] == "orders"


def test_serve_cancelled_returns_false(tmp_path, monkeypatch):
    path, config = _metric_pair(tmp_path)
    _setup(tmp_path, monkeypatch, FakeInternal(), [(path, config)])
    monkeypatch.setattr(tune_cmd, "serve_tuner", lambda **kw: None)
    assert tune_cmd.run_tune(select="orders") is False


def test_multiple_metrics_refused(tmp_path, monkeypatch):
    p1 = _metric_pair(tmp_path, "orders")
    p2 = _metric_pair(tmp_path, "signups")
    _setup(tmp_path, monkeypatch, FakeInternal(), [p1, p2])
    assert tune_cmd.run_tune(select="*") is False


def test_no_datapoints_is_noop(tmp_path, monkeypatch):
    pair = _metric_pair(tmp_path)
    _setup(tmp_path, monkeypatch, FakeInternal(empty=True), [pair])
    assert tune_cmd.run_tune(select="orders", no_serve=True) is False


def test_no_matching_metric_returns_false(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, FakeInternal(), [])
    assert tune_cmd.run_tune(select="ghost") is False
