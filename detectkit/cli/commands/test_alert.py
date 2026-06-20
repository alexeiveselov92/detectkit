"""
Test alert command - send test alert to configured channels.

Allows testing alert rendering and channel delivery without real anomalies.
Useful for:
- Verifying Mattermost/Slack message formatting
- Testing webhook connectivity
- Previewing alert templates
"""

from pathlib import Path

import numpy as np

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.channels.factory import AlertChannelFactory
from detectkit.config.metric_config import MetricConfig
from detectkit.utils.datetime_utils import now_utc


def create_mock_alert_data(
    metric_config: MetricConfig,
    alerting_config,
    timezone_display: str = "UTC",
    help_url: str | None = None,
) -> AlertData:
    """
    Create realistic mock AlertData for testing.

    Args:
        metric_config: Metric configuration
        alerting_config: Single ``AlertingConfig`` from
            ``metric_config.alerting`` to source mentions/timezone from.
            ``metric_config.alerting`` is a list — the test command
            iterates it and passes one entry at a time.
        timezone_display: Timezone for display
        help_url: Resolved "how to read this alert" link to preview (the
            project's ``alert_help_url``); ``None`` renders no help link.

    Returns:
        AlertData with mock anomaly data
    """
    # Use current time
    now = now_utc()

    # Mentions are per-AlertingConfig (different alert routes can mention
    # different teams). Pull them from the specific config we're testing.
    mentions = list(alerting_config.mentions) if alerting_config else []

    # Preview the alert with the rule it would actually fire on (min_detectors
    # / direction / consecutive) so the test message matches the alert-centric
    # default layout. Observed counts are set to satisfy the rule, as a real
    # firing would.
    min_detectors = getattr(alerting_config, "min_detectors", 1) or 1
    direction_policy = getattr(alerting_config, "direction", "same") or "same"
    consecutive_required = getattr(alerting_config, "consecutive_anomalies", 1) or 1
    # Observed direction for the preview: a concrete side for up/down/same; for
    # an "any" quorum of 2+ detectors show "mixed" (its whole point is that
    # cross-direction anomalies combine), mirroring the real engine output.
    if direction_policy in ("up", "down"):
        observed_direction = direction_policy
    elif direction_policy == "any" and min_detectors >= 2:
        observed_direction = "mixed"
    else:
        observed_direction = "up"

    # Create realistic mock data
    return AlertData(
        metric_name=metric_config.name,
        timestamp=np.datetime64(now, "ms"),
        timezone=timezone_display,
        value=0.8532,  # Mock anomalous value
        confidence_lower=0.4521,
        confidence_upper=0.6234,
        detector_name="MADDetector:threshold=3.0",
        detector_params='{"threshold": 3.0, "window_size": 8640}',
        direction=observed_direction,
        severity=4.52,
        detection_metadata={
            "global_median": 0.5123,
            "adjusted_median": 0.5234,
            "seasonality_groups": [
                {
                    "group": ["offset_10minutes", "league_day"],
                    "median_multiplier": 1.023,
                    "mad_multiplier": 0.876,
                    "group_size": 23,
                }
            ],
        },
        consecutive_count=consecutive_required,
        mentions=mentions,
        dashboard_url=getattr(alerting_config, "dashboard_url", None),
        links=dict(getattr(alerting_config, "links", {}) or {}),
        help_url=help_url,
        min_detectors=min_detectors,
        direction_policy=direction_policy,
        consecutive_required=consecutive_required,
        detector_count=min_detectors,
    )


def run_test_alert(metric_name: str, profile: str | None = None):
    """
    Send test alert for specified metric.

    Args:
        metric_name: Name of metric to test alert for
        profile: Optional profile override
    """
    # Load project config
    project_root = Path.cwd()
    project_config_path = project_root / "detectkit_project.yml"

    if not project_config_path.exists():
        print("Error: No detectkit_project.yml found in current directory")
        print("Run this command from your detectkit project root")
        return

    # Load project config manually (avoid validation issues)
    import yaml

    with open(project_config_path) as f:
        project_data = yaml.safe_load(f)

    metrics_dir_name = project_data.get("metrics_path", "metrics")

    # Resolve the "how to read this alert" link so the preview matches what real
    # alerts would carry (brand default, a custom URL, or hidden via false).
    from detectkit.config.project_config import resolve_alert_help_url

    help_url = resolve_alert_help_url(project_data.get("alert_help_url"))

    # Find metric config
    metrics_dir = project_root / metrics_dir_name
    metric_files = list(metrics_dir.glob("**/*.yml")) + list(metrics_dir.glob("**/*.yaml"))

    metric_config = None
    for metric_file in metric_files:
        try:
            config = MetricConfig.from_yaml_file(metric_file)
            if config.name == metric_name:
                metric_config = config
                break
        except Exception:
            continue

    if not metric_config:
        print(f"Error: Metric '{metric_name}' not found")
        print(f"Searched in: {metrics_dir}")
        return

    # Check if alerting is configured
    if not metric_config.alerting:
        print(f"Error: Alerting not enabled for metric '{metric_name}'")
        print("Enable alerting in metric config (alerting.enabled: true)")
        return

    active_configs = [c for c in metric_config.alerting if c.enabled and c.channels]
    if not active_configs:
        print(f"Error: No active alert configs for metric '{metric_name}'")
        return

    # Load profiles
    profiles_path = project_root / "profiles.yml"
    if not profiles_path.exists():
        print("Error: profiles.yml not found")
        return

    import yaml

    with open(profiles_path) as f:
        profiles_data = yaml.safe_load(f)

    alert_channels_config = profiles_data.get("alert_channels", {})

    print(f"\n📨 Sending test alert for metric: {metric_name}")

    total_success = 0
    total_channels = 0

    for i, alerting_config in enumerate(active_configs):
        timezone_display = alerting_config.timezone or "UTC"
        if len(active_configs) > 1:
            print(f"\n   [config {i + 1}/{len(active_configs)}]")
        print(f"   Timezone: {timezone_display}")
        print(f"   Channels: {', '.join(alerting_config.channels)}\n")

        alert_data = create_mock_alert_data(
            metric_config, alerting_config, timezone_display, help_url=help_url
        )

        success_count = 0
        for channel_name in alerting_config.channels:
            total_channels += 1
            if channel_name not in alert_channels_config:
                print(f"⚠️  Channel '{channel_name}' not found in profiles.yml - skipping")
                continue

            channel_config = alert_channels_config[channel_name]

            try:
                channel = AlertChannelFactory.create_from_config(channel_config)

                template = alerting_config.template_consecutive or None

                print(f"   → Sending to {channel_name}...", end=" ")
                success = channel.send(alert_data, template=template)

                if success:
                    print("✓ SUCCESS")
                    success_count += 1
                    total_success += 1
                else:
                    print("✗ FAILED")

            except Exception as e:
                print(f"✗ ERROR: {e}")

        print(
            f"\n{'✓' if success_count > 0 else '✗'} Sent test alert to {success_count}/{len(alerting_config.channels)} channels"
        )

    if len(active_configs) > 1:
        print(
            f"\nTotal: {total_success}/{total_channels} channels across {len(active_configs)} alert configs"
        )

    if success_count > 0:
        print("\n💡 Check your configured channels to verify message formatting")
        print("   Mock data used: value=0.8532, confidence=[0.4521, 0.6234], severity=4.52")
