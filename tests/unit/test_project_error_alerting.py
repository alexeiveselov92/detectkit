"""Tests for project-level error alerting (TaskManager._maybe_send_error_alert)."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.config.project_config import (
    ProjectConfig,
    ProjectErrorAlertingConfig,
)
from detectkit.orchestration.task_manager import TaskManager, TaskStatus


class _RecordingChannel(BaseAlertChannel):
    """Channel that records the AlertData it was sent."""

    def __init__(self, *, succeed: bool = True):
        self.received = []
        self.succeed = succeed

    def send(self, alert_data, template=None):
        self.received.append((alert_data, template))
        return self.succeed


def _make_project_config(
    *,
    enabled: bool = True,
    channels=None,
    template=None,
    mentions=None,
):
    return ProjectConfig(
        name="test_project",
        default_profile="test",
        error_alerting=ProjectErrorAlertingConfig(
            enabled=enabled,
            channels=channels if channels is not None else ["test_channel"],
            template=template,
            mentions=mentions or [],
        ),
    )


def _make_task_manager(
    *, project_config, recording_channel=None, channels_factory=None
):
    """Build a TaskManager and stub _create_alert_channels."""
    tm = TaskManager(
        internal_manager=Mock(),
        db_manager=Mock(),
        profiles_config=Mock(),  # presence-only — channels factory is stubbed
        project_config=project_config,
    )
    if channels_factory is not None:
        tm._create_alert_channels = channels_factory
    elif recording_channel is not None:
        tm._create_alert_channels = lambda names: [recording_channel]
    else:
        tm._create_alert_channels = lambda names: []
    return tm


class TestProjectErrorAlertingConfig:
    """Config parsing & defaults."""

    def test_default_disabled(self):
        cfg = ProjectErrorAlertingConfig()
        assert cfg.enabled is False
        assert cfg.channels == []
        assert cfg.mentions == []
        assert cfg.template is None

    def test_project_config_optional(self):
        """``error_alerting`` is optional on ProjectConfig (back-compat)."""
        cfg = ProjectConfig(name="p", default_profile="x")
        assert cfg.error_alerting is None


class TestMaybeSendErrorAlert:
    """``TaskManager._maybe_send_error_alert`` behaviour."""

    def test_disabled_returns_false(self):
        tm = _make_task_manager(
            project_config=_make_project_config(enabled=False),
            recording_channel=_RecordingChannel(),
        )
        assert tm._maybe_send_error_alert("m", RuntimeError("boom")) is False
        assert tm._error_alert_sent_in_run is False

    def test_no_project_config_returns_false(self):
        tm = TaskManager(
            internal_manager=Mock(),
            db_manager=Mock(),
            profiles_config=Mock(),
            project_config=None,
        )
        tm._create_alert_channels = lambda names: []
        assert tm._maybe_send_error_alert("m", RuntimeError("boom")) is False

    def test_no_channels_in_config_returns_false(self):
        tm = _make_task_manager(
            project_config=_make_project_config(channels=[]),
            recording_channel=_RecordingChannel(),
        )
        assert tm._maybe_send_error_alert("m", RuntimeError("boom")) is False
        assert tm._error_alert_sent_in_run is False

    def test_dispatches_to_channel(self):
        channel = _RecordingChannel()
        tm = _make_task_manager(
            project_config=_make_project_config(mentions=["oncall"]),
            recording_channel=channel,
        )
        result = tm._maybe_send_error_alert(
            "league_metric",
            RuntimeError("Connection refused (clickhouse-8.services:9100)"),
        )

        assert result is True
        assert tm._error_alert_sent_in_run is True
        assert len(channel.received) == 1

        alert_data, template = channel.received[0]
        assert isinstance(alert_data, AlertData)
        assert alert_data.is_error is True
        assert alert_data.metric_name == "league_metric"
        assert alert_data.error_type == "RuntimeError"
        assert "Connection refused" in alert_data.error_message
        assert alert_data.mentions == ["oncall"]

    def test_uses_custom_template(self):
        channel = _RecordingChannel()
        tm = _make_task_manager(
            project_config=_make_project_config(
                template="X={metric_name} Y={error_type}",
            ),
            recording_channel=channel,
        )
        tm._maybe_send_error_alert("m", ValueError("bad"))

        _, template = channel.received[0]
        assert template == "X={metric_name} Y={error_type}"

    def test_dedup_within_run(self):
        """Second call in the same run is suppressed but still aborts."""
        channel = _RecordingChannel()
        tm = _make_task_manager(
            project_config=_make_project_config(),
            recording_channel=channel,
        )

        first = tm._maybe_send_error_alert("m1", RuntimeError("a"))
        second = tm._maybe_send_error_alert("m2", RuntimeError("b"))

        assert first is True
        # Already alerted → second call should NOT dispatch a new alert,
        # but MUST still signal abort so the CLI breaks the loop.
        assert second is True
        assert len(channel.received) == 1
        assert channel.received[0][0].metric_name == "m1"

    def test_channel_dispatch_exception_is_swallowed(self):
        """A crashing channel.send() must not crash run_metric."""
        bad_channel = Mock(spec=BaseAlertChannel)
        bad_channel.__class__ = type(
            "ExplodingChannel", (BaseAlertChannel,), {"send": lambda *_: None}
        )
        bad_channel.send.side_effect = ConnectionError("network blew up")

        tm = _make_task_manager(
            project_config=_make_project_config(),
            recording_channel=bad_channel,
        )
        # No exception should leak out, and we still signal abort + mark sent.
        result = tm._maybe_send_error_alert("m", RuntimeError("boom"))
        assert result is True
        assert tm._error_alert_sent_in_run is True

    def test_no_valid_channels_resolved(self):
        """Channel factory returning [] (e.g. all names invalid) → False, no abort."""
        tm = _make_task_manager(
            project_config=_make_project_config(),
            channels_factory=lambda names: [],
        )
        assert tm._maybe_send_error_alert("m", RuntimeError("boom")) is False
        assert tm._error_alert_sent_in_run is False


class TestRunMetricSetsAbortFlag:
    """End-to-end: run_metric pushes ``abort_run`` into the result dict."""

    def test_run_metric_failure_sets_abort_when_error_alerting_enabled(self):
        from detectkit.config.metric_config import MetricConfig

        channel = _RecordingChannel()
        tm = _make_task_manager(
            project_config=_make_project_config(),
            recording_channel=channel,
        )
        tm.internal.acquire_lock.return_value = True
        # Force LOAD step to blow up like the user's ClickHouse outage.
        tm._run_load_step = Mock(side_effect=RuntimeError("Connection refused"))

        config = Mock(spec=MetricConfig)
        config.name = "league_metric"

        result = tm.run_metric(config=config, force=True)

        assert result["status"] == TaskStatus.FAILED
        assert result["abort_run"] is True
        assert "Connection refused" in result["error"]
        assert len(channel.received) == 1

    def test_run_metric_failure_no_abort_when_disabled(self):
        from detectkit.config.metric_config import MetricConfig

        tm = _make_task_manager(
            project_config=_make_project_config(enabled=False),
            recording_channel=_RecordingChannel(),
        )
        tm.internal.acquire_lock.return_value = True
        tm._run_load_step = Mock(side_effect=RuntimeError("boom"))

        config = Mock(spec=MetricConfig)
        config.name = "m"

        result = tm.run_metric(config=config, force=True)
        assert result["status"] == TaskStatus.FAILED
        assert result["abort_run"] is False


class TestErrorAlertFormatting:
    """Channel-level rendering of error alerts."""

    def _error_alert(self):
        import numpy as np

        return AlertData(
            metric_name="cpu_usage",
            timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
            timezone="UTC",
            value=None,
            confidence_lower=None,
            confidence_upper=None,
            detector_name="pipeline",
            detector_params="",
            direction="none",
            severity=0.0,
            detection_metadata={"reason": "pipeline_error"},
            is_error=True,
            error_type="RuntimeError",
            error_message="Connection refused (clickhouse-8.services:9100)",
        )

    def test_default_template_includes_error_type_and_message(self):
        channel = _RecordingChannel()
        message = channel.format_message(self._error_alert())
        assert "Pipeline failed for metric: cpu_usage" in message
        assert "RuntimeError" in message
        assert "Connection refused" in message

    def test_status_is_error(self):
        channel = _RecordingChannel()
        message = channel.format_message(
            self._error_alert(), template="status={status}"
        )
        assert message == "status=ERROR"

    def test_custom_template_with_error_vars(self):
        channel = _RecordingChannel()
        message = channel.format_message(
            self._error_alert(),
            template="{metric_name}: {error_type} - {error_message}",
        )
        assert message == (
            "cpu_usage: RuntimeError - "
            "Connection refused (clickhouse-8.services:9100)"
        )

    def test_invalid_format_falls_back_to_default(self):
        """``{value:.2f}`` on an error alert falls back to default error template."""
        channel = _RecordingChannel()
        message = channel.format_message(
            self._error_alert(),
            template="{metric_name}: {value:.2f}",
        )
        assert "Pipeline failed for metric: cpu_usage" in message
