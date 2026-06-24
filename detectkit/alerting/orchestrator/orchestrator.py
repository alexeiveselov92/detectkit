"""Composite :class:`AlertOrchestrator` assembled from per-concern mixins."""

from __future__ import annotations

from detectkit.alerting.orchestrator._cooldown import _CooldownMixin
from detectkit.alerting.orchestrator._decision import _DecisionMixin
from detectkit.alerting.orchestrator._dispatch import _DispatchMixin
from detectkit.alerting.orchestrator._recovery import _RecoveryMixin
from detectkit.alerting.orchestrator._replay import _ReplayMixin


class AlertOrchestrator(
    _DecisionMixin,
    _CooldownMixin,
    _RecoveryMixin,
    _ReplayMixin,
    _DispatchMixin,
):
    """Coordinates alert decisions, cooldown, recovery and dispatch.

    The class itself adds no behaviour; each mixin owns one concern:

    * ``_DecisionMixin`` — should we alert? builds AlertData.
    * ``_CooldownMixin`` — suppress within the configured window.
    * ``_RecoveryMixin`` — direction-aware "all-clear" detection.
    * ``_ReplayMixin``   — pure historical replay of alert/recovery/no-data
      events (no dispatch, no DB state, no wall-clock).
    * ``_DispatchMixin``  — ship to channels and stamp state.
    """

    def __repr__(self) -> str:
        return (
            "AlertOrchestrator("
            f"metric='{self.metric_name}', "
            f"interval={self.interval}, "
            f"config_id='{self.alert_config_id[:8]}...', "
            f"min_detectors={self.conditions.min_detectors}, "
            f"direction='{self.conditions.direction}', "
            f"consecutive={self.conditions.consecutive_anomalies})"
        )
