"""Runtime knobs for the autotune engine.

Distinct from :class:`detectkit.config.metric_config.AutoTuneConfig` (the
user-facing YAML block). ``TuneSettings`` is the resolved, internal
configuration the engine actually searches with — built by the command from
flags + the YAML block, with sane defaults so a bare ``dtk autotune`` works.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from detectkit.autotune._types import ScoringMetric


@dataclass
class TuneSettings:
    """Resolved search configuration."""

    # Scoring
    metric: ScoringMetric = ScoringMetric.MCC
    beta: float = 1.0
    fpr_target: float = 0.01  # unsupervised: target max flag-rate

    # Cross-validation
    fold_count: int = 5
    # aggregate = mean(folds) - lambda * downside_semideviation(folds); downside-only
    # so a regime-adaptive config isn't penalized for scoring *better* on recent folds.
    stability_lambda: float = 0.5

    # Detector selection: by default the grid search evaluates ALL windowed
    # statistical detectors and lets cross-validation pick the winner; the
    # distribution suitability vote only ORDERS them (most promising first) and is
    # never used to exclude a type. The cap is a cost backstop, set above the
    # current number of statistical detectors so none is dropped.
    max_candidate_types: int = 4

    # Grid search
    min_improvement: float = 1e-3  # accept a move only if it beats by this margin
    max_candidates: int = 200  # hard ceiling on candidate evaluations
    # The high rungs (5/6 sigma, 4/6 Tukey) act as a "near-suppress" option so a
    # heavy-tailed metric can widen the band under the flag-rate budget instead of
    # being trapped flagging its legitimate tail.
    threshold_grid_sigma: tuple[float, ...] = (2.5, 3.0, 3.5, 4.0, 5.0, 6.0)  # mad / zscore
    threshold_grid_iqr: tuple[float, ...] = (1.5, 2.0, 3.0, 4.0, 6.0)  # iqr (Tukey)
    # AR-order sweep for the prediction-based autoreg detector (axis gated by
    # its AxisSpec; the residual z is in σ-units so it reuses the sigma grid).
    lags_grid: tuple[int, ...] = (2, 3, 5, 8)

    # History / window selection
    window_tie_margin: float = 0.01  # prefer a larger window within this score gap

    # Fraction alert window (supervised 2-D sweep, OR-ed with the consecutive
    # rule exactly as the pipeline deploys it). Window grid is in grid points
    # of the metric interval; entries < 2 are dropped (MetricConfig rejects an
    # anomaly_window spanning < 2 intervals). Shares are fractions in (0, 1].
    alert_window_points_grid: tuple[int, ...] = (4, 6, 12, 24)
    alert_share_grid: tuple[float, ...] = (0.2, 0.3, 0.5)

    # Stage-1 seasonality search probe
    probe_detector_type: str = "mad"

    # Constraints injected from the YAML autotune: block / CLI flags
    allowed_detector_types: list[str] | None = None
    allowed_seasonality: list[str] | None = None
    force_seasonality: list[str | list[str]] | None = None  # pin the grouping (skip the search)
    fixed_params: dict[str, object] = field(default_factory=dict)
    max_history: int | None = None

    def threshold_grid(self, detector_type: str) -> tuple[float, ...]:
        """Threshold sweep for a detector type (Tukey multipliers for IQR).

        ``autoreg`` deliberately falls through to the sigma grid: its residual
        z-score is in σ-units, directly comparable with mad/zscore thresholds.
        """
        return self.threshold_grid_iqr if detector_type == "iqr" else self.threshold_grid_sigma
