"""Supervised alert-rule sweep tests (issue #101, Part 1).

Covers the pure ``_fraction_fire`` semantics (latest-point gate, trailing-share
count, start-of-series denominator), the 2-D (window × share) sweep that ORs the
fraction rule with the chosen consecutive rule and adopts it only on a strictly
greater score, and the result → config-emitter plumbing (exact-seconds
``anomaly_window`` round-trip, run-id stability).
"""

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from detectkit.autotune import (
    ScoringMetric,
    TuneSettings,
    compute_run_id,
    emit_tuned_config,
    parse_incident_labels,
)
from detectkit.autotune.autotuner import AutoTuner, _fraction_fire
from detectkit.autotune.result import AutoTuneResult
from detectkit.config.metric_config import MetricConfig
from detectkit.core.interval import Interval

HOUR = 3600


def _hourly_ts(n):
    return np.array(
        [np.datetime64("2026-01-01T00:00:00", "ms") + np.timedelta64(i, "h") for i in range(n)],
        dtype="datetime64[ms]",
    )


def _dt_str(ts, i):
    ms = int(np.datetime64(ts[i], "ms").astype(np.int64))
    return (datetime(1970, 1, 1) + timedelta(milliseconds=ms)).strftime("%Y-%m-%d %H:%M:%S")


def _data(ts, values):
    return {
        "timestamp": ts,
        "value": values,
        "seasonality_data": np.array([], dtype=object),
        "seasonality_columns": [],
    }


def _tuner(ts, values, incident_spans, settings=None):
    labels = parse_incident_labels(
        {
            "incidents": [
                {"start": _dt_str(ts, a), "end": _dt_str(ts, b)} for a, b in incident_spans
            ]
        },
        interval_seconds=HOUR,
    )
    gt = labels.to_ground_truth(ts, HOUR)
    assert gt.mode.value == "supervised"
    return AutoTuner(
        metric_name="demo",
        data=_data(ts, values),
        ground_truth=gt,
        interval_seconds=HOUR,
        settings=settings or TuneSettings(metric=ScoringMetric.MCC),
    )


# ── _fraction_fire semantics ─────────────────────────────────────────────────


class TestFractionFire:
    def test_latest_point_gate(self):
        """A stale window never fires: the current point must itself be flagged."""
        flags = np.array([True, True, True, False], dtype=bool)
        out = _fraction_fire(flags, 4, 0.5)
        assert not out[3]  # 3/4 anomalous but latest clean → no fire

    def test_trailing_share_current_inclusive(self):
        flags = np.array([False, True, True, False, True], dtype=bool)
        out = _fraction_fire(flags, 4, 0.5)
        # index 2: trailing 4 slots hold 2 anomalies → 0.5 → fires
        assert out[2]
        # index 4: trailing 4 slots (1..4) hold 3 → fires
        assert out[4]
        # clean points never fire
        assert not out[0] and not out[3]

    def test_slots_before_series_count_in_denominator_only(self):
        """The window extends past the series start; missing slots make the
        rule harder to fire (pipeline missing-slot parity)."""
        flags = np.array([True, False, False, False], dtype=bool)
        assert not _fraction_fire(flags, 4, 0.5)[0]  # 1/4 < 0.5
        assert _fraction_fire(flags, 4, 0.25)[0]  # 1/4 >= 0.25

    def test_isolated_point_below_share_never_fires(self):
        flags = np.zeros(50, dtype=bool)
        flags[25] = True
        assert not _fraction_fire(flags, 6, 0.3).any()  # 1/6 < 0.3


# ── the 2-D sweep ────────────────────────────────────────────────────────────


def _diffuse_scenario():
    """Solid incident + diffuse (alternating) incident + isolated false flags.

    Isolated noise makes k=1 lose the 1-D sweep to k=2; k=2 misses the diffuse
    incident entirely; the OR-ed fraction rule catches its anomalous points
    without re-admitting the isolated noise — a strictly greater score.
    """
    n = 600
    ts = _hourly_ts(n)
    values = np.zeros(n)
    values[100:106] = 100.0  # incident A: 6 solid points
    diffuse = list(range(200, 224, 2))  # incident B: 12 alternating points in 200..223
    values[diffuse] = 100.0
    noise = list(range(300, 500, 4))  # 50 isolated unlabeled anomalies
    values[noise] = 100.0
    return ts, values, [(100, 105), (200, 223)]


