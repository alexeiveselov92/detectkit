"""Command-level tests for `dtk autotune` (_tune_one) with a fake manager."""

import json
from datetime import datetime, timedelta

import numpy as np
import pytest

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
        scoring_override=None,
        from_dt=None,
        to_dt=None,
        force=False,
        dry_run=False,
    )
    assert ok is True
    assert fake.runs[0]["mode"] == "supervised"


def test_tune_one_supervised_with_inline_incidents(tmp_path, monkeypatch):
    """Incidents declared inline in the metric's autotune block tune supervised."""
    monkeypatch.setattr(autotune_cmd.sys.stdin, "isatty", lambda: False)
    data = _series()
    fake = FakeInternal(data)
    (tmp_path / "metrics").mkdir()
    metric_path = tmp_path / "metrics" / "demo.yml"
    config = MetricConfig(
        name="demo",
        interval="1h",
        query="SELECT 1",
        seasonality_columns=["hour"],
        autotune={
            "enabled": True,
            "incidents": [{"at": _to_dt(data["timestamp"], i)} for i in (300, 301, 600)],
        },
    )

    ok = autotune_cmd._tune_one(
        metric_path=metric_path,
        config=config,
        project_root=tmp_path,
        internal_manager=fake,
        incidents_path=None,
        scoring_override=None,
        from_dt=None,
        to_dt=None,
        force=False,
        dry_run=False,
    )
    assert ok is True
    assert fake.runs[0]["mode"] == "supervised"


def test_tune_one_auto_discovers_incidents_dir(tmp_path, monkeypatch):
    """Labels saved in incidents/<metric>/ (e.g. by `dtk tune` Label mode) tune
    supervised with no --incidents flag."""
    monkeypatch.setattr(autotune_cmd.sys.stdin, "isatty", lambda: False)
    data = _series()
    fake = FakeInternal(data)
    metric_path, config = _make_project(tmp_path)
    inc = tmp_path / "incidents" / "demo"
    inc.mkdir(parents=True)
    rows = "\n".join(f"  - {{at: '{_to_dt(data['timestamp'], i)}'}}" for i in (300, 301, 600))
    (inc / "demo-20260101T000000Z.yml").write_text("metric: demo\nincidents:\n" + rows + "\n")

    ok = autotune_cmd._tune_one(
        metric_path=metric_path,
        config=config,
        project_root=tmp_path,
        internal_manager=fake,
        incidents_path=None,
        scoring_override=None,
        from_dt=None,
        to_dt=None,
        force=False,
        dry_run=False,
    )
    assert ok is True
    assert fake.runs[0]["mode"] == "supervised"


def test_resolve_labels_precedence(tmp_path):
    """`--incidents` flag wins; else labels_file; else inline incidents; else none."""
    from detectkit.config.metric_config import AutoTuneConfig

    cfg_inline = AutoTuneConfig(incidents=[{"at": "2026-01-13 12:00:00"}])
    labels, source = autotune_cmd._resolve_labels(
        metric_name="demo",
        interval_seconds=3600,
        incidents_path=None,
        autotune_cfg=cfg_inline,
        project_root=tmp_path,
    )
    assert "inline config" in source
    assert len(labels.points) == 1

    # flag overrides inline incidents
    flag_file = tmp_path / "flag.yml"
    flag_file.write_text("incidents:\n  - {at: '2026-01-14 12:00:00'}\n")
    labels, source = autotune_cmd._resolve_labels(
        metric_name="demo",
        interval_seconds=3600,
        incidents_path=str(flag_file),
        autotune_cfg=cfg_inline,
        project_root=tmp_path,
    )
    assert source.startswith("file ")


def test_resolve_labels_directory_uses_newest(tmp_path):
    """A directory resolves to its newest versioned labels file."""
    from detectkit.config.metric_config import AutoTuneConfig

    inc = tmp_path / "incidents" / "demo"
    inc.mkdir(parents=True)
    (inc / "demo-20260101T000000Z.yml").write_text("incidents:\n  - {at: '2026-01-01 00:00:00'}\n")
    (inc / "demo-20260315T120000Z.yml").write_text(
        "incidents:\n"
        "  - {start: '2026-03-15 10:00:00', end: '2026-03-15 14:00:00'}\n"
        "  - {at: '2026-03-16 09:00:00'}\n"
    )
    labels, source = autotune_cmd._resolve_labels(
        metric_name="demo",
        interval_seconds=3600,
        incidents_path=str(inc),
        autotune_cfg=AutoTuneConfig(),
        project_root=tmp_path,
    )
    assert "newest in" in source
    assert "demo-20260315T120000Z.yml" in source
    # the newer file has one interval + one point, not the older single point
    assert len(labels.intervals) == 1 and len(labels.points) == 1


def test_resolve_labels_auto_discovers_incidents_dir(tmp_path):
    """With no flag/inline labels, the newest file in incidents/<metric>/ is used."""
    from detectkit.config.metric_config import AutoTuneConfig

    inc = tmp_path / "incidents" / "demo"
    inc.mkdir(parents=True)
    (inc / "demo-20260101T000000Z.yml").write_text("incidents:\n  - {at: '2026-01-01 00:00:00'}\n")
    (inc / "demo-20260315T120000Z.yml").write_text(
        "incidents:\n  - {start: '2026-03-15 10:00:00', end: '2026-03-15 14:00:00'}\n"
    )
    labels, source = autotune_cmd._resolve_labels(
        metric_name="demo",
        interval_seconds=3600,
        incidents_path=None,
        autotune_cfg=AutoTuneConfig(),
        project_root=tmp_path,
    )
    assert "auto-discovered" in source
    assert "demo-20260315T120000Z.yml" in source
    assert len(labels.intervals) == 1


def test_resolve_labels_directory_interactive_pick(tmp_path, monkeypatch):
    """When interactive with multiple sets, the chosen one is used (not just newest)."""
    from detectkit.config.metric_config import AutoTuneConfig

    inc = tmp_path / "incidents" / "demo"
    inc.mkdir(parents=True)
    (inc / "demo-20260101T000000Z.yml").write_text("incidents:\n  - {at: '2026-01-01 00:00:00'}\n")
    (inc / "demo-20260315T120000Z.yml").write_text("incidents:\n  - {at: '2026-03-15 12:00:00'}\n")
    monkeypatch.setattr(autotune_cmd.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(autotune_cmd.click, "prompt", lambda *a, **k: 1)  # pick the first (oldest)
    _labels, source = autotune_cmd._resolve_labels(
        metric_name="demo",
        interval_seconds=3600,
        incidents_path=str(inc),
        autotune_cfg=AutoTuneConfig(),
        project_root=tmp_path,
    )
    assert "chosen in" in source
    assert "demo-20260101T000000Z.yml" in source


def test_resolve_labels_empty_directory_errors(tmp_path):
    from detectkit.config.metric_config import AutoTuneConfig

    empty = tmp_path / "incidents" / "demo"
    empty.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        autotune_cmd._resolve_labels(
            metric_name="demo",
            interval_seconds=3600,
            incidents_path=str(empty),
            autotune_cfg=AutoTuneConfig(),
            project_root=tmp_path,
        )


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
        scoring_override=None,
        from_dt=None,
        to_dt=None,
        force=False,
        dry_run=False,
    )
    assert ok is False
    assert fake.runs == []
