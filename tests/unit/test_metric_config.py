"""Tests for MetricConfig."""

from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory

import pytest
import yaml

from detectkit.config.metric_config import (
    AlertConfig,
    DetectorConfig,
    MetricConfig,
)


class TestDetectorConfig:
    """Test DetectorConfig model."""

    def test_valid_detector_types(self):
        """Test valid detector types."""
        valid_types = ["mad", "zscore", "iqr", "manual_bounds", "prophet", "timesfm"]

        for detector_type in valid_types:
            config = DetectorConfig(type=detector_type)
            assert config.type == detector_type

    def test_invalid_detector_type(self):
        """Test invalid detector type."""
        with pytest.raises(ValueError, match="Invalid detector type"):
            DetectorConfig(type="invalid_detector")

    def test_detector_with_params(self):
        """Test detector with parameters."""
        config = DetectorConfig(
            type="mad",
            params={"threshold": 3.0, "use_seasonality": True}
        )

        assert config.type == "mad"
        assert config.params["threshold"] == 3.0
        assert config.params["use_seasonality"] is True


class TestAlertConfig:
    """Test AlertConfig model."""

    def test_default_alert_config(self):
        """Test default alert configuration."""
        config = AlertConfig()

        assert config.enabled is True
        assert config.channels == []
        assert config.consecutive_anomalies == 3
        assert config.no_data_alert is False
        assert config.min_detectors == 1
        assert config.direction == "same"

    def test_custom_alert_config(self):
        """Test custom alert configuration."""
        config = AlertConfig(
            enabled=True,
            channels=["mattermost", "slack"],
            consecutive_anomalies=5,
            no_data_alert=True,
            min_detectors=2,
            direction="any",
        )

        assert config.enabled is True
        assert config.channels == ["mattermost", "slack"]
        assert config.consecutive_anomalies == 5
        assert config.no_data_alert is True
        assert config.min_detectors == 2
        assert config.direction == "any"

    def test_invalid_consecutive_anomalies(self):
        """Test validation of consecutive_anomalies."""
        with pytest.raises(ValueError, match="must be at least 1"):
            AlertConfig(consecutive_anomalies=0)


