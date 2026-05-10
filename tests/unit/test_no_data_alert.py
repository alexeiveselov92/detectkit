"""Tests for the ``no_data_alert`` path in the alerting pipeline."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np

from detectkit.alerting.channels.base import AlertData, BaseAlertChannel
from detectkit.alerting.orchestrator import AlertOrchestrator
from detectkit.core.interval import Interval


def _make_alert_config(
    *,
    no_data_alert: bool = True,
    alert_cooldown=None,
    template_no_data=None,
):
    """Build a minimal alert_config stand-in.

    Uses ``SimpleNamespace`` rather than the full pydantic AlertingConfig so
    that we can twiddle individual attributes per test without going through
    full validation.
    """
    return SimpleNamespace(
        no_data_alert=no_data_alert,
        alert_cooldown=alert_cooldown,
        cooldown_reset_on_recovery=False,
        template_no_data=template_no_data,
    )


def _make_internal(value=None, last_alert_timestamp=None):
    """Build a mock InternalTablesManager for the no-data path."""
    internal = Mock()
    internal.get_value_at.return_value = value
    internal.get_last_alert_timestamp.return_value = last_alert_timestamp
    return internal


class TestShouldAlertNoData:
    """Decision logic for ``should_alert_no_data``."""

    last_point = datetime(2024, 1, 1, 12, 0, 0)

    def _orchestrator(self, *, alert_config, internal):
        return AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            internal=internal,
            alert_config=alert_config,
        )

    def test_no_alert_config(self):
        """Without an alert_config, no-data alert never fires."""
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            internal=_make_internal(value=None),
            alert_config=None,
        )

        should, data = orchestrator.should_alert_no_data(self.last_point)
        assert should is False
        assert data is None

    def test_no_data_alert_disabled(self):
        """``no_data_alert=False`` blocks the alert even with missing data."""
        orchestrator = self._orchestrator(
            alert_config=_make_alert_config(no_data_alert=False),
            internal=_make_internal(value=None),
        )

        should, data = orchestrator.should_alert_no_data(self.last_point)
        assert should is False
        assert data is None

    def test_no_internal_manager(self):
        """No internal manager → can't read state, no alert."""
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="test_config_id",
            interval=Interval("10min"),
            internal=None,
            alert_config=_make_alert_config(no_data_alert=True),
        )

        should, data = orchestrator.should_alert_no_data(self.last_point)
        assert should is False
        assert data is None

    def test_fires_when_no_row(self):
        """No row at last_point → alert fires."""
        internal = _make_internal(value=None)
        orchestrator = self._orchestrator(
            alert_config=_make_alert_config(no_data_alert=True),
            internal=internal,
        )

        should, data = orchestrator.should_alert_no_data(self.last_point)
        assert should is True
        assert data is not None
        assert data.is_no_data is True
        assert data.metric_name == "cpu_usage"
        assert data.value is None
        assert data.detector_name == "no_data"
        internal.get_value_at.assert_called_once_with("cpu_usage", self.last_point)

    def test_fires_when_value_is_nan(self):
        """Row exists but value is NaN (gap-fill case) → alert fires.

        ``get_value_at`` already returns ``None`` for NaN-valued rows, but we
        also accept a raw NaN here to keep the orchestrator robust.
        """
        internal = _make_internal(value=float("nan"))
        orchestrator = self._orchestrator(
            alert_config=_make_alert_config(no_data_alert=True),
            internal=internal,
        )

        should, data = orchestrator.should_alert_no_data(self.last_point)
        assert should is True
        assert data is not None

    def test_does_not_fire_when_value_present(self):
        """Real value at last_point → no alert."""
        internal = _make_internal(value=42.0)
        orchestrator = self._orchestrator(
            alert_config=_make_alert_config(no_data_alert=True),
            internal=internal,
        )

        should, data = orchestrator.should_alert_no_data(self.last_point)
        assert should is False
        assert data is None

    def test_blocked_by_cooldown(self):
        """Within ``alert_cooldown`` window → no alert (shared with anomaly)."""
        internal = _make_internal(
            value=None,
            last_alert_timestamp=datetime.utcnow() - timedelta(seconds=60),
        )
        orchestrator = self._orchestrator(
            alert_config=_make_alert_config(no_data_alert=True, alert_cooldown="30min"),
            internal=internal,
        )

        should, data = orchestrator.should_alert_no_data(self.last_point)
        assert should is False
        assert data is None

    def test_cooldown_expired(self):
        """Outside cooldown window → alert fires."""
        internal = _make_internal(
            value=None,
            last_alert_timestamp=datetime.utcnow() - timedelta(hours=2),
        )
        orchestrator = self._orchestrator(
            alert_config=_make_alert_config(no_data_alert=True, alert_cooldown="30min"),
            internal=internal,
        )

        should, data = orchestrator.should_alert_no_data(self.last_point)
        assert should is True
        assert data is not None


