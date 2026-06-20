"""Tests for the ``dtk test-alert`` preview command.

The preview is meant to render *exactly* what a real ``dtk run`` firing would,
so operators can verify channel formatting. These tests lock in two things that
previously diverged from a real firing:

- the **project-name ``[name]`` prefix** is stamped on the mock alert (the run
  pipeline sets ``project_name`` in ``_alert_step.py``; the preview must too), and
- the metrics directory is resolved from **``paths.metrics``** (the deprecated
  top-level ``metrics_path`` key is ignored by ``ProjectConfig``).
"""

import yaml

from detectkit.alerting.channels.webhook import WebhookChannel
from detectkit.cli.commands import test_alert as test_alert_cmd
from detectkit.cli.commands.test_alert import create_mock_alert_data, run_test_alert
from detectkit.config.metric_config import MetricConfig

METRIC_YAML = """
name: api_error_rate
description: API 5xx error rate
interval: "5min"
query: |
  SELECT toStartOfInterval(timestamp, INTERVAL 5 MINUTE) AS timestamp,
         countIf(status_code >= 500) / count() * 100 AS value
  FROM http_requests
  WHERE timestamp >= '{{ dtk_start_time }}' AND timestamp < '{{ dtk_end_time }}'
  GROUP BY timestamp ORDER BY timestamp
detectors:
  - type: manual_bounds
    params:
      upper_bound: 5.0
alerting:
  enabled: true
  channels:
    - test_ch
  consecutive_anomalies: 2
  direction: "up"
"""


def _metric_config():
    return MetricConfig.model_validate(yaml.safe_load(METRIC_YAML))


def _alerting_config(cfg):
    return cfg.alerting[0]


# --------------------------------------------------------------------------
# create_mock_alert_data — project-name prefix
# --------------------------------------------------------------------------
class TestMockAlertData:
    def test_project_name_stamped(self):
        cfg = _metric_config()
        data = create_mock_alert_data(cfg, _alerting_config(cfg), "UTC", project_name="Kiss 1")
        assert data.project_name == "Kiss 1"

    def test_project_name_none_by_default(self):
        cfg = _metric_config()
        data = create_mock_alert_data(cfg, _alerting_config(cfg), "UTC")
        assert data.project_name is None

    def test_rendered_title_carries_prefix(self):
        # The whole point of the fix: a preview must read like a real firing,
        # i.e. "🔴 [Kiss 1] Alert: api_error_rate".
        cfg = _metric_config()
        data = create_mock_alert_data(cfg, _alerting_config(cfg), "UTC", project_name="Kiss 1")
        title = WebhookChannel(webhook_url="https://x").format_title(data)
        assert "[Kiss 1] Alert: api_error_rate" in title

    def test_rendered_title_no_prefix_when_unset(self):
        cfg = _metric_config()
        data = create_mock_alert_data(cfg, _alerting_config(cfg), "UTC")
        title = WebhookChannel(webhook_url="https://x").format_title(data)
        assert "Alert: api_error_rate" in title
        assert "[" not in title  # no empty/stray project prefix


# --------------------------------------------------------------------------
# run_test_alert — end to end, paths.metrics resolution + project_name threading
# --------------------------------------------------------------------------
def _capture_channels(monkeypatch):
    """Patch the channel factory to record every AlertData asked to be sent.

    Returns the list it captures into. Per-test local state (closed over by the
    fake channel) — no shared class attribute, so tests can't pollute each other.
    """
    sent: list = []

    class _CapturingChannel:
        def send(self, alert_data, template=None):
            sent.append(alert_data)
            return True

    monkeypatch.setattr(
        test_alert_cmd.AlertChannelFactory,
        "create_from_config",
        staticmethod(lambda cfg: _CapturingChannel()),
    )
    return sent


def _write_project(tmp_path, *, metrics_dirname, paths_style="paths"):
    """Write a project. ``paths_style``: "paths" (paths.metrics), "deprecated"
    (legacy top-level metrics_path), or "none" (no paths block at all)."""
    metrics_dir = tmp_path / metrics_dirname
    metrics_dir.mkdir()
    (metrics_dir / "m.yml").write_text(METRIC_YAML)

    paths_block = {
        "paths": f"paths:\n  metrics: {metrics_dirname}\n",
        "deprecated": f"metrics_path: {metrics_dirname}\n",  # ignored by ProjectConfig
        "none": "",
    }[paths_style]
    (tmp_path / "detectkit_project.yml").write_text(
        'name: "Kiss 1"\n' "default_profile: dev\n" + paths_block
    )
    (tmp_path / "profiles.yml").write_text(
        "alert_channels:\n"
        "  test_ch:\n"
        "    type: webhook\n"
        "    webhook_url: https://example.test/hook\n"
    )


def test_run_test_alert_threads_project_name_and_custom_metrics_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _write_project(tmp_path, metrics_dirname="custom_metrics")
    sent = _capture_channels(monkeypatch)

    run_test_alert("api_error_rate")

    # Metric was found under the custom paths.metrics dir AND the alert carried
    # the project label, matching a real firing.
    assert len(sent) == 1
    assert sent[0].project_name == "Kiss 1"
    # Full-chain check: the captured alert renders the [name] prefix a real
    # firing would, not just the bare attribute.
    title = WebhookChannel(webhook_url="https://x").format_title(sent[0])
    assert "[Kiss 1] Alert: api_error_rate" in title


def test_run_test_alert_resolves_default_metrics_dir_without_paths_block(tmp_path, monkeypatch):
    # No paths block at all → the `or {}` / default-"metrics" fallback must still
    # resolve the default `metrics/` dir and fire the preview.
    monkeypatch.chdir(tmp_path)
    _write_project(tmp_path, metrics_dirname="metrics", paths_style="none")
    sent = _capture_channels(monkeypatch)

    run_test_alert("api_error_rate")

    assert len(sent) == 1
    assert sent[0].project_name == "Kiss 1"


def test_run_test_alert_ignores_deprecated_metrics_path_key(tmp_path, monkeypatch, capsys):
    # A project that only sets the deprecated top-level `metrics_path` key (and
    # whose metrics live in a non-default dir) must NOT be found — proving the
    # command reads `paths.metrics`, not the legacy key.
    monkeypatch.chdir(tmp_path)
    _write_project(tmp_path, metrics_dirname="custom_metrics", paths_style="deprecated")
    sent = _capture_channels(monkeypatch)

    run_test_alert("api_error_rate")

    assert sent == []
    # Assert on the metric name (not just the boilerplate wording) so the test
    # pins the not-found branch for THIS metric without coupling to exact phrasing.
    assert "api_error_rate" in capsys.readouterr().out
