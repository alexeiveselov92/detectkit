"""Unit tests for detectkit.ui.overview (the ``GET /api/overview`` payload builder).

Mirrors the fake-manager style of ``tests/unit/test_report.py`` / the
``_StubManager`` in ``tests/unit/test_tune_server.py``: a small in-memory stand-in
for ``InternalTablesManager`` that honors the real half-open ``[from, to)``
filtering so the tests exercise the same window math the server uses.

Detection rows are always *dense* (one row per point per detector, matching
what the real pipeline writes to ``_dtk_detections``) — a sparse feed (rows only
at the anomalous points) would make ``AlertOrchestrator.replay`` treat the last
seen row as "still current" for every remaining grid step and re-fire forever,
which is not how the real detection stream behaves.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

import detectkit.ui.overview as overview_mod
from detectkit.config.metric_config import AlertConfig, DetectorConfig, MetricConfig
from detectkit.config.project_config import ProjectConfig
from detectkit.detectors.factory import DetectorFactory
from detectkit.ui.overview import build_overview_payload


def _detector_id_for(dtype: str, params: dict | None = None) -> str:
    """The real detector id the metric's config derives (the overview reads
    only the currently-configured ids — stub rows must carry matching ids)."""
    return DetectorFactory.create_from_config(
        {"type": dtype, "params": params or {}}
    ).get_detector_id()


INTERVAL_S = 3600


def _times(base: datetime, n: int, interval_s: int = INTERVAL_S) -> list[datetime]:
    return [base + timedelta(seconds=i * interval_s) for i in range(n)]


def _ts_array(times: list[datetime]) -> np.ndarray:
    return np.array([np.datetime64(t, "ms") for t in times])


def _ms(dt: datetime) -> int:
    return int(np.datetime64(dt, "ms").astype("int64"))


def _dense_rows(
    times: list[datetime],
    detector_id: str,
    detector_name: str,
    anomalies: dict[int, str],
) -> list[dict]:
    """One detection row per timestamp; ``anomalies`` maps index -> direction
    (``"above"``/``"below"``) for the anomalous points, all others normal."""
    rows = []
    for i, ts in enumerate(times):
        is_anom = i in anomalies
        meta = {"direction": anomalies[i], "severity": 6.0} if is_anom else {}
        rows.append(
            {
                "timestamp": ts,
                "detector_id": detector_id,
                "detector_name": detector_name,
                "is_anomaly": is_anom,
                "confidence_lower": 90.0,
                "confidence_upper": 110.0,
                "value": 100.0,
                "detection_metadata": meta,
            }
        )
    return rows


class _StubManager:
    """Minimal InternalTablesManager stand-in — one series per metric name.

    ``load_datapoints``/``load_detections`` honor real ``[from, to)``
    half-open filtering (numpy comparison for datapoints, plain-datetime
    comparison for detections, matching how the real rows are shaped).
    """

    def __init__(self) -> None:
        self._series: dict[str, dict] = {}
        self._detections: dict[str, list[dict]] = {}
        self._last: dict[str, datetime | None] = {}
        self._first: dict[str, datetime | None] = {}
        self._locked: set[str] = set()
        self._raises: set[str] = set()

    def add_metric(
        self,
        name: str,
        *,
        ts: np.ndarray,
        val: np.ndarray,
        last: datetime | None,
        first: datetime | None,
        det_rows: list[dict],
    ) -> None:
        self._series[name] = {
            "timestamp": ts,
            "value": val,
            "seasonality_data": np.array(["{}"] * len(ts), dtype=object),
            "seasonality_columns": [],
        }
        self._detections[name] = det_rows
        self._last[name] = last
        self._first[name] = first

    def set_locked(self, name: str) -> None:
        self._locked.add(name)

    def set_raises(self, name: str) -> None:
        self._raises.add(name)

    def get_last_datapoint_timestamp(self, metric_name: str) -> datetime | None:
        if metric_name in self._raises:
            raise RuntimeError("boom")
        return self._last.get(metric_name)

    def get_first_datapoint_timestamp(self, metric_name: str) -> datetime | None:
        return self._first.get(metric_name)

    def check_lock(
        self, metric_name: str, detector_id: str, process_type: str
    ) -> dict | None:  # noqa: ARG002
        return {"status": "running"} if metric_name in self._locked else None

    def load_datapoints(
        self,
        metric_name: str,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
    ) -> dict:
        data = self._series.get(metric_name)
        if data is None:
            return {
                "timestamp": np.array([], dtype="datetime64[ms]"),
                "value": np.array([], dtype=np.float64),
                "seasonality_data": np.array([], dtype=object),
                "seasonality_columns": [],
            }
        ts = data["timestamp"]
        mask = np.ones(len(ts), dtype=bool)
        if from_timestamp is not None:
            mask &= ts >= np.datetime64(from_timestamp, "ms")
        if to_timestamp is not None:
            mask &= ts < np.datetime64(to_timestamp, "ms")
        return {
            "timestamp": ts[mask],
            "value": data["value"][mask],
            "seasonality_data": data["seasonality_data"][mask],
            "seasonality_columns": data["seasonality_columns"],
        }

    def load_detections(
        self,
        metric_name: str,
        detector_id: str | None = None,
        from_timestamp: datetime | None = None,
        to_timestamp: datetime | None = None,
    ) -> list[dict]:
        rows = self._detections.get(metric_name, [])
        out = []
        for r in rows:
            ts = r["timestamp"]
            if detector_id is not None and r["detector_id"] != detector_id:
                continue
            if from_timestamp is not None and ts < from_timestamp:
                continue
            if to_timestamp is not None and ts >= to_timestamp:
                continue
            out.append(r)
        return out


def _project_config(**kwargs: object) -> ProjectConfig:
    return ProjectConfig(name="proj", default_profile="p", **kwargs)  # type: ignore[arg-type]


# ── (a) alert counting, per_day, spark bucketing + union-flagged counting ────


def test_a_alert_counts_per_day_spark_union_flagged(tmp_path):
    now = datetime(2026, 3, 8, 0, 0, 0)
    n = 169  # 7 days hourly, inclusive of both ends -> > 160, exercises bucketing
    base = now - timedelta(hours=n - 1)
    times = _times(base, n)
    ts_arr = _ts_array(times)
    val_arr = np.full(n, 100.0)

    # Two detectors: both anomalous at idx 100 (union must count that timestamp
    # once), only "mad" anomalous at idx 101 -> a grid-adjacent 2-point streak
    # that trips consecutive_anomalies=2.
    det_rows = _dense_rows(
        times, _detector_id_for("mad"), "MADDetector", {100: "above", 101: "above"}
    )
    det_rows += _dense_rows(times, _detector_id_for("zscore"), "ZScoreDetector", {100: "above"})

    stub = _StubManager()
    stub.add_metric("checkouts", ts=ts_arr, val=val_arr, last=now, first=base, det_rows=det_rows)

    config = MetricConfig(
        name="checkouts",
        interval="1h",
        query="SELECT 1",
        detectors=[DetectorConfig(type="mad"), DetectorConfig(type="zscore")],
        alerting=[
            AlertConfig(
                channels=["slack"], min_detectors=1, direction="any", consecutive_anomalies=2
            )
        ],
    )
    payload = build_overview_payload(
        project_config=_project_config(),
        project_root=tmp_path,
        metrics=[(tmp_path / "metrics" / "checkouts.yml", config)],
        internal=stub,
        window_preset="7d",
        now=now,
    )
    assert payload["window"] == {"preset": "7d", "days": 7}
    row = payload["metrics"][0]
    assert row["error"] is None
    assert row["detectors"] == ["mad", "zscore"]
    assert row["alert_rule"] == {
        "configs": 1,
        "enabled": 1,
        "min_detectors": 1,
        "direction": "any",
        "consecutive": 2,
    }
    assert row["points"] == n
    # Union across detectors: 3 anomalous rows, 2 distinct anomalous timestamps.
    assert row["flagged"] == 2
    assert row["anomaly_rate"] == pytest.approx(2 / n)
    assert row["alerts"]["anomaly"] == 1
    assert row["alerts"]["recovery"] == 0
    assert row["alerts"]["per_day"] == pytest.approx(1 / 7.0)
    assert row["alerts"]["last_ts"] == _ms(times[101])
    # Spark is bucketed to <= 160 entries even though the window has 169 points.
    assert 0 < len(row["spark"]) <= 160
    assert len(row["spark"]) == 85  # ceil(169/160) = step 2 -> ceil(169/2) buckets
    assert row["spark_anoms"] == [_ms(times[100]), _ms(times[101])]
    assert row["last_point"] == _ms(now)
    assert row["lag_seconds"] == 0.0
    assert row["locked"] is False
    assert row["quality"] is None


def test_stale_detector_generations_are_excluded(tmp_path):
    """Rows persisted under superseded detector ids (pre-retune generations)
    must not inflate flagged counts or replayed alerts; a metric with no
    configured detectors falls back to the unfiltered read."""
    now = datetime(2026, 3, 2, 0, 0, 0)
    n = 25
    base = now - timedelta(hours=n - 1)
    times = _times(base, n)
    ts_arr = _ts_array(times)
    val_arr = np.full(n, 100.0)

    # Current config: mad, one anomalous point. A dead generation ("stale123")
    # is anomalous EVERYWHERE — unfiltered it would fire on every timestamp.
    det_rows = _dense_rows(times, _detector_id_for("mad"), "MADDetector", {10: "above"})
    det_rows += _dense_rows(times, "stale123", "MADDetector", dict.fromkeys(range(n), "above"))

    stub = _StubManager()
    stub.add_metric("tuned_often", ts=ts_arr, val=val_arr, last=now, first=base, det_rows=det_rows)

    config = MetricConfig(
        name="tuned_often",
        interval="1h",
        query="SELECT 1",
        detectors=[DetectorConfig(type="mad")],
        alerting=[
            AlertConfig(
                channels=["slack"], min_detectors=1, direction="any", consecutive_anomalies=1
            )
        ],
    )
    payload = build_overview_payload(
        project_config=_project_config(),
        project_root=tmp_path,
        metrics=[(tmp_path / "metrics" / "tuned_often.yml", config)],
        internal=stub,
        window_preset="24h",
        now=now,
    )
    row = payload["metrics"][0]
    assert row["error"] is None
    assert row["flagged"] == 1  # only the live generation's anomaly
    assert row["alerts"]["anomaly"] == 1
    assert row["spark_anoms"] == [_ms(times[10])]

    # No configured detectors -> unfiltered fallback still sees stored rows.
    bare = MetricConfig(
        name="tuned_often",
        interval="1h",
        query="SELECT 1",
        alerting=[
            AlertConfig(
                channels=["slack"], min_detectors=1, direction="any", consecutive_anomalies=1
            )
        ],
    )
    payload = build_overview_payload(
        project_config=_project_config(),
        project_root=tmp_path,
        metrics=[(tmp_path / "metrics" / "tuned_often.yml", bare)],
        internal=stub,
        window_preset="24h",
        now=now,
    )
    assert payload["metrics"][0]["flagged"] == n  # stale rows visible again


# ── (b) no-data events when no_data_alert is on and values are missing ───────


def test_b_no_data_events_counted(tmp_path):
    now = datetime(2026, 4, 1, 0, 0, 0)
    n = 25  # 24h window inclusive of both ends
    base = now - timedelta(hours=n - 1)
    times = _times(base, n)
    ts_arr = _ts_array(times)
    val_arr = np.full(n, 50.0)
    val_arr[5] = np.nan
    val_arr[15] = np.nan

    stub = _StubManager()
    stub.add_metric("billing", ts=ts_arr, val=val_arr, last=now, first=base, det_rows=[])

    config = MetricConfig(
        name="billing",
        interval="1h",
        query="SELECT 1",
        alerting=[
            AlertConfig(
                channels=["slack"], no_data_alert=True, min_detectors=1, consecutive_anomalies=1
            )
        ],
    )
    payload = build_overview_payload(
        project_config=_project_config(),
        project_root=tmp_path,
        metrics=[(tmp_path / "metrics" / "billing.yml", config)],
        internal=stub,
        window_preset="24h",
        now=now,
    )
    row = payload["metrics"][0]
    assert row["error"] is None
    assert row["alerts"]["no_data"] == 2
    assert row["alerts"]["anomaly"] == 0


# ── (c) labels file -> recall / fdr / reviewed per the overlap rules ─────────


def test_c_quality_recall_fdr_reviewed(tmp_path):
    base = datetime(2026, 5, 1, 0, 0, 0)
    now = base + timedelta(hours=24)
    n = 25
    times = _times(base, n)
    ts_arr = _ts_array(times)
    val_arr = np.full(n, 10.0)

    idx_caught, idx_valid_reviewed, idx_false = 5, 12, 19
    idx_missed = 2
    det_rows = _dense_rows(
        times,
        _detector_id_for("mad"),
        "MADDetector",
        {idx_caught: "above", idx_valid_reviewed: "above", idx_false: "above"},
    )

    stub = _StubManager()
    stub.add_metric("signups", ts=ts_arr, val=val_arr, last=now, first=base, det_rows=det_rows)

    config = MetricConfig(
        name="signups",
        interval="1h",
        query="SELECT 1",
        detectors=[DetectorConfig(type="mad")],
        alerting=[
            AlertConfig(
                channels=["slack"], min_detectors=1, direction="any", consecutive_anomalies=1
            )
        ],
    )

    inc_dir = tmp_path / "incidents" / "signups"
    inc_dir.mkdir(parents=True)
    fmt = "%Y-%m-%d %H:%M:%S"
    labels_yaml = f"""metric: signups
