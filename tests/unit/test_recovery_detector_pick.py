"""Tests that a recovery message renders the band of the detector that FIRED.

Regression cover for the reported bug: on a multi-detector metric the recovery
payload was built from ``detections[-1]`` — the last row of the latest
timestamp, i.e. whichever ``detector_id`` sorted last in
``get_recent_detections``'s ``ORDER BY timestamp DESC, detector_id``. So a
metric with a MAD detector (band ``[249.34, 418.61]``) plus a ``manual_bounds``
floor (``lower_bound: 30``) fired with the MAD band and cleared with
``Expected >= 30.00`` — a detector that had nothing to do with the alert.

The shape that exposes it is the realistic one: the alert step fetches only
``lookback_points`` (``consecutive_anomalies``) points, so by the time the
metric clears the shallow window can be entirely clean and the incident lives
only in the deeper ``_resolve_incident`` lookback. The payload is now anchored
on the incident's firing detector, so the outcome no longer depends on SQL row
ordering.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import Mock

import numpy as np

from detectkit.alerting.channels.webhook import WebhookChannel
from detectkit.alerting.orchestrator import AlertConditions, AlertOrchestrator
from detectkit.alerting.orchestrator._types import hydrate_detection_records
from detectkit.core.interval import Interval

MAD_BAND = (249.34, 418.61)
FLOOR = 30.0
WINDOW_POINTS = 2  # consecutive_anomalies — what the alert step actually fetches


def _row(ts: str, dets: list[dict], value: float) -> dict:
    """One ``get_recent_detections`` grouped row (per-detector lists)."""
    ordered = sorted(dets, key=lambda d: d["id"])  # SQL: ORDER BY …, detector_id
    return {
        "timestamp": datetime.fromisoformat(ts),
        "detector_ids": [d["id"] for d in ordered],
        "detector_names": [d["name"] for d in ordered],
        "detector_params_list": [d["params"] for d in ordered],
        "detection_metadata_list": [
            ({"direction": d.get("dir", "below"), "severity": 2.0} if d["anomaly"] else {})
            for d in ordered
        ],
        "is_anomaly_flags": [d["anomaly"] for d in ordered],
        "confidence_lowers": [d["lower"] for d in ordered],
        "confidence_uppers": [d["upper"] for d in ordered],
        "value": value,
    }


def _mad(mad_id: str, anomaly: bool = False) -> dict:
    return {
        "id": mad_id,
        "name": "MADDetector",
        "params": '{"threshold": 3.0}',
        "anomaly": anomaly,
        "lower": MAD_BAND[0],
        "upper": MAD_BAND[1],
    }


def _floor(floor_id: str, anomaly: bool = False) -> dict:
    """A one-sided ``manual_bounds`` floor: lower bound only, no upper."""
    return {
        "id": floor_id,
        "name": "ManualBoundsDetector",
        "params": '{"lower_bound": 30.0}',
        "anomaly": anomaly,
        "lower": FLOOR,
        "upper": None,
    }


def _scenario(mad_id: str, floor_id: str) -> list[dict]:
    """A 3-point MAD-driven down incident that ended before the alert window.

    Newest→oldest, as SQL returns them. The floor detector is clean throughout
    (the value never drops near 30), exactly like the reported metric.
    """
    return [
        _row("2026-08-17T11:20:00", [_mad(mad_id), _floor(floor_id)], 287.0),
        _row("2026-08-17T11:10:00", [_mad(mad_id), _floor(floor_id)], 281.0),
        # ── everything below is outside the shallow alert window ──
        _row("2026-08-17T11:00:00", [_mad(mad_id, True), _floor(floor_id)], 193.0),
        _row("2026-08-17T10:50:00", [_mad(mad_id, True), _floor(floor_id)], 190.0),
        _row("2026-08-17T10:40:00", [_mad(mad_id, True), _floor(floor_id)], 188.0),
        _row("2026-08-17T10:30:00", [_mad(mad_id), _floor(floor_id)], 300.0),
    ]


def _orchestrator(rows: list[dict], internal: bool = True) -> AlertOrchestrator:
    handle = None
    if internal:
        handle = Mock()
        handle.get_recent_detections.return_value = rows
        handle.get_last_alert_timestamp.return_value = datetime(2026, 8, 17, 10, 58, 0)
        handle.get_last_recovery_timestamp.return_value = None
    return AlertOrchestrator(
        metric_name="session_started_count__not_ru_region",
        alert_config_id="cfg",
        interval=Interval("10min"),
        conditions=AlertConditions(
            min_detectors=1, direction="down", consecutive_anomalies=WINDOW_POINTS
        ),
        internal=handle,
    )


def _alert_window(rows: list[dict]):
    """What ``_run_alert_step`` passes in: only ``lookback_points`` timestamps."""
    return hydrate_detection_records(rows[:WINDOW_POINTS])


def _context(data):
    return WebhookChannel({"webhook_url": "https://example.com/hook"}).build_context(data)


# --------------------------------------------------------------------------- #
# The bug: the rendered band must not depend on detector_id ordering
# --------------------------------------------------------------------------- #
def test_recovery_shows_firing_detector_when_floor_sorts_last():
    """The reported case: the floor's id sorts last, so it hijacked the message."""
    rows = _scenario(mad_id="a_mad", floor_id="z_floor")

    data = _orchestrator(rows)._build_recovery_data(_alert_window(rows))

    assert data.detector_name == "MADDetector"
    assert (data.confidence_lower, data.confidence_upper) == MAD_BAND
    assert _context(data)["expected_range"] == f"[{MAD_BAND[0]:.2f}, {MAD_BAND[1]:.2f}]"
    assert _context(data)["expected_range"] != f">= {FLOOR:.2f}"  # the reported symptom


