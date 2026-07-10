"""Public-dataset loaders for the detectkit benchmark harness.

Three providers, each returning a ``list[LabeledSeries]``:

- :func:`load_nab` — the Numenta Anomaly Benchmark (MIT-licensed, downloadable
  via :func:`download_nab`).
- :func:`load_yahoo` — Yahoo S5 (Webscope), license-gated: the user requests
  the dataset from Yahoo and points ``--yahoo-dir`` at the extracted folder.
- :func:`load_synthetic` — a deterministic, offline smoke set requiring no
  network access, used for quick sanity checks of the harness itself.

Series hygiene shared by all loaders: sort by timestamp, drop duplicate
timestamps, coerce values to float64, and reindex onto the regular grid
inferred from the median step (gaps become NaN) — mirroring detectkit's own
gap-filled loader contract (``detectkit/loaders/metric_loader.py``).
"""

from __future__ import annotations

import csv
import json
import logging
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

NAB_ZIP_URL = "https://github.com/numenta/NAB/archive/refs/heads/master.zip"

# Synthetic-dataset shape constants (see load_synthetic).
_SYNTH_N_POINTS = 2000
_SYNTH_STEP_MINUTES = 5


@dataclass
class LabeledSeries:
    """One labeled time series ready for detector evaluation."""

    name: str
    dataset: str
    timestamps: np.ndarray  # datetime64[ms]
    values: np.ndarray  # float64, may contain NaN (gap-filled grid)
    y_true: np.ndarray  # bool


# ---------------------------------------------------------------------------
# Shared hygiene: sort/dedup/coerce + regrid onto a regular time grid.
# ---------------------------------------------------------------------------


