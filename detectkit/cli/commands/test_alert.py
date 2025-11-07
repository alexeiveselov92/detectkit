"""
Test alert command - send test alert to configured channels.

Allows testing alert rendering and channel delivery without real anomalies.
Useful for:
- Verifying Mattermost/Slack message formatting
- Testing webhook connectivity
- Previewing alert templates
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np

from detectkit.alerting.channels.base import AlertData
from detectkit.alerting.channels.factory import AlertChannelFactory
from detectkit.config.metric_config import MetricConfig


def create_mock_alert_data(
    metric_config: MetricConfig,
    timezone_display: str = "UTC",
) -> AlertData:
    """
    Create realistic mock AlertData for testing.

    Args:
        metric_config: Metric configuration
        timezone_display: Timezone for display

    Returns:
        AlertData with mock anomaly data
    """
    # Use current time
    now = datetime.now(timezone.utc)

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
        direction="above",
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
        consecutive_count=3,
    )


def run_test_alert(metric_name: str, profile: Optional[str] = None):
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

    # Find metric config
    metrics_dir = project_root / metrics_dir_name
    metric_files = list(metrics_dir.glob("**/*.yml")) + list(
        metrics_dir.glob("**/*.yaml")
    )

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
    if not metric_config.alerting or not metric_config.alerting.enabled:
        print(f"Error: Alerting not enabled for metric '{metric_name}'")
        print("Enable alerting in metric config (alerting.enabled: true)")
        return

    if not metric_config.alerting.channels:
        print(f"Error: No alert channels configured for metric '{metric_name}'")
        print("Add channels in metric config (alerting.channels: [...])")
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

    # Get timezone for display
    timezone_display = metric_config.alerting.timezone or "UTC"

    # Create mock alert data
    print(f"\n📨 Sending test alert for metric: {metric_name}")
    print(f"   Timezone: {timezone_display}")
    print(f"   Channels: {', '.join(metric_config.alerting.channels)}\n")

    alert_data = create_mock_alert_data(metric_config, timezone_display)

    # Send to each configured channel
    success_count = 0
    for channel_name in metric_config.alerting.channels:
        if channel_name not in alert_channels_config:
            print(f"⚠️  Channel '{channel_name}' not found in profiles.yml - skipping")
            continue

        channel_config = alert_channels_config[channel_name]

        try:
            # Create channel instance
            # channel_config должен содержать 'type' + остальные параметры
            channel = AlertChannelFactory.create_from_config(channel_config)

            # Get custom template if configured
            template = None
            if metric_config.alerting.template_consecutive:
                template = metric_config.alerting.template_consecutive

            # Send alert
            print(f"   → Sending to {channel_name}...", end=" ")
            success = channel.send(alert_data, template=template)

            if success:
                print("✓ SUCCESS")
                success_count += 1
            else:
                print("✗ FAILED")

        except Exception as e:
            print(f"✗ ERROR: {e}")

    # Summary
    print(f"\n{'✓' if success_count > 0 else '✗'} Sent test alert to {success_count}/{len(metric_config.alerting.channels)} channels")

    if success_count > 0:
        print("\n💡 Check your configured channels to verify message formatting")
        print(f"   Mock data used: value=0.8532, confidence=[0.4521, 0.6234], severity=4.52")
