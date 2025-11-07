"""
Example usage of detectkit with full pipeline integration.

This demonstrates how to use detectkit with:
- ClickHouse database
- Metric loading
- Anomaly detection (MAD, Z-Score)
- Mattermost alerting
"""

from datetime import datetime, timedelta, timezone

from detectkit.alerting.channels.mattermost import MattermostChannel
from detectkit.config.metric_config import AlertConfig, DetectorConfig, MetricConfig
from detectkit.config.profile import ProfileConfig, ProfilesConfig
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.orchestration.task_manager import PipelineStep, TaskManager


def example_full_pipeline():
    """Example: Full pipeline with ClickHouse and Mattermost."""

    # 1. Create profile configuration
    profile = ProfileConfig(
        type="clickhouse",
        host="localhost",
        port=9000,
        user="default",
        password="",
        internal_database="detectkit_internal",
        data_database="default",
    )

    # 2. Create profiles config with alert channels
    profiles_config = ProfilesConfig(
        profiles={"dev": profile},
        default_profile="dev",
        alert_channels={
            "mattermost_alerts": {
                "type": "mattermost",
                "webhook_url": "https://mattermost.example.com/hooks/xxx",
                "username": "detectkit",
            }
        },
    )

    # 3. Create database manager
    db_manager = profile.create_manager()

    # 4. Create internal tables manager
    internal_manager = InternalTablesManager(db_manager)
    internal_manager.initialize_tables()

    # 5. Create metric configuration
    metric_config = MetricConfig(
        name="cpu_usage",
        query="""
        SELECT
            timestamp,
            cpu_usage as value
        FROM system_metrics
        WHERE metric_name = 'cpu_usage'
          AND timestamp >= {from_date}
          AND timestamp < {to_date}
        ORDER BY timestamp
        """,
        interval="1min",
        detectors=[
            DetectorConfig(type="zscore", params={"threshold": 3.0}),
            DetectorConfig(type="mad", params={"threshold": 3.0}),
        ],
        alerting=AlertConfig(
            enabled=True,
            channels=["mattermost_alerts"],
            consecutive_anomalies=3,
        ),
    )

    # 6. Create task manager
    task_manager = TaskManager(
        internal_manager=internal_manager,
        db_manager=db_manager,
        profiles_config=profiles_config,
    )

    # 7. Run full pipeline
    result = task_manager.run_metric(
        config=metric_config,
        steps=[PipelineStep.LOAD, PipelineStep.DETECT, PipelineStep.ALERT],
        from_date=datetime.now(timezone.utc) - timedelta(hours=1),
        to_date=datetime.now(timezone.utc),
    )

    print("Pipeline execution result:")
    print(f"  Status: {result['status']}")
    print(f"  Datapoints loaded: {result['datapoints_loaded']}")
    print(f"  Anomalies detected: {result['anomalies_detected']}")
    print(f"  Alerts sent: {result['alerts_sent']}")

    if result["error"]:
        print(f"  Error: {result['error']}")


def example_python_api():
    """Example: Using Python API directly (without CLI)."""

    # Create Mattermost channel directly
    channel = MattermostChannel(
        webhook_url="https://mattermost.example.com/hooks/xxx",
        username="detectkit",
        icon_url="https://example.com/icon.png",
    )

    # Send test alert
    from detectkit.alerting.channels.base import AlertData

    alert_data = AlertData(
        metric_name="cpu_usage",
        timestamp=datetime.now(timezone.utc),
        value=95.5,
        is_anomaly=True,
        anomaly_score=4.2,
        expected_value=70.0,
        confidence=0.95,
    )

    success = channel.send(alert_data)
    print(f"Alert sent: {success}")


if __name__ == "__main__":
    print("=" * 60)
    print("detectkit - Full Pipeline Example")
    print("=" * 60)
    print()

    print("Example 1: Python API (direct channel usage)")
    print("-" * 60)
    # Uncomment to test:
    # example_python_api()
    print("(Commented out - set MATTERMOST_WEBHOOK_URL to test)")
    print()

    print("Example 2: Full Pipeline (recommended)")
    print("-" * 60)
    # Uncomment to test:
    # example_full_pipeline()
    print("(Commented out - requires ClickHouse running)")
    print()

    print("To test:")
    print("1. Start ClickHouse: docker run -d -p 9000:9000 clickhouse/clickhouse-server")
    print("2. Set environment variable: export MATTERMOST_WEBHOOK_URL='https://...'")
    print("3. Uncomment example_full_pipeline() above")
    print("4. Run: python example_usage.py")