class TestNoDataAlertData:
    """Shape of the AlertData payload built by the no-data path."""

    def test_payload_fields(self):
        """All payload fields are set sensibly for downstream channels."""
        internal = _make_internal(value=None)
        orchestrator = AlertOrchestrator(
            metric_name="cpu_usage",
            alert_config_id="cfg",
            interval=Interval("10min"),
            internal=internal,
            alert_config=_make_alert_config(no_data_alert=True),
            timezone_display="Europe/Moscow",
            description="CPU usage on prod cluster",
            mentions=["oncall"],
        )

        last_point = datetime(2024, 1, 1, 12, 0, 0)
        _, data = orchestrator.should_alert_no_data(last_point)

        assert data.metric_name == "cpu_usage"
        assert data.timezone == "Europe/Moscow"
        assert data.value is None
        assert data.confidence_lower is None
        assert data.confidence_upper is None
        assert data.detector_name == "no_data"
        assert data.detector_params == ""
        assert data.direction == "none"
        assert data.severity == 0.0
        assert data.is_no_data is True
        assert data.is_recovery is False
        assert data.description == "CPU usage on prod cluster"
        assert data.mentions == ["oncall"]
        assert data.timestamp == np.datetime64(last_point, "ms")


class _RecordingChannel(BaseAlertChannel):
    """Minimal channel that just records what it was sent."""

    def __init__(self):
        self.received = []

    def send(self, alert_data, template=None):
        self.received.append((alert_data, template))
        return True


class TestNoDataMessageFormatting:
    """Channel-level formatting must not crash on no-data payloads."""

    def _no_data_alert(self, value=None):
        return AlertData(
            metric_name="cpu_usage",
            timestamp=np.datetime64("2024-01-01T12:00:00", "ms"),
            timezone="UTC",
            value=value,
            confidence_lower=None,
            confidence_upper=None,
            detector_name="no_data",
            detector_params="",
            direction="none",
            severity=0.0,
            detection_metadata={"reason": "no_data"},
            is_no_data=True,
        )

    def test_default_template_renders_with_none_value(self):
        """``value=None`` does not crash the default no-data template."""
        channel = _RecordingChannel()
        message = channel.format_message(self._no_data_alert(value=None))

        assert "No data for metric: cpu_usage" in message
        assert "2024-01-01 12:00:00" in message
        assert "no datapoint" in message

    def test_default_template_renders_with_nan_value(self):
        """``value=NaN`` also renders cleanly via ``value_display=\"no data\"``."""
        channel = _RecordingChannel()
        message = channel.format_message(self._no_data_alert(value=float("nan")))

        assert "No data for metric: cpu_usage" in message

    def test_status_variable_is_no_data(self):
        """``{status}`` resolves to ``NO_DATA`` for no-data alerts."""
        channel = _RecordingChannel()
        message = channel.format_message(
            self._no_data_alert(),
            template="status={status} metric={metric_name}",
        )
        assert message == "status=NO_DATA metric=cpu_usage"

    def test_custom_template_with_value_display(self):
        """``{value_display}`` is the safe placeholder for no-data templates."""
        channel = _RecordingChannel()
        message = channel.format_message(
            self._no_data_alert(),
            template="{metric_name}: {value_display}",
        )
        assert message == "cpu_usage: no data"

    def test_invalid_value_format_falls_back_to_default(self):
        """A user template that does ``{value:.2f}`` for a no-data alert
        falls back to the default no-data template instead of crashing."""
        channel = _RecordingChannel()
        message = channel.format_message(
            self._no_data_alert(),
            template="{metric_name}: {value:.2f}",
        )
        assert "No data for metric: cpu_usage" in message


class TestGetValueAt:
    """``InternalTablesManager.get_value_at`` semantics."""

    def _mixin(self, query_result):
        from detectkit.database.internal_tables._datapoints import (
            _DatapointsMixin,
        )

        manager = Mock()
        manager.get_full_table_name.return_value = "internal._dtk_datapoints"
        manager.execute_query.return_value = query_result

        instance = _DatapointsMixin.__new__(_DatapointsMixin)
        instance._manager = manager
        return instance, manager

    def test_returns_none_when_no_row(self):
        instance, _ = self._mixin([])
        assert instance.get_value_at("metric", datetime(2024, 1, 1)) is None

    def test_returns_none_when_value_is_null(self):
        instance, _ = self._mixin([{"value": None}])
        assert instance.get_value_at("metric", datetime(2024, 1, 1)) is None

    def test_returns_none_when_value_is_nan(self):
        instance, _ = self._mixin([{"value": float("nan")}])
        assert instance.get_value_at("metric", datetime(2024, 1, 1)) is None

    def test_returns_float_value(self):
        instance, _ = self._mixin([{"value": 42.5}])
        assert instance.get_value_at("metric", datetime(2024, 1, 1)) == 42.5

    def test_returns_none_when_value_unparsable(self):
        instance, _ = self._mixin([{"value": "not a number"}])
        assert instance.get_value_at("metric", datetime(2024, 1, 1)) is None
