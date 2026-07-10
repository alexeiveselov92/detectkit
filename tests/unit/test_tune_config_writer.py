"""Tests for the dtk tune config writer (validate → archive → merge → re-emit)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from detectkit.config.metric_config import MetricConfig
from detectkit.tuning.config_writer import TunedDetector, apply_tuned_config

_FIXED = datetime(2026, 6, 24, 10, 15, 30, tzinfo=timezone.utc)

_METRIC_YAML = """# a hand-written comment
name: orders
description: order volume
interval: 1h
query: "SELECT timestamp, value FROM t"
seasonality_columns:
  - hour
detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 100
alerting:
  - enabled: true
    channels: [slack_alerts]
    consecutive_anomalies: 3
"""

# The documented robust combo: a windowed pattern detector PLUS a manual_bounds hard
# floor, with a min_detectors: 2 quorum. Retuning the mad must not drop the floor
# (which would make the quorum permanently unsatisfiable — the reported bug).
_MULTI_YAML = """name: orders
interval: 1h
query: "SELECT timestamp, value FROM t"
detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 8640
  - type: manual_bounds
    params:
      lower_bound: 1
alerting:
  - channels: [slack_alerts]
    min_detectors: 2
    direction: down
    consecutive_anomalies: 2
"""


def _project(tmp_path: Path, text: str = _METRIC_YAML, name: str = "orders") -> Path:
    (tmp_path / "metrics").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "metrics" / f"{name}.yml"
    path.write_text(text, encoding="utf-8")
    return path


def _one(dtype: str, params: dict, index: int | None = 0) -> list[TunedDetector]:
    return [TunedDetector(type=dtype, params=params, index=index)]


def test_apply_swaps_detector_and_archives(tmp_path):
    path = _project(tmp_path)
    res = apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=_one(
            "zscore",
            {
                "threshold": 2.5,
                "window_size": 200,
                "window_weights": "exponential",
                "half_life": 50,
            },
        ),
        consecutive_anomalies=5,
        now=_FIXED,
    )
    assert res.metric == "orders"
    assert res.updated == ("zscore",)
    assert res.preserved == ()
    # archive holds the ORIGINAL bytes verbatim (comments preserved)
    assert res.archived.exists()
    assert (
        res.archived == tmp_path / "metrics" / ".history" / "orders" / "orders-20260624T101530Z.yml"
    )
    assert res.archived.read_text() == _METRIC_YAML

    # the live metric now validates and carries the tuned detector + alert window
    cfg = MetricConfig.from_yaml_file(path)
    assert len(cfg.detectors) == 1
    assert cfg.detectors[0].type == "zscore"
    assert cfg.detectors[0].params["window_size"] == 200
    assert cfg.detectors[0].params["window_weights"] == "exponential"
    assert cfg.detectors[0].params["half_life"] == 50
    assert cfg.alerting[0].consecutive_anomalies == 5
    # untouched fields survive
    assert cfg.description == "order volume"
    assert cfg.seasonality_columns == ["hour"]
    # a fresh header points at the archive
    assert "Hand-tuned via `dtk tune`" in path.read_text()


def test_invalid_params_write_nothing(tmp_path):
    path = _project(tmp_path)
    before = path.read_text()
    with pytest.raises(ValueError, match="threshold"):
        apply_tuned_config(
            original_path=path,
            project_root=tmp_path,
            detectors=_one("mad", {"threshold": -1.0}),
            now=_FIXED,
        )
    # original untouched, no archive created
    assert path.read_text() == before
    assert not (tmp_path / "metrics" / ".history").exists()


def test_untunable_type_rejected(tmp_path):
    path = _project(tmp_path)
    with pytest.raises(ValueError, match="not tunable"):
        apply_tuned_config(
            original_path=path,
            project_root=tmp_path,
            detectors=_one("prophet", {"foo": 1}),  # not a tunable type
            now=_FIXED,
        )
    assert not (tmp_path / "metrics" / ".history").exists()


def test_empty_detector_list_rejected(tmp_path):
    path = _project(tmp_path)
    with pytest.raises(ValueError, match="no detector"):
        apply_tuned_config(original_path=path, project_root=tmp_path, detectors=[], now=_FIXED)
    assert not (tmp_path / "metrics" / ".history").exists()


def test_apply_manual_bounds_swaps_detector(tmp_path):
    # manual_bounds is tunable: dragging the lower/upper sliders writes a stateless
    # threshold detector back into the metric (no window/threshold params).
    path = _project(tmp_path)
    res = apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=_one("manual_bounds", {"lower_bound": 5.0, "upper_bound": 95.0}),
        consecutive_anomalies=2,
        now=_FIXED,
    )
    assert res.metric == "orders"
    body = MetricConfig.from_yaml_file(res.saved)
    assert len(body.detectors) == 1
    det = body.detectors[0]
    assert det.type == "manual_bounds"
    assert det.params["lower_bound"] == 5.0
    assert det.params["upper_bound"] == 95.0
    assert "window_size" not in det.params
    assert body.alerting[0].consecutive_anomalies == 2


def test_apply_manual_bounds_invalid_bounds_rejected(tmp_path):
    # lower >= upper fails the detector's own validation → writes nothing.
    path = _project(tmp_path)
    with pytest.raises(ValueError):
        apply_tuned_config(
            original_path=path,
            project_root=tmp_path,
            detectors=_one("manual_bounds", {"lower_bound": 90.0, "upper_bound": 10.0}),
            now=_FIXED,
        )
    assert not (tmp_path / "metrics" / ".history").exists()


def test_nested_metric_form_round_trips(tmp_path):
    nested = """metric:
  name: nested_one
  interval: 10min
  query: "SELECT 1"
  detectors:
    - type: iqr
      params: {threshold: 1.5}
