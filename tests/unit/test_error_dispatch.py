"""Tests for the standalone ``dispatch_project_error_alert`` helper."""

from unittest.mock import Mock

import detectkit.orchestration.error_dispatch as error_dispatch_module
from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.config.project_config import ProjectConfig, ProjectErrorAlertingConfig
from detectkit.orchestration.error_dispatch import dispatch_project_error_alert


class _RecordingChannel(BaseAlertChannel):
    """Minimal channel that records what it was sent."""

    def __init__(self, *, succeed: bool = True):
        self.received = []
        self.succeed = succeed

    def send(self, alert_data, template=None):
        self.received.append((alert_data, template))
        return self.succeed


def _patch_channel_factory(monkeypatch, channel: BaseAlertChannel | None) -> Mock:
    """Patch the helper's channel-resolution path to return *channel*.

    Restored automatically by pytest's ``monkeypatch`` fixture.
    """
    profiles = Mock()
    profiles.get_alert_channel_config.return_value = {"type": "test"}

    if channel is None:
        monkeypatch.setattr(
            error_dispatch_module,
            "_build_channels",
            lambda profiles_config, channel_names: [],
        )
    else:
        monkeypatch.setattr(
            error_dispatch_module,
            "_build_channels",
            lambda profiles_config, channel_names: [channel],
        )
    return profiles


def _make_project(*, enabled: bool = True, channels: list[str] | None = None) -> ProjectConfig:
    return ProjectConfig(
        name="p",
        default_profile="dev",
        error_alerting=ProjectErrorAlertingConfig(
            enabled=enabled,
            channels=channels if channels is not None else ["test_channel"],
            template=None,
            mentions=[],
        ),
    )


class TestDispatchProjectErrorAlert:
    """Behaviour of the standalone dispatcher used by both CLI and TaskManager."""

    def test_disabled_returns_false(self, monkeypatch):
        channel = _RecordingChannel()
        profiles = _patch_channel_factory(monkeypatch, channel)
        result = dispatch_project_error_alert(
            profiles_config=profiles,
            project_config=_make_project(enabled=False),
            metric_name="<startup>",
            exc=RuntimeError("Connection reset by peer"),
        )
        assert result is False
        assert channel.received == []

    def test_no_project_config_returns_false(self, monkeypatch):
        channel = _RecordingChannel()
        profiles = _patch_channel_factory(monkeypatch, channel)
        result = dispatch_project_error_alert(
            profiles_config=profiles,
            project_config=None,
            metric_name="<startup>",
            exc=RuntimeError("boom"),
        )
        assert result is False
        assert channel.received == []

    def test_no_profiles_returns_false(self):
        """Without ``profiles_config`` we can't resolve channels — bail out."""
        result = dispatch_project_error_alert(
            profiles_config=None,
            project_config=_make_project(),
            metric_name="<startup>",
            exc=RuntimeError("boom"),
        )
        assert result is False

    def test_empty_channels_returns_false(self, monkeypatch):
        channel = _RecordingChannel()
        profiles = _patch_channel_factory(monkeypatch, channel)
        result = dispatch_project_error_alert(
            profiles_config=profiles,
            project_config=_make_project(channels=[]),
            metric_name="<startup>",
            exc=RuntimeError("boom"),
        )
        assert result is False
        assert channel.received == []

    def test_dispatches_with_error_metadata(self, monkeypatch):
        """Real failure → channel receives AlertData with error_type/message."""
        channel = _RecordingChannel()
        profiles = _patch_channel_factory(monkeypatch, channel)
        result = dispatch_project_error_alert(
            profiles_config=profiles,
            project_config=_make_project(),
            metric_name="<startup>",
            exc=ConnectionResetError("Connection reset by peer (10.10.0.93:9100)"),
        )

        assert result is True
        assert len(channel.received) == 1
        alert_data, template = channel.received[0]
        assert isinstance(alert_data, AlertData)
        assert alert_data.is_error is True
        assert alert_data.metric_name == "<startup>"
        assert alert_data.error_type == "ConnectionResetError"
        assert "Connection reset by peer" in alert_data.error_message
        assert alert_data.detector_name == "pipeline"
        assert template is None  # no custom template configured

    def test_channel_send_exception_does_not_propagate(self, monkeypatch):
        """A crashing channel must not crash the caller."""
        bad_channel = _RecordingChannel()

        def boom(*args, **kwargs):
            raise ConnectionError("network blew up while sending")

        bad_channel.send = boom
        profiles = _patch_channel_factory(monkeypatch, bad_channel)

        # The caller is already handling another exception — this one must
        # be swallowed rather than masking it.
        result = dispatch_project_error_alert(
            profiles_config=profiles,
            project_config=_make_project(),
            metric_name="<startup>",
            exc=RuntimeError("DB down"),
        )
        assert result is True  # we attempted, even though the channel itself failed
