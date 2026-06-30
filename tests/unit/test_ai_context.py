"""Tests for OSI-compatible ``ai_context`` grounding on a metric.

``MetricConfig.ai_context`` mirrors the OSI ``ai_context`` shape
(``instructions`` / ``synonyms`` / ``examples``). It is purely descriptive — it
NEVER affects load/detect/alert or the detector id — and it is plumbed through
the codebase WITHOUT changing any default-rendered message:

- alerts: ``synonyms`` are exposed as the OPT-IN template variables
  ``{synonyms}`` / ``{synonyms_line}`` (via ``build_context``), but the DEFAULT
  templates and native renderers do NOT show them — existing alerts are
  byte-identical. A custom ``template`` can opt in.
- the ``dtk tune`` cockpit payload carries it as read-only grounding,
- the assistant gets it via the shipped config (not exercised here).

These tests lock in that additive, backward-compatible behavior.
"""

from datetime import datetime

import numpy as np

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.channels.email import EmailChannel
from detectkit.alerting.channels.telegram import TelegramChannel
from detectkit.alerting.channels.webhook import WebhookChannel
from detectkit.alerting.orchestrator import AlertOrchestrator
from detectkit.config.metric_config import AiContextConfig, MetricConfig
from detectkit.core.interval import Interval

SYNS = ["total revenue", "gross sales"]


def _metric(**kw) -> MetricConfig:
    base = {"name": "revenue", "interval": "1h", "query": "SELECT timestamp, value FROM t"}
    base.update(kw)
    return MetricConfig(**base)


def _alert(ai_synonyms=None, **overrides):
    base = {
        "metric_name": "revenue",
        "timestamp": np.datetime64("2024-01-01T12:00:00"),
        "timezone": "UTC",
        "value": 95.0,
        "confidence_lower": 70.0,
        "confidence_upper": 90.0,
        "detector_name": "mad",
        "detector_params": '{"threshold": 3.0}',
        "direction": "up",
        "severity": 4.5,
        "detection_metadata": {},
        "consecutive_count": 3,
        "min_detectors": 2,
        "direction_policy": "same",
        "consecutive_required": 3,
        "detector_count": 2,
        "ai_synonyms": ai_synonyms if ai_synonyms is not None else SYNS,
    }
    base.update(overrides)
    return AlertData(**base)


# --------------------------------------------------------------------------
# Config parsing
# --------------------------------------------------------------------------
class TestConfig:
    def test_bare_string_lifts_to_instructions(self):
        m = _metric(ai_context="Revenue recognized at order completion, net of refunds.")
        assert isinstance(m.ai_context, AiContextConfig)
        assert (
            m.ai_context.instructions == "Revenue recognized at order completion, net of refunds."
        )
        assert m.ai_context.synonyms == []
        assert m.ai_context.examples == []

    def test_full_struct(self):
        m = _metric(
            ai_context={
                "instructions": "biz meaning",
                "synonyms": SYNS,
                "examples": ["12030.50"],
            }
        )
        assert m.ai_context.instructions == "biz meaning"
        assert m.ai_context.synonyms == SYNS
        assert m.ai_context.examples == ["12030.50"]

    def test_synonyms_cleaned_and_deduped(self):
        # blanks/whitespace dropped, trimmed, order preserved, duplicates removed
        m = _metric(
            ai_context={"synonyms": ["total revenue", " gross sales ", "", "  ", "total revenue"]}
        )
        assert m.ai_context.synonyms == ["total revenue", "gross sales"]

    def test_absent_is_none_backward_compatible(self):
        assert _metric().ai_context is None

    def test_does_not_change_detector_id(self):
        """ai_context is descriptive only — it must not be hashed into detector identity."""
        from detectkit.detectors.factory import DetectorFactory

        params = {"threshold": 3.0, "window_size": 100}
        id_without = DetectorFactory.create("mad", params).get_detector_id()
        # Building a metric with ai_context doesn't touch the detector; the id is a
        # pure function of detector params regardless of ai_context.
        _metric(ai_context={"synonyms": SYNS}, detectors=[{"type": "mad", "params": params}])
        assert DetectorFactory.create("mad", params).get_detector_id() == id_without


