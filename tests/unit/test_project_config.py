"""Tests for ProjectConfig fields not covered elsewhere."""

import pytest

from detectkit.config.project_config import ProjectConfig


def _project(**kw) -> ProjectConfig:
    base = {"name": "demo", "default_profile": "ch"}
    base.update(kw)
    return ProjectConfig(**base)


class TestProjectFalseAlertBudget:
    """Project-wide false-alert-rate budget (default for `dtk tune`'s quality bar)."""

    def test_default_is_none(self):
        assert _project().false_alert_budget is None

    def test_valid_fraction_accepted(self):
        assert _project(false_alert_budget=0.25).false_alert_budget == 0.25
        assert _project(false_alert_budget=1.0).false_alert_budget == 1.0

    def test_out_of_range_rejected(self):
        for bad in (0.0, -0.2, 2.0):
            with pytest.raises(ValueError, match="false_alert_budget"):
                _project(false_alert_budget=bad)