class TestMetricConfig:
    """Test MetricConfig model."""

    def test_metric_with_inline_query(self):
        """Test metric with inline SQL query."""
        config = MetricConfig(
            name="cpu_usage",
            query="SELECT timestamp, value FROM metrics",
            interval="10min",
        )

        assert config.name == "cpu_usage"
        assert config.query == "SELECT timestamp, value FROM metrics"
        assert config.query_file is None
        assert config.interval == "10min"

    def test_metric_with_query_file(self):
        """Test metric with query file."""
        config = MetricConfig(
            name="cpu_usage",
            query_file=Path("sql/cpu_usage.sql"),
            interval=600,
        )

        assert config.name == "cpu_usage"
        assert config.query is None
        assert config.query_file == Path("sql/cpu_usage.sql")
        assert config.interval == 600

    def test_missing_query_source(self):
        """Test error when neither query nor query_file specified."""
        with pytest.raises(ValueError, match="Either 'query' or 'query_file'"):
            MetricConfig(
                name="cpu_usage",
                interval="10min",
            )

    def test_both_query_sources(self):
        """Test error when both query and query_file specified."""
        with pytest.raises(ValueError, match="Only one of"):
            MetricConfig(
                name="cpu_usage",
                query="SELECT 1",
                query_file=Path("sql/query.sql"),
                interval="10min",
            )

    def test_invalid_metric_name(self):
        """Test validation of metric name."""
        # Empty name
        with pytest.raises(ValueError, match="cannot be empty"):
            MetricConfig(
                name="",
                query="SELECT 1",
                interval="10min",
            )

        # Invalid characters
        with pytest.raises(ValueError, match="alphanumeric"):
            MetricConfig(
                name="cpu usage!",
                query="SELECT 1",
                interval="10min",
            )

    def test_valid_metric_names(self):
        """Test valid metric names."""
        valid_names = ["cpu_usage", "cpu-usage", "CpuUsage123", "metric_1"]

        for name in valid_names:
            config = MetricConfig(
                name=name,
                query="SELECT 1",
                interval="10min",
            )
            assert config.name == name

    def test_seasonality_columns(self):
        """Test seasonality columns validation."""
        config = MetricConfig(
            name="cpu_usage",
            query="SELECT 1",
            interval="10min",
            seasonality_columns=["hour", "day_of_week", "is_weekend"],
        )

        assert config.seasonality_columns == ["hour", "day_of_week", "is_weekend"]

    def test_invalid_seasonality_column(self):
        """Test invalid seasonality column."""
        with pytest.raises(ValueError, match="Invalid seasonality column"):
            MetricConfig(
                name="cpu_usage",
                query="SELECT 1",
                interval="10min",
                seasonality_columns=["invalid_column"],
            )

    def test_duplicate_seasonality_columns(self):
        """Test duplicate seasonality columns."""
        with pytest.raises(ValueError, match="Duplicate seasonality"):
            MetricConfig(
                name="cpu_usage",
                query="SELECT 1",
                interval="10min",
                seasonality_columns=["hour", "hour"],
            )

    def test_loading_batch_size_validation(self):
        """Test batch size validation."""
        # Valid batch size
        config = MetricConfig(
            name="cpu_usage",
            query="SELECT 1",
            interval="10min",
            loading_batch_size=5000,
        )
        assert config.loading_batch_size == 5000

        # Too small
        with pytest.raises(ValueError, match="must be at least 1"):
            MetricConfig(
                name="cpu_usage",
                query="SELECT 1",
                interval="10min",
                loading_batch_size=0,
            )

        # Too large
        with pytest.raises(ValueError, match="too large"):
            MetricConfig(
                name="cpu_usage",
                query="SELECT 1",
                interval="10min",
                loading_batch_size=2_000_000,
            )

    def test_get_interval(self):
        """Test get_interval() method."""
        # String interval
        config = MetricConfig(
            name="cpu_usage",
            query="SELECT 1",
            interval="10min",
        )
        interval = config.get_interval()
        assert interval.seconds == 600

        # Int interval
        config = MetricConfig(
            name="cpu_usage",
            query="SELECT 1",
            interval=3600,
        )
        interval = config.get_interval()
        assert interval.seconds == 3600

    def test_get_query_text_inline(self):
        """Test get_query_text() with inline query."""
        config = MetricConfig(
            name="cpu_usage",
            query="SELECT timestamp, value FROM metrics",
            interval="10min",
        )

        query_text = config.get_query_text()
        assert query_text == "SELECT timestamp, value FROM metrics"

    def test_get_query_text_from_file(self):
        """Test get_query_text() from file."""
        # Create temporary SQL file
        with NamedTemporaryFile(mode="w", suffix=".sql", delete=False) as f:
            f.write("SELECT * FROM cpu_metrics WHERE timestamp > NOW() - INTERVAL 1 DAY")
            temp_path = Path(f.name)

        try:
            config = MetricConfig(
                name="cpu_usage",
                query_file=temp_path,
                interval="10min",
            )

            query_text = config.get_query_text()
            assert "SELECT * FROM cpu_metrics" in query_text
        finally:
            temp_path.unlink()

    def test_get_query_text_file_not_found(self):
        """Test get_query_text() when file doesn't exist."""
        config = MetricConfig(
            name="cpu_usage",
            query_file=Path("/nonexistent/query.sql"),
            interval="10min",
        )

        with pytest.raises(FileNotFoundError):
            config.get_query_text()

    def test_metric_with_detectors(self):
        """Test metric with detector configurations."""
        config = MetricConfig(
            name="cpu_usage",
            query="SELECT 1",
            interval="10min",
            detectors=[
                DetectorConfig(type="mad", params={"threshold": 3.0}),
                DetectorConfig(type="zscore", params={"threshold": 2.5}),
            ],
        )

        assert len(config.detectors) == 2
        assert config.detectors[0].type == "mad"
        assert config.detectors[1].type == "zscore"

    def test_metric_with_alerting(self):
        """Test metric with alerting configuration."""
        config = MetricConfig(
            name="cpu_usage",
            query="SELECT 1",
            interval="10min",
            alerting=AlertConfig(
                enabled=True,
                channels=["mattermost"],
                consecutive_anomalies=5,
            ),
        )

        assert config.alerting is not None
        assert config.alerting.enabled is True
        assert config.alerting.channels == ["mattermost"]
        assert config.alerting.consecutive_anomalies == 5

    def test_from_yaml_file(self):
        """Test loading from YAML file."""
        yaml_content = """
name: cpu_usage
query: SELECT timestamp, value FROM metrics
interval: 10min
seasonality_columns:
  - hour
  - day_of_week
loading_batch_size: 5000
detectors:
  - type: mad
    params:
      threshold: 3.0
  - type: zscore
    params:
      threshold: 2.5
alerting:
  enabled: true
  channels:
    - mattermost
  consecutive_anomalies: 3
        """

        with NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = MetricConfig.from_yaml_file(temp_path)

            assert config.name == "cpu_usage"
            assert config.query == "SELECT timestamp, value FROM metrics"
            assert config.interval == "10min"
            assert config.seasonality_columns == ["hour", "day_of_week"]
            assert config.loading_batch_size == 5000
            assert len(config.detectors) == 2
            assert config.alerting.enabled is True
        finally:
            temp_path.unlink()

    def test_from_yaml_file_not_found(self):
        """Test error when YAML file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            MetricConfig.from_yaml_file(Path("/nonexistent/config.yml"))

    def test_from_yaml_file_empty(self):
        """Test error when YAML file is empty."""
        with NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("")
            temp_path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="Empty metric config"):
                MetricConfig.from_yaml_file(temp_path)
        finally:
            temp_path.unlink()
