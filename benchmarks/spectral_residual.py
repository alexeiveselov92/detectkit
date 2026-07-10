"""Pure-numpy Spectral Residual (SR) saliency detector — benchmark-local only.

This is NOT part of the detectkit library. It exists purely to be measured
against detectkit's real detectors on the same labeled benchmarks, as a
measure-first gate: results decide whether SR is ever worth shipping as a
library detector (see benchmarks/README.md).

Implements the Spectral Residual algorithm from:

    Ren, H., Xu, B., Wang, Y., Yi, C., Huang, C., Kou, X., Xing, T., Yang,
    M., Tong, J., Zhang, Q. "Time-Series Anomaly Detection Service at
    Microsoft." KDD 2019. https://arxiv.org/abs/1906.03821

Intuition: transform the series into the frequency domain and look at its
log-amplitude spectrum. Subtract a locally-smoothed version of that spectrum
(the "expected"/generic spectral shape) to get the *spectral residual* — what
is left after removing the generic shape. Transforming the residual back to
the time domain (keeping the original phase) produces a "saliency map" that
lights up wherever the local waveform shape departs from the series' general
character, independent of any windowed mean/median baseline.
"""

from __future__ import annotations

import numpy as np

# Moving-average window over the log-amplitude spectrum (paper: q=3).
_SPECTRAL_SMOOTH_WINDOW = 3
# Trailing window for the local-average baseline of the saliency map (paper: z=21).
_SALIENCY_LOCAL_WINDOW = 21
# Minimum series length for the local-window normalization to be meaningful.
_MIN_SERIES_LENGTH = _SALIENCY_LOCAL_WINDOW + 2


def _interpolate_nans(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Linearly interpolate NaNs (the FFT needs a fully-defined signal).

    Returns ``(filled_values, was_nan_mask)`` — the mask is used afterward to
    zero the score at originally-missing points.
    """
    values = np.asarray(values, dtype=np.float64)
    was_nan = np.isnan(values)
    if not was_nan.any():
        return values.copy(), was_nan

    filled = values.copy()
    idx = np.arange(len(values))
    valid = ~was_nan
    if not valid.any():
        filled[:] = 0.0  # all-NaN series: nothing sensible to transform
        return filled, was_nan
    filled[was_nan] = np.interp(idx[was_nan], idx[valid], filled[valid])
    return filled, was_nan


def _trailing_moving_average(x: np.ndarray, window: int) -> np.ndarray:
    """O(n) trailing moving average (edges average over what's available)."""
    n = len(x)
    cumsum = np.concatenate(([0.0], np.cumsum(x)))
    idx = np.arange(n)
    starts = np.maximum(0, idx - window + 1)
    ends = idx + 1
    return (cumsum[ends] - cumsum[starts]) / (ends - starts)


def spectral_residual_scores(values: np.ndarray) -> np.ndarray:
    """Compute the SR saliency-based anomaly score for each point.

    Returns a non-negative array (same length as ``values``): higher means
    more anomalous. Points that were originally NaN score exactly 0 (there is
    nothing to flag at a missing point).
    """
    filled, was_nan = _interpolate_nans(values)
    n = len(filled)
    if n < _MIN_SERIES_LENGTH:
        return np.zeros(n, dtype=np.float64)

    # 1. FFT -> amplitude + phase spectra.
    spectrum = np.fft.fft(filled)
    amplitude = np.abs(spectrum)
    phase = np.angle(spectrum)

    # 2. Log-amplitude spectrum (eps guards log(0) on a constant/all-zero series).
    log_amplitude = np.log(amplitude + 1e-12)

    # 3. Spectral residual: actual log-amplitude minus its local (smoothed)
    # average — the part of the spectrum that ISN'T the generic/expected shape.
    avg_log_amplitude = _trailing_moving_average(log_amplitude, _SPECTRAL_SMOOTH_WINDOW)
    residual = log_amplitude - avg_log_amplitude

    # 4. Inverse FFT of exp(residual) with the ORIGINAL phase reconstructs a
    # time-domain "saliency map".
    sr_spectrum = np.exp(residual + 1j * phase)
    saliency = np.abs(np.fft.ifft(sr_spectrum))

    # 5. Normalize each point against a trailing local average of the
    # saliency map itself: score = (s - local_mean) / local_mean, clipped at
    # >= 0 so only points saliently ABOVE their own local baseline count.
    local_mean = _trailing_moving_average(saliency, _SALIENCY_LOCAL_WINDOW)
    with np.errstate(divide="ignore", invalid="ignore"):
        score = (saliency - local_mean) / local_mean
    score = np.nan_to_num(score, nan=0.0, posinf=0.0, neginf=0.0)
    score = np.clip(score, 0.0, None)

    score[was_nan] = 0.0
    return score


def detect(values: np.ndarray, threshold: float = 3.0) -> np.ndarray:
    """Boolean anomaly flags: saliency score strictly above ``threshold``."""
    return spectral_residual_scores(values) > threshold
