"""Tests for the ``loading_delay`` data-maturity delay.

Covers the whole seam: config validation, metric → project → 0 resolution,
the load step's subtract-then-snap end bound (the order that keeps the
boundary on the metric's grid for delays that aren't a multiple of the
interval), the delay-aware ``get_last_complete_point`` that keeps the
no-data expectation in lockstep with the loader, and the opt-in
``{data_delay_*}`` template variables.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.orchestrator import AlertOrchestrator
from detectkit.config.metric_config import MetricConfig, resolve_loading_delay_seconds
from detectkit.config.project_config import ProjectConfig
from detectkit.core.interval import Interval
from detectkit.orchestration.task_manager import TaskManager
from detectkit.orchestration.task_manager import _load_step as load_step_module

UTC = timezone.utc


# ── resolution ──────────────────────────────────────────────────────────────


class TestResolveLoadingDelaySeconds:
    def test_metric_value_wins(self):
        assert resolve_loading_delay_seconds("10min", "1h") == 600

    def test_project_fallback(self):
        assert resolve_loading_delay_seconds(None, "5min") == 300

    def test_metric_zero_opts_out_of_project_default(self):
        assert resolve_loading_delay_seconds(0, "5min") == 0

    def test_unset_everywhere_is_zero(self):
        assert resolve_loading_delay_seconds(None, None) == 0

    def test_int_seconds(self):
        assert resolve_loading_delay_seconds(480, None) == 480

    def test_zero_string_forms_opt_out(self):
        """ "0", "0s", "0min" mean the same explicit opt-out as int 0."""
        for zero in ("0", "0s", "0min"):
            assert resolve_loading_delay_seconds(zero, "5min") == 0


# ── config validation ───────────────────────────────────────────────────────


class TestLoadingDelayValidation:
    def _metric(self, **kwargs):
        return MetricConfig(name="m", interval="10min", query="SELECT 1", **kwargs)

    def test_metric_accepts_duration_string(self):
        assert self._metric(loading_delay="10min").loading_delay == "10min"

    def test_metric_accepts_int_seconds_and_zero(self):
        assert self._metric(loading_delay=480).loading_delay == 480
        assert self._metric(loading_delay=0).loading_delay == 0

    def test_metric_accepts_zero_string_forms(self):
        """A quoted/templated zero ("0", "0min") validates like int 0."""
        for zero in ("0", "0s", "0min"):
            assert self._metric(loading_delay=zero).loading_delay == zero

    def test_metric_default_is_none(self):
        assert self._metric().loading_delay is None

    def test_metric_rejects_garbage(self):
        with pytest.raises(ValueError, match="loading_delay"):
            self._metric(loading_delay="banana")

    def test_metric_rejects_negative(self):
        with pytest.raises(ValueError, match="loading_delay"):
            self._metric(loading_delay=-60)

    def test_project_accepts_and_rejects(self):
        base = {"name": "p", "default_profile": "default"}
        assert ProjectConfig(**base, loading_delay="8min").loading_delay == "8min"
        with pytest.raises(ValueError, match="loading_delay"):
            ProjectConfig(**base, loading_delay="nope")


# ── load step: subtract-then-snap end bound ────────────────────────────────


class _LoaderStub:
    """Stands in for MetricLoader; records every load_and_save window."""

    def __init__(self, config, db_manager, internal_manager, source_profile_name=None):
        self.calls: list[tuple[datetime, datetime]] = []
        _LoaderStub.last_instance = self

    def load_and_save(self, from_date, to_date):
        self.calls.append((from_date, to_date))
        return 1


class TestLoadStepDelay:
    LAST_TS = datetime(2026, 1, 1, 10, 0, 0)

    def _run(self, monkeypatch, *, now, metric_delay=None, project_delay=None, to_date=None):
        monkeypatch.setattr(load_step_module, "MetricLoader", _LoaderStub)
        monkeypatch.setattr(load_step_module, "now_utc_naive", lambda: now)

        internal = Mock()
        internal.get_last_datapoint_timestamp.return_value = self.LAST_TS

        manager = TaskManager(
            internal_manager=internal,
            db_manager=Mock(),
            profiles_config=None,
            project_config=SimpleNamespace(loading_delay=project_delay),
        )
        config = MetricConfig(
            name="m",
            interval="10min",
            query="SELECT 1",
            loading_delay=metric_delay,
        )
        result = manager._run_load_step(config, None, to_date, False)
        return result, _LoaderStub.last_instance

    def test_delay_withholds_immature_interval(self, monkeypatch):
        """At 10:31 with a 10min delay, only buckets mature by 10:21 load."""
        result, loader = self._run(
            monkeypatch, now=datetime(2026, 1, 1, 10, 31, 0), metric_delay="10min"
        )
        assert result["points_loaded"] == 1
        assert loader.calls == [(datetime(2026, 1, 1, 10, 10), datetime(2026, 1, 1, 10, 20))]

    def test_non_multiple_delay_stays_on_grid(self, monkeypatch):
        """Subtract-then-snap: an 8min delay on a 10min grid still lands the
        bound on the grid (snap-then-subtract would produce off-grid 10:22)."""
        result, loader = self._run(
            monkeypatch, now=datetime(2026, 1, 1, 10, 31, 0), metric_delay=480
        )
        assert loader.calls == [(datetime(2026, 1, 1, 10, 10), datetime(2026, 1, 1, 10, 20))]

    def test_delay_defers_load_until_maturity(self, monkeypatch):
        """At 10:27 an 8min delay means bucket [10:10,10:20) isn't mature yet."""
        result, _ = self._run(monkeypatch, now=datetime(2026, 1, 1, 10, 27, 0), metric_delay=480)
        assert result["points_loaded"] == 0

    def test_delay_behind_resume_cursor_is_a_clean_noop(self, monkeypatch):
        """Turning the delay on for a caught-up metric just waits (no crash)."""
        result, _ = self._run(
            monkeypatch, now=datetime(2026, 1, 1, 10, 15, 0), metric_delay="10min"
        )
        assert result["points_loaded"] == 0

    def test_explicit_to_bypasses_delay(self, monkeypatch):
        """An operator-supplied --to is trusted verbatim; no delay applied."""
        result, loader = self._run(
            monkeypatch,
            now=datetime(2026, 1, 1, 10, 31, 0),
            metric_delay="10min",
            to_date=datetime(2026, 1, 1, 10, 30, 0),
        )
        assert loader.calls == [(datetime(2026, 1, 1, 10, 10), datetime(2026, 1, 1, 10, 30))]

    def test_project_delay_applies_when_metric_unset(self, monkeypatch):
        result, loader = self._run(
            monkeypatch, now=datetime(2026, 1, 1, 10, 31, 0), project_delay="8min"
        )
        assert loader.calls == [(datetime(2026, 1, 1, 10, 10), datetime(2026, 1, 1, 10, 20))]

    def test_metric_zero_overrides_project_delay(self, monkeypatch):
        result, loader = self._run(
            monkeypatch,
            now=datetime(2026, 1, 1, 10, 31, 0),
            metric_delay=0,
            project_delay="8min",
        )
        # No delay: both complete buckets ([10:10,10:20) and [10:20,10:30)) load.
        assert loader.calls == [(datetime(2026, 1, 1, 10, 10), datetime(2026, 1, 1, 10, 30))]


