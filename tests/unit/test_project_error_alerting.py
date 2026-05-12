"""Tests for project-level error alerting (TaskManager._maybe_send_error_alert)."""

from unittest.mock import Mock

import numpy as np

import detectkit.orchestration.task_manager.manager as manager_module
from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.config.project_config import (
    ProjectConfig,
    ProjectErrorAlertingConfig,
)
from detectkit.orchestration.task_manager import TaskManager, TaskStatus
from detectkit.utils.datetime_utils import now_utc_naive


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


def _make_task_manager(*, project_config):
    """Build a TaskManager with all collaborators mocked."""
    return TaskManager(
        internal_manager=Mock(),
        db_manager=Mock(),
        profiles_config=Mock(),
        project_config=project_config,
    )


def _patch_dispatcher_to_record(monkeypatch, recording_channel: BaseAlertChannel):
    """Replace ``dispatch_project_error_alert`` so it forwards to *recording_channel*.

    Since v0.5.x TaskManager delegates the dispatch to the standalone
    helper (so the CLI can use the same code path for startup failures).
    These tests pin TaskManager's *behaviour around* the dispatcher
    (per-run dedup, abort signalling, return-value plumbing), not the
    dispatcher's internals — those have their own unit tests in
    ``test_error_dispatch.py``.
    """

    def _record(*, profiles_config, project_config, metric_name, exc):
        cfg = project_config.error_alerting
        alert_data = AlertData(
            metric_name=metric_name,
            timestamp=np.datetime64(now_utc_naive(), "ms"),
            timezone=cfg.timezone or "UTC",
            value=None,
            confidence_lower=None,
            confidence_upper=None,
            detector_name="pipeline",
            detector_params="",
            direction="none",
            severity=0.0,
            detection_metadata={"reason": "pipeline_error"},
            consecutive_count=0,
            is_error=True,
            error_type=type(exc).__name__,
            error_message=str(exc),
            description=None,
            mentions=cfg.mentions,
        )
        try:
            recording_channel.send(alert_data, template=cfg.template)
        except Exception:
            pass
        return True

    monkeypatch.setattr(manager_module, "dispatch_project_error_alert", _record)


def _patch_dispatcher_returning(monkeypatch, return_value: bool):
    """Replace the dispatcher with one that just returns *return_value*."""
    monkeypatch.setattr(
        manager_module, "dispatch_project_error_alert", Mock(return_value=return_value)
    )


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

    def test_disabled_returns_false(self, monkeypatch):
        channel = _RecordingChannel()
        _patch_dispatcher_to_record(monkeypatch, channel)
        tm = _make_task_manager(project_config=_make_project_config(enabled=False))
        assert tm._maybe_send_error_alert("m", RuntimeError("boom")) is False
        assert tm._error_alert_sent_in_run is False
        assert channel.received == []  # dispatcher never invoked

    def test_no_project_config_returns_false(self, monkeypatch):
        _patch_dispatcher_to_record(monkeypatch, _RecordingChannel())
        tm = TaskManager(
            internal_manager=Mock(),
            db_manager=Mock(),
            profiles_config=Mock(),
            project_config=None,
        )
        assert tm._maybe_send_error_alert("m", RuntimeError("boom")) is False

    def test_dispatches_to_channel(self, monkeypatch):
        channel = _RecordingChannel()
        _patch_dispatcher_to_record(monkeypatch, channel)
        tm = _make_task_manager(project_config=_make_project_config(mentions=["oncall"]))

        result = tm._maybe_send_error_alert(
            "league_metric",
            RuntimeError("Connection refused (clickhouse-8.services:9100)"),
        )

        assert result is True
        assert tm._error_alert_sent_in_run is True
        assert len(channel.received) == 1

        alert_data, _ = channel.received[0]
        assert isinstance(alert_data, AlertData)
        assert alert_data.is_error is True
        assert alert_data.metric_name == "league_metric"
        assert alert_data.error_type == "RuntimeError"
        assert "Connection refused" in alert_data.error_message
        assert alert_data.mentions == ["oncall"]

    def test_dedup_within_run(self, monkeypatch):
        """Second call in the same run is suppressed but still aborts."""
        channel = _RecordingChannel()
        _patch_dispatcher_to_record(monkeypatch, channel)
        tm = _make_task_manager(project_config=_make_project_config())

        first = tm._maybe_send_error_alert("m1", RuntimeError("a"))
        second = tm._maybe_send_error_alert("m2", RuntimeError("b"))

        assert first is True
        # Already alerted → second call must NOT re-invoke the dispatcher,
        # but MUST still signal abort so the CLI breaks the loop.
        assert second is True
        assert len(channel.received) == 1
        assert channel.received[0][0].metric_name == "m1"

    def test_dispatcher_returning_false_does_not_abort(self, monkeypatch):
        """Helper returning False (e.g. no channels resolved) → no abort."""
        _patch_dispatcher_returning(monkeypatch, False)
        tm = _make_task_manager(project_config=_make_project_config())
        assert tm._maybe_send_error_alert("m", RuntimeError("boom")) is False
        assert tm._error_alert_sent_in_run is False


