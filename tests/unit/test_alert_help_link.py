"""Tests for the "How to read this alert" stakeholder help link.

Every default-rendered alert carries a guide link (label + URL from
``branding``) so non-operator stakeholders can click through to an
interpretation page. It is on by default (the official docs), redirectable to a
custom URL, and hideable — all via ``ProjectConfig.alert_help_url``. These tests
lock in:

- the per-channel native rendering (webhook field / Telegram link / email footer),
- the ``{help_url}`` / ``{help_line}`` template variables,
- the tri-state config resolution, and
- that the orchestrator stamps the resolved URL onto ``AlertData``.
"""

import numpy as np
import pytest

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.channels.branding import ALERT_GUIDE_LABEL, BRAND_ALERT_GUIDE_URL
from detectkit.alerting.channels.email import EmailChannel
from detectkit.alerting.channels.telegram import TelegramChannel
from detectkit.alerting.channels.webhook import WebhookChannel
from detectkit.alerting.orchestrator import AlertOrchestrator
from detectkit.config.project_config import ProjectConfig, resolve_alert_help_url
from detectkit.core.interval import Interval

CUSTOM_URL = "https://wiki.acme.com/oncall/detectkit"


def _alert(help_url=BRAND_ALERT_GUIDE_URL, **overrides):
    base = {
        "metric_name": "api_errors",
        "timestamp": np.datetime64("2024-01-01T12:00:00"),
        "timezone": "UTC",
        "value": 95.0,
        "confidence_lower": 70.0,
        "confidence_upper": 90.0,
        "detector_name": "mad",
        "detector_params": '{"threshold": 3.0, "window_size": 8640}',
        "direction": "up",
        "severity": 4.5,
        "detection_metadata": {},
        "consecutive_count": 3,
        "min_detectors": 2,
        "direction_policy": "same",
        "consecutive_required": 3,
        "detector_count": 2,
        "project_name": "payments",
        "help_url": help_url,
    }
    base.update(overrides)
    return AlertData(**base)


# --------------------------------------------------------------------------
# build_context / template variables
# --------------------------------------------------------------------------
class TestBuildContext:
    def test_help_vars_present_when_set(self):
        ctx = WebhookChannel(webhook_url="https://x").build_context(_alert())
        assert ctx["help_url"] == BRAND_ALERT_GUIDE_URL
        assert ctx["help_label"] == ALERT_GUIDE_LABEL
        assert ctx["help_line"] == f"{ALERT_GUIDE_LABEL}: {BRAND_ALERT_GUIDE_URL}\n"

    def test_help_vars_empty_when_unset(self):
        ctx = WebhookChannel(webhook_url="https://x").build_context(_alert(help_url=None))
        assert ctx["help_url"] == ""
        assert ctx["help_line"] == ""

    def test_default_template_carries_help_line(self):
        ch = WebhookChannel(webhook_url="https://x")
        msg = ch.format_message(_alert())
        assert f"{ALERT_GUIDE_LABEL}: {BRAND_ALERT_GUIDE_URL}" in msg

    def test_default_template_no_help_line_when_unset(self):
        ch = WebhookChannel(webhook_url="https://x")
        assert ALERT_GUIDE_LABEL not in ch.format_message(_alert(help_url=None))


# --------------------------------------------------------------------------
# Per-channel native rendering
# --------------------------------------------------------------------------
class TestWebhookRendering:
    def test_help_field_rendered(self):
        payload = WebhookChannel(webhook_url="https://x").build_payload(_alert())
        fields = payload["attachments"][0]["fields"]
        help_fields = [f for f in fields if f["title"] == ALERT_GUIDE_LABEL]
        assert len(help_fields) == 1
        assert help_fields[0]["value"] == BRAND_ALERT_GUIDE_URL
        assert help_fields[0]["short"] is False

    def test_help_field_uses_custom_url(self):
        payload = WebhookChannel(webhook_url="https://x").build_payload(_alert(help_url=CUSTOM_URL))
        fields = payload["attachments"][0]["fields"]
        assert any(f["value"] == CUSTOM_URL for f in fields if f["title"] == ALERT_GUIDE_LABEL)

    def test_no_help_field_when_unset(self):
        payload = WebhookChannel(webhook_url="https://x").build_payload(_alert(help_url=None))
        fields = payload["attachments"][0]["fields"]
        assert not any(f["title"] == ALERT_GUIDE_LABEL for f in fields)

    def test_rendered_on_all_alert_kinds(self):
        ch = WebhookChannel(webhook_url="https://x")
        for kw in ({"is_recovery": True}, {"is_no_data": True}, {"is_error": True}):
            payload = ch.build_payload(_alert(**kw))
            fields = payload["attachments"][0]["fields"]
            assert any(f["title"] == ALERT_GUIDE_LABEL for f in fields), kw


