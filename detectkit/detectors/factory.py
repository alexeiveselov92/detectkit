"""
Detector factory for creating detector instances from configuration.
"""

from typing import Dict, List

from detectkit.detectors.base import BaseDetector
from detectkit.detectors.statistical.iqr import IQRDetector
from detectkit.detectors.statistical.mad import MADDetector
from detectkit.detectors.statistical.manual_bounds import ManualBoundsDetector
from detectkit.detectors.statistical.zscore import ZScoreDetector


class DetectorFactory:
    """
    Factory for creating detector instances from configuration.

    Supports creating detectors by type name with parameters.

    Example:
        >>> factory = DetectorFactory()
        >>> detector = factory.create("zscore", {"threshold": 3.0})
        >>> isinstance(detector, ZScoreDetector)
        True
    """

    # Registry of available detector types
    DETECTOR_TYPES = {
        "zscore": ZScoreDetector,
        "mad": MADDetector,
        "iqr": IQRDetector,
        "manual_bounds": ManualBoundsDetector,
        "manual": ManualBoundsDetector,  # Alias
    }

    @classmethod
    def create(cls, detector_type: str, params: Dict = None) -> BaseDetector:
        """
        Create detector instance from type and parameters.

        Args:
            detector_type: Type of detector (e.g., "zscore", "mad")
            params: Detector parameters (optional)

        Returns:
            Detector instance

        Raises:
            ValueError: If detector type is unknown

        Example:
            >>> detector = DetectorFactory.create("zscore", {"threshold": 3.0, "window_size": 100})
            >>> detector = DetectorFactory.create("mad", {"threshold": 2.5})
        """
        params = params or {}

        detector_type = detector_type.lower()

        if detector_type not in cls.DETECTOR_TYPES:
            available = ", ".join(sorted(cls.DETECTOR_TYPES.keys()))
            raise ValueError(
                f"Unknown detector type: '{detector_type}'. "
                f"Available types: {available}"
            )

        detector_class = cls.DETECTOR_TYPES[detector_type]

        try:
            return detector_class(**params)
        except TypeError as e:
            raise ValueError(
                f"Invalid parameters for {detector_type} detector: {e}"
            ) from e

    @classmethod
    def create_from_config(cls, detector_config: Dict) -> BaseDetector:
        """
        Create detector from configuration dictionary.

        Args:
            detector_config: Configuration with 'type' and optional 'params'
                Example: {"type": "zscore", "params": {"threshold": 3.0}}

        Returns:
            Detector instance

        Example:
            >>> config = {"type": "zscore", "params": {"threshold": 3.0}}
            >>> detector = DetectorFactory.create_from_config(config)
        """
        detector_type = detector_config.get("type")
        if not detector_type:
            raise ValueError("Detector config must have 'type' field")

        params = detector_config.get("params", {})

        return cls.create(detector_type, params)

    @classmethod
    def create_multiple(cls, detector_configs: List[Dict]) -> List[BaseDetector]:
        """
        Create multiple detectors from list of configurations.

        Args:
            detector_configs: List of detector configurations

        Returns:
            List of detector instances

        Example:
            >>> configs = [
            ...     {"type": "zscore", "params": {"threshold": 3.0}},
            ...     {"type": "mad", "params": {"threshold": 2.5}},
            ... ]
            >>> detectors = DetectorFactory.create_multiple(configs)
            >>> len(detectors)
            2
        """
        detectors = []
        for config in detector_configs:
            detector = cls.create_from_config(config)
            detectors.append(detector)
        return detectors

    @classmethod
    def list_available_types(cls) -> List[str]:
        """
        Get list of available detector types.

        Returns:
            List of detector type names

        Example:
            >>> types = DetectorFactory.list_available_types()
            >>> "zscore" in types
            True
        """
        return sorted(cls.DETECTOR_TYPES.keys())