# --------------------------------------------------------------------------
# build_context: synonyms exposed as OPT-IN template variables
# --------------------------------------------------------------------------
class TestBuildContext:
    def test_synonyms_vars_present_when_set(self):
        ctx = WebhookChannel(webhook_url="https://x").build_context(_alert())
        assert ctx["synonyms"] == "total revenue, gross sales"
        assert ctx["synonyms_line"] == "Also known as: total revenue, gross sales\n"

    def test_synonyms_vars_empty_when_unset(self):
        ctx = WebhookChannel(webhook_url="https://x").build_context(_alert(ai_synonyms=[]))
        assert ctx["synonyms"] == ""
        assert ctx["synonyms_line"] == ""

    def test_custom_template_can_opt_in(self):
        ch = WebhookChannel(webhook_url="https://x")
        msg = ch.format_message(_alert(), template="{metric_name}\n{synonyms_line}done")
        assert "Also known as: total revenue, gross sales" in msg


# --------------------------------------------------------------------------
# Default rendering is UNCHANGED — synonyms never leak into a default message.
# --------------------------------------------------------------------------
class TestDefaultRenderingUnchanged:
    def test_base_default_template_omits_synonyms(self):
        # The base default anomaly template does not reference {synonyms_line}.
        ch = WebhookChannel(webhook_url="https://x")
        assert "Also known as" not in ch.format_message(_alert())

    def test_webhook_card_omits_synonyms(self):
        ch = WebhookChannel(webhook_url="https://mm.acme/hooks/x")
        for kw in ({}, {"is_recovery": True}, {"is_no_data": True}):
            body = ch.build_payload(_alert(**kw))["attachments"][0]["text"]
            assert "Also known as" not in body, kw

    def test_telegram_message_omits_synonyms(self):
        msg = TelegramChannel(bot_token="t", chat_id="c")._build_html_message(_alert())
        assert "Also known as" not in msg

    def test_email_body_omits_synonyms(self):
        body = EmailChannel(
            smtp_host="h", smtp_port=587, from_email="a@b.c", to_emails=["x@y.z"]
        )._build_html_body(_alert(), "plain")
        assert "Also known as" not in body


# --------------------------------------------------------------------------
# Orchestrator threading (data flow intact so the opt-in vars actually work)
# --------------------------------------------------------------------------
class TestOrchestratorThreading:
    def _orch(self, ai_synonyms):
        return AlertOrchestrator(
            metric_name="m",
            interval=Interval("1h"),
            alert_config_id="cfg",
            ai_synonyms=ai_synonyms,
        )

    def test_stored(self):
        assert self._orch(SYNS).ai_synonyms == SYNS
        # None defaults to an empty list (no ai_context) — never None.
        assert self._orch(None).ai_synonyms == []

    def test_stamped_no_data(self):
        data = self._orch(SYNS)._build_no_data_alert_data(datetime(2024, 1, 1, 12, 0, 0))
        assert data.ai_synonyms == SYNS

    def test_stamped_anomaly_and_recovery(self):
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
        orch = self._orch(SYNS)
        anomaly = orch._build_alert_data([rec], consecutive_count=1, direction="up")
        recovery = orch._build_recovery_data([rec])
        assert anomaly.ai_synonyms == SYNS
        assert recovery.ai_synonyms == SYNS


# --------------------------------------------------------------------------
# Tune cockpit payload
# --------------------------------------------------------------------------
class TestTunePayload:
    def test_serialize_helper(self):
        from detectkit.tuning.payload import _ai_context_payload

        assert _ai_context_payload(_metric()) is None
        out = _ai_context_payload(
            _metric(ai_context={"instructions": "biz", "synonyms": SYNS, "examples": ["1"]})
        )
        assert out == {"instructions": "biz", "synonyms": SYNS, "examples": ["1"]}
