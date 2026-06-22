"""Command-level tests for `dtk autotune` (_tune_one) with a fake manager."""

import json
from datetime import datetime, timedelta

import numpy as np

from detectkit.cli.commands import autotune as autotune_cmd
from detectkit.config.metric_config import MetricConfig


def _series(n=24 * 30, anomalies=(300, 301, 600), seed=5):
    rng = np.random.RandomState(seed)
    ts = np.array(
        [np.datetime64("2026-01-01T00:00:00", "ms") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[ms]",
    )
    hours = np.array([i % 24 for i in range(n)])
    vals = (100 + 30 * np.sin(2 * np.pi * hours / 24) + rng.normal(0, 4, n)).astype(np.float64)
    for i in anomalies:
        vals[i] += 70
    seas = np.array([json.dumps({"hour": int(h)}) for h in hours], dtype=object)
    return {
        "timestamp": ts,
        "value": vals,
        "seasonality_data": seas,
        "seasonality_columns": ["hour"],
    }


class FakeInternal:
    """In-memory stand-in for InternalTablesManager covering autotune's calls."""

    def __init__(self, data):
        self._data = data
        self.runs = []
        self.saved_detections = []
        self.deleted = []
        self.locked = False

    def load_datapoints(self, name, from_timestamp=None, to_timestamp=None):
        return self._data

    def acquire_lock(self, name, detector_id, process_type):
        self.locked = True
        return True

    def release_lock(self, name, detector_id, process_type, status, error_message=None):
        self.locked = False

    def save_autotune_run(self, **kwargs):
        self.runs.append(kwargs)
        return 1

    def save_detections(self, name, detector_id, detector_name, batch, params):
        self.saved_detections.append(detector_id)
        return len(batch["timestamp"])

    def delete_detections(self, name, detector_id=None, mutations_sync=False):
        self.deleted.append(detector_id)
        return 0

    def list_detector_ids(self, name):
        return {}

    def get_autotune_runs(self, name):
        return []


def _make_project(tmp_path):
    (tmp_path / "metrics").mkdir()
    metric_path = tmp_path / "metrics" / "demo.yml"
    config = MetricConfig(
        name="demo", interval="1h", query="SELECT 1", seasonality_columns=["hour"]
    )
    return metric_path, config


def _to_dt(ts, i):
    ms = int(np.datetime64(ts[i], "ms").astype(np.int64))
    return (datetime(1970, 1, 1) + timedelta(milliseconds=ms)).strftime("%Y-%m-%d %H:%M:%S")


def test_tune_one_writes_config_and_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(autotune_cmd.sys.stdin, "isatty", lambda: False)
    data = _series()
    fake = FakeInternal(data)
    metric_path, config = _make_project(tmp_path)

    ok = autotune_cmd._tune_one(
        metric_path=metric_path,
        config=config,
        project_root=tmp_path,
        internal_manager=fake,
        incidents_path=None,
        label=False,
        scoring_override=None,
        from_dt=None,
        to_dt=None,
        force=False,
        dry_run=False,
    )
    assert ok is True
    # a tuned config was written
    tuned = list((tmp_path / "metrics").glob("demo__tuned_*.yml"))
    assert len(tuned) == 1
    text = tuned[0].read_text()
    assert text.lstrip().startswith("#")
    reparsed = MetricConfig.from_yaml_file(tuned[0])
    assert len(reparsed.detectors) == 1
    # run row persisted + winner detections persisted, lock released
    assert len(fake.runs) == 1 and fake.runs[0]["status"] == "success"
    assert len(fake.saved_detections) == 1
    assert fake.locked is False


def test_tune_one_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(autotune_cmd.sys.stdin, "isatty", lambda: False)
    fake = FakeInternal(_series())
    metric_path, config = _make_project(tmp_path)

    ok = autotune_cmd._tune_one(
        metric_path=metric_path,
        config=config,
        project_root=tmp_path,
        internal_manager=fake,
        incidents_path=None,
        label=False,
        scoring_override=None,
        from_dt=None,
        to_dt=None,
        force=False,
        dry_run=True,
    )
    assert ok is True
    assert list((tmp_path / "metrics").glob("demo__tuned_*.yml")) == []
    assert fake.runs == []
    assert fake.saved_detections == []


def test_tune_one_supervised_with_incidents_file(tmp_path, monkeypatch):
    monkeypatch.setattr(autotune_cmd.sys.stdin, "isatty", lambda: False)
    data = _series()
    fake = FakeInternal(data)
    metric_path, config = _make_project(tmp_path)
    incidents = tmp_path / "incidents.yml"
    rows = "\n".join(f"  - {{at: '{_to_dt(data['timestamp'], i)}'}}" for i in (300, 301, 600))
    incidents.write_text("metric: demo\nincidents:\n" + rows + "\n")

    ok = autotune_cmd._tune_one(
        metric_path=metric_path,
        config=config,
        project_root=tmp_path,
        internal_manager=fake,
        incidents_path=str(incidents),
        label=False,
        scoring_override=None,
        from_dt=None,
        to_dt=None,
        force=False,
        dry_run=False,
    )
    assert ok is True
    assert fake.runs[0]["mode"] == "supervised"


def test_tune_one_no_datapoints_skips(tmp_path, monkeypatch):
    monkeypatch.setattr(autotune_cmd.sys.stdin, "isatty", lambda: False)
    empty = {
        "timestamp": np.array([], dtype="datetime64[ms]"),
        "value": np.array([], dtype=np.float64),
        "seasonality_data": np.array([], dtype=object),
        "seasonality_columns": [],
    }
    fake = FakeInternal(empty)
    metric_path, config = _make_project(tmp_path)
    ok = autotune_cmd._tune_one(
        metric_path=metric_path,
        config=config,
        project_root=tmp_path,
        internal_manager=fake,
        incidents_path=None,
        label=False,
        scoring_override=None,
        from_dt=None,
        to_dt=None,
        force=False,
        dry_run=False,
    )
    assert ok is False
    assert fake.runs == []


def test_label_flag_emits_html(tmp_path, monkeypatch):
    monkeypatch.setattr(autotune_cmd.sys.stdin, "isatty", lambda: False)
    fake = FakeInternal(_series())
    metric_path, config = _make_project(tmp_path)
    ok = autotune_cmd._tune_one(
        metric_path=metric_path,
        config=config,
        project_root=tmp_path,
        internal_manager=fake,
        incidents_path=None,
        label=True,
        scoring_override=None,
        from_dt=None,
        to_dt=None,
        force=False,
        dry_run=False,
    )
    assert ok is True
    html = tmp_path / "metrics" / "demo__labeler.html"
    assert html.exists()
    assert "__PAYLOAD__" not in html.read_text()
    assert fake.runs == []  # labeling persists nothing
