"""Tests for the dtk tune config writer (validate → archive → re-emit)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from detectkit.config.metric_config import MetricConfig
from detectkit.tuning.config_writer import apply_tuned_config

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


def _project(tmp_path: Path, text: str = _METRIC_YAML, name: str = "orders") -> Path:
    (tmp_path / "metrics").mkdir(parents=True, exist_ok=True)
    path = tmp_path / "metrics" / f"{name}.yml"
    path.write_text(text, encoding="utf-8")
    return path


def test_apply_swaps_detector_and_archives(tmp_path):
    path = _project(tmp_path)
    res = apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detector_type="zscore",
        detector_params={
            "threshold": 2.5,
            "window_size": 200,
            "window_weights": "exponential",
            "half_life": 50,
        },
        consecutive_anomalies=5,
        now=_FIXED,
    )
    assert res.metric == "orders"
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
            detector_type="mad",
            detector_params={"threshold": -1.0},
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
            detector_type="manual_bounds",
            detector_params={"lower_bound": 0, "upper_bound": 10},
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
        detector_type="mad",
        detector_params={"threshold": 4.0, "window_size": 300},
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
        detector_type="mad",
        detector_params={"threshold": 2.0},
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
            detector_type="mad",
            detector_params={"threshold": 3.0},
            consecutive_anomalies=0,
            now=_FIXED,
        )


def test_type_and_consecutive_keys_stripped_from_params(tmp_path):
    """Stray non-param keys from the client never reach the detector / YAML."""
    path = _project(tmp_path)
    apply_tuned_config(
        original_path=path,
        project_root=tmp_path,
        detector_type="mad",
        detector_params={"threshold": 3.0, "type": "mad", "consecutive_anomalies": 9},
        now=_FIXED,
    )
    cfg = MetricConfig.from_yaml_file(path)
    assert "type" not in cfg.detectors[0].params
    assert "consecutive_anomalies" not in cfg.detectors[0].params
