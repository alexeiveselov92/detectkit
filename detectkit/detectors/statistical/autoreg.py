"""
Autoregressive (AR) anomaly detector — detectkit's first *dynamics* detector.

Where MAD/Z-Score/IQR model a metric's **level** (is this value far from the
recent center?), ``AutoregDetector`` models its **short-range dynamics**: it
fits an AR(p) model on a trailing window (predicting the current value from
its ``lags`` immediately preceding values), scores the residual between the
observed value and the model's one-step-ahead prediction, and flags a point
when that residual exceeds ``threshold`` standard deviations. A value that
sits well within the metric's historical range can still be anomalous here if
it breaks the metric's usual dynamics (e.g. a sudden jump that no recent
trajectory would predict).

Deliberate exception to the "reuse WindowedStatDetector" rule: this class
subclasses ``BaseDetector`` directly, like ``ManualBoundsDetector``, NOT
``WindowedStatDetector``. Three reasons:

1. The windowed template's trailing window drops NaNs and closes the gap
   before computing statistics — for a level statistic (median, mean) that is
   fine, but for a **lag model** it would silently splice together
   non-adjacent points into a fabricated ``(y_{t-1}, y_t)`` pair, teaching the
   AR coefficients a transition that never happened.
2. The windowed template's per-seasonality-group multiplier machinery has no
   meaning for a lag model (a lag model already captures local dynamics; a
   "group median multiplier" doesn't compose with autoregressive
   coefficients), so seasonality is explicitly unsupported in v1 (see
   ``seasonality_components`` below).
3. Fitting AR coefficients per point needs its own control flow (design
   matrix assembly, normal equations, a fallback solver) that doesn't fit the
   three-hook `_compute_stats` / `_build_interval` / `_severity` shape the
   windowed template expects.

v1 is deliberately minimal: no smoothing, no recency weighting, no
detrending, no seasonality — the AR residual model already adapts to the
local level and short-range dynamics on its own. Performance: like the
windowed detectors, this refits per point in a Python loop (documented
roadmap gap); the per-point design-matrix assembly is vectorized with numpy
sliding-window views rather than an inner Python loop.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from detectkit.detectors.base import BaseDetector, DetectionResult

_INPUT_TYPES = {"values", "changes", "absolute_changes", "log_changes"}
_CHANGE_INPUT_TYPES = {"changes", "absolute_changes", "log_changes"}
_STABILIZATION_METHODS = {None, "clamp"}


class AutoregDetector(BaseDetector):
    """Autoregressive AR(p) detector: predicts each point from its trailing
    lags and flags residuals that exceed ``threshold`` standard deviations.

    Parameters:
        lags (int): AR order — number of immediately-preceding values used as
            predictors (default: 5). Must be >= 1 and < window_size.
        window_size (int): Trailing history used to fit the AR model at each
            point, current point excluded (default: 200).
        threshold (float): Residual-sigma band half-width (default: 3.0).
        min_samples (int): Minimum valid (gap-free) fit rows required in the
            window before scoring (default: 30). Must be at least
            ``lags + 2`` (the AR(p) + intercept model has ``lags + 1``
            unknowns, so at least one more row than that is needed to fit).
        input_type (str): "values" (default), "changes", "absolute_changes"
            or "log_changes" — see ``BaseDetector._preprocess_input``.
        stabilization (str | None): "clamp" (default — ON) or None. Mirrors
            ``WindowedStatDetector``'s stabilization: once a point is flagged
            anomalous, later windows see it clamped to the confidence bound
            it violated (not the raw observation), so a sustained incident
            cannot inflate the residual scale and mask its own tail. See the
            write-back comment in ``detect()`` for why the bound (not the
            prediction) is the substitution target.
        seasonality_components: NOT supported in v1. Accepted only so the
            detect step's generic per-detector param injection doesn't raise
            a confusing ``TypeError`` when a metric configures it globally;
            passing a truthy value raises ``ValueError`` at construction.

    All algorithm parameters above (everything except ``seasonality_components``,
    which can only ever be ``None``/empty here) participate in the detector ID
    hash — see ``_get_non_default_params``.
    """

    ALGORITHM_VERSION = 2

    def __init__(
        self,
        lags: int = 5,
        window_size: int = 200,
        threshold: float = 3.0,
        min_samples: int = 30,
        input_type: str = "values",
        stabilization: str | None = "clamp",
        seasonality_components: list[str | list[str]] | None = None,
    ):
        super().__init__(
            lags=lags,
            window_size=window_size,
            threshold=threshold,
            min_samples=min_samples,
            input_type=input_type,
            stabilization=stabilization,
            seasonality_components=seasonality_components,
        )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_params(self) -> None:
        p = self.params

        lags = p.get("lags")
        if lags is None or lags < 1:
            raise ValueError("lags must be at least 1")

        window_size = p.get("window_size")
        if window_size is None or window_size < lags + 2:
            raise ValueError(f"window_size must be at least lags + 2 ({lags + 2})")
        if lags >= window_size:
            raise ValueError("lags must be less than window_size")

        threshold = p.get("threshold")
        if threshold is None or threshold <= 0:
            raise ValueError("threshold must be positive")

        min_samples = p.get("min_samples")
        if min_samples is None or min_samples < lags + 2:
            raise ValueError(f"min_samples must be at least lags + 2 ({lags + 2})")
        if min_samples > window_size:
            raise ValueError("min_samples cannot exceed window_size")

        input_type = p.get("input_type", "values")
        if input_type not in _INPUT_TYPES:
            raise ValueError(
                f"Unknown input_type: {input_type}. "
                f"Supported values: {', '.join(sorted(_INPUT_TYPES))}"
            )

        stabilization = p.get("stabilization")
        if stabilization not in _STABILIZATION_METHODS:
            raise ValueError(f"Unknown stabilization method: {stabilization}. Supported: clamp")

        if p.get("seasonality_components"):
            raise ValueError(
                "autoreg does not support seasonality_components (v1); "
                "remove it or use a windowed detector (mad/zscore/iqr)"
            )

    # ------------------------------------------------------------------
    # Identity
    # ------------------------------------------------------------------

    def _defaults(self) -> dict[str, Any]:
        return {
            "lags": 5,
            "window_size": 200,
            "threshold": 3.0,
            "min_samples": 30,
            "input_type": "values",
            "stabilization": "clamp",
        }

    def _get_non_default_params(self) -> dict[str, Any]:
        """Every algorithm parameter that changes detection output is hashed.

        ``seasonality_components`` is deliberately excluded: it can only be
        ``None``/empty after validation (a truthy value raises), so it never
        carries information and must not participate in the hash.
        """
        defaults = self._defaults()
        return {
            k: v
            for k, v in self.params.items()
            if k != "seasonality_components" and v != defaults.get(k)
        }

    # ------------------------------------------------------------------
    # Context
    # ------------------------------------------------------------------

    def get_context_size(self) -> int:
        """Historical points needed before the first scored point.

        ``window_size`` points are needed to fit the AR model at the very
        first scored point, plus ``lags`` points to seed that window's own
        oldest lag vector. One extra point is added when ``input_type``
        computes changes (needs a prior raw point to diff against). When
        ``stabilization`` is on, one extra ``window_size`` of warm-up is
        added so an incremental batch reproduces the same substitution
        history a continuous run would see (mirrors
        ``WindowedStatDetector.get_context_size``).
        """
        context = int(self.params["window_size"]) + int(self.params["lags"])

        if self.params.get("input_type", "values") in _CHANGE_INPUT_TYPES:
            context += 1

        if self.params.get("stabilization"):
            context += int(self.params["window_size"])

        return context

    # ------------------------------------------------------------------
    # Fitting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _fit_ar(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """Solve the AR normal equations with a tiny ridge for conditioning.

        ``x`` is the design matrix (intercept column + lag columns), ``y`` the
        fit targets. Falls back to a least-squares solve if the (ridge-
        regularized) normal equations are singular.
        """
        a = x.T @ x
        ridge = 1e-8 * (np.trace(a) / a.shape[0])
        a = a + ridge * np.eye(a.shape[0])
        b = x.T @ y
        try:
            return np.asarray(np.linalg.solve(a, b), dtype=np.float64)
        except np.linalg.LinAlgError:
            coef, *_ = np.linalg.lstsq(x, y, rcond=None)
            return np.asarray(coef, dtype=np.float64)

    def _preprocessing_metadata(self) -> dict[str, Any] | None:
        input_type = self.params.get("input_type", "values")
        if input_type == "values":
            return None
        return {"input_type": input_type}

    # ------------------------------------------------------------------
    # Detection pipeline
    # ------------------------------------------------------------------

    def detect(self, data: dict[str, np.ndarray]) -> list[DetectionResult]:
        """Run per-point AR(p) fit + residual scoring. See class docstring."""
        timestamps = data["timestamp"]
        values = data["value"]  # ORIGINAL values (always kept)

        lags = int(self.params["lags"])
        window_size = int(self.params["window_size"])
        threshold = float(self.params["threshold"])
        min_samples = int(self.params["min_samples"])
        stabilization = self.params.get("stabilization")

        processed = self._preprocess_input(values)

        # Stabilization (opt-in, default ON): both the lag features and the
        # fit targets read from a working copy where every previously-flagged
        # point is clamped to the confidence bound it violated, so a
        # sustained incident cannot poison its own residual scale. The scored
        # value and the persisted processed_value stay the raw observation.
        work = processed.copy() if stabilization else processed
        replaced = np.zeros(len(processed), dtype=bool) if stabilization else None

        preprocessing_metadata = self._preprocessing_metadata()

        results: list[DetectionResult] = []
        n_points = len(timestamps)

        for i in range(n_points):
            current_val = values[i]
            current_processed = processed[i]
            current_ts = timestamps[i]

            if np.isnan(current_processed):
                metadata: dict[str, Any] = {"reason": "missing_data"}
                if preprocessing_metadata:
                    metadata["preprocessing"] = preprocessing_metadata
                results.append(
                    DetectionResult(
                        timestamp=current_ts,
                        value=current_val,
                        processed_value=current_processed,
                        is_anomaly=False,
                        detection_metadata=metadata,
                    )
                )
                continue

            # Lag vector for the point being scored: oldest -> newest, i.e.
            # [work[i-lags], ..., work[i-1]]. Strict v1 policy: never impute
            # across a gap, so any non-finite lag (or too little history)
            # skips scoring entirely rather than fabricating a value.
            if i < lags or not np.all(np.isfinite(work[i - lags : i])):
                metadata = {"reason": "missing_lags"}
                if preprocessing_metadata:
                    metadata["preprocessing"] = preprocessing_metadata
                results.append(
                    DetectionResult(
                        timestamp=current_ts,
                        value=current_val,
                        processed_value=current_processed,
                        is_anomaly=False,
                        detection_metadata=metadata,
                    )
                )
                continue

            lag_vec = work[i - lags : i]

            # Fit rows: targets y_j for j in [start, i), each paired with its
            # own lag vector work[j-lags:j]. Vectorized via a sliding-window
            # view over work[start-lags:i] (length (i-start)+lags), which
            # yields (i-start+1) windows of size `lags`; the last of those
            # windows is exactly `lag_vec` (the current point's own lag
            # vector) and is dropped, leaving one row per candidate target.
            start = max(lags, i - window_size)
            lag_start = start - lags
            segment = work[lag_start:i]
            windows = sliding_window_view(segment, lags)  # shape (i-start+1, lags)
            x_lags_all = windows[:-1]  # shape (i-start, lags), oldest -> newest per row
            y_all = work[start:i]  # shape (i-start,)

            valid_mask = np.isfinite(y_all) & np.all(np.isfinite(x_lags_all), axis=1)
            n_valid = int(np.count_nonzero(valid_mask))

            if n_valid < min_samples:
                metadata = {
                    "reason": "insufficient_data",
                    "fit_points": n_valid,
                    "min_samples": min_samples,
                }
                if preprocessing_metadata:
                    metadata["preprocessing"] = preprocessing_metadata
                results.append(
                    DetectionResult(
                        timestamp=current_ts,
                        value=current_val,
                        processed_value=current_processed,
                        is_anomaly=False,
                        detection_metadata=metadata,
                    )
                )
                continue

            x_valid = x_lags_all[valid_mask]
            y_valid = y_all[valid_mask]

            # Center/scale the fit window before assembling the design matrix.
            # OLS with an intercept is affine-equivariant, so the model is the
            # same in exact arithmetic — but with raw values ~1e9 the Gram
            # matrix mixes an intercept column of ones with lag columns of
            # ~1e18, a conditioning gap beyond float64 precision that produced
            # garbage coefficients (and, clamp-amplified, inf) on real NAB
            # series. Fitting at ~unit scale fixes the conditioning; the
            # prediction and residual scale are transformed back afterwards.
            center = float(np.mean(y_valid))
            scale = float(np.std(y_valid))
            if not np.isfinite(center):
                center = 0.0
            if not np.isfinite(scale) or scale <= 0.0:
                scale = 1.0
            design = np.column_stack([np.ones(n_valid), (x_valid - center) / scale])
            y_scaled = (y_valid - center) / scale

            coef = self._fit_ar(design, y_scaled)

            residuals = y_scaled - design @ coef
            sigma = (
                float(np.sqrt(np.sum(residuals**2) / max(n_valid - (lags + 1), 1))) * scale
            )

            pred_features = np.concatenate([[1.0], (lag_vec - center) / scale])
            pred = float(pred_features @ coef) * scale + center

            lower = pred - threshold * sigma
            upper = pred + threshold * sigma
            # sigma == 0 collapses the band to a single point (lower == upper
            # == pred): any deviation from the prediction is then anomalous,
            # the same degenerate-band convention as MAD/Z-Score.
            is_anomaly = bool(current_processed < lower or current_processed > upper)

            # Stabilization write-back: later windows see this point clamped
            # to the bound it violated, not the anomalous observation. We
            # deliberately clamp to the violated bound instead of
            # substituting the prediction (pred) itself: pure-prediction
            # substitution feeds zero-residual points into later fits,
            # collapsing sigma_r and causing false-flag cascades (the exact
            # center-substitution failure measured and rejected for the
            # windowed detectors in v0.51.0). The clamped value keeps a
            # threshold * sigma residual, so the AR model keeps flagging a
            # sustained incident instead of adapting to it. The substitution
            # is additionally capped to the observed (raw) range of the fit
            # window, so a degenerate fit whose bound explodes can never write
            # an astronomic value into the working history and amplify itself
            # through later fits (measured on NAB, see _fit_ar conditioning).
            if stabilization == "clamp" and is_anomaly:
                bound = lower if current_processed < lower else upper
                raw_window = processed[lag_start:i]
                finite_raw = raw_window[np.isfinite(raw_window)]
                if finite_raw.size:
                    bound = float(np.clip(bound, np.min(finite_raw), np.max(finite_raw)))
                work[i] = bound
                replaced[i] = True  # type: ignore[index]

            metadata = {
                "fit_points": n_valid,
                "sigma_r": sigma,
                "prediction": pred,
            }
            if preprocessing_metadata:
                metadata["preprocessing"] = preprocessing_metadata
            if replaced is not None:
                n_replaced = int(np.count_nonzero(replaced[lag_start:i]))
                if n_replaced:
                    metadata["stabilized_in_window"] = n_replaced

            if is_anomaly:
                if current_processed < lower:
                    direction = "below"
                    distance = lower - current_processed
                else:
                    direction = "above"
                    distance = current_processed - upper
                severity = distance / sigma if sigma > 0 else float("inf")
                metadata["direction"] = direction
                metadata["distance"] = float(distance)
                metadata["severity"] = float(severity)

            results.append(
                DetectionResult(
                    timestamp=current_ts,
                    value=current_val,
                    processed_value=current_processed,
                    is_anomaly=is_anomaly,
                    confidence_lower=float(lower),
                    confidence_upper=float(upper),
                    detection_metadata=metadata,
                )
            )

        return results
