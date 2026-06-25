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

import re
from dataclasses import dataclass, field
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
    label: str | None = None


@dataclass(frozen=True)
class IncidentPoint:
    """A single anomalous point, snapped to the nearest grid interval."""

    at: datetime
    label: str | None = None


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
    # Optional threshold-capture time window(s) painted in the labeler. Pure
    # metadata: it records the regime scope the user reasoned about (auditable in
    # the saved file, restored on reopen); it does NOT affect ground truth.
    capture_windows: list[tuple[datetime, datetime]] = field(default_factory=list)

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
        tolerance_ms = interval_seconds * 1000
        for interval in self.intervals:
            start_ms = np.datetime64(interval.start, "ms").astype(np.int64)
            end_ms = np.datetime64(interval.end, "ms").astype(np.int64)
            if start_ms == end_ms:
                # A degenerate interval (start == end) is a point — snap to the
                # nearest grid timestamp within one interval, like the point loop
                # below. This keeps an off-grid point that round-trips through the
                # labeler as {start: T, end: T} from silently matching nothing.
                idx = int(np.argmin(np.abs(ts_ms - start_ms)))
                if abs(int(ts_ms[idx]) - int(start_ms)) <= tolerance_ms:
                    y[idx] = True
            else:
                y |= (ts_ms >= start_ms) & (ts_ms <= end_ms)

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

    raw_windows: list = []
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
        raw_windows = raw.get("capture_windows") or []
        if not isinstance(raw_windows, list):
            raise ValueError("'capture_windows' must be a list")
    else:
        raise ValueError("Labels must be a mapping with 'incidents' or a list of incidents")

    intervals: list[IncidentInterval] = []
    points: list[IncidentPoint] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(f"Each incident must be a mapping, got {type(entry).__name__}")
        raw_label = entry.get("label")
        label = str(raw_label) if raw_label is not None else None
        if "at" in entry:
            points.append(IncidentPoint(at=_parse_dt(entry["at"], tz), label=label))
        elif "start" in entry and "end" in entry:
            start = _parse_dt(entry["start"], tz)
            end = _parse_dt(entry["end"], tz)
            if start > end:
                raise ValueError(f"Incident start {start} is after end {end}")
            intervals.append(IncidentInterval(start=start, end=end, label=label))
        else:
            raise ValueError(
                "Each incident needs either 'at' (a point) or 'start'+'end' (an interval)"
            )

    capture_windows: list[tuple[datetime, datetime]] = []
    for win in raw_windows:
        if not isinstance(win, dict) or "start" not in win or "end" not in win:
            raise ValueError("Each capture_windows entry needs 'start' and 'end'")
        ws, we = _parse_dt(win["start"], tz), _parse_dt(win["end"], tz)
        if ws > we:
            raise ValueError(f"Capture window start {ws} is after end {we}")
        capture_windows.append((ws, we))

    return IncidentLabels(intervals=intervals, points=points, capture_windows=capture_windows)


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


_DISPLAY_FMT = "%Y-%m-%d %H:%M:%S"


def incidents_to_display(labels: IncidentLabels) -> list[dict[str, str]]:
    """Render parsed labels as labeler display dicts (naive-UTC strings).

    Each is ``{"start", "end", "label"}`` in ``"YYYY-MM-DD HH:MM:SS"``; a point
    becomes a degenerate span with ``start == end``. Used to seed the HTML labeler
    when editing an existing labels file.
    """
    out: list[dict[str, str]] = []
    for iv in labels.intervals:
        out.append(
            {
                "start": iv.start.strftime(_DISPLAY_FMT),
                "end": iv.end.strftime(_DISPLAY_FMT),
                "label": iv.label or "",
            }
        )
    for p in labels.points:
        at = p.at.strftime(_DISPLAY_FMT)
        out.append({"start": at, "end": at, "label": p.label or ""})
    return out


def load_incidents_for_display(
    path: str | Path,
    *,
    interval_seconds: int,
    metric_name: str | None = None,
) -> list[dict[str, str]]:
    """Load a canonical labels file and render it as labeler display dicts."""
    labels = parse_labels_file(path, interval_seconds=interval_seconds, metric_name=metric_name)
    return incidents_to_display(labels)


def capture_windows_to_display(labels: IncidentLabels) -> list[dict[str, str]]:
    """Render parsed capture windows as labeler display dicts (naive-UTC strings)."""
    return [
        {"start": start.strftime(_DISPLAY_FMT), "end": end.strftime(_DISPLAY_FMT)}
        for start, end in labels.capture_windows
    ]


def load_capture_windows(
    path: str | Path,
    *,
    interval_seconds: int,
    metric_name: str | None = None,
) -> list[dict[str, str]]:
    """Load a labels file and render its capture windows as labeler display dicts."""
    labels = parse_labels_file(path, interval_seconds=interval_seconds, metric_name=metric_name)
    return capture_windows_to_display(labels)


# Versioned labels store helpers (shared by the autotune labeler server and the
# `dtk tune` labeler so both name + discover files the same way).
_LABELS_GLOBS = ("*.yml", "*.yaml", "*.json")
_NAME_RE = re.compile(r"[^a-z0-9_-]+")


def newest_labels_file(directory: str | Path) -> Path | None:
    """Newest versioned labels file in *directory* (``None`` if empty/absent).

    Versioned names (``<metric>[-<set>]-<UTCstamp>.yml``) sort chronologically by
    name; mtime tie-breaks.
    """
    d = Path(directory)
    if not d.is_dir():
        return None
    files: list[Path] = []
    for pattern in _LABELS_GLOBS:
        files.extend(d.glob(pattern))
    if not files:
        return None
    return sorted(files, key=lambda p: (p.name, p.stat().st_mtime))[-1]


def sanitize_label_set_name(name: str) -> str:
    """Filesystem-safe slug for an optional label-set name (``""`` when blank)."""
    return _NAME_RE.sub("-", name.strip().lower()).strip("-")


def versioned_labels_path(incidents_dir: str | Path, metric: str, name: str = "") -> Path:
    """Versioned labels path ``<metric>[-<slug>]-<UTCstamp>.yml`` in *incidents_dir*.

    The single source of the labels filename convention: the optional set *name*
    is sanitized to a suffix, blank → just the metric name.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    slug = sanitize_label_set_name(name)
    stem = f"{metric}-{slug}" if slug else metric
    return Path(incidents_dir) / f"{stem}-{stamp}.yml"
