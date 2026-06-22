"""Tests for incident-label parsing and grid alignment."""

import json

import numpy as np
import pytest

from detectkit.autotune._types import TuneMode
from detectkit.autotune.labels import parse_incident_labels, parse_labels_file


def _grid():
    return np.array(
        [np.datetime64("2026-01-01T00:00:00", "ms") + np.timedelta64(i, "h") for i in range(48)],
        dtype="datetime64[ms]",
    )


def test_interval_marks_all_points_inside():
    labels = parse_incident_labels(
        {"incidents": [{"start": "2026-01-01 03:00:00", "end": "2026-01-01 05:00:00"}]},
        interval_seconds=3600,
    )
    gt = labels.to_ground_truth(_grid(), 3600)
    # hours 03, 04, 05 inclusive
    assert gt.n_positive == 3
    assert gt.mode == TuneMode.SUPERVISED
    assert gt.n_intervals == 1


def test_point_snaps_to_nearest_grid():
    labels = parse_incident_labels(
        {"incidents": [{"at": "2026-01-01 10:20:00"}]}, interval_seconds=3600
    )
    gt = labels.to_ground_truth(_grid(), 3600)
    assert gt.n_positive == 1
    assert gt.n_points == 1
    assert bool(gt.y_true[10]) is True  # snapped to 10:00


def test_empty_labels_is_unsupervised():
    labels = parse_incident_labels(None, interval_seconds=3600)
    assert labels.is_empty()
    gt = labels.to_ground_truth(_grid(), 3600)
    assert gt.mode == TuneMode.UNSUPERVISED
    assert gt.n_positive == 0


def test_json_equals_yaml(tmp_path):
    payload = {
        "metric": "m",
        "incidents": [{"start": "2026-01-01 03:00:00", "end": "2026-01-01 05:00:00"}],
    }
    yml = tmp_path / "labels.yml"
    yml.write_text(
        "metric: m\nincidents:\n  - {start: '2026-01-01 03:00:00', end: '2026-01-01 05:00:00'}\n"
    )
    js = tmp_path / "labels.json"
    js.write_text(json.dumps(payload))

    a = parse_labels_file(yml, interval_seconds=3600, metric_name="m")
    b = parse_labels_file(js, interval_seconds=3600, metric_name="m")
    assert (
        a.to_ground_truth(_grid(), 3600).n_positive == b.to_ground_truth(_grid(), 3600).n_positive
    )


def test_metric_mismatch_raises():
    with pytest.raises(ValueError, match="for metric"):
        parse_incident_labels(
            {"metric": "other", "incidents": [{"at": "2026-01-01 10:00:00"}]},
            interval_seconds=3600,
            metric_name="mine",
        )


def test_inverted_interval_raises():
    with pytest.raises(ValueError, match="after end"):
        parse_incident_labels(
            {"incidents": [{"start": "2026-01-01 05:00:00", "end": "2026-01-01 03:00:00"}]},
            interval_seconds=3600,
        )


def test_timezone_conversion_to_utc():
    # 12:00 in a +03:00 zone → 09:00 UTC
    labels = parse_incident_labels(
        {"timezone": "Europe/Moscow", "incidents": [{"at": "2026-01-01 12:00:00"}]},
        interval_seconds=3600,
    )
    gt = labels.to_ground_truth(_grid(), 3600)
    assert bool(gt.y_true[9]) is True