"""
    path = _project(tmp_path, text=nested, name="nested_one")
    apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=_one("mad", {"threshold": 4.0, "window_size": 300}),
        now=_FIXED,
    )
    cfg = MetricConfig.from_yaml_file(path)
    assert cfg.name == "nested_one"
    assert cfg.detectors[0].type == "mad"
    assert cfg.detectors[0].params["window_size"] == 300


def test_no_alerting_block_is_not_invented(tmp_path):
    text = """name: bare
interval: 1h
query: "SELECT 1"
detectors:
  - type: mad
    params: {threshold: 3.0}
"""
    path = _project(tmp_path, text=text, name="bare")
    apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=_one("mad", {"threshold": 2.0}),
        consecutive_anomalies=7,  # ignored: metric has no alerting block
        now=_FIXED,
    )
    cfg = MetricConfig.from_yaml_file(path)
    assert cfg.alerting is None


def test_consecutive_anomalies_must_be_positive(tmp_path):
    path = _project(tmp_path)
    with pytest.raises(ValueError, match="consecutive_anomalies"):
        apply_tuned_config(
            original_path=path,
            project_root=tmp_path,
            detectors=_one("mad", {"threshold": 3.0}),
            consecutive_anomalies=0,
            now=_FIXED,
        )


def test_type_and_consecutive_keys_stripped_from_params(tmp_path):
    """Stray non-param keys from the client never reach the detector / YAML."""
    path = _project(tmp_path)
    apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=_one("mad", {"threshold": 3.0, "type": "mad", "consecutive_anomalies": 9}),
        now=_FIXED,
    )
    cfg = MetricConfig.from_yaml_file(path)
    assert "type" not in cfg.detectors[0].params
    assert "consecutive_anomalies" not in cfg.detectors[0].params


# --- merge: the multi-detector fix (the reported bug) ----------------------------


def test_merge_preserves_untouched_manual_bounds_floor(tmp_path):
    """Retuning the mad in a [mad, manual_bounds] metric must keep the floor verbatim.

    The reported bug: the whole detectors list was replaced with the single tuned
    detector, dropping the manual_bounds floor and permanently killing a
    min_detectors: 2 alert. The floor is preserved with its lower_bound only — NO
    phantom upper_bound added (a single-bound floor must stay single-bound).
    """
    path = _project(tmp_path, text=_MULTI_YAML)
    res = apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=_one("mad", {"threshold": 3.2, "window_size": 8640}, index=0),
        consecutive_anomalies=2,
        now=_FIXED,
    )
    assert res.updated == ("mad",)
    assert res.preserved == ("manual_bounds",)
    cfg = MetricConfig.from_yaml_file(path)
    assert [d.type for d in cfg.detectors] == ["mad", "manual_bounds"]
    assert cfg.detectors[0].params["threshold"] == 3.2
    floor = cfg.detectors[1]
    assert floor.params == {"lower_bound": 1}  # verbatim — no phantom upper_bound
    # the min_detectors: 2 quorum is still satisfiable (both detectors present)
    assert cfg.alerting[0].min_detectors == 2
    # the header names what was preserved instead of the old misleading "only the
    # detector block was changed"
    assert "preserved verbatim: manual_bounds" in path.read_text()


def test_merge_preserves_non_tunable_detector(tmp_path):
    """A prophet/timesfm detector the cockpit can't tune is still preserved verbatim."""
    text = """name: orders
interval: 1h
query: "SELECT 1"
detectors:
  - type: prophet
    params: {interval_width: 0.99}
  - type: mad
    params: {threshold: 3.0, window_size: 100}
"""
    path = _project(tmp_path, text=text)
    res = apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=_one("mad", {"threshold": 2.0, "window_size": 120}, index=1),
        now=_FIXED,
    )
    assert res.updated == ("mad",)
    assert res.preserved == ("prophet",)
    cfg = MetricConfig.from_yaml_file(path)
    assert [d.type for d in cfg.detectors] == ["prophet", "mad"]
    assert cfg.detectors[0].params == {"interval_width": 0.99}  # untouched
    assert cfg.detectors[1].params["window_size"] == 120


