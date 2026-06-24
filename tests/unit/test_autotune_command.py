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
        label=False,
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
        label=False,
        scoring_override=None,
        from_dt=None,
        to_dt=None,
        force=False,
        dry_run=False,
    )
    assert ok is False
    assert fake.runs == []


def test_label_no_serve_emits_static_html(tmp_path, monkeypatch):
    """--label --no-serve writes a static labeler file and exits (no server, no tuning)."""
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
        no_serve=True,
        scoring_override=None,
        from_dt=None,
        to_dt=None,
        force=False,
        dry_run=False,
    )
    assert ok is True
    html = tmp_path / "metrics" / "demo__labeler.html"
    assert html.exists()
    assert "__PAYLOAD__" not in html.read_text() and "__SAVE_URL__" not in html.read_text()
    assert "const SAVE_URL = null;" in html.read_text()  # static mode → download fallback
    assert fake.runs == []  # labeling persists nothing


def test_label_serve_then_tunes(tmp_path, monkeypatch):
    """--label (server mode): after the labeler saves a set, autotune runs on it."""
    monkeypatch.setattr(autotune_cmd.sys.stdin, "isatty", lambda: False)
    data = _series()
    fake = FakeInternal(data)
    metric_path, config = _make_project(tmp_path)

    def fake_serve(
        *, metric_name, data, incidents_dir, interval_seconds, open_browser, echo, preload=None
    ):
        incidents_dir.mkdir(parents=True, exist_ok=True)
        out = incidents_dir / "demo-20260101T000000Z.yml"
        rows = "\n".join(f"  - {{at: '{_to_dt(data['timestamp'], i)}'}}" for i in (300, 301, 600))
        out.write_text("metric: demo\nincidents:\n" + rows + "\n")
        return out

    monkeypatch.setattr(autotune_cmd, "serve_labeler", fake_serve)
    ok = autotune_cmd._tune_one(
        metric_path=metric_path,
        config=config,
        project_root=tmp_path,
        internal_manager=fake,
        incidents_path=None,
        label=True,
        no_serve=False,
        scoring_override=None,
        from_dt=None,
        to_dt=None,
        force=False,
        dry_run=False,
    )
    assert ok is True
    assert fake.runs and fake.runs[0]["mode"] == "supervised"  # tuned on the saved labels


def test_resolve_preload_incidents_from_default_dir(tmp_path):
    """The labeler is seeded from the newest file in incidents/<metric>/ by default."""
    from detectkit.config.metric_config import AutoTuneConfig

    inc = tmp_path / "incidents" / "demo"
    inc.mkdir(parents=True)
    (inc / "demo-20260101T000000Z.yml").write_text(
        "metric: demo\nincidents:\n  - {start: '2026-01-02 00:00:00', end: '2026-01-02 06:00:00', "
        "label: 'old'}\n"
    )
    (inc / "demo-20260201T000000Z.yml").write_text(  # newest wins
        "metric: demo\nincidents:\n  - {start: '2026-03-02 00:00:00', end: '2026-03-02 06:00:00', "
        "label: 'newest'}\n"
    )
    preload, src = autotune_cmd._resolve_preload_incidents(
        metric="demo",
        interval_seconds=3600,
        incidents_path=None,
        autotune_cfg=AutoTuneConfig(),
        project_root=tmp_path,
    )
    assert src is not None and src.name == "demo-20260201T000000Z.yml"
    assert preload == [
        {"start": "2026-03-02 00:00:00", "end": "2026-03-02 06:00:00", "label": "newest"}
    ]


def test_resolve_preload_incidents_explicit_flag_wins(tmp_path):
    """An explicit --incidents file is preferred over the default dir."""
    from detectkit.config.metric_config import AutoTuneConfig

    (tmp_path / "incidents" / "demo").mkdir(parents=True)
    (tmp_path / "incidents" / "demo" / "demo-20260101T000000Z.yml").write_text(
        "metric: demo\nincidents:\n  - {at: '2026-01-09 00:00:00'}\n"
    )
    explicit = tmp_path / "my_labels.yml"
    explicit.write_text(
        "metric: demo\nincidents:\n  - {start: '2026-05-02 00:00:00', end: '2026-05-02 06:00:00'}\n"
    )
    preload, src = autotune_cmd._resolve_preload_incidents(
        metric="demo",
        interval_seconds=3600,
        incidents_path=str(explicit),
        autotune_cfg=AutoTuneConfig(),
        project_root=tmp_path,
    )
    assert src == explicit
    assert preload == [{"start": "2026-05-02 00:00:00", "end": "2026-05-02 06:00:00", "label": ""}]


def test_resolve_preload_incidents_none_when_absent(tmp_path):
    from detectkit.config.metric_config import AutoTuneConfig

    preload, src = autotune_cmd._resolve_preload_incidents(
        metric="demo",
        interval_seconds=3600,
        incidents_path=None,
        autotune_cfg=AutoTuneConfig(),
        project_root=tmp_path,
    )
    assert preload == [] and src is None


