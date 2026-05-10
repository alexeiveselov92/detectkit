"""DETECT pipeline step: runs configured detectors with idempotent batching."""

from __future__ import annotations

from datetime import datetime, timedelta

import click
import numpy as np

from detectkit.config.metric_config import MetricConfig
from detectkit.detectors.factory import DetectorFactory
from detectkit.orchestration.task_manager._base import _TaskManagerBase
from detectkit.utils.datetime_utils import now_utc_naive, to_naive_utc
from detectkit.utils.json_utils import json_dumps_sorted


class _DetectStepMixin(_TaskManagerBase):
    def _run_detect_step(
        self,
        config: MetricConfig,
        from_date: datetime | None,
        to_date: datetime | None,
        full_refresh: bool = False,
    ) -> dict[str, int]:
        """Run every detector in *config* with batching and idempotency."""
        anomalies_count = 0

        if not config.detectors:
            click.echo("  │ No detectors configured, skipping detection")
            return {"anomalies_count": 0}

        interval = config.get_interval()
        click.echo(f"  │ Running {len(config.detectors)} detector(s)...")

        actual_to = to_naive_utc(to_date) if to_date else now_utc_naive()
        normalized_from_date = to_naive_utc(from_date)

        for idx, detector_config in enumerate(config.detectors, 1):
            click.echo("  │")
            click.echo(f"  │ [{idx}/{len(config.detectors)}] " f"Detector: {detector_config.type}")

            detector_params = detector_config.get_algorithm_params()
            seasonality_components = detector_config.get_seasonality_components()
            if seasonality_components is not None:
                detector_params["seasonality_components"] = seasonality_components

            detector = DetectorFactory.create_from_config(
                {"type": detector_config.type, "params": detector_params}
            )
            detector_id = detector.get_detector_id()

            if full_refresh:
                click.echo("  │   Deleting existing detections...")
                self.internal.delete_detections(
                    metric_name=config.name,
                    detector_id=detector_id,
                    from_timestamp=normalized_from_date,
                    to_timestamp=actual_to,
                )

            # Idempotency: resume after the last persisted detection.
            last_detection_ts = to_naive_utc(
                self.internal.get_last_detection_timestamp(
                    metric_name=config.name, detector_id=detector_id
                )
            )

            actual_from = normalized_from_date
            if not full_refresh and last_detection_ts:
                resume_from = last_detection_ts + timedelta(seconds=interval.seconds)
                actual_from = max(actual_from, resume_from) if actual_from else resume_from

            start_time_str = detector_config.get_start_time()
            if start_time_str:
                start_time = to_naive_utc(
                    datetime.fromisoformat(start_time_str.replace("Z", "+00:00"))
                )
                actual_from = max(actual_from, start_time) if actual_from else start_time

            actual_from = to_naive_utc(actual_from)
            if not actual_from or actual_from >= actual_to:
                click.echo("  │   Nothing to detect (already up to date)")
                continue

            batch_size = detector_config.get_batch_size() or 1000
            context_size = detector.get_context_size()

            total_seconds = (actual_to - actual_from).total_seconds()
            total_points = int(total_seconds / interval.seconds)
            if total_points < 1:
                click.echo("  │   Waiting for at least one complete interval")
                continue

            click.echo(
                f"  │   Detecting from {actual_from.strftime('%Y-%m-%d %H:%M:%S')} "
                f"to {actual_to.strftime('%Y-%m-%d %H:%M:%S')}"
            )
            click.echo(f"  │   Total points: ~{total_points:,} | Batch size: {batch_size:,}")

            current_from = actual_from
            detector_anomalies = 0
            num_batches = int(total_points / batch_size) + 1 if total_points > batch_size else 1
            batch_num = 0

            while current_from < actual_to:
                batch_num += 1
                batch_seconds = batch_size * interval.seconds
                batch_to = current_from + timedelta(seconds=batch_seconds)
                if batch_to > actual_to:
                    batch_to = actual_to

                context_seconds = context_size * interval.seconds
                context_from = current_from - timedelta(seconds=context_seconds)

                data = self.internal.load_datapoints(
                    metric_name=config.name,
                    from_timestamp=context_from,
                    to_timestamp=batch_to,
                )
                if not data or len(data["timestamp"]) == 0:
                    current_from = batch_to
                    continue

                results = detector.detect(data)

                # Strip the historical context window from the persisted output.
                current_from_np = np.datetime64(current_from, "ms")
                batch_to_np = np.datetime64(batch_to, "ms")
                batch_results = [
                    r
                    for r in results
                    if current_from_np <= np.datetime64(r.timestamp, "ms") < batch_to_np
                ]

                if batch_results:
                    detection_data = {
                        "timestamp": np.array(
                            [r.timestamp for r in batch_results],
                            dtype="datetime64[ms]",
                        ),
                        "is_anomaly": np.array([r.is_anomaly for r in batch_results], dtype=bool),
                        "confidence_lower": np.array(
                            [r.confidence_lower for r in batch_results],
                            dtype=np.float64,
                        ),
                        "confidence_upper": np.array(
                            [r.confidence_upper for r in batch_results],
                            dtype=np.float64,
                        ),
                        "value": np.array([r.value for r in batch_results], dtype=np.float64),
                        "processed_value": np.array(
                            [r.processed_value for r in batch_results],
                            dtype=np.float64,
                        ),
                        "detection_metadata": np.array(
                            [
                                (
                                    json_dumps_sorted(r.detection_metadata)
                                    if r.detection_metadata
                                    else "{}"
                                )
                                for r in batch_results
                            ],
                            dtype=object,
                        ),
                    }

                    self.internal.save_detections(
                        metric_name=config.name,
                        detector_id=detector_id,
                        detector_name=detector.__class__.__name__,
                        data=detection_data,
                        detector_params=detector.get_detector_params(),
                    )

                    batch_anomalies = sum(1 for r in batch_results if r.is_anomaly)
                    detector_anomalies += batch_anomalies
                    anomalies_count += batch_anomalies

                    if num_batches > 1:
                        click.echo(
                            f"  │     Batch {batch_num}/{num_batches}: "
                            f"{len(batch_results):,} points, "
                            f"{batch_anomalies} anomalies"
                        )

                current_from = batch_to

            click.echo(
                click.style(
                    f"  │   └─ Detected {detector_anomalies:,} anomalies",
                    fg="yellow" if detector_anomalies > 0 else "green",
                )
            )

        click.echo(
            click.style(
                f"  └─ Total anomalies: {anomalies_count:,}",
                fg="yellow" if anomalies_count > 0 else "green",
            )
        )
        return {"anomalies_count": anomalies_count}
