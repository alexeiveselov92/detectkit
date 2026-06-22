"""Incident labels: parse the canonical labels file and align it to the grid.

The canonical labels file (YAML or JSON) marks known incidents so the tuner
can score detectors against ground truth::

    metric: api_error_rate        # optional; must match the tuned metric
    timezone: UTC                 # optional; interprets the naive times below
    incidents:
      - {start: "2026-05-02 14:00:00", end: "2026-05-02 16:30:00"}   # interval
      - {at: "2026-05-11 09:05:00"}                                  # point

When no labels are supplied the tuner falls back to unsupervised mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from detectkit.autotune._types import TuneMode
from detectkit.utils.datetime_utils import to_naive_utc

_DT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


@dataclass(frozen=True)
class IncidentInterval:
    """A sustained incident over ``[start, end]`` (inclusive), naive UTC."""

    start: datetime
    end: datetime


@dataclass(frozen=True)
class IncidentPoint:
    """A single anomalous point, snapped to the nearest grid interval."""

    at: datetime


@dataclass
class GroundTruth:
    """Per-timestamp boolean labels aligned 1:1 with the loaded series."""

    y_true: np.ndarray
    mode: TuneMode
    n_positive: int
    n_intervals: int
    n_points: int


@dataclass
class IncidentLabels:
    """Parsed incident windows + points (naive UTC)."""

    intervals: list[IncidentInterval]
    points: list[IncidentPoint]

    def is_empty(self) -> bool:
        return not self.intervals and not self.points

    def to_ground_truth(self, timestamps: np.ndarray, interval_seconds: int) -> GroundTruth:
        """Project labels onto the series grid.

        Intervals mark every grid point inside ``[start, end]``; points snap to
        the nearest grid timestamp (within one interval, else dropped). With no
        positive grid points the mode is unsupervised.
        """
        n = int(len(timestamps))
        y = np.zeros(n, dtype=bool)
        if n == 0:
            return GroundTruth(y, TuneMode.UNSUPERVISED, 0, len(self.intervals), len(self.points))

        ts_ms = timestamps.astype("datetime64[ms]").astype(np.int64)
        for interval in self.intervals:
            start_ms = np.datetime64(interval.start, "ms").astype(np.int64)
            end_ms = np.datetime64(interval.end, "ms").astype(np.int64)
            y |= (ts_ms >= start_ms) & (ts_ms <= end_ms)

        tolerance_ms = interval_seconds * 1000
        for point in self.points:
            at_ms = np.datetime64(point.at, "ms").astype(np.int64)
            idx = int(np.argmin(np.abs(ts_ms - at_ms)))
            if abs(int(ts_ms[idx]) - int(at_ms)) <= tolerance_ms:
                y[idx] = True

        mode = TuneMode.UNSUPERVISED if not y.any() else TuneMode.SUPERVISED
        return GroundTruth(
            y_true=y,
            mode=mode,
            n_positive=int(y.sum()),
            n_intervals=len(self.intervals),
            n_points=len(self.points),
        )


def _parse_dt_string(text: str) -> datetime:
    """Parse a timestamp string in one of the accepted formats, or raise."""
    for fmt in _DT_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(
        f"Invalid incident timestamp: {text!r}. "
        f"Use 'YYYY-MM-DD HH:MM:SS' or 'YYYY-MM-DD' (UTC)."
    )


def _parse_dt(raw: Any, tz: ZoneInfo | None) -> datetime:
    """Parse a timestamp string/datetime to naive UTC."""
    dt: datetime = raw if isinstance(raw, datetime) else _parse_dt_string(str(raw).strip())
    if tz is not None and dt.tzinfo is None:
        # Localize to the declared zone, then convert the offset to UTC
        # (to_naive_utc only strips tzinfo; it does not shift the clock).
        dt = dt.replace(tzinfo=tz).astimezone(timezone.utc)
    result = to_naive_utc(dt)
    assert result is not None  # dt is never None here
    return result


def parse_incident_labels(
    raw: Any,
    *,
    interval_seconds: int,
    metric_name: str | None = None,
) -> IncidentLabels:
    """Parse a labels mapping (or bare incident list) into :class:`IncidentLabels`.

    Args:
        raw: A mapping with an ``incidents`` list (and optional ``metric`` /
            ``timezone``), or a bare list of incident entries, or ``None``.
        interval_seconds: Metric interval (used only for messages here).
        metric_name: If given and the file declares ``metric``, they must match.
    """
    if raw is None:
        return IncidentLabels([], [])

    if isinstance(raw, list):
        entries = raw
        tz: ZoneInfo | None = None
    elif isinstance(raw, dict):
        declared = raw.get("metric")
        if declared is not None and metric_name is not None and declared != metric_name:
            raise ValueError(f"Labels file is for metric '{declared}', not '{metric_name}'")
        tz_name = raw.get("timezone")
        tz = ZoneInfo(tz_name) if tz_name and tz_name != "UTC" else None
        entries = raw.get("incidents", [])
        if not isinstance(entries, list):
            raise ValueError("'incidents' must be a list")
    else:
        raise ValueError("Labels must be a mapping with 'incidents' or a list of incidents")

    intervals: list[IncidentInterval] = []
    points: list[IncidentPoint] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"Each incident must be a mapping, got {type(entry).__name__}")
        if "at" in entry:
            points.append(IncidentPoint(at=_parse_dt(entry["at"], tz)))
        elif "start" in entry and "end" in entry:
            start = _parse_dt(entry["start"], tz)
            end = _parse_dt(entry["end"], tz)
            if start > end:
                raise ValueError(f"Incident start {start} is after end {end}")
            intervals.append(IncidentInterval(start=start, end=end))
        else:
            raise ValueError(
                "Each incident needs either 'at' (a point) or 'start'+'end' (an interval)"
            )

    return IncidentLabels(intervals=intervals, points=points)


def parse_labels_file(
    path: str | Path,
    *,
    interval_seconds: int,
    metric_name: str | None = None,
) -> IncidentLabels:
    """Load and parse a canonical labels file (YAML or JSON, by content)."""
    import yaml

    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Labels file not found: {file_path}")
    with open(file_path) as f:
        raw = yaml.safe_load(f)
    if raw is None:
        raise ValueError(f"Empty labels file: {file_path}")
    return parse_incident_labels(raw, interval_seconds=interval_seconds, metric_name=metric_name)