def test_label_serve_preloads_existing(tmp_path, monkeypatch):
    """--label server mode seeds the page with the metric's newest saved set."""
    monkeypatch.setattr(autotune_cmd.sys.stdin, "isatty", lambda: False)
    data = _series()
    fake = FakeInternal(data)
    metric_path, config = _make_project(tmp_path)
    inc = tmp_path / "incidents" / "demo"
    inc.mkdir(parents=True)
    (inc / "demo-20260101T000000Z.yml").write_text(
        f"metric: demo\nincidents:\n  - {{at: '{_to_dt(data['timestamp'], 300)}'}}\n"
    )
    captured = {}

    def fake_serve(*, preload=None, **kw):
        captured["preload"] = preload
        out = kw["incidents_dir"] / "demo-20260102T000000Z.yml"
        kw["incidents_dir"].mkdir(parents=True, exist_ok=True)
        out.write_text(
            f"metric: demo\nincidents:\n  - {{at: '{_to_dt(data['timestamp'], 600)}'}}\n"
        )
        return out

    monkeypatch.setattr(autotune_cmd, "serve_labeler", fake_serve)
    autotune_cmd._tune_one(
        metric_path=metric_path,
        config=config,
        project_root=tmp_path,
        internal_manager=fake,
        incidents_path=None,
        label=True,
        no_serve=False,
        scoring_override=None,
        from_dt=None,
        to_dt=None,
        force=False,
        dry_run=False,
    )
    assert captured["preload"] and captured["preload"][0]["start"] == _to_dt(data["timestamp"], 300)


def test_resolve_preload_incidents_from_labels_file_config(tmp_path):
    """The config `labels_file` seeds the labeler when no --incidents flag is given."""
    from detectkit.config.metric_config import AutoTuneConfig

    f = tmp_path / "lab.yml"
    f.write_text(
        "metric: demo\nincidents:\n  - {start: '2026-02-02 00:00:00', end: '2026-02-02 06:00:00'}\n"
    )
    preload, src = autotune_cmd._resolve_preload_incidents(
        metric="demo",
        interval_seconds=3600,
        incidents_path=None,
        autotune_cfg=AutoTuneConfig(labels_file="lab.yml"),
        project_root=tmp_path,
    )
    assert src == f
    assert preload[0]["start"] == "2026-02-02 00:00:00"


def test_resolve_preload_incidents_from_inline_config(tmp_path):
    """With no file anywhere, inline `autotune.incidents` still seeds the labeler."""
    from detectkit.config.metric_config import AutoTuneConfig

    cfg = AutoTuneConfig(
        incidents=[{"start": "2026-01-02 00:00:00", "end": "2026-01-02 06:00:00", "label": "inl"}]
    )
    preload, src = autotune_cmd._resolve_preload_incidents(
        metric="demo",
        interval_seconds=3600,
        incidents_path=None,
        autotune_cfg=cfg,
        project_root=tmp_path,
    )
    assert src is None  # inline → no source path
    assert preload == [
        {"start": "2026-01-02 00:00:00", "end": "2026-01-02 06:00:00", "label": "inl"}
    ]


def test_label_no_serve_preloads_and_tolerates_outside_path(tmp_path, monkeypatch):
    """--label --no-serve seeds the static page, and an absolute labels path OUTSIDE
    the project tree does not crash the run (regression: relative_to ValueError)."""
    monkeypatch.setattr(autotune_cmd.sys.stdin, "isatty", lambda: False)
    data = _series()
    fake = FakeInternal(data)
    proj = tmp_path / "proj"
    (proj / "metrics").mkdir(parents=True)
    metric_path = proj / "metrics" / "demo.yml"
    config = MetricConfig(
        name="demo", interval="1h", query="SELECT 1", seasonality_columns=["hour"]
    )
    outside = tmp_path / "outside_labels.yml"  # absolute, NOT under proj
    outside.write_text(
        "metric: demo\nincidents:\n"
        f"  - {{start: '{_to_dt(data['timestamp'], 300)}', "
        f"end: '{_to_dt(data['timestamp'], 305)}', label: 'seeded'}}\n"
    )
    ok = autotune_cmd._tune_one(
        metric_path=metric_path,
        config=config,
        project_root=proj,
        internal_manager=fake,
        incidents_path=str(outside),
        label=True,
        no_serve=True,
        scoring_override=None,
        from_dt=None,
        to_dt=None,
        force=False,
        dry_run=False,
    )
    assert ok is True  # did not raise on relative_to() of an outside path
    html = (proj / "metrics" / "demo__labeler.html").read_text()
    assert "const PRELOAD = [" in html and "seeded" in html