# ── alert side: delay-aware last complete point ────────────────────────────


class TestGetLastCompletePointDelay:
    def _orchestrator(self, delay_seconds=0):
        return AlertOrchestrator(
            metric_name="m",
            alert_config_id="cfg",
            interval=Interval("10min"),
            loading_delay_seconds=delay_seconds,
        )

    NOW = datetime(2026, 1, 1, 10, 31, 0, tzinfo=UTC)

    def test_no_delay_baseline(self):
        assert self._orchestrator().get_last_complete_point(self.NOW) == datetime(
            2026, 1, 1, 10, 20, tzinfo=UTC
        )

    def test_one_interval_delay_shifts_expectation_back(self):
        assert self._orchestrator(600).get_last_complete_point(self.NOW) == datetime(
            2026, 1, 1, 10, 10, tzinfo=UTC
        )

    def test_non_multiple_delay(self):
        orch = self._orchestrator(480)
        assert orch.get_last_complete_point(self.NOW) == datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
        assert orch.get_last_complete_point(
            datetime(2026, 1, 1, 10, 39, 0, tzinfo=UTC)
        ) == datetime(2026, 1, 1, 10, 20, tzinfo=UTC)

    def test_no_data_stays_in_lockstep_with_loader(self):
        """The motivating bug: without the delay the no-data check looks up a
        bucket the loader deliberately hasn't written yet and fires falsely;
        with the delay it looks up the newest MATURE bucket and stays quiet."""
        mature_point = datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
        internal = Mock()
        internal.get_value_at.side_effect = lambda name, ts: 5.0 if ts == mature_point else None
        internal.get_last_alert_timestamp.return_value = None
        alert_config = SimpleNamespace(
            no_data_alert=True, alert_cooldown=None, cooldown_reset_on_recovery=False
        )

        delayed = AlertOrchestrator(
            metric_name="m",
            alert_config_id="cfg",
            interval=Interval("10min"),
            internal=internal,
            alert_config=alert_config,
            loading_delay_seconds=600,
        )
        last_point = delayed.get_last_complete_point(self.NOW)
        should, _ = delayed.should_alert_no_data(last_point)
        assert should is False  # newest mature bucket is present — healthy

        undelayed = AlertOrchestrator(
            metric_name="m",
            alert_config_id="cfg",
            interval=Interval("10min"),
            internal=internal,
            alert_config=alert_config,
        )
        last_point = undelayed.get_last_complete_point(self.NOW)
        should, data = undelayed.should_alert_no_data(last_point)
        assert should is True  # the false positive the delay exists to fix
        assert data is not None


# ── messages: opt-in {data_delay_*} variables ──────────────────────────────


class _StubChannel(BaseAlertChannel):
    def send(self, alert_data, template=None):
        return True


def _alert_data(**kwargs):
    return AlertData(
        metric_name="m",
        timestamp=np.datetime64("2026-01-01T10:10:00", "ms"),
        timezone="",
        value=42.0,
        confidence_lower=1.0,
        confidence_upper=10.0,
        detector_name="mad",
        detector_params="{}",
        direction="up",
        severity=1.0,
        detection_metadata={},
        **kwargs,
    )


class TestDataDelayTemplateVars:
    def test_opt_in_vars_present_when_delay_set(self):
        ctx = _StubChannel().build_context(_alert_data(loading_delay_seconds=600))
        assert ctx["data_delay_display"] == "10m"
        assert ctx["data_delay_line"].startswith("Data maturity delay: 10m")

    def test_vars_empty_without_delay(self):
        ctx = _StubChannel().build_context(_alert_data())
        assert ctx["data_delay_display"] == ""
        assert ctx["data_delay_line"] == ""

    def test_default_rendering_untouched(self):
        """The default templates never reference the delay vars, so a delayed
        metric's message renders byte-identically to an undelayed one."""
        channel = _StubChannel()
        with_delay = channel.format_message(_alert_data(loading_delay_seconds=600))
        without = channel.format_message(_alert_data())
        assert with_delay == without
        assert "maturity" not in with_delay.lower()
