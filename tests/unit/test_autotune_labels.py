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


def test_labels_carry_description_for_editing():
    """Parsed incidents keep their `label`, so editing a file round-trips text."""
    labels = parse_incident_labels(
        {
            "incidents": [
                {"start": "2026-01-01 03:00:00", "end": "2026-01-01 05:00:00", "label": "outage"},
                {"at": "2026-01-01 10:00:00", "label": "spike"},
            ]
        },
        interval_seconds=3600,
    )
    assert labels.intervals[0].label == "outage"
    assert labels.points[0].label == "spike"


def test_incidents_to_display_round_trip(tmp_path):
    """`load_incidents_for_display` renders a file as labeler seed dicts."""
    from detectkit.autotune.labels import incidents_to_display, load_incidents_for_display

    labels = parse_incident_labels(
        {
            "incidents": [
                {"start": "2026-01-01 03:00:00", "end": "2026-01-01 05:00:00", "label": "outage"},
                {"at": "2026-01-01 10:00:00"},  # a point → degenerate span
            ]
        },
        interval_seconds=3600,
    )
    disp = incidents_to_display(labels)
    assert disp[0] == {
        "start": "2026-01-01 03:00:00",
        "end": "2026-01-01 05:00:00",
        "label": "outage",
    }
    assert disp[1] == {"start": "2026-01-01 10:00:00", "end": "2026-01-01 10:00:00", "label": ""}

    f = tmp_path / "demo.yml"
    f.write_text(
        "metric: demo\nincidents:\n"
        "  - {start: '2026-01-01 03:00:00', end: '2026-01-01 05:00:00', label: 'outage'}\n"
    )
    loaded = load_incidents_for_display(f, interval_seconds=3600, metric_name="demo")
    assert loaded == [
        {"start": "2026-01-01 03:00:00", "end": "2026-01-01 05:00:00", "label": "outage"}
    ]


def test_offgrid_degenerate_interval_snaps_like_point():
    """A degenerate interval (start == end) off the grid snaps to the nearest grid
    point, so an `{at}` point that round-trips through the labeler as
    `{start: T, end: T}` still matches instead of silently marking nothing."""
    # 03:07 is 7 min past the 03:00 grid point — well within the 1h tolerance.
    labels = parse_incident_labels(
        {"incidents": [{"start": "2026-01-01 03:07:00", "end": "2026-01-01 03:07:00"}]},
        interval_seconds=3600,
    )
    gt = labels.to_ground_truth(_grid(), 3600)
    assert gt.n_positive == 1
    assert bool(gt.y_true[3]) is True  # snapped to hour 03

    # Far off the grid (beyond tolerance) marks nothing, same as a point.
    far = parse_incident_labels(
        {"incidents": [{"start": "2030-01-01 00:00:00", "end": "2030-01-01 00:00:00"}]},
        interval_seconds=3600,
    )
    assert far.to_ground_truth(_grid(), 3600).n_positive == 0
