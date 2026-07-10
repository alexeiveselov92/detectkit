"""Pure historical replay of alert/recovery/no-data events.

Reconstructs the alert events the orchestrator *would have* produced over a
historical period from already-persisted detections — **without** any channel
dispatch, DB state writes or wall-clock. It is the offline counterpart of the
live ``should_alert`` / ``should_send_recovery`` / ``should_alert_no_data`` path:
state (last alert / last recovery) is simulated in memory and the decision at
every grid point is evaluated *causally* (only records with ``timestamp <= t``,
since the windowed detector is causal), reusing the exact same quorum,
consecutive-walk, cooldown and recovery arithmetic as the live path.

Used to answer "what would these detections have alerted on over this window"
for backtesting / autotune alert-window sweeps, where firing real channels and
mutating ``_dtk_alert_states`` would be wrong.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.orchestrator._base import STREAK_LOOKBACK_POINTS, _OrchestratorBase
from detectkit.alerting.orchestrator._types import DetectionRecord
from detectkit.core.interval import Interval


@dataclass(frozen=True)
class ReplayedEvent:
    """One alert event reconstructed by :meth:`_ReplayMixin.replay`.

    ``kind`` is ``"anomaly"``, ``"recovery"`` or ``"no_data"``; ``timestamp`` is
    the grid point at which the event fired (the simulated "now"); ``alert_data``
    is identical in shape to a live :class:`AlertData` (built via the same
    ``_build_*`` helpers as the live path).
    """

    kind: str
    timestamp: np.datetime64
    alert_data: AlertData


class _ReplayMixin(_OrchestratorBase):
    def replay(
        self,
        detections: list[DetectionRecord],
        value_at: dict[np.datetime64, float | None],
        start: datetime,
        end: datetime,
    ) -> list[ReplayedEvent]:
        """Reconstruct alert/recovery/no-data events over ``[start, end]``.

        Forward pass over every interval boundary in the closed range
        ``[start, end]``. At each grid point ``t`` the decision is evaluated
        causally — only ``detections`` with ``timestamp <= t`` are considered —
        reusing the live quorum / consecutive-walk / cooldown / recovery logic.
        Simulated state (last alert / last recovery) lives in memory, so nothing
        is dispatched and no DB row is written.

        Args:
            detections: every persisted detection over the period (any order;
                the same per-detector-per-timestamp shape the live path uses).
            value_at: grid ``np.datetime64`` → value, with ``None`` for a
                missing / NaN datapoint (drives the no-data check).
            start: first grid boundary to evaluate (inclusive).
            end: last grid boundary to evaluate (inclusive).

        Returns:
            The fired events in chronological order.
        """
        by_time = self._group_by_timestamp(detections)

        sim_last_alert: np.datetime64 | None = None
        sim_last_recovery: np.datetime64 | None = None
        events: list[ReplayedEvent] = []

        # The causal view grows monotonically as the grid advances, so it is
        # maintained incrementally: one sorted pass up front, then each grid
        # step admits the newly-covered timestamps (appendleft keeps ts_desc
        # newest-first at O(1)). Rebuilding the dict + re-sorting per grid
        # point — the previous shape — is O(n^2 log n) and turns a month of a
        # 1-minute metric into a multi-minute replay.
        all_ts_asc = sorted(by_time)
        causal: dict[np.datetime64, list[DetectionRecord]] = {}
        ts_desc: deque[np.datetime64] = deque()
        next_ts = 0

        for t in self._replay_grid(start, end):
            while next_ts < len(all_ts_asc) and all_ts_asc[next_ts] <= t:
                ts = all_ts_asc[next_ts]
                causal[ts] = by_time[ts]
                ts_desc.appendleft(ts)
                next_ts += 1

            # No-data fires independently of the quorum (a single binary
            # metric-level signal), only when configured and not in cooldown.
            if (
                self.alert_config
                and getattr(self.alert_config, "no_data_alert", False)
                and value_at.get(t) is None
                and not self._replay_in_cooldown(t, sim_last_alert, sim_last_recovery)
            ):
                last_point = t.astype("datetime64[ms]").astype(datetime)
                events.append(
                    ReplayedEvent("no_data", t, self._build_no_data_alert_data(last_point))
                )
                sim_last_alert = t
                continue

            consecutive, latest_quorum, direction = self._count_consecutive_anomalies(
                causal, ts_desc
            )
            fired_consecutive = (
                latest_quorum is not None and consecutive >= self.conditions.consecutive_anomalies
            )
            # The fraction rule is OR-ed, exactly like the live path — only
            # evaluated when the consecutive rule didn't fire (and only when
            # configured; ``_share_fire`` returns None otherwise).
            share_fire = None if fired_consecutive else self._share_fire(causal, ts_desc)
            fired = (fired_consecutive or share_fire is not None) and not self._replay_in_cooldown(
                t, sim_last_alert, sim_last_recovery
            )

            if fired:
                if fired_consecutive:
                    assert latest_quorum is not None  # narrowed by ``fired_consecutive``
                    streak, onset, capped = self._replay_streak(causal, ts_desc)
                    ad = self._build_alert_data(latest_quorum, streak, direction, onset, capped)
                else:
                    assert share_fire is not None  # narrowed by ``fired``
                    matched, onset, quorum, share_direction = share_fire
                    ad = self._build_alert_data(
                        quorum,
                        matched,
                        share_direction,
                        onset,
                        False,
                        window_matched=matched,
                        fired_by_share=True,
                    )
                events.append(ReplayedEvent("anomaly", t, ad))
                sim_last_alert = t
            elif (
                self.alert_config
                and getattr(self.alert_config, "notify_on_recovery", False)
                and sim_last_alert is not None
                and (sim_last_recovery is None or sim_last_recovery < sim_last_alert)
                and self._replay_recovered(causal, ts_desc, sim_last_alert)
            ):
                slice_ = [d for d in detections if d.timestamp <= t]
                # Pure replay: resolve the just-ended incident from the in-memory
                # slice, never from the DB (keeps replay standalone).
                rd = self._build_recovery_data(slice_, incident_records=slice_)
                if rd is not None:
                    events.append(ReplayedEvent("recovery", t, rd))
                    sim_last_recovery = t

        return events

    def _replay_grid(self, start: datetime, end: datetime) -> list[np.datetime64]:
        """Every interval boundary in the closed range ``[start, end]``.

        Boundaries are produced in ``datetime64[ms]`` so they compare exactly
        with hydrated detection timestamps and ``value_at`` keys.
        """
        step = timedelta(seconds=self.interval.seconds)
        grid: list[np.datetime64] = []
        cur = start
        while cur <= end:
            grid.append(np.datetime64(cur, "ms"))
            cur = cur + step
        return grid

    def _replay_in_cooldown(
        self,
        t: np.datetime64,
        sim_last_alert: np.datetime64 | None,
        sim_last_recovery: np.datetime64 | None,
    ) -> bool:
        """In-memory analog of :meth:`_CooldownMixin._is_in_cooldown`.

        Elapsed time is measured on the grid (``t - sim_last_alert``) rather than
        from the wall clock. ``cooldown_reset_on_recovery`` clears the cooldown
        when a recovery has been simulated since the last alert.
        """
        if not self.alert_config or not getattr(self.alert_config, "alert_cooldown", None):
            return False
        if sim_last_alert is None:
            return False

        cooldown = np.timedelta64(Interval(self.alert_config.alert_cooldown).seconds, "s")
        elapsed = (t - sim_last_alert).astype("timedelta64[s]")

        if getattr(self.alert_config, "cooldown_reset_on_recovery", True):
            if sim_last_recovery is not None and sim_last_recovery > sim_last_alert:
                return False

        return bool(elapsed < cooldown)

    def _replay_recovered(
        self,
        causal: dict[np.datetime64, list[DetectionRecord]],
        ts_desc: Sequence[np.datetime64],
        sim_last_alert: np.datetime64,
    ) -> bool:
        """Pure half of :meth:`_RecoveryMixin._check_recovery_since_last_alert`.

        Returns ``True`` when the metric has recovered as of the latest causal
        point: no blocking anomalies under the trigger direction, OR no causal
        detections strictly after the last simulated alert.
        """
        if not ts_desc:
            # No detections at all → nothing blocking → recovered.
            return True

        # No fresh detections after the alert → assume recovery (mirrors the
        # live "no fresh detections" branch). ts_desc is newest-first, so the
        # head carries the maximum — no full scan needed.
        if not ts_desc[0] > sim_last_alert:
            return True

        latest_ts = ts_desc[0]
        latest_anomalies = [d for d in causal[latest_ts] if d.is_anomaly]

        policy = self.conditions.direction
        locked_direction: str | None = None
        if policy == "down":
            blocking = [d for d in latest_anomalies if d.direction == "down"]
            locked_direction = "down"
        elif policy == "up":
            blocking = [d for d in latest_anomalies if d.direction == "up"]
            locked_direction = "up"
        elif policy == "same":
            trigger_direction = self._replay_trigger_direction(causal, sim_last_alert)
            if trigger_direction is None:
                blocking = latest_anomalies  # conservative fallback
            else:
                blocking = [d for d in latest_anomalies if d.direction == trigger_direction]
            locked_direction = trigger_direction
        else:  # "any" / unknown — preserve historical behaviour
            blocking = latest_anomalies

        if blocking:
            return False
        # Fraction-rule hysteresis (in-memory analog of the live check): a share
        # hovering at the threshold would flap alert/recover, so recovery also
        # requires the window share to drop below half the firing threshold.
        return not self._share_still_elevated(causal, latest_ts, locked_direction)

    def _replay_trigger_direction(
        self,
        causal: dict[np.datetime64, list[DetectionRecord]],
        sim_last_alert: np.datetime64,
    ) -> str | None:
        """Direction of the anomaly that triggered the simulated last alert.

        Pure analog of :meth:`_RecoveryMixin._get_alert_trigger_direction`: the
        live code reads the single detection row at the alert timestamp; here the
        alert fired at the grid point ``sim_last_alert``, so the triggering
        quorum is the latest causal point at or before it.
        """
        candidates = [ts for ts in causal if ts <= sim_last_alert]
        if not candidates:
            return None
        latest_ts = max(candidates)
        anomalies = [d for d in causal[latest_ts] if d.is_anomaly]
        if not anomalies:
            return None

        _, direction = self._quorum_at(anomalies, None)
        if direction in ("up", "down"):
            return direction

        ups = sum(1 for d in anomalies if d.direction == "up")
        downs = sum(1 for d in anomalies if d.direction == "down")
        if ups > downs:
            return "up"
        if downs > ups:
            return "down"
        return None

    def _replay_streak(
        self,
        causal: dict[np.datetime64, list[DetectionRecord]],
        ts_desc: Sequence[np.datetime64],
    ) -> tuple[int, np.datetime64, bool]:
        """In-memory analog of :meth:`_DecisionMixin._resolve_streak`.

        Re-walks the same direction-aware quorum logic over the causal records to
        get the *true* streak length, then derives the onset and the cap flag the
        same way the live path does.
        """
        latest_ts = ts_desc[0]
        step = np.timedelta64(self.interval.seconds, "s")
        count, _, _ = self._count_consecutive_anomalies(causal, ts_desc)
        count = max(count, 1)
        capped = count >= STREAK_LOOKBACK_POINTS
        return count, latest_ts - step * (count - 1), capped
