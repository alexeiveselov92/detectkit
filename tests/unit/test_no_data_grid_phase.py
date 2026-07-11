"""Tests for grid-phase-aware no-data alerts (issue #114).

The loader anchors a metric's datapoint grid on ``loading_start_time``, so a
start that isn't a multiple of the interval on the epoch clock (e.g. ``00:07:00``
on a 10-minute grid) puts the whole stored series at an arbitrary phase. The
alert step's no-data check does an *exact-timestamp* lookup, so it must floor to
that same phase — flooring plain epoch time asks for a boundary the loader never
writes and fires a permanent false no-data alert.

Covers the seam end to end: the ``resolve_grid_phase_seconds`` resolver, the
``_TaskManagerBase._grid_phase_seconds`` helper, the phase-aware
``get_last_complete_point`` (with and without a ``loading_delay``), and the
motivating no-data behaviour (a healthy misaligned metric stays quiet; the old
epoch-only floor would have false-fired).
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from detectkit.alerting.orchestrator import AlertOrchestrator
from detectkit.config.metric_config import MetricConfig, resolve_grid_phase_seconds
from detectkit.core.interval import Interval
from detectkit.orchestration.task_manager._base import _TaskManagerBase

UTC = timezone.utc


# ── the resolver: loading_start_time → epoch-grid phase ─────────────────────


class TestResolveGridPhaseSeconds:
    def test_epoch_aligned_start_is_phase_zero(self):
        # Every midnight UTC is a multiple of 600 and 3600.
        assert resolve_grid_phase_seconds("2024-06-01 00:00:00", 600) == 0
        assert resolve_grid_phase_seconds("2024-06-01 00:00:00", 3600) == 0

    def test_misaligned_ten_minute_start(self):
        # 00:07:00 → 7 minutes past a 10-minute boundary.
        assert resolve_grid_phase_seconds("2024-06-01 00:07:00", 600) == 420

    def test_misaligned_hourly_start(self):
        assert resolve_grid_phase_seconds("2024-06-01 00:30:00", 3600) == 1800

    def test_none_is_epoch_grid(self):
        assert resolve_grid_phase_seconds(None, 600) == 0

    def test_unparseable_falls_back_to_epoch_grid(self):
        assert resolve_grid_phase_seconds("not a timestamp", 600) == 0
        assert resolve_grid_phase_seconds("2024-06-01", 600) == 0

    def test_non_positive_interval_is_guarded(self):
        assert resolve_grid_phase_seconds("2024-06-01 00:07:00", 0) == 0

    def test_phase_is_always_in_range(self):
        for start in ("2024-06-01 00:07:00", "2024-06-01 13:23:11", "2024-06-01 00:30:00"):
            for interval in (600, 3600, 25200):
                phase = resolve_grid_phase_seconds(start, interval)
                assert 0 <= phase < interval


# ── the TaskManager helper: config → phase ──────────────────────────────────


class TestGridPhaseHelper:
    def _base(self):
        return _TaskManagerBase(internal_manager=Mock(), db_manager=Mock())

    def test_helper_matches_resolver(self):
        config = MetricConfig(
            name="m", interval="10min", query="SELECT 1", loading_start_time="2024-06-01 00:07:00"
        )
        assert self._base()._grid_phase_seconds(config) == 420

    def test_helper_epoch_grid_without_start(self):
        config = MetricConfig(name="m", interval="10min", query="SELECT 1")
        assert self._base()._grid_phase_seconds(config) == 0


# ── the fix: get_last_complete_point floors on the metric's grid phase ───────


class TestGetLastCompletePointPhase:
    def _orchestrator(self, phase=0, delay=0):
        return AlertOrchestrator(
            metric_name="m",
            alert_config_id="cfg",
            interval=Interval("10min"),
            grid_phase_seconds=phase,
            loading_delay_seconds=delay,
        )

    NOW = datetime(2026, 1, 1, 10, 35, 30, tzinfo=UTC)

    def test_phase_zero_matches_epoch_floor(self):
        # Backward compat: no phase → identical to the epoch-grid behaviour.
        assert self._orchestrator().get_last_complete_point(self.NOW) == datetime(
            2026, 1, 1, 10, 20, tzinfo=UTC
        )

    def test_misaligned_phase_returns_on_grid_boundary(self):
        # :07 grid ⇒ boundaries …:07/:17/:27…; 10:27 is the latest ≤ now, so the
        # last *complete* point is 10:17 — a timestamp the loader actually wrote.
        phase = resolve_grid_phase_seconds("2026-01-01 00:07:00", 600)
        assert self._orchestrator(phase=phase).get_last_complete_point(self.NOW) == datetime(
            2026, 1, 1, 10, 17, tzinfo=UTC
        )

    def test_now_exactly_on_a_boundary(self):
        phase = resolve_grid_phase_seconds("2026-01-01 00:07:00", 600)
        on_boundary = datetime(2026, 1, 1, 10, 27, 0, tzinfo=UTC)
        assert self._orchestrator(phase=phase).get_last_complete_point(on_boundary) == datetime(
            2026, 1, 1, 10, 17, tzinfo=UTC
        )

    def test_phase_and_delay_compose(self):
        # phase :07 + one-interval delay ⇒ effective now 10:25:30 → floor 10:17
        # → last complete 10:07.
        phase = resolve_grid_phase_seconds("2026-01-01 00:07:00", 600)
        assert self._orchestrator(phase=phase, delay=600).get_last_complete_point(
            self.NOW
        ) == datetime(2026, 1, 1, 10, 7, tzinfo=UTC)


# ── the motivating bug: a healthy misaligned metric must stay quiet ──────────


class TestNoDataStaysInLockstepWithGrid:
    """Issue #114: the no-data exact-timestamp lookup must ask for a boundary the
    loader writes. With the phase it stays quiet on a healthy metric; the old
    epoch-only floor asked for a never-written boundary and false-fired."""

    NOW = datetime(2026, 1, 1, 10, 35, 30, tzinfo=UTC)

    def _internal(self, present_point):
        internal = Mock()
        internal.get_value_at.side_effect = lambda name, ts: 5.0 if ts == present_point else None
        internal.get_last_alert_timestamp.return_value = None
        return internal

    def _alert_config(self):
        return SimpleNamespace(
            no_data_alert=True, alert_cooldown=None, cooldown_reset_on_recovery=False
        )

    def test_phase_aware_stays_quiet(self):
        # The loader wrote the :07 grid; 10:17 is the newest complete point.
        phase = resolve_grid_phase_seconds("2026-01-01 00:07:00", 600)
        present = datetime(2026, 1, 1, 10, 17, tzinfo=UTC)
        orch = AlertOrchestrator(
            metric_name="m",
            alert_config_id="cfg",
            interval=Interval("10min"),
            internal=self._internal(present),
            alert_config=self._alert_config(),
            grid_phase_seconds=phase,
        )
        last_point = orch.get_last_complete_point(self.NOW)
        assert last_point == present
        should, _ = orch.should_alert_no_data(last_point)
        assert should is False  # datapoint present on the metric's own grid

    def test_epoch_only_floor_would_false_fire(self):
        # Same healthy :07-grid data, but the pre-fix epoch floor (phase 0) asks
        # for 10:20 — a boundary the loader never writes — and false-fires.
        present = datetime(2026, 1, 1, 10, 17, tzinfo=UTC)
        orch = AlertOrchestrator(
            metric_name="m",
            alert_config_id="cfg",
            interval=Interval("10min"),
            internal=self._internal(present),
            alert_config=self._alert_config(),
            # grid_phase_seconds defaults to 0 — the buggy behaviour.
        )
        last_point = orch.get_last_complete_point(self.NOW)
        assert last_point == datetime(2026, 1, 1, 10, 20, tzinfo=UTC)
        should, data = orch.should_alert_no_data(last_point)
        assert should is True  # the false positive the phase fix removes
        assert data is not None
