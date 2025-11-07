"""
Task manager for metric processing pipeline.

Orchestrates the complete workflow:
1. Load data from database
2. Run anomaly detection
3. Send alerts
"""

from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Dict, List, Optional
import json

import numpy as np

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.channels.factory import AlertChannelFactory
from detectkit.alerting.orchestrator import (
    AlertConditions,
    AlertOrchestrator,
    DetectionRecord,
)
from detectkit.config.metric_config import MetricConfig
from detectkit.core.interval import Interval
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.detectors.base import BaseDetector
from detectkit.detectors.factory import DetectorFactory
from detectkit.loaders.metric_loader import MetricLoader


class PipelineStep(str, Enum):
    """Pipeline execution steps."""

    LOAD = "load"
    DETECT = "detect"
    ALERT = "alert"


class TaskStatus(str, Enum):
    """Task execution status."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


class TaskManager:
    """
    Manages metric processing pipeline.

    Responsibilities:
    - Execute pipeline steps (load, detect, alert)
    - Task locking to prevent concurrent runs
    - Idempotency (resume from last processed timestamp)
    - Error handling and status tracking

    Example:
        >>> config = MetricConfig.from_yaml("metrics/cpu_usage.yml")
        >>> manager = TaskManager(
        ...     internal_manager=internal_tables,
        ...     db_manager=clickhouse,
        ... )
        >>> manager.run_metric(
        ...     config,
        ...     steps=[PipelineStep.LOAD, PipelineStep.DETECT, PipelineStep.ALERT]
        ... )
    """

    def __init__(
        self,
        internal_manager: InternalTablesManager,
        db_manager,  # BaseDatabaseManager
        profiles_config=None,  # ProfilesConfig (optional for backward compatibility)
    ):
        """
        Initialize task manager.

        Args:
            internal_manager: Manager for internal detectk tables
            db_manager: Database manager for metric data
            profiles_config: Profiles configuration (for alert channels)
        """
        self.internal = internal_manager
        self.db_manager = db_manager
        self.profiles_config = profiles_config

    def run_metric(
        self,
        config: MetricConfig,
        steps: Optional[List[PipelineStep]] = None,
        from_date: Optional[datetime] = None,
        to_date: Optional[datetime] = None,
        full_refresh: bool = False,
        force: bool = False,
    ) -> Dict[str, any]:
        """
        Run metric processing pipeline.

        Args:
            config: Metric configuration
            steps: Pipeline steps to execute (default: all steps)
            from_date: Start date for data loading (optional)
            to_date: End date for data loading (optional)
            full_refresh: Delete all existing data and reload from scratch
            force: Ignore task locks

        Returns:
            Dict with execution results:
            {
                "status": "success" | "failed",
                "steps_completed": ["load", "detect"],
                "datapoints_loaded": 1000,
                "anomalies_detected": 5,
                "alerts_sent": 2,
                "error": None | "error message"
            }

        Example:
            >>> result = manager.run_metric(
            ...     config,
            ...     steps=[PipelineStep.LOAD, PipelineStep.DETECT],
            ...     from_date=datetime(2024, 1, 1),
            ... )
            >>> print(result["status"])
            success
        """
        steps = steps or [PipelineStep.LOAD, PipelineStep.DETECT, PipelineStep.ALERT]
        metric_name = config.name

        result = {
            "status": TaskStatus.SUCCESS,
            "steps_completed": [],
            "datapoints_loaded": 0,
            "anomalies_detected": 0,
            "alerts_sent": 0,
            "error": None,
        }

        try:
            # Step 0: Acquire lock
            if not force:
                # Default timeout: 1 hour (can be overridden via ProjectConfig in future)
                timeout_seconds = 3600
                lock_acquired = self.internal.acquire_lock(
                    metric_name=metric_name,
                    detector_id="pipeline",  # General pipeline lock
                    process_type="pipeline",  # Full pipeline execution
                    timeout_seconds=timeout_seconds,
                )
                if not lock_acquired:
                    raise RuntimeError(
                        f"Failed to acquire lock for metric '{metric_name}'. "
                        f"Another task is running. Use --force to override."
                    )

            try:
                # Step 1: Load data
                if PipelineStep.LOAD in steps:
                    load_result = self._run_load_step(
                        config, from_date, to_date, full_refresh
                    )
                    result["datapoints_loaded"] = load_result["points_loaded"]
                    result["steps_completed"].append(PipelineStep.LOAD)

                # Step 2: Detect anomalies
                if PipelineStep.DETECT in steps:
                    detect_result = self._run_detect_step(config, from_date, to_date, full_refresh)
                    result["anomalies_detected"] = detect_result["anomalies_count"]
                    result["steps_completed"].append(PipelineStep.DETECT)

                # Step 3: Send alerts
                if PipelineStep.ALERT in steps:
                    alert_result = self._run_alert_step(config)
                    result["alerts_sent"] = alert_result["alerts_sent"]
                    result["steps_completed"].append(PipelineStep.ALERT)

            finally:
                # Always release lock
                if not force:
                    status = "completed" if result["status"] == TaskStatus.SUCCESS else "failed"
                    error_msg = result.get("error")
                    self.internal.release_lock(
                        metric_name=metric_name,
                        detector_id="pipeline",
                        process_type="pipeline",
                        status=status,
                        error_message=error_msg,
                    )

        except Exception as e:
            result["status"] = TaskStatus.FAILED
            result["error"] = str(e)

        return result

    def _run_load_step(
        self,
        config: MetricConfig,
        from_date: Optional[datetime],
        to_date: Optional[datetime],
        full_refresh: bool,
    ) -> Dict[str, int]:
        """
        Execute data loading step with batching.

        Args:
            config: Metric configuration
            from_date: Start date (optional)
            to_date: End date (optional)
            full_refresh: Delete existing data

        Returns:
            Dict with {"points_loaded": N}
        """
        loader = MetricLoader(
            config=config,
            db_manager=self.db_manager,
            internal_manager=self.internal,
        )

        # Determine date range
        if full_refresh:
            # Delete existing data for this metric
            self.internal.delete_datapoints(
                metric_name=config.name,
                from_timestamp=from_date,
                to_timestamp=to_date,
            )

        # Determine actual from_date and to_date
        actual_from = from_date
        actual_to = to_date

        if actual_from is None:
            # Get last saved timestamp
            last_ts = self.internal.get_last_datapoint_timestamp(config.name)
            if last_ts:
                # Start from next interval after last timestamp
                interval = config.get_interval()
                actual_from = last_ts + timedelta(seconds=interval.seconds)
            else:
                # No data yet - use loading_start_time from config
                if config.loading_start_time:
                    actual_from = datetime.strptime(
                        config.loading_start_time, "%Y-%m-%d %H:%M:%S"
                    ).replace(tzinfo=timezone.utc)
                else:
                    raise ValueError(
                        "No existing data and no loading_start_time configured. "
                        "Please specify from_date or set loading_start_time in config."
                    )

        if actual_to is None:
            actual_to = datetime.now(timezone.utc)

        # Calculate total points and batch size
        interval = config.get_interval()
        total_seconds = (actual_to - actual_from).total_seconds()
        total_points = int(total_seconds / interval.seconds)
        batch_size = config.loading_batch_size

        # If total points <= batch_size, load in one go
        if total_points <= batch_size:
            rows_inserted = loader.load_and_save(from_date=actual_from, to_date=actual_to)
            return {"points_loaded": rows_inserted}

        # Load in batches
        total_loaded = 0
        current_from = actual_from

        while current_from < actual_to:
            # Calculate batch end time
            batch_seconds = batch_size * interval.seconds
            batch_to = current_from + timedelta(seconds=batch_seconds)
            if batch_to > actual_to:
                batch_to = actual_to

            # Load batch
            rows = loader.load_and_save(from_date=current_from, to_date=batch_to)
            total_loaded += rows

            # Move to next batch
            current_from = batch_to

        return {"points_loaded": total_loaded}

    def _run_detect_step(
        self,
        config: MetricConfig,
        from_date: Optional[datetime],
        to_date: Optional[datetime],
        full_refresh: bool = False,
    ) -> Dict[str, int]:
        """
        Execute anomaly detection step with batching and idempotency.

        Args:
            config: Metric configuration
            from_date: Start date for detection (optional)
            to_date: End date for detection (optional)
            full_refresh: Delete existing detections before running

        Returns:
            Dict with {"anomalies_count": N}
        """
        anomalies_count = 0

        # Skip if no detectors configured
        if not config.detectors:
            return {"anomalies_count": 0}

        # Get interval
        interval = config.get_interval()

        # Determine to_date if not specified
        actual_to = to_date or datetime.now(timezone.utc)
        # Normalize to naive datetime (remove timezone info)
        if actual_to and actual_to.tzinfo is not None:
            actual_to = actual_to.replace(tzinfo=None)

        # Normalize from_date to naive
        normalized_from_date = from_date
        if normalized_from_date and normalized_from_date.tzinfo is not None:
            normalized_from_date = normalized_from_date.replace(tzinfo=None)

        # Run each detector
        for detector_config in config.detectors:
            # Create detector to get detector_id
            # Combine algorithm params with execution params (seasonality_components)
            detector_params = detector_config.get_algorithm_params()

            # Add seasonality_components if configured
            seasonality_components = detector_config.get_seasonality_components()
            if seasonality_components is not None:
                detector_params["seasonality_components"] = seasonality_components

            detector_dict = {
                "type": detector_config.type,
                "params": detector_params
            }
            detector = DetectorFactory.create_from_config(detector_dict)
            detector_id = detector.get_detector_id()

            # Delete existing detections if full_refresh
            if full_refresh:
                self.internal.delete_detections(
                    metric_name=config.name,
                    detector_id=detector_id,
                    from_timestamp=normalized_from_date,
                    to_timestamp=actual_to,
                )

            # IDEMPOTENCY: Get last detected timestamp
            last_detection_ts = self.internal.get_last_detection_timestamp(
                metric_name=config.name,
                detector_id=detector_id
            )

            # Determine actual from_date
            actual_from = normalized_from_date
            if not full_refresh and last_detection_ts:
                # Resume from last detected point + 1 interval
                resume_from = last_detection_ts + timedelta(seconds=interval.seconds)
                if actual_from:
                    actual_from = max(actual_from, resume_from)
                else:
                    actual_from = resume_from

            # Apply start_time filter if configured
            start_time_str = detector_config.get_start_time()
            if start_time_str:
                start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
                # Always normalize to naive datetime
                start_time = start_time.replace(tzinfo=None)
                if actual_from:
                    # Ensure actual_from is also naive
                    if actual_from.tzinfo is not None:
                        actual_from = actual_from.replace(tzinfo=None)
                    actual_from = max(actual_from, start_time)
                else:
                    actual_from = start_time

            # Skip if nothing to detect
            if not actual_from or actual_from >= actual_to:
                continue

            # Get batch_size and window_size
            batch_size = detector_config.get_batch_size() or 1000  # Default batch size
            window_size = detector_config.params.get('window_size', 0)

            # Calculate total points to detect
            total_seconds = (actual_to - actual_from).total_seconds()
            total_points = int(total_seconds / interval.seconds)

            # BATCHING: Process in batches
            current_from = actual_from

            while current_from < actual_to:
                # Calculate batch end
                batch_seconds = batch_size * interval.seconds
                batch_to = current_from + timedelta(seconds=batch_seconds)
                if batch_to > actual_to:
                    batch_to = actual_to

                # Calculate window start (need historical data for window)
                window_seconds = window_size * interval.seconds
                window_from = current_from - timedelta(seconds=window_seconds)

                # Load data with window
                data = self.internal.load_datapoints(
                    metric_name=config.name,
                    from_timestamp=window_from,
                    to_timestamp=batch_to,
                )

                if not data or len(data["timestamp"]) == 0:
                    # No data, move to next batch
                    current_from = batch_to
                    continue

                # Run detection on data
                # Detector will handle window sliding internally
                results = detector.detect(data)

                # Filter results to only current batch (not historical window)
                current_from_np = np.datetime64(current_from, 'ms')
                batch_to_np = np.datetime64(batch_to, 'ms')
                batch_results = [
                    r for r in results
                    if current_from_np <= np.datetime64(r.timestamp, 'ms') < batch_to_np
                ]

                # Save results to _dtk_detections
                if batch_results and len(batch_results) > 0:
                    # Convert List[DetectionResult] to dict with numpy arrays
                    detection_data = {
                        "timestamp": np.array([r.timestamp for r in batch_results], dtype="datetime64[ms]"),
                        "is_anomaly": np.array([r.is_anomaly for r in batch_results], dtype=bool),
                        "confidence_lower": np.array([r.confidence_lower for r in batch_results], dtype=np.float64),
                        "confidence_upper": np.array([r.confidence_upper for r in batch_results], dtype=np.float64),
                        "value": np.array([r.value for r in batch_results], dtype=np.float64),
                        "detection_metadata": np.array([
                            json.dumps(r.detection_metadata) if r.detection_metadata else "{}"
                            for r in batch_results
                        ], dtype=object),
                    }

                    self.internal.save_detections(
                        metric_name=config.name,
                        detector_id=detector_id,
                        data=detection_data,
                        detector_params=detector.get_detector_params(),
                    )

                    # Count anomalies
                    anomalies_count += sum(1 for r in batch_results if r.is_anomaly)

                # Move to next batch
                current_from = batch_to

        return {"anomalies_count": anomalies_count}

    def _run_alert_step(self, config: MetricConfig) -> Dict[str, int]:
        """
        Execute alerting step.

        Args:
            config: Metric configuration

        Returns:
            Dict with {"alerts_sent": N}
        """
        alerts_sent = 0

        # Check if alerting is configured
        if not config.alerting or not config.alerting.enabled:
            return {"alerts_sent": 0}

        if not config.alerting.channels:
            return {"alerts_sent": 0}

        # Get alerting config
        alerting_config = config.alerting

        # Create alert orchestrator
        interval = config.get_interval()
        orchestrator = AlertOrchestrator(
            metric_name=config.name,
            interval=interval,
            conditions=AlertConditions(
                min_detectors=1,  # At least one detector must flag anomaly
                direction="any",  # Any direction (up or down)
                consecutive_anomalies=alerting_config.consecutive_anomalies,
            ),
            timezone_display="UTC",
        )

        # Get last complete point
        last_point = orchestrator.get_last_complete_point()

        # Load recent detections for consecutive anomaly checking
        # We need N recent points where N = consecutive_anomalies
        recent_detections = self._load_recent_detections(
            metric_name=config.name,
            last_point=last_point,
            num_points=alerting_config.consecutive_anomalies,
        )

        if not recent_detections:
            return {"alerts_sent": 0}

        # Check if alert should be sent
        should_alert, alert_data = orchestrator.should_alert(recent_detections)

        if should_alert:
            # Create alert channels from config
            channels = self._create_alert_channels(alerting_config.channels)

            if channels:
                # Send alerts
                results = orchestrator.send_alerts(alert_data, channels)
                alerts_sent = sum(1 for success in results.values() if success)

        return {"alerts_sent": alerts_sent}

    def _load_recent_detections(
        self,
        metric_name: str,
        last_point: datetime,
        num_points: int,
    ) -> List[DetectionRecord]:
        """
        Load recent detection records for consecutive anomaly checking.

        Args:
            metric_name: Metric name
            last_point: Last complete timestamp
            num_points: Number of recent points to load

        Returns:
            List of DetectionRecord objects
        """
        # Get full table name for _dtk_detections
        from detectkit.database.tables import TABLE_DETECTIONS
        full_table_name = self.db_manager.get_full_table_name(
            TABLE_DETECTIONS, use_internal=True
        )

        # Query _dtk_detections for recent points
        # GROUP BY timestamp to combine results from multiple detectors
        query = f"""
        SELECT
            timestamp,
            groupArray(detector_id) as detector_ids,
            groupArray(is_anomaly) as is_anomaly_flags,
            groupArray(confidence_lower) as confidence_lowers,
            groupArray(confidence_upper) as confidence_uppers,
            any(value) as value
        FROM {full_table_name}
        WHERE metric_name = %(metric_name)s
          AND timestamp <= %(last_point)s
        GROUP BY timestamp
        ORDER BY timestamp DESC
        LIMIT %(num_points)s
        """

        results = self.db_manager.execute_query(
            query,
            params={
                "metric_name": metric_name,
                "last_point": last_point,
                "num_points": num_points,
            },
        )

        if not results:
            return []

        # Convert to DetectionRecord objects
        records = []
        for row in results:
            # Check if any detector flagged this point as anomaly
            is_anomaly = any(row["is_anomaly_flags"])

            # Get detector IDs that flagged anomaly
            anomaly_detectors = [
                d_id
                for d_id, flag in zip(row["detector_ids"], row["is_anomaly_flags"])
                if flag
            ]

            # Determine direction and severity for the most severe detector
            direction = "none"
            severity = 0.0
            confidence_lower = None
            confidence_upper = None

            if is_anomaly and anomaly_detectors:
                # Get confidence bounds from first detector (they should be similar)
                first_detector_idx = row["detector_ids"].index(anomaly_detectors[0])
                confidence_lower = row["confidence_lowers"][first_detector_idx]
                confidence_upper = row["confidence_uppers"][first_detector_idx]

                # Determine direction
                value = row["value"]
                if value < confidence_lower:
                    direction = "down"
                    severity = (confidence_lower - value) / max(abs(confidence_lower), 1e-10)
                elif value > confidence_upper:
                    direction = "up"
                    severity = (value - confidence_upper) / max(abs(confidence_upper), 1e-10)

            records.append(
                DetectionRecord(
                    timestamp=row["timestamp"],
                    detector_name=anomaly_detectors[0] if anomaly_detectors else "unknown",
                    detector_id=anomaly_detectors[0] if anomaly_detectors else "unknown",
                    value=row["value"],
                    is_anomaly=is_anomaly,
                    confidence_lower=confidence_lower,
                    confidence_upper=confidence_upper,
                    direction=direction,
                    severity=severity,
                    detection_metadata={},
                )
            )

        # Reverse to get chronological order
        return list(reversed(records))

    def _create_alert_channels(
        self, channel_names: List[str]
    ) -> List[BaseAlertChannel]:
        """
        Create alert channel instances from channel names.

        Args:
            channel_names: List of channel names to create

        Returns:
            List of alert channel instances
        """
        if not self.profiles_config:
            # No profiles config available, return empty list
            return []

        channels = []
        for channel_name in channel_names:
            try:
                # Get channel config from profiles
                channel_config = self.profiles_config.get_alert_channel_config(
                    channel_name
                )

                # Create channel instance using factory
                channel = AlertChannelFactory.create_from_config(channel_config)
                channels.append(channel)

            except Exception as e:
                # Log error but continue with other channels
                print(f"Warning: Failed to create channel '{channel_name}': {e}")
                continue

        return channels

    def get_metric_status(self, metric_name: str) -> Optional[Dict]:
        """
        Get current status of a metric.

        Args:
            metric_name: Name of the metric

        Returns:
            Dict with status information or None if not found

        Example:
            >>> status = manager.get_metric_status("cpu_usage")
            >>> print(status["last_run"])
            2024-01-01 12:00:00
        """
        # Check if locked
        lock_info = self.internal.check_lock(metric_name)

        # Get last datapoint timestamp
        last_timestamp = self.internal.get_last_datapoint_timestamp(metric_name)

        return {
            "metric_name": metric_name,
            "is_locked": lock_info is not None,
            "locked_by": lock_info.get("locked_by") if lock_info else None,
            "locked_at": lock_info.get("locked_at") if lock_info else None,
            "last_datapoint": last_timestamp,
        }

    def __repr__(self) -> str:
        """String representation."""
        return f"TaskManager(db={self.db_manager.__class__.__name__})"