timezone: UTC
incidents:
  - {{start: "{times[idx_caught].strftime(fmt)}", end: "{times[idx_caught].strftime(fmt)}"}}
  - {{start: "{times[idx_missed].strftime(fmt)}", end: "{times[idx_missed].strftime(fmt)}"}}
alert_reviews:
  - {{start: "{times[idx_valid_reviewed].strftime(fmt)}", end: "{times[idx_valid_reviewed].strftime(fmt)}", verdict: valid}}
"""
    labels_path = inc_dir / "signups-20260101T000000Z.yml"
    labels_path.write_text(labels_yaml, encoding="utf-8")

    payload = build_overview_payload(
        project_config=_project_config(),
        project_root=tmp_path,
        metrics=[(tmp_path / "metrics" / "signups.yml", config)],
        internal=stub,
        window_preset="24h",
        now=now,
    )
    row = payload["metrics"][0]
    assert row["error"] is None
    assert row["alerts"]["anomaly"] == 3  # one isolated alert per anomalous point

    q = row["quality"]
    assert q is not None
    assert q["incidents"] == 2
    assert q["incidents_in_window"] == 2
    assert q["caught"] == 1  # idx_caught only; idx_missed is never overlapped
    assert q["recall"] == pytest.approx(0.5)
    assert q["false_alerts"] == 1  # idx_false: no incident overlap, no valid review
    assert q["fdr"] == pytest.approx(1 / 3)
    assert q["reviewed"] == 1
    assert q["reviewed_valid"] == 1
    assert q["reviewed_false"] == 0
    assert q["labels_file"] == "incidents/signups/signups-20260101T000000Z.yml"


# ── (d) zero datapoints -> row present, error null, stats null/0 ────────────


def test_d_zero_datapoints_row_present_with_defaults(tmp_path):
    stub = _StubManager()
    stub.add_metric(
        "nodata_yet",
        ts=np.array([], dtype="datetime64[ms]"),
        val=np.array([], dtype=np.float64),
        last=None,
        first=None,
        det_rows=[],
    )

    config = MetricConfig(name="nodata_yet", interval="1h", query="SELECT 1")
    payload = build_overview_payload(
        project_config=_project_config(),
        project_root=tmp_path,
        metrics=[(tmp_path / "metrics" / "nodata_yet.yml", config)],
        internal=stub,
        window_preset="7d",
        now=datetime(2026, 1, 1),
    )
    row = payload["metrics"][0]
    assert row["error"] is None
    assert row["last_point"] is None
    assert row["lag_seconds"] is None
    assert row["points"] == 0
    assert row["flagged"] == 0
    assert row["anomaly_rate"] is None
    assert row["alerts"] == {
        "anomaly": 0,
        "recovery": 0,
        "no_data": 0,
        "per_day": None,
        "last_ts": None,
    }
    assert row["quality"] is None
    assert row["spark"] == []
    assert row["spark_anoms"] == []
    assert row["locked"] is False


# ── (e) a stub failure is isolated to its own row ────────────────────────────


def test_e_metric_failure_isolated_others_unaffected(tmp_path):
    now = datetime(2026, 1, 10, 0, 0, 0)
    good_times = _times(now - timedelta(hours=5), 6)

    stub = _StubManager()
    stub.add_metric(
        "good_metric",
        ts=_ts_array(good_times),
        val=np.full(6, 1.0),
        last=now,
        first=good_times[0],
        det_rows=[],
    )
    stub.add_metric(
        "bad_metric",
        ts=np.array([], dtype="datetime64[ms]"),
        val=np.array([], dtype=np.float64),
        last=None,
        first=None,
        det_rows=[],
    )
    stub.set_raises("bad_metric")

    metrics = [
        (
            tmp_path / "metrics" / "good_metric.yml",
            MetricConfig(name="good_metric", interval="1h", query="SELECT 1"),
        ),
        (
            tmp_path / "metrics" / "bad_metric.yml",
            MetricConfig(name="bad_metric", interval="1h", query="SELECT 1"),
        ),
    ]
    payload = build_overview_payload(
        project_config=_project_config(),
        project_root=tmp_path,
        metrics=metrics,
        internal=stub,
        window_preset="7d",
        now=now,
    )
    assert len(payload["metrics"]) == 2
    rows = {r["name"]: r for r in payload["metrics"]}
    assert rows["bad_metric"]["error"] is not None
    assert "RuntimeError" in rows["bad_metric"]["error"]
    assert rows["good_metric"]["error"] is None
    assert rows["good_metric"]["last_point"] == _ms(now)
    assert rows["good_metric"]["points"] == 6


# ── (f) a disabled metric is flagged, not skipped ────────────────────────────


def test_f_disabled_metric_row_flagged_but_still_computed(tmp_path):
    now = datetime(2026, 2, 1, 0, 0, 0)
    times = _times(now - timedelta(hours=5), 6)

    stub = _StubManager()
    stub.add_metric(
        "legacy", ts=_ts_array(times), val=np.full(6, 3.0), last=now, first=times[0], det_rows=[]
    )

    config = MetricConfig(name="legacy", interval="1h", query="SELECT 1", enabled=False)
    payload = build_overview_payload(
        project_config=_project_config(),
        project_root=tmp_path,
        metrics=[(tmp_path / "metrics" / "legacy.yml", config)],
        internal=stub,
        window_preset="7d",
        now=now,
    )
    row = payload["metrics"][0]
    assert row["enabled"] is False
    assert row["error"] is None
    assert row["points"] == 6  # disabled only flags the row, doesn't blank stats


# ── (g) window preset math: fixed presets vs the bounded "all" lookback ─────


def test_g_window_preset_math_fixed_vs_all_capped(monkeypatch):
    stub = _StubManager()
    end = datetime(2026, 6, 10, 5, 0, 0)
    now = end + timedelta(hours=3)

    stub.add_metric(
        "far_history",
        ts=np.array([], dtype="datetime64[ms]"),
        val=np.array([], dtype=np.float64),
        last=end,
        first=datetime(2020, 1, 1),
        det_rows=[],
    )
    stub.add_metric(
        "short_history",
        ts=np.array([], dtype="datetime64[ms]"),
        val=np.array([], dtype=np.float64),
        last=end,
        first=end - timedelta(seconds=INTERVAL_S * 2),
        det_rows=[],
    )
    stub.add_metric(
        "no_first",
        ts=np.array([], dtype="datetime64[ms]"),
        val=np.array([], dtype=np.float64),
        last=end,
        first=None,
        det_rows=[],
    )

    # Fixed preset: start = now - preset_days, end = last datapoint (NOT now).
    start, resolved_end = overview_mod._resolve_metric_window(
        stub, "far_history", INTERVAL_S, "24h", now
    )
    assert resolved_end == end
    assert start == now - timedelta(days=1)

    # "all", capped: history goes back to 2020 but MAX_STAT_POINTS bounds the
    # lookback to a handful of intervals before the last datapoint.
    monkeypatch.setattr(overview_mod, "MAX_STAT_POINTS", 5)
    start_far, end_far = overview_mod._resolve_metric_window(
        stub, "far_history", INTERVAL_S, "all", now
    )
    assert end_far == end
    assert start_far == end - timedelta(seconds=INTERVAL_S * 5)

    # "all", not capped: history is shorter than the cap -> start = first datapoint.
    start_short, _ = overview_mod._resolve_metric_window(
        stub, "short_history", INTERVAL_S, "all", now
    )
    assert start_short == end - timedelta(seconds=INTERVAL_S * 2)

    # "all", no first datapoint at all -> pure lookback from the cap.
    start_no_first, _ = overview_mod._resolve_metric_window(
        stub, "no_first", INTERVAL_S, "all", now
    )
    assert start_no_first == end - timedelta(seconds=INTERVAL_S * 5)


def test_unknown_window_preset_raises(tmp_path):
    with pytest.raises(ValueError):
        build_overview_payload(
            project_config=_project_config(),
            project_root=tmp_path,
            metrics=[],
            internal=_StubManager(),
            window_preset="bogus",
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
