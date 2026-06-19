"""Decision logic: ``should_alert`` and the consecutive-anomaly helpers.

The multi-detector alert contract (documented in docs/guides/alerting.md):

    For every timestamp, an alert *quorum* is the set of anomalous
    detections that match the configured direction policy:

    - ``"up"`` / ``"down"``: only anomalies in that direction count.
      Detectors firing the other way are ignored (they neither help nor
      block the quorum).
    - ``"any"``: every anomaly counts, regardless of direction (an
      up-anomaly and a down-anomaly together can satisfy
      ``min_detectors=2``).
    - ``"same"``: at the latest point at least ``min_detectors`` detectors
      must agree on ONE direction (up- and down-anomalies are counted
      separately; disagreement does not form a quorum). The winning
      direction is then locked for the consecutive walk.

    An alert fires when the latest ``consecutive_anomalies`` timestamps
    each satisfy the quorum AND are exactly one metric interval apart —
    a gap in the detection grid breaks the chain.

    The alert payload (value/CI shown in the message) is built from the
    highest-severity record of the latest quorum; ties are broken by
    detector name, then detector id, so the outcome never depends on SQL
    row ordering.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.orchestrator._base import _OrchestratorBase
from detectkit.alerting.orchestrator._types import DetectionRecord
from detectkit.utils.datetime_utils import now_utc, to_aware_utc


class _DecisionMixin(_OrchestratorBase):
    def should_alert(
        self,
        recent_detections: list[DetectionRecord],
    ) -> tuple[bool, AlertData | None]:
        """Decide whether to fire an alert from recent detections.

        Steps (cheap → expensive):
            1. Bail out on empty input.
            2. Honour the alert cooldown so we don't spam channels.
            3. Walk timestamps newest→oldest counting points where the
               direction-aware quorum holds (see module docstring).
            4. Require ``consecutive_anomalies`` such points on a
               contiguous interval grid.
        """
        if not recent_detections:
            return False, None

        # Cooldown is checked first so a noisy run doesn't waste effort.
        if self._is_in_cooldown():
            return False, None

        detections_by_time = self._group_by_timestamp(recent_detections)
        timestamps_sorted = sorted(detections_by_time.keys(), reverse=True)

        consecutive, latest_quorum, direction = self._count_consecutive_anomalies(
            detections_by_time, timestamps_sorted
        )
        if not latest_quorum or consecutive < self.conditions.consecutive_anomalies:
            return False, None

        return True, self._build_alert_data(latest_quorum, consecutive, direction)

    def _quorum_at(
        self,
        anomalies: list[DetectionRecord],
        locked_direction: str | None,
    ) -> tuple[list[DetectionRecord] | None, str | None]:
        """Anomalies satisfying the direction policy at one timestamp.

        Returns ``(quorum, direction)`` or ``(None, None)`` when the quorum
        is not met. ``locked_direction`` carries the winning direction of
        the latest point through the consecutive walk for ``"same"``.
        """
        policy = self.conditions.direction
        required = self.conditions.min_detectors

        if policy in ("up", "down"):
            qualifying = [d for d in anomalies if d.direction == policy]
            if len(qualifying) >= required:
                return qualifying, policy
            return None, None

        if policy == "same":
            if locked_direction is not None:
                qualifying = [d for d in anomalies if d.direction == locked_direction]
                if len(qualifying) >= required:
                    return qualifying, locked_direction
                return None, None

            ups = [d for d in anomalies if d.direction == "up"]
            downs = [d for d in anomalies if d.direction == "down"]
            candidates = [c for c in (ups, downs) if len(c) >= required]
            if not candidates:
                return None, None
            if len(candidates) == 2:
                if len(ups) != len(downs):
                    winner = ups if len(ups) > len(downs) else downs
                else:
                    # Same detector count in both directions: prefer the
                    # more severe side (deterministic tie-break).
                    winner = max(
                        candidates,
                        key=lambda c: max((d.severity, d.detector_name) for d in c),
                    )
            else:
                winner = candidates[0]
            return winner, winner[0].direction

        # "any" (unknown policies are rejected at config validation; if one
        # sneaks in through the direct API, fail open like "any")
        if len(anomalies) >= required:
            return anomalies, None
        return None, None

    def _count_consecutive_anomalies(
        self,
        detections_by_time: dict[np.datetime64, list[DetectionRecord]],
        timestamps_sorted: list[np.datetime64],
    ) -> tuple[int, list[DetectionRecord] | None, str | None]:
        """Walk timestamps newest→oldest counting quorum-satisfying points.

        The chain requires grid adjacency: each older timestamp must be
        exactly one metric interval before the previous one, so detection
        gaps (days without runs, detector start_time boundaries) are not
        miscounted as "consecutive".

        Returns ``(count, latest_quorum, direction)`` where direction is
        the locked/policy direction (None for "any").
        """
        expected_step = np.timedelta64(self.interval.seconds, "s")
        consecutive = 0
        locked_direction: str | None = None
        latest_quorum: list[DetectionRecord] | None = None
        latest_direction: str | None = None
        prev_ts: np.datetime64 | None = None

        for ts in timestamps_sorted:
            if prev_ts is not None and (prev_ts - ts) != expected_step:
                break

            anomalies = [d for d in detections_by_time[ts] if d.is_anomaly]
            quorum, direction = self._quorum_at(anomalies, locked_direction)
            if quorum is None:
                break

            if self.conditions.direction == "same":
                locked_direction = direction
            if latest_quorum is None:
                latest_quorum = quorum
                latest_direction = direction

            consecutive += 1
            prev_ts = ts

        return consecutive, latest_quorum, latest_direction

    @staticmethod
    def _primary_record(anomalies: list[DetectionRecord]) -> DetectionRecord:
        """Highest-severity record; ties broken by name/id for determinism."""

        def sort_key(d: DetectionRecord):
            severity = d.severity
            if math.isnan(severity):
                severity = 0.0
            elif math.isinf(severity):
                severity = 1e308 if severity > 0 else -1e308
            return (-severity, d.detector_name, d.detector_id)

        return min(anomalies, key=sort_key)

    def _build_alert_data(
        self,
        anomalies: list[DetectionRecord],
        consecutive_count: int,
        direction: str | None,
    ) -> AlertData:
        primary = self._primary_record(anomalies)

        if len(anomalies) > 1:
            max_severity = max(d.severity for d in anomalies)
            detector_names = [d.detector_name for d in anomalies]
            detector_name = f"{len(anomalies)} detectors"
            detector_params = "; ".join(
                f"{d.detector_name}: {d.detector_params}" for d in anomalies
            )
            combined_metadata = {
                "detectors": detector_names,
                "count": len(anomalies),
            }
            for i, d in enumerate(anomalies):
                combined_metadata[f"detector_{i}_metadata"] = d.detection_metadata
        else:
            max_severity = primary.severity
            detector_name = primary.detector_name
            detector_params = primary.detector_params
            combined_metadata = primary.detection_metadata

        # Observed direction shown in the message. For "same"/"up"/"down" the
        # caller passes the locked/policy direction. For "any" it passes None
        # because the quorum may combine directions — collapse to the shared
        # side only when every quorum member agrees, otherwise label it
        # "mixed" so the message never claims an agreement that did not happen
        # (e.g. one up + one down satisfying min_detectors=2).
        if direction:
            observed_direction = direction
        else:
            quorum_dirs = {d.direction for d in anomalies if d.direction in ("up", "down")}
            if len(quorum_dirs) == 1:
                observed_direction = next(iter(quorum_dirs))
            elif len(quorum_dirs) >= 2:
                observed_direction = "mixed"
            else:
                observed_direction = primary.direction

        return AlertData(
            metric_name=self.metric_name,
            timestamp=primary.timestamp,
            timezone=self.timezone_display,
            value=primary.value,
            confidence_lower=primary.confidence_lower,
            confidence_upper=primary.confidence_upper,
            detector_name=detector_name,
            detector_params=detector_params,
            direction=observed_direction,
            severity=max_severity,
            detection_metadata=combined_metadata,
            consecutive_count=consecutive_count,
            description=self.description,
            mentions=self.mentions,
            # Alert rule the message foregrounds: configured thresholds plus
            # the observed quorum size that satisfied them.
            min_detectors=self.conditions.min_detectors,
            direction_policy=self.conditions.direction,
            consecutive_required=self.conditions.consecutive_anomalies,
            detector_count=len(anomalies),
        )

    def should_alert_no_data(
        self,
        last_point: datetime,
    ) -> tuple[bool, AlertData | None]:
        """Decide whether to fire a no-data alert for *last_point*.

        Conditions (all must hold):
            1. ``alert_config.no_data_alert`` is true.
            2. Not currently in alert cooldown for this alert config.
            3. The latest expected datapoint is missing — there is no row
               in ``_dtk_datapoints`` for *last_point* OR the row's value
               is NULL/NaN. ``get_value_at`` returns ``None`` for both.

        ``min_detectors`` and ``consecutive_anomalies`` deliberately do
        not apply here: missing data is a single binary metric-level
        signal, not a per-detector vote.
        """
        if not self.alert_config or not getattr(self.alert_config, "no_data_alert", False):
            return False, None
        if not self.internal:
            return False, None

        if self._is_in_cooldown():
            return False, None

        value = self.internal.get_value_at(self.metric_name, last_point)
        if value is not None and not (isinstance(value, float) and math.isnan(value)):
            return False, None

        return True, self._build_no_data_alert_data(last_point)

    def _build_no_data_alert_data(self, last_point: datetime) -> AlertData:
        """Construct the AlertData payload for a no-data alert."""
        return AlertData(
            metric_name=self.metric_name,
            timestamp=np.datetime64(last_point, "ms"),
            timezone=self.timezone_display,
            value=None,
            confidence_lower=None,
            confidence_upper=None,
            detector_name="no_data",
            detector_params="",
            direction="none",
            severity=0.0,
            detection_metadata={"reason": "no_data"},
            consecutive_count=0,
            is_no_data=True,
            description=self.description,
            mentions=self.mentions,
        )

    def get_last_complete_point(self, now: datetime | None = None) -> datetime:
        """Floor ``now`` to the previous fully completed interval boundary."""
        if now is None:
            now = now_utc()
        now = to_aware_utc(now)

        interval_seconds = self.interval.seconds
        floored = (int(now.timestamp()) // interval_seconds) * interval_seconds
        last_complete = floored - interval_seconds
        return datetime.fromtimestamp(last_complete, tz=timezone.utc)
