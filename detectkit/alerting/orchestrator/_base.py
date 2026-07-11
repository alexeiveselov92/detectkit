"""Shared state for orchestrator mixins."""

from __future__ import annotations

import numpy as np

from detectkit.alerting.orchestrator._types import (
    AlertConditions,
    DetectionRecord,
)
from detectkit.core.interval import Interval

# How far back the orchestrator looks to reconstruct the *true* length of an
# anomalous run when an alert fires / clears. The decision itself only needs
# ``consecutive_anomalies`` points, but the message reports "how long has this
# been going on", which needs the full streak. Bounded so a metric stuck
# anomalous for a very long time never loads unboundedly — past this the run is
# reported as a lower bound ("over …"). Only queried on fire/recovery, never on
# the hot no-alert path.
STREAK_LOOKBACK_POINTS = 1000


class _OrchestratorBase:
    def __init__(
        self,
        metric_name: str,
        interval: Interval,
        alert_config_id: str,
        conditions: AlertConditions | None = None,
        timezone_display: str = "UTC",
        internal=None,  # InternalTablesManager
        alert_config=None,  # AlertConfig
        description: str | None = None,
        mentions: list[str] | None = None,
        dashboard_url: str | None = None,
        links: dict[str, str] | None = None,
        project_name: str | None = None,
        help_url: str | None = None,
        ai_synonyms: list[str] | None = None,
        loading_delay_seconds: int = 0,
        grid_phase_seconds: int = 0,
    ):
        self.metric_name = metric_name
        self.interval = interval
        self.alert_config_id = alert_config_id
        self.conditions = conditions or AlertConditions()
        self.timezone_display = timezone_display
        self.internal = internal
        self.alert_config = alert_config
        self.description = description
        self.mentions = mentions or []
        self.dashboard_url = dashboard_url
        self.links = links or {}
        # Optional project name (``detectkit_project.yml`` ``name``). Stamped
        # onto every AlertData so channels can label which project an alert
        # came from — keeps multiple projects sharing one channel distinct
        # while the bot keeps the default brand name + avatar.
        self.project_name = project_name
        # Resolved "how to read this alert" link (from ProjectConfig.alert_help_url,
        # defaulting to the official docs; None when opted out). Stamped onto every
        # AlertData so channels render a guide link for non-operator stakeholders.
        self.help_url = help_url
        # OSI ai_context synonyms (the metric's alternative names). Stamped onto
        # every AlertData so channels can render an "Also known as" identity line.
        # Empty list when the metric has no ai_context — renders unchanged.
        self.ai_synonyms = ai_synonyms or []
        # Resolved data-maturity delay (``loading_delay``, metric → project → 0).
        # Constructor state — not a per-call argument — so every internal
        # ``get_last_complete_point()`` call site (the no-data check in the alert
        # step AND the recovery mixin's own fetch bound) computes the same
        # delay-aware boundary as the load step's maturity cut-off.
        self.loading_delay_seconds = int(loading_delay_seconds or 0)
        # Phase of the metric's interval grid on the epoch clock, in
        # [0, interval). The loader anchors datapoints on loading_start_time, so
        # a non-epoch-aligned start puts the stored grid at an arbitrary phase;
        # ``get_last_complete_point`` floors to THIS phase (not plain epoch time)
        # so its exact-timestamp no-data lookup asks for a boundary the loader
        # actually writes. Constructor state, like ``loading_delay_seconds`` —
        # the two together keep the no-data expectation in lockstep with the load
        # step's grid. Defaults to 0 (the epoch grid), so direct-API callers and
        # epoch-aligned metrics are unchanged (issue #114).
        self.grid_phase_seconds = int(grid_phase_seconds or 0) % interval.seconds

    @staticmethod
    def _group_by_timestamp(
        detections: list[DetectionRecord],
    ) -> dict[np.datetime64, list[DetectionRecord]]:
        grouped: dict[np.datetime64, list[DetectionRecord]] = {}
        for d in detections:
            grouped.setdefault(d.timestamp, []).append(d)
        return grouped