class TestRunMetricSetsAbortFlag:
    """End-to-end: run_metric pushes ``abort_run`` into the result dict."""

    def test_run_metric_failure_sets_abort_when_error_alerting_enabled(self, monkeypatch):
        from detectkit.config.metric_config import MetricConfig

        channel = _RecordingChannel()
        _patch_dispatcher_to_record(monkeypatch, channel)
        tm = _make_task_manager(project_config=_make_project_config())
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

    def test_run_metric_failure_no_abort_when_disabled(self, monkeypatch):
        from detectkit.config.metric_config import MetricConfig

        _patch_dispatcher_to_record(monkeypatch, _RecordingChannel())
        tm = _make_task_manager(project_config=_make_project_config(enabled=False))
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
        message = channel.format_message(self._error_alert(), template="status={status}")
        assert message == "status=ERROR"

    def test_custom_template_with_error_vars(self):
        channel = _RecordingChannel()
        message = channel.format_message(
            self._error_alert(),
            template="{metric_name}: {error_type} - {error_message}",
        )
        assert message == (
            "cpu_usage: RuntimeError - " "Connection refused (clickhouse-8.services:9100)"
        )

    def test_invalid_format_falls_back_to_default(self):
        """``{value:.2f}`` on an error alert falls back to default error template."""
        channel = _RecordingChannel()
        message = channel.format_message(
            self._error_alert(),
            template="{metric_name}: {value:.2f}",
        )
        assert "Pipeline failed for metric: cpu_usage" in message

    def test_project_name_prefixes_default_title_when_set(self):
        """Multiple projects on the same channel — title must distinguish them."""
        import numpy as np

        channel = _RecordingChannel()
        alert = AlertData(
            metric_name="<startup>",
            timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
            timezone="UTC",
            value=None,
            confidence_lower=None,
            confidence_upper=None,
            detector_name="pipeline",
            detector_params="",
            direction="none",
            severity=0.0,
            detection_metadata={},
            is_error=True,
            error_type="ConnectionResetError",
            error_message="boom",
            project_name="my_monitoring",
        )
        assert channel.format_title(alert) == "[my_monitoring] Pipeline error: <startup>"

    def test_default_title_unchanged_without_project_name(self):
        """When project_name is None the prefix collapses — backwards-compat."""
        channel = _RecordingChannel()
        alert = self._error_alert()  # project_name not set
        assert channel.format_title(alert) == "Pipeline error: cpu_usage"

    def test_project_name_available_in_custom_template(self):
        channel = _RecordingChannel()
        import numpy as np

        alert = AlertData(
            metric_name="<startup>",
            timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
            timezone="UTC",
            value=None,
            confidence_lower=None,
            confidence_upper=None,
            detector_name="pipeline",
            detector_params="",
            direction="none",
            severity=0.0,
            detection_metadata={},
            is_error=True,
            error_type="RuntimeError",
            error_message="x",
            project_name="my_monitoring",
        )
        message = channel.format_message(
            alert,
            template="project={project_name} type={error_type}",
        )
        assert message == "project=my_monitoring type=RuntimeError"