def _sort_dedup_coerce(
    timestamps: np.ndarray, values: np.ndarray, y_true: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ts = np.asarray(timestamps, dtype="datetime64[ms]")
    vals = np.asarray(values, dtype=np.float64)
    yt = np.asarray(y_true, dtype=bool)

    order = np.argsort(ts, kind="mergesort")
    ts, vals, yt = ts[order], vals[order], yt[order]

    # Keep the first occurrence of each timestamp.
    _, first_idx = np.unique(ts, return_index=True)
    first_idx = np.sort(first_idx)
    return ts[first_idx], vals[first_idx], yt[first_idx]


def _regrid(
    timestamps: np.ndarray, values: np.ndarray, y_true: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Reindex onto the regular grid inferred from the median step.

    Points that already sit on a regular grid pass through unchanged; any
    missing slot becomes NaN (value) / False (label) — mirroring detectkit's
    gap-filled ``_dtk_datapoints`` contract.
    """
    if len(timestamps) < 2:
        return timestamps, values, y_true

    ts_int = timestamps.astype("datetime64[ms]").astype(np.int64)
    steps = np.diff(ts_int)
    step_ms = int(np.median(steps))
    if step_ms <= 0:
        # Degenerate (all-but-one duplicate) step; nothing sensible to grid.
        return timestamps, values, y_true
    if np.all(steps == step_ms):
        return timestamps, values, y_true

    start, end = ts_int[0], ts_int[-1]
    n = int((end - start) // step_ms) + 1
    grid_ts = (start + np.arange(n) * step_ms).astype("datetime64[ms]")
    grid_values = np.full(n, np.nan, dtype=np.float64)
    grid_y = np.zeros(n, dtype=bool)

    idx = ((ts_int - start) // step_ms).astype(np.int64)
    valid = (idx >= 0) & (idx < n)
    grid_values[idx[valid]] = values[valid]
    grid_y[idx[valid]] = y_true[valid]
    return grid_ts, grid_values, grid_y


def _finalize(
    name: str, dataset: str, timestamps: np.ndarray, values: np.ndarray, y_true: np.ndarray
) -> LabeledSeries:
    ts, vals, yt = _sort_dedup_coerce(timestamps, values, y_true)
    ts, vals, yt = _regrid(ts, vals, yt)
    return LabeledSeries(name=name, dataset=dataset, timestamps=ts, values=vals, y_true=yt)


# ---------------------------------------------------------------------------
# NAB
# ---------------------------------------------------------------------------


def download_nab(root: Path) -> Path:
    """Download the NAB repo zip (~100MB) and extract only ``data/**`` and
    ``labels/combined_windows.json`` into ``root/nab``.

    The zip is streamed to disk in chunks (never held fully in memory), then
    ``zipfile`` extracts selectively so the ~1GB uncompressed repo doesn't all
    have to land on disk — only the CSV series and the combined labels file.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    zip_path = root / "_nab_master.zip"

    logger.info("Downloading NAB from %s ...", NAB_ZIP_URL)
    with urllib.request.urlopen(NAB_ZIP_URL) as resp, open(zip_path, "wb") as fh:
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            fh.write(chunk)

    nab_dir = root / "nab"
    nab_dir.mkdir(parents=True, exist_ok=True)
    wanted_prefix = "NAB-master/data/"
    wanted_labels = "NAB-master/labels/combined_windows.json"

    logger.info("Extracting data/ and labels/combined_windows.json into %s ...", nab_dir)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            if member.endswith("/"):
                continue
            if not (member.startswith(wanted_prefix) or member == wanted_labels):
                continue
            rel = Path(member).relative_to("NAB-master")
            target = nab_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as src, open(target, "wb") as dst:
                dst.write(src.read())

    zip_path.unlink(missing_ok=True)
    logger.info("NAB ready at %s", nab_dir)
    return nab_dir


def _read_nab_csv(path: Path) -> tuple[np.ndarray, np.ndarray]:
    timestamps = []
    values = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            timestamps.append(row["timestamp"])
            values.append(float(row["value"]))
    ts = np.array([np.datetime64(t, "ms") for t in timestamps], dtype="datetime64[ms]")
    return ts, np.array(values, dtype=np.float64)


def _mark_nab_windows(timestamps: np.ndarray, windows: list[list[str]]) -> np.ndarray:
    y_true = np.zeros(len(timestamps), dtype=bool)
    for start_str, end_str in windows:
        start = np.datetime64(start_str, "ms")
        end = np.datetime64(end_str, "ms")
        y_true |= (timestamps >= start) & (timestamps <= end)
    return y_true


def load_nab(root: Path, max_series: int | None = None) -> list[LabeledSeries]:
    """Load NAB series from ``root`` (expects the layout :func:`download_nab`
    produces: ``<root>/data/<group>/<file>.csv`` +
    ``<root>/labels/combined_windows.json``; ``<root>/nab/...`` is also
    accepted so callers can pass the parent ``data/`` directory directly).

    All groups are kept, including ``artificialNoAnomaly`` (all-negative
    series) — they measure false-positive behavior rather than recall, which
    is exactly the signal a benchmark needs. Each series is named
    ``"<group>/<file>.csv"`` so the group is visible in results.
    """
    root = Path(root)
    nab_root = root / "nab" if (root / "nab" / "data").exists() else root
    data_dir = nab_root / "data"
    labels_path = nab_root / "labels" / "combined_windows.json"
    if not data_dir.exists() or not labels_path.exists():
        raise FileNotFoundError(
            f"NAB data not found under {nab_root} (expected data/ and "
            "labels/combined_windows.json). Run with --download-nab, or see "
            "benchmarks/README.md for manual setup."
        )

    with open(labels_path) as fh:
        windows_map: dict[str, list[list[str]]] = json.load(fh)

    series: list[LabeledSeries] = []
    for csv_path in sorted(data_dir.rglob("*.csv")):
        rel_key = csv_path.relative_to(data_dir).as_posix()
        group = csv_path.parent.name
        try:
            timestamps, values = _read_nab_csv(csv_path)
        except Exception as exc:  # noqa: BLE001 - one bad file shouldn't kill the load
            logger.warning("Skipping unreadable NAB file %s: %s", csv_path, exc)
            continue
        y_true = _mark_nab_windows(timestamps, windows_map.get(rel_key, []))
        series.append(_finalize(f"{group}/{csv_path.name}", "nab", timestamps, values, y_true))
        if max_series is not None and len(series) >= max_series:
            break
    return series


# ---------------------------------------------------------------------------
# Yahoo S5 (Webscope) — license-gated, user-supplied directory.
# ---------------------------------------------------------------------------


class _UnsupportedYahooFile(Exception):
    """Raised internally when a CSV's columns can't be interpreted."""


def _yahoo_column_index(header_lower: list[str], *candidates: str) -> int | None:
    for name in candidates:
        if name in header_lower:
            return header_lower.index(name)
    return None


def _load_yahoo_file(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse one Yahoo S5 CSV. Raises _UnsupportedYahooFile if the columns
    can't be interpreted (caller logs a warning and skips)."""
    with open(path, newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header:
            raise _UnsupportedYahooFile("empty file")
        header_lower = [h.strip().lower() for h in header]
        rows = [r for r in reader if r]

    ts_idx = _yahoo_column_index(header_lower, "timestamp", "timestamps")
    val_idx = _yahoo_column_index(header_lower, "value")
    # A1/A2 use is_anomaly; A3/A4 use anomaly (and sometimes changepoint).
    label_idx = _yahoo_column_index(header_lower, "is_anomaly", "anomaly", "changepoint")

    if ts_idx is None or val_idx is None:
        raise _UnsupportedYahooFile(f"missing timestamp/value column in header {header}")
    if label_idx is None:
        raise _UnsupportedYahooFile(f"no is_anomaly/anomaly/changepoint column in header {header}")

    raw_ts = [r[ts_idx] for r in rows]
    values = np.array([float(r[val_idx]) for r in rows], dtype=np.float64)
    labels = np.array([float(r[label_idx]) for r in rows]) > 0

    # A1/A2/A3/A4 all use a plain integer index in the timestamp column
    # (there is no wall-clock time in the public release); synthesize a
    # 1-hour grid from it so downstream code has real datetime64 values.
    try:
        int_ts = np.array([int(float(t)) for t in raw_ts], dtype=np.int64)
        order = np.argsort(int_ts, kind="mergesort")
        int_ts, values, labels = int_ts[order], values[order], labels[order]
        base = np.datetime64("2000-01-01T00:00:00", "h")
        timestamps = (base + (int_ts - int_ts.min())).astype("datetime64[ms]")
    except ValueError as exc:
        # Not an integer index — try parsing as an actual datetime string.
        try:
            timestamps = np.array([np.datetime64(t, "ms") for t in raw_ts], dtype="datetime64[ms]")
        except ValueError:
            raise _UnsupportedYahooFile(f"unparseable timestamp column: {exc}") from exc

    return timestamps, values, labels


def load_yahoo(root: Path, max_series: int | None = None) -> list[LabeledSeries]:
    """Load Yahoo S5 series from a user-supplied, already-extracted directory.

    Supports the standard layout: ``A1Benchmark/real_*.csv`` and
    ``A2Benchmark/synthetic_*.csv`` (``timestamp,value,is_anomaly``), plus
    ``A3Benchmark``/``A4Benchmark`` (``timestamps,value,anomaly[,changepoint]``).
    A file whose columns can't be interpreted is skipped with a warning
    rather than failing the whole load.
    """
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(
            f"Yahoo S5 directory not found: {root}. Webscope S5 is license-gated — "
            "request it from Yahoo and pass --yahoo-dir <extracted-folder>."
        )

    series: list[LabeledSeries] = []
    for csv_path in sorted(root.rglob("*.csv")):
        try:
            timestamps, values, y_true = _load_yahoo_file(csv_path)
        except _UnsupportedYahooFile as exc:
            logger.warning("Skipping Yahoo file %s: %s", csv_path, exc)
            continue
        except Exception as exc:  # noqa: BLE001 - one bad file shouldn't kill the load
            logger.warning("Skipping unreadable Yahoo file %s: %s", csv_path, exc)
            continue
        series.append(_finalize(csv_path.stem, "yahoo", timestamps, values, y_true))
        if max_series is not None and len(series) >= max_series:
            break
    return series


# ---------------------------------------------------------------------------
# Offline synthetic smoke set — no download required.
# ---------------------------------------------------------------------------


def _make_spikes(rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Level + Gaussian noise with a handful of injected point spikes."""
    values = rng.normal(loc=50.0, scale=3.0, size=n)
    y_true = np.zeros(n, dtype=bool)
    n_spikes = 6
    positions = rng.choice(np.arange(50, n - 50), size=n_spikes, replace=False)
    for pos in positions:
        direction = rng.choice([-1.0, 1.0])
        magnitude = rng.uniform(15.0, 30.0)
        values[pos] += direction * magnitude
        y_true[pos] = True
    return values, y_true


def _make_seasonal(rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Daily-seasonal sinusoid with a few sustained anomalous windows that
    break the seasonal pattern."""
    t = np.arange(n)
    points_per_day = int(24 * 60 / _SYNTH_STEP_MINUTES)
    daily = 10.0 * np.sin(2 * np.pi * t / points_per_day)
    noise = rng.normal(0.0, 1.5, size=n)
    values = 40.0 + daily + noise
    y_true = np.zeros(n, dtype=bool)

    n_windows = 3
    starts = rng.choice(np.arange(100, n - 150), size=n_windows, replace=False)
    for ws in starts:
        length = int(rng.integers(10, 25))
        shift = rng.uniform(12.0, 20.0) * rng.choice([-1.0, 1.0])
        values[ws : ws + length] += shift
        y_true[ws : ws + length] = True
    return values, y_true


def _make_ar2(rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
    """AR(2) dynamics with one segment whose coefficients change (a
    dynamics-breaking regime, not just a level/variance shift)."""
    values = np.zeros(n, dtype=np.float64)
    phi1, phi2 = 0.6, 0.25
    noise_std = 1.0
    values[:2] = rng.normal(0.0, noise_std, size=2)
    y_true = np.zeros(n, dtype=bool)

    break_start = int(rng.integers(int(n * 0.4), int(n * 0.6)))
    break_len = int(rng.integers(30, 60))
    break_end = break_start + break_len

    for i in range(2, n):
        if break_start <= i < break_end:
            values[i] = 0.2 * values[i - 1] - 0.9 * values[i - 2] + rng.normal(0.0, noise_std * 2.5)
            y_true[i] = True
        else:
            values[i] = phi1 * values[i - 1] + phi2 * values[i - 2] + rng.normal(0.0, noise_std)
    return values + 30.0, y_true


def _make_clean(rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
    """A clean series with zero injected anomalies — measures pure FP rate."""
    values = rng.normal(loc=20.0, scale=2.0, size=n)
    return values, np.zeros(n, dtype=bool)


_SYNTH_FAMILIES: dict[str, Any] = {
    "spikes": _make_spikes,
    "seasonal": _make_seasonal,
    "ar2": _make_ar2,
    "clean": _make_clean,
}


def load_synthetic(seed: int = 7, n_series: int = 12) -> list[LabeledSeries]:
    """Deterministic offline smoke set: no download, ready in seconds.

    Cycles through four series families — ``spikes`` (level + noise with
    injected point anomalies), ``seasonal`` (daily sinusoid with anomalous
    windows), ``ar2`` (AR(2) dynamics with a dynamics-breaking segment) and
    ``clean`` (zero anomalies, pure FP-rate signal) — deterministically from
    ``np.random.default_rng(seed)`` so results are reproducible across runs.
    """
    rng = np.random.default_rng(seed)
    family_names = list(_SYNTH_FAMILIES.keys())
    start = np.datetime64("2024-01-01T00:00:00", "m")
    step = np.timedelta64(_SYNTH_STEP_MINUTES, "m")

    series: list[LabeledSeries] = []
    for i in range(n_series):
        family = family_names[i % len(family_names)]
        values, y_true = _SYNTH_FAMILIES[family](rng, _SYNTH_N_POINTS)
        timestamps = (start + np.arange(_SYNTH_N_POINTS) * step).astype("datetime64[ms]")
        series.append(
            LabeledSeries(
                name=f"{family}_{i:02d}",
                dataset="synthetic",
                timestamps=timestamps,
                values=values,
                y_true=y_true,
            )
        )
    return series