class TestTelegramRendering:
    def test_help_link_rendered(self):
        msg = TelegramChannel(bot_token="t", chat_id="c")._build_html_message(_alert())
        assert f'href="{BRAND_ALERT_GUIDE_URL}"' in msg
        assert ALERT_GUIDE_LABEL in msg

    def test_no_help_link_when_unset(self):
        msg = TelegramChannel(bot_token="t", chat_id="c")._build_html_message(_alert(help_url=None))
        assert ALERT_GUIDE_LABEL not in msg

    def test_help_link_alongside_dashboard(self):
        msg = TelegramChannel(bot_token="t", chat_id="c")._build_html_message(
            _alert(dashboard_url="https://grafana.ops/d/x")
        )
        assert "Open dashboard" in msg
        assert ALERT_GUIDE_LABEL in msg


class TestEmailRendering:
    def test_help_link_in_footer(self):
        body = EmailChannel(
            smtp_host="h", smtp_port=587, from_email="a@b.c", to_emails=["x@y.z"]
        )._build_html_body(_alert(), "plain")
        assert f'href="{BRAND_ALERT_GUIDE_URL}"' in body
        assert ALERT_GUIDE_LABEL in body

    def test_no_help_link_when_unset(self):
        body = EmailChannel(
            smtp_host="h", smtp_port=587, from_email="a@b.c", to_emails=["x@y.z"]
        )._build_html_body(_alert(help_url=None), "plain")
        assert ALERT_GUIDE_LABEL not in body


# --------------------------------------------------------------------------
# Config resolution (tri-state)
# --------------------------------------------------------------------------
class TestConfigResolution:
    def test_module_resolver_default(self):
        assert resolve_alert_help_url(None) == BRAND_ALERT_GUIDE_URL
        assert resolve_alert_help_url(True) == BRAND_ALERT_GUIDE_URL
        assert resolve_alert_help_url("") == BRAND_ALERT_GUIDE_URL

    def test_module_resolver_custom_and_off(self):
        assert resolve_alert_help_url(CUSTOM_URL) == CUSTOM_URL
        assert resolve_alert_help_url("  " + CUSTOM_URL + "  ") == CUSTOM_URL
        assert resolve_alert_help_url(False) is None

    def test_project_config_default(self):
        pc = ProjectConfig(name="p", default_profile="x")
        assert pc.alert_help_url is None
        assert pc.resolve_alert_help_url() == BRAND_ALERT_GUIDE_URL

    def test_project_config_custom(self):
        pc = ProjectConfig(name="p", default_profile="x", alert_help_url=CUSTOM_URL)
        assert pc.resolve_alert_help_url() == CUSTOM_URL

    def test_project_config_disabled(self):
        pc = ProjectConfig(name="p", default_profile="x", alert_help_url=False)
        assert pc.resolve_alert_help_url() is None

    def test_project_config_rejects_non_url(self):
        with pytest.raises(ValueError):
            ProjectConfig(name="p", default_profile="x", alert_help_url="not-a-url")


# --------------------------------------------------------------------------
# Orchestrator threading
# --------------------------------------------------------------------------
class TestOrchestratorThreading:
    def _orch(self, help_url):
        return AlertOrchestrator(
            metric_name="m",
            interval=Interval("10min"),
            alert_config_id="cfg",
            help_url=help_url,
        )

    def test_help_url_stored(self):
        assert self._orch(BRAND_ALERT_GUIDE_URL).help_url == BRAND_ALERT_GUIDE_URL
        assert self._orch(None).help_url is None

    def test_help_url_stamped_no_data(self):
        from datetime import datetime

        orch = self._orch(CUSTOM_URL)
        data = orch._build_no_data_alert_data(datetime(2024, 1, 1, 12, 0, 0))
        assert data.help_url == CUSTOM_URL

    def test_help_url_stamped_anomaly_and_recovery(self):
        # Cover the two AlertData builders that don't go through the no-data
        # path, so a regression dropping help_url= from either is caught.
        from detectkit.alerting.orchestrator._types import DetectionRecord

        rec = DetectionRecord(
            timestamp=np.datetime64("2024-01-01T12:00:00"),
            detector_name="mad",
            detector_id="abc123",
            detector_params="{}",
            value=95.0,
            is_anomaly=True,
            confidence_lower=70.0,
            confidence_upper=90.0,
            direction="up",
            severity=4.5,
            detection_metadata={},
        )
        orch = self._orch(CUSTOM_URL)
        anomaly = orch._build_alert_data([rec], consecutive_count=1, direction="up")
        recovery = orch._build_recovery_data([rec])
        assert anomaly.help_url == CUSTOM_URL
        assert recovery.help_url == CUSTOM_URL
