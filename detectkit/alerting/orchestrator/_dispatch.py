"""Dispatch mixin — actually sends alerts/recoveries via channels."""

from __future__ import annotations

from typing import Dict, List, Optional

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.orchestrator._base import _OrchestratorBase
from detectkit.utils.datetime_utils import now_utc_naive
from detectkit.utils.logging import get_logger

logger = get_logger(__name__)


class _DispatchMixin(_OrchestratorBase):
    def send_alerts(
        self,
        alert_data: AlertData,
        channels: List[BaseAlertChannel],
        template: Optional[str] = None,
    ) -> Dict[str, bool]:
        """Send *alert_data* to every channel; record success per-channel.

        Updates ``last_alert_sent`` (and increments the counter) when at
        least one channel succeeded — this is what powers cooldown and
        recovery detection.
        """
        results = self._dispatch(channels, alert_data, template, "alert")

        if any(results.values()) and self.internal:
            self.internal.update_alert_timestamp(
                metric_name=self.metric_name,
                alert_config_id=self.alert_config_id,
                timestamp=now_utc_naive(),
                increment_count=True,
            )
        return results

    def send_recovery(
        self,
        alert_data: AlertData,
        channels: List[BaseAlertChannel],
        template: Optional[str] = None,
    ) -> Dict[str, bool]:
        """Send a recovery notification and stamp ``last_recovery_sent``."""
        results = self._dispatch(channels, alert_data, template, "recovery")

        if any(results.values()) and self.internal:
            self.internal.update_recovery_timestamp(
                metric_name=self.metric_name,
                alert_config_id=self.alert_config_id,
                timestamp=now_utc_naive(),
            )
        return results

    @staticmethod
    def _dispatch(
        channels: List[BaseAlertChannel],
        alert_data: AlertData,
        template: Optional[str],
        kind: str,
    ) -> Dict[str, bool]:
        results: Dict[str, bool] = {}
        for channel in channels:
            channel_name = channel.__class__.__name__
            try:
                results[channel_name] = bool(channel.send(alert_data, template))
            except Exception:
                # One bad channel must not abort the others.
                logger.error(
                    "Error sending %s via %s", kind, channel_name, exc_info=True
                )
                results[channel_name] = False
        return results