def test_merge_floor_first_preserves_single_bound_floor(tmp_path):
    """Floor-FIRST combo: tuning the windowed detector at a later slot must keep the
    leading manual_bounds floor verbatim — its single lower_bound intact, NO phantom
    upper_bound. (The cockpit opens on the windowed detector, so this is the slot the
    picker writes; the floor at slot 0 is preserved.)"""
    text = """name: orders
interval: 1h
query: "SELECT 1"
detectors:
  - type: manual_bounds
    params: {lower_bound: 1}
  - type: mad
    params: {threshold: 3.0, window_size: 8640}
alerting:
  - channels: [slack_alerts]
    min_detectors: 2
    consecutive_anomalies: 2
"""
    path = _project(tmp_path, text=text)
    res = apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=_one("mad", {"threshold": 2.8, "window_size": 4000}, index=1),
        now=_FIXED,
    )
    assert res.updated == ("mad",)
    assert res.preserved == ("manual_bounds",)
    cfg = MetricConfig.from_yaml_file(path)
    assert [d.type for d in cfg.detectors] == ["manual_bounds", "mad"]
    assert cfg.detectors[0].params == {"lower_bound": 1}  # verbatim — no phantom upper_bound
    assert cfg.detectors[1].params["window_size"] == 4000
    assert cfg.alerting[0].min_detectors == 2


def test_merge_writes_multiple_tuned_detectors(tmp_path):
    """The picker can tune more than one detector; Apply rewrites each in place."""
    path = _project(tmp_path, text=_MULTI_YAML)
    res = apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=[
            TunedDetector(type="zscore", params={"threshold": 4.0, "window_size": 500}, index=0),
            TunedDetector(type="manual_bounds", params={"lower_bound": 2}, index=1),
        ],
        now=_FIXED,
    )
    assert res.updated == ("zscore", "manual_bounds")
    assert res.preserved == ()
    cfg = MetricConfig.from_yaml_file(path)
    assert [d.type for d in cfg.detectors] == ["zscore", "manual_bounds"]
    assert cfg.detectors[0].params["window_size"] == 500
    assert cfg.detectors[1].params == {"lower_bound": 2}


def test_out_of_range_index_appends_and_preserves(tmp_path):
    """No tunable slot (index None / out of range) → append, keeping existing detectors."""
    text = """name: orders
interval: 1h
query: "SELECT 1"
detectors:
  - type: prophet
    params: {interval_width: 0.99}
"""
    path = _project(tmp_path, text=text)
    res = apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=_one("mad", {"threshold": 3.0, "window_size": 100}, index=None),
        now=_FIXED,
    )
    assert res.updated == ("mad",)
    assert res.preserved == ("prophet",)
    cfg = MetricConfig.from_yaml_file(path)
    assert [d.type for d in cfg.detectors] == ["prophet", "mad"]


def test_merge_preserves_execution_params_of_edited_detector(tmp_path):
    """start_time / batch_size the cockpit never exposes survive a retune of that slot."""
    text = """name: orders
interval: 1h
query: "SELECT 1"
detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 100
      start_time: "2024-02-01 00:00:00"
      batch_size: 500
"""
    path = _project(tmp_path, text=text)
    apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        # client sends only the tunable knobs
        detectors=_one("mad", {"threshold": 2.5, "window_size": 200}, index=0),
        now=_FIXED,
    )
    cfg = MetricConfig.from_yaml_file(path)
    det = cfg.detectors[0]
    assert det.params["threshold"] == 2.5
    assert det.params["window_size"] == 200
    assert det.params["start_time"] == "2024-02-01 00:00:00"  # carried over
    assert det.params["batch_size"] == 500  # carried over