class TestAlertRuleSweep:
    def test_fraction_pair_adopted_on_diffuse_incident(self):
        ts, values, spans = _diffuse_scenario()
        tuner = _tuner(ts, values, spans)

        choice = tuner._select_alert_window(
            "manual_bounds", {"lower_bound": -50.0, "upper_bound": 50.0}
        )

        assert choice is not None
        assert choice.consecutive_anomalies == 2  # k=2 suppresses the isolated noise
        assert choice.window_points in TuneSettings().alert_window_points_grid
        assert choice.min_anomaly_share in TuneSettings().alert_share_grid
        # The decision log names the composite rule.
        window_entries = [e for e in tuner.decision_log if e.stage == "window"]
        assert window_entries and "min_anomaly_share" in window_entries[-1].message

    def test_legacy_rule_kept_when_fraction_does_not_strictly_improve(self):
        """A clean solid incident is fully caught by consecutive=1; the OR-ed
        fraction rule can only equal that (fraction fires ⊆ flagged points), so
        the strict-> tie policy keeps the legacy-only rule."""
        n = 300
        ts = _hourly_ts(n)
        values = np.zeros(n)
        values[100:106] = 100.0
        tuner = _tuner(ts, values, [(100, 105)])

        choice = tuner._select_alert_window(
            "manual_bounds", {"lower_bound": -50.0, "upper_bound": 50.0}
        )

        assert choice is not None
        assert choice.consecutive_anomalies == 1
        assert choice.window_points is None
        assert choice.min_anomaly_share is None

    def test_unsupervised_returns_none(self):
        n = 300
        ts = _hourly_ts(n)
        values = np.zeros(n)
        labels = parse_incident_labels(None, interval_seconds=HOUR)
        gt = labels.to_ground_truth(ts, HOUR)
        tuner = AutoTuner(
            metric_name="demo",
            data=_data(ts, values),
            ground_truth=gt,
            interval_seconds=HOUR,
            settings=TuneSettings(),
        )
        assert (
            tuner._select_alert_window("manual_bounds", {"lower_bound": -50.0, "upper_bound": 50.0})
            is None
        )


# ── result plumbing + emission ───────────────────────────────────────────────


def _result(**overrides):
    base = dict(
        metric_name="demo",
        mode="supervised",
        scoring_metric="mcc",
        training_start=datetime(2026, 1, 1),
        training_end=datetime(2026, 2, 1),
        interval_seconds=HOUR,
        n_points=744,
        labels_summary={"intervals": 2, "points": 0, "positive_grid_points": 30},
        chosen_seasonality=None,
        chosen_detector_type="mad",
        chosen_detector_params={"threshold": 3.0, "window_size": 100},
        winning_detector_id="abc123def456",
        score=0.5,
        cv_per_fold=[0.5],
        cv_stability_penalty=0.0,
        consecutive_anomalies=2,
        candidate_detector_ids=["abc123def456"],
    )
    base.update(overrides)
    return AutoTuneResult(**base)


class TestEmission:
    def test_emitter_writes_the_pair_and_config_round_trips(self, tmp_path):
        result = _result(anomaly_window=f"{6 * HOUR}s", min_anomaly_share=0.3)
        orig = MetricConfig(
            name="demo",
            interval="1h",
            query="SELECT 1",
            alerting=[{"channels": ["slack"], "consecutive_anomalies": 3}],
        )
        out_path, text, _rid = emit_tuned_config(
            original_config=orig,
            original_path=Path("metrics/demo.yml"),
            result=result,
            project_root=Path("."),
        )
        written = tmp_path / out_path.name
        written.write_text(text)
        reparsed = MetricConfig.from_yaml_file(written)
        alert = reparsed.alerting[0]
        assert alert.anomaly_window == f"{6 * HOUR}s"
        assert alert.min_anomaly_share == 0.3
        assert alert.consecutive_anomalies == 2
        # Exact-seconds string → lossless points round-trip (the sweep unit).
        assert Interval(alert.anomaly_window).seconds // HOUR == 6

    def test_emitter_omits_the_pair_when_not_chosen(self, tmp_path):
        result = _result()
        orig = MetricConfig(
            name="demo",
            interval="1h",
            query="SELECT 1",
            alerting=[{"channels": ["slack"]}],
        )
        _out, text, _rid = emit_tuned_config(
            original_config=orig,
            original_path=Path("metrics/demo.yml"),
            result=result,
            project_root=Path("."),
        )
        assert "anomaly_window" not in text
        assert "min_anomaly_share" not in text

    def test_run_id_ignores_the_alert_rule(self):
        """Like consecutive_anomalies, the fraction pair is non-identity
        metadata: it must not change the deterministic run id."""
        plain = _result()
        with_pair = _result(anomaly_window=f"{6 * HOUR}s", min_anomaly_share=0.3)
        assert compute_run_id(plain) == compute_run_id(with_pair)
