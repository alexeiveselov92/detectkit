"""Per-detector-type axis specification for the grid search (issue #97 Phase 2).

``grid_search`` used to be one hardcoded coordinate sweep whose every axis name
(``window_weights``, ``half_life``, ``detrend``, ``seasonality_components``) is
a ``WindowedStatDetector`` constructor kwarg. The prediction-based ``autoreg``
detector accepts none of those (and *raises* on truthy
``seasonality_components``), so the sweep dispatches on a small spec keyed by
detector type — kept here, NOT on the detector classes, the same
easy-to-remove externalized-knowledge choice as ``detector_select``'s
suitability spec. Unlisted (future) types get the windowed default, which is
behavior-identical to the pre-seam sweep.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from detectkit.detectors.factory import DetectorFactory

if TYPE_CHECKING:
    from detectkit.autotune._base import _AutoTuneBase


@dataclass(frozen=True)
class AxisSpec:
    """Which grid-search axes apply to a detector type, plus per-type floors.

    ``min_samples_floor`` / ``threshold_default`` override the class-attribute
    lookup (``MIN_SAMPLES_FLOOR`` / ``THRESHOLD_DEFAULT``) for types that don't
    carry the windowed template's attributes; ``None`` keeps the lookup.
    ``initial`` seeds the accepted-params dict so type-specific defaults (e.g.
    autoreg's default-on stabilization) are explicit from the first candidate.
    """

    seasonality: bool = True  # inject the chosen seasonality_components
    weighting: bool = True  # window_weights + half_life axes
    detrend: bool = True  # detrend axis (still trend-gated)
    stabilization: bool = True  # stabilization axis
    lags: bool = False  # AR-order axis (settings.lags_grid)
    min_samples_floor: int | None = None
    threshold_default: float | None = None
    initial: dict[str, Any] = field(default_factory=dict)


_WINDOWED = AxisSpec()

_AXIS_SPECS: dict[str, AxisSpec] = {
    # v1 autoreg has no seasonality/smoothing/weighting/detrend by design (the
    # AR residual model adapts to level and short-range dynamics on its own);
    # it *rejects* seasonality_components, so the seam must never inject them.
    # min_samples additionally floors at lags + 2 — see ``min_samples_for``.
    "autoreg": AxisSpec(
        seasonality=False,
        weighting=False,
        detrend=False,
        lags=True,
        min_samples_floor=10,
        threshold_default=3.0,
        initial={"lags": 5, "stabilization": "clamp"},
    ),
}


def axis_spec_for(detector_type: str) -> AxisSpec:
    """The axis spec for *detector_type* (windowed default when unlisted)."""
    return _AXIS_SPECS.get(detector_type, _WINDOWED)


def resolve_floor(detector_type: str) -> int:
    """Min-samples floor: spec override first, then the class attribute."""
    spec = axis_spec_for(detector_type)
    if spec.min_samples_floor is not None:
        return spec.min_samples_floor
    detector_cls = DetectorFactory.DETECTOR_TYPES[detector_type]
    return int(getattr(detector_cls, "MIN_SAMPLES_FLOOR", 1))


def resolve_threshold_default(detector_type: str) -> float:
    """Default threshold: spec override first, then the class attribute."""
    spec = axis_spec_for(detector_type)
    if spec.threshold_default is not None:
        return spec.threshold_default
    detector_cls = DetectorFactory.DETECTOR_TYPES[detector_type]
    return float(getattr(detector_cls, "THRESHOLD_DEFAULT", 3.0))


def max_context_size(tuner: _AutoTuneBase, grid: list[int]) -> int:
    """Largest ``get_context_size()`` any candidate the search can build needs.

    The CV plan must reserve this much lead-in — deriving it from the raw
    window grid alone (the pre-fix behavior) under-reserves for stabilization
    (an extra window of warm-up) and for autoreg (``+ lags``), silently
    scoring points where ``detect()`` returns ``insufficient_data`` /
    ``missing_lags`` (they become ``valid=False``, degrading the CV signal
    without erroring).
    """
    from detectkit.autotune.detector_select import _candidate_types

    max_window = max([*grid, 100])
    context = max_window
    for detector_type in _candidate_types(tuner):
        spec = axis_spec_for(detector_type)
        params: dict[str, Any] = {**tuner.settings.fixed_params}
        params["window_size"] = max_window
        # Worst-case axes the sweep can adopt: stabilization adds a window of
        # warm-up; the largest lags in the grid adds `lags` context points.
        params["stabilization"] = "clamp"
        if spec.lags and tuner.settings.lags_grid:
            max_lags = max(tuner.settings.lags_grid)
            params["lags"] = max_lags
            params["min_samples"] = max(max_lags + 2, min(30, max_window))
        try:
            detector = DetectorFactory.create(detector_type, params)
        except ValueError:
            continue
        context = max(context, detector.get_context_size())
    return context