# ── autoreg write-back (issue #97 Phase 3) ───────────────────────────────────


def test_apply_autoreg_swaps_detector(tmp_path):
    path = _project(tmp_path)
    res = apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=_one(
            "autoreg",
            {"lags": 3, "threshold": 3.5, "window_size": 150, "min_samples": 20},
        ),
        now=_FIXED,
    )
    assert res.updated == ("autoreg",)
    cfg = MetricConfig.from_yaml_file(path)
    det = cfg.detectors[0]
    assert det.type == "autoreg"
    assert det.params["lags"] == 3
    assert det.params["min_samples"] == 20


def test_apply_autoreg_stabilization_off_written_as_null(tmp_path):
    """autoreg's stabilization is default-ON, so turning it off must land as an
    explicit null in the YAML (an absent key would silently mean clamp)."""
    path = _project(tmp_path)
    apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=_one(
            "autoreg",
            {"lags": 5, "threshold": 3.0, "window_size": 100, "min_samples": 20,
             "stabilization": None},
        ),
        now=_FIXED,
    )
    text = path.read_text()
    assert "stabilization" in text
    cfg = MetricConfig.from_yaml_file(path)
    assert cfg.detectors[0].params["stabilization"] is None


def test_apply_autoreg_invalid_lags_write_nothing(tmp_path):
    path = _project(tmp_path)
    before = path.read_text()
    with pytest.raises(ValueError):
        apply_tuned_config(
            original_path=path,
            project_root=tmp_path,
            detectors=_one("autoreg", {"lags": 0, "window_size": 100}),
            now=_FIXED,
        )
    assert path.read_text() == before


# ── fraction alert rule write-back (issue #101 Part 2) ───────────────────────

_PAIR_YAML = """name: orders
interval: 1h
query: "SELECT timestamp, value FROM t"
detectors:
  - type: mad
    params:
      threshold: 3.0
      window_size: 100
alerting:
  - channels: [slack_alerts]
    consecutive_anomalies: 3
    anomaly_window: 21600s
    min_anomaly_share: 0.5
"""


def test_apply_writes_the_fraction_pair(tmp_path):
    path = _project(tmp_path)
    apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=_one("mad", {"threshold": 3.0, "window_size": 100}),
        consecutive_anomalies=2,
        anomaly_window_update=("14400s", 0.3),
        now=_FIXED,
    )
    cfg = MetricConfig.from_yaml_file(path)
    alert = cfg.alerting[0]
    assert alert.anomaly_window == "14400s"
    assert alert.min_anomaly_share == 0.3
    assert alert.consecutive_anomalies == 2


def test_apply_removes_the_pair_when_unset(tmp_path):
    path = _project(tmp_path, text=_PAIR_YAML)
    apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=_one("mad", {"threshold": 3.0, "window_size": 100}),
        anomaly_window_update=(None, None),
        now=_FIXED,
    )
    cfg = MetricConfig.from_yaml_file(path)
    assert cfg.alerting[0].anomaly_window is None
    assert cfg.alerting[0].min_anomaly_share is None


def test_apply_without_update_leaves_existing_pair(tmp_path):
    """A legacy caller that doesn't pass anomaly_window_update must not strip a
    configured pair."""
    path = _project(tmp_path, text=_PAIR_YAML)
    apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detectors=_one("mad", {"threshold": 2.5, "window_size": 100}),
        now=_FIXED,
    )
    cfg = MetricConfig.from_yaml_file(path)
    assert cfg.alerting[0].anomaly_window == "21600s"
    assert cfg.alerting[0].min_anomaly_share == 0.5


def test_apply_half_pair_rejected(tmp_path):
    path = _project(tmp_path)
    before = path.read_text()
    with pytest.raises(ValueError):
        apply_tuned_config(
            original_path=path,
            project_root=tmp_path,
            detectors=_one("mad", {"threshold": 3.0, "window_size": 100}),
            anomaly_window_update=("14400s", None),
            now=_FIXED,
        )
    assert path.read_text() == before


def test_apply_invalid_window_write_nothing(tmp_path):
    """A window under 2 metric intervals fails MetricConfig validation → nothing
    is written."""
    path = _project(tmp_path)
    before = path.read_text()
    with pytest.raises(Exception):
        apply_tuned_config(
            original_path=path,
            project_root=tmp_path,
            detectors=_one("mad", {"threshold": 3.0, "window_size": 100}),
            anomaly_window_update=("3600s", 0.3),  # 1 interval — validator rejects
            now=_FIXED,
        )
    assert path.read_text() == before
