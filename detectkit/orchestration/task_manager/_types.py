"""Pipeline step / status enums and small helpers."""

from __future__ import annotations

import hashlib
from enum import Enum

from detectkit.utils.json_utils import json_dumps_sorted


class PipelineStep(str, Enum):
    """Pipeline execution steps."""

    LOAD = "load"
    DETECT = "detect"
    ALERT = "alert"


class TaskStatus(str, Enum):
    """Final status of a metric run."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


def make_alert_config_id(alerting_config) -> str:
    """Stable 16-char ID for an alerting config block.

    Hashes every field that affects the config's identity so that
    cosmetic edits (e.g. extra whitespace in YAML) don't reset alert
    state, but functional edits (channels, thresholds) do.
    """
    config_dict = {
        "channels": sorted(alerting_config.channels),
        "min_detectors": alerting_config.min_detectors,
        "direction": alerting_config.direction,
        "consecutive_anomalies": alerting_config.consecutive_anomalies,
        "alert_cooldown": (
            str(alerting_config.alert_cooldown) if alerting_config.alert_cooldown else None
        ),
        "cooldown_reset_on_recovery": alerting_config.cooldown_reset_on_recovery,
    }
    return hashlib.md5(json_dumps_sorted(config_dict).encode()).hexdigest()[:16]
