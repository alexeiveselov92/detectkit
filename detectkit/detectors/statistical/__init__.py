"""Statistical anomaly detectors."""

from detectkit.detectors.statistical.autoreg import AutoregDetector
from detectkit.detectors.statistical.iqr import IQRDetector
from detectkit.detectors.statistical.mad import MADDetector
from detectkit.detectors.statistical.manual_bounds import ManualBoundsDetector
from detectkit.detectors.statistical.zscore import ZScoreDetector

__all__ = [
    "AutoregDetector",
    "IQRDetector",
    "MADDetector",
    "ManualBoundsDetector",
    "ZScoreDetector",
]
