"""Statistical anomaly detectors."""

from detectkit.detectors.statistical.iqr import IQRDetector
from detectkit.detectors.statistical.mad import MADDetector
from detectkit.detectors.statistical.manual_bounds import ManualBoundsDetector
from detectkit.detectors.statistical.zscore import ZScoreDetector

__all__ = ["IQRDetector", "MADDetector", "ManualBoundsDetector", "ZScoreDetector"]