def test_recovery_shows_firing_detector_when_floor_sorts_first():
    """Same incident, ids swapped — the old code happened to be right here."""
    rows = _scenario(mad_id="z_mad", floor_id="a_floor")

    data = _orchestrator(rows)._build_recovery_data(_alert_window(rows))

    assert data.detector_name == "MADDetector"
    assert (data.confidence_lower, data.confidence_upper) == MAD_BAND


def test_recovery_band_is_ordering_independent():
    """Same incident, ids swapped → identical payload (no SQL-order dependence)."""
    payloads = []
    for mad_id, floor_id in (("a_mad", "z_floor"), ("z_mad", "a_floor")):
        rows = _scenario(mad_id=mad_id, floor_id=floor_id)
        data = _orchestrator(rows)._build_recovery_data(_alert_window(rows))
        payloads.append((data.detector_name, data.confidence_lower, data.confidence_upper))

    assert payloads[0] == payloads[1]


def test_should_send_recovery_end_to_end_picks_firing_detector():
    """The production entry point, not just the payload builder."""
    rows = _scenario(mad_id="a_mad", floor_id="z_floor")

    should_recover, data = _orchestrator(rows).should_send_recovery(_alert_window(rows))

    assert should_recover is True
    assert data.detector_name == "MADDetector"
    assert (data.confidence_lower, data.confidence_upper) == MAD_BAND
    assert data.detector_params == '{"threshold": 3.0}'
    # The incident span is still resolved (3 quorum points on the 10min grid).
    assert data.consecutive_count == 3
    assert data.onset_timestamp == np.datetime64("2026-08-17T10:40:00", "ms")


# --------------------------------------------------------------------------- #
# The mirror case: a one-sided firing detector keeps its own bound
# --------------------------------------------------------------------------- #
def test_one_sided_firing_detector_keeps_its_own_bound():
    """When the FLOOR fires, the message must clear with ">= 30.00".

    Mirror of the bug: the MAD detector's id sorts last and carries a two-sided
    band, so ``detections[-1]`` showed the MAD band for a floor-driven incident.
    The MAD anomaly in the window is an ``up`` one, which the ``direction:
    down`` policy excludes from the quorum — so the floor is unambiguously the
    firing detector.
    """
    rows = [
        _row("2026-08-17T11:20:00", [_mad("z_mad"), _floor("a_floor")], 287.0),
        _row("2026-08-17T11:10:00", [_mad("z_mad"), _floor("a_floor")], 281.0),
        _row("2026-08-17T11:00:00", [_mad("z_mad"), _floor("a_floor", True)], 12.0),
        _row("2026-08-17T10:50:00", [_mad("z_mad"), _floor("a_floor", True)], 11.0),
    ]

    data = _orchestrator(rows)._build_recovery_data(_alert_window(rows))

    assert data.detector_name == "ManualBoundsDetector"
    assert data.confidence_lower == FLOOR
    assert data.confidence_upper is None
    # A one-sided band is a band: it must not inherit another detector's numbers.
    assert _context(data)["expected_range"] == f">= {FLOOR:.2f}"


# --------------------------------------------------------------------------- #
# Unchanged paths
# --------------------------------------------------------------------------- #
def test_single_detector_recovery_unchanged():
    """A single-detector metric resolves to the same record as before."""
    rows = [
        _row("2026-08-17T11:20:00", [_mad("only")], 287.0),
        _row("2026-08-17T11:10:00", [_mad("only")], 281.0),
        _row("2026-08-17T11:00:00", [_mad("only", True)], 193.0),
    ]

    data = _orchestrator(rows)._build_recovery_data(_alert_window(rows))

    assert data.detector_name == "MADDetector"
    assert (data.confidence_lower, data.confidence_upper) == MAD_BAND


def test_no_incident_to_walk_falls_back_to_anomalous_detector():
    """Direct-API path with no DB: anchor on the newest anomalous record."""
    rows = _scenario(mad_id="a_mad", floor_id="z_floor")
    # The whole history is passed in, so the MAD anomalies are visible here even
    # though there is no ``internal`` handle to reconstruct the incident from.
    data = _orchestrator(rows, internal=False)._build_recovery_data(hydrate_detection_records(rows))

    assert data.detector_name == "MADDetector"
    assert (data.confidence_lower, data.confidence_upper) == MAD_BAND
    assert data.consecutive_count == 0  # incident span unresolvable without a DB


def test_no_anomaly_anywhere_falls_back_to_latest_row():
    """Nothing to anchor on at all → ``detections[-1]``, exactly as before."""
    rows = [_row("2026-08-17T11:20:00", [_mad("a_mad"), _floor("z_floor")], 287.0)]
    window = hydrate_detection_records(rows)

    data = _orchestrator(rows, internal=False)._build_recovery_data(window)

    assert data.detector_name == window[-1].detector_name
