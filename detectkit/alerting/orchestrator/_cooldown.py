"""Cooldown logic — suppresses repeat alerts within a configured window."""

from __future__ import annotations

from detectkit.alerting.orchestrator._base import _OrchestratorBase
from detectkit.core.interval import Interval
from detectkit.utils.datetime_utils import now_utc_naive


class _CooldownMixin(_OrchestratorBase):
    def _is_in_cooldown(self) -> bool:
        """Return ``True`` while a previously sent alert is still cooling down.

        Logic:
            1. No ``alert_cooldown`` configured → never in cooldown.
            2. No internal manager wired in → can't read state, allow alert.
            3. Never alerted before → no cooldown.
            4. ``cooldown_reset_on_recovery`` and a recovery has happened
               since the last alert → cooldown is reset, allow alert.
            5. Otherwise: ``elapsed < cooldown_seconds`` → suppress.
        """
        if not self.alert_config or not self.alert_config.alert_cooldown:
            return False
        if not self.internal:
            return False

        last_sent = self.internal.get_last_alert_timestamp(
            self.metric_name, self.alert_config_id
        )
        if not last_sent:
            return False

        cooldown_seconds = Interval(self.alert_config.alert_cooldown).seconds
        elapsed = (now_utc_naive() - last_sent).total_seconds()

        if self.alert_config.cooldown_reset_on_recovery:
            if self._check_recovery_since_last_alert(last_sent):
                return False

        return elapsed < cooldown_seconds
