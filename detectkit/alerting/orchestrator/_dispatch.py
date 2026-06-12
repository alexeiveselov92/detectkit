"""Dispatch mixin — actually sends alerts/recoveries via channels."""

from __future__ import annotations

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.orchestrator._base import _OrchestratorBase
from detectkit.utils.datetime_utils import now_utc_naive


class _DispatchMixin(_OrchestratorBase):
    def send_alerts(
        self,
        alert_data: AlertData,
        channels: list[BaseAlertChannel],
        template: str | None = None,
    ) -> dict[str, bool]:
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
        channels: list[BaseAlertChannel],
        template: str | None = None,
    ) -> dict[str, bool]:
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
        channels: list[BaseAlertChannel],
        alert_data: AlertData,
        template: str | None,
        kind: str,
    ) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for channel in channels:
            channel_name = channel.__class__.__name__
            # Two channels of the same type must not collapse into one
            # result entry (that would undercount sends).
            if channel_name in results:
                suffix = 2
                while f"{channel_name}#{suffix}" in results:
                    suffix += 1
                channel_name = f"{channel_name}#{suffix}"
            try:
                results[channel_name] = bool(channel.send(alert_data, template))
            except Exception as exc:
                # One bad channel must not abort the others.
                print(f"Error sending {kind} via {channel_name}: {exc}")
                results[channel_name] = False
        return results
