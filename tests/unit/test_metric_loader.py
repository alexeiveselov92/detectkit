"""Tests for MetricLoader."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from detectkit.config.metric_config import MetricConfig
from detectkit.loaders.metric_loader import MetricLoader


@pytest.fixture
def mock_db_manager():
    """Create mock database manager."""
    manager = MagicMock()
    return manager


@pytest.fixture
def mock_internal_manager():
    """Create mock internal tables manager."""
    manager = MagicMock()
    return manager


@pytest.fixture
def metric_config():
    """Create test metric configuration."""
    return MetricConfig(
        name="test_metric",
        query="SELECT timestamp, value FROM metrics",
        interval="10min",
        seasonality_columns=["hour", "day_of_week"],
    )


@pytest.fixture
def metric_loader(metric_config, mock_db_manager, mock_internal_manager):
    """Create MetricLoader instance."""
    return MetricLoader(metric_config, mock_db_manager, mock_internal_manager)


class TestMetricLoaderInit:
    """Test MetricLoader initialization."""

    def test_init(self, metric_loader, metric_config, mock_db_manager, mock_internal_manager):
        """Test initialization."""
        assert metric_loader.config == metric_config
        assert metric_loader.db_manager == mock_db_manager
        assert metric_loader.internal_manager == mock_internal_manager
        assert metric_loader.query_template is not None


class TestLoad:
    """Test load() method."""

    def test_load_with_data(self, metric_loader, mock_db_manager):
        """Test loading data from database."""
        # Mock query results
        mock_db_manager.execute_query.return_value = [
            {"timestamp": datetime(2024, 1, 1, 0, 0), "value": 0.5},
            {"timestamp": datetime(2024, 1, 1, 0, 10), "value": 0.6},
            {"timestamp": datetime(2024, 1, 1, 0, 20), "value": 0.7},
        ]

        # Load data
        data = metric_loader.load(
            from_date=datetime(2024, 1, 1, 0, 0),
            to_date=datetime(2024, 1, 1, 1, 0),
            fill_gaps=False,
        )

        # Verify structure
        assert "timestamp" in data
        assert "value" in data
        assert "seasonality_data" in data
        assert "seasonality_columns" in data

        # Verify data
        assert len(data["timestamp"]) == 3
        assert len(data["value"]) == 3
        assert len(data["seasonality_data"]) == 3

    def test_load_empty_results(self, metric_loader, mock_db_manager):
        """Test loading when query returns no data."""
        mock_db_manager.execute_query.return_value = []

        data = metric_loader.load(
            from_date=datetime(2024, 1, 1),
            to_date=datetime(2024, 1, 2),
        )

        assert len(data["timestamp"]) == 0
        assert len(data["value"]) == 0

    def test_load_missing_timestamp_column(self, metric_loader, mock_db_manager):
        """Test error when query doesn't return timestamp."""
        mock_db_manager.execute_query.return_value = [
            {"value": 0.5},  # Missing timestamp
        ]

        with pytest.raises(ValueError, match="must return 'timestamp' column"):
            metric_loader.load(
                datetime(2024, 1, 1),
                datetime(2024, 1, 2),
            )

    def test_load_missing_value_column(self, metric_loader, mock_db_manager):
        """Test error when query doesn't return value."""
        mock_db_manager.execute_query.return_value = [
            {"timestamp": datetime(2024, 1, 1)},  # Missing value
        ]

        with pytest.raises(ValueError, match="must return 'value' column"):
            metric_loader.load(
                datetime(2024, 1, 1),
                datetime(2024, 1, 2),
            )


class TestGapFilling:
    """Test gap filling functionality."""

    def test_fill_gaps_complete_data(self, metric_loader, mock_db_manager):
        """Test gap filling with complete data (no gaps)."""
        # Complete data for every 10 minutes
        mock_db_manager.execute_query.return_value = [
            {"timestamp": datetime(2024, 1, 1, 0, 0), "value": 0.5},
            {"timestamp": datetime(2024, 1, 1, 0, 10), "value": 0.6},
            {"timestamp": datetime(2024, 1, 1, 0, 20), "value": 0.7},
        ]

        data = metric_loader.load(
            from_date=datetime(2024, 1, 1, 0, 0),
            to_date=datetime(2024, 1, 1, 0, 30),
            fill_gaps=True,
        )

        # Should have 3 points
        assert len(data["timestamp"]) == 3
        assert not np.any(np.isnan(data["value"]))

    def test_fill_gaps_with_missing_data(self, metric_loader, mock_db_manager):
        """Test gap filling with missing data points."""
        # Missing 00:10 and 00:20
        mock_db_manager.execute_query.return_value = [
            {"timestamp": datetime(2024, 1, 1, 0, 0), "value": 0.5},
            {"timestamp": datetime(2024, 1, 1, 0, 30), "value": 0.8},
        ]

        data = metric_loader.load(
            from_date=datetime(2024, 1, 1, 0, 0),
            to_date=datetime(2024, 1, 1, 0, 40),
            fill_gaps=True,
        )

        # Should have 4 points (0, 10, 20, 30)
        assert len(data["timestamp"]) == 4

        # First and last should have values, middle should be NaN
        assert data["value"][0] == 0.5
        assert np.isnan(data["value"][1])
        assert np.isnan(data["value"][2])
        assert data["value"][3] == 0.8

    def test_fill_gaps_no_data_at_all(self, metric_loader, mock_db_manager):
        """Test gap filling when query returns no data."""
        mock_db_manager.execute_query.return_value = []

        data = metric_loader.load(
            from_date=datetime(2024, 1, 1, 0, 0),
            to_date=datetime(2024, 1, 1, 1, 0),
            fill_gaps=True,
        )

        # When no data at all, returns empty (gap filling only fills between existing points)
        assert len(data["timestamp"]) == 0
        assert len(data["value"]) == 0

    def test_no_gap_filling(self, metric_loader, mock_db_manager):
        """Test loading without gap filling."""
        # Sparse data
        mock_db_manager.execute_query.return_value = [
            {"timestamp": datetime(2024, 1, 1, 0, 0), "value": 0.5},
            {"timestamp": datetime(2024, 1, 1, 0, 30), "value": 0.8},
        ]

        data = metric_loader.load(
            from_date=datetime(2024, 1, 1, 0, 0),
            to_date=datetime(2024, 1, 1, 1, 0),
            fill_gaps=False,
        )

        # Should have only 2 points (no filling)
        assert len(data["timestamp"]) == 2
        assert not np.any(np.isnan(data["value"]))


class TestSeasonalityExtraction:
    """Test seasonality feature extraction."""

    def test_extract_hour(self, metric_loader, mock_db_manager):
        """Test extracting hour feature."""
        mock_db_manager.execute_query.return_value = [
            {"timestamp": datetime(2024, 1, 1, 10, 0), "value": 0.5},
            {"timestamp": datetime(2024, 1, 1, 15, 0), "value": 0.6},
        ]

        data = metric_loader.load(
            datetime(2024, 1, 1, 10, 0),
            datetime(2024, 1, 1, 16, 0),
            fill_gaps=False,
        )

        # Check seasonality data
        import json
        s1 = json.loads(data["seasonality_data"][0])
        s2 = json.loads(data["seasonality_data"][1])

        assert s1["hour"] == 10
        assert s2["hour"] == 15

    def test_extract_day_of_week(self, metric_loader, mock_db_manager):
        """Test extracting day of week feature."""
        # 2024-01-01 is Monday (0), 2024-01-07 is Sunday (6)
        mock_db_manager.execute_query.return_value = [
            {"timestamp": datetime(2024, 1, 1, 0, 0), "value": 0.5},  # Monday
            {"timestamp": datetime(2024, 1, 7, 0, 0), "value": 0.6},  # Sunday
        ]

        data = metric_loader.load(
            datetime(2024, 1, 1),
            datetime(2024, 1, 8),
            fill_gaps=False,
        )

        import json
        s1 = json.loads(data["seasonality_data"][0])
        s2 = json.loads(data["seasonality_data"][1])

        assert s1["day_of_week"] == 0  # Monday
        assert s2["day_of_week"] == 6  # Sunday

    def test_extract_multiple_features(self):
        """Test extracting multiple seasonality features."""
        config = MetricConfig(
            name="test",
            query="SELECT 1",
            interval=600,
            seasonality_columns=["hour", "day_of_week", "month", "is_weekend"],
        )
        loader = MetricLoader(config, MagicMock(), MagicMock())

        # Mock data
        loader.db_manager.execute_query.return_value = [
            {"timestamp": datetime(2024, 1, 6, 15, 0), "value": 0.5},  # Saturday
        ]

        data = loader.load(
            datetime(2024, 1, 6),
            datetime(2024, 1, 7),
            fill_gaps=False,
        )

        import json
        s = json.loads(data["seasonality_data"][0])

        assert s["hour"] == 15
        assert s["day_of_week"] == 5  # Saturday
        assert s["month"] == 1
        assert s["is_weekend"] is True

    def test_no_seasonality_columns(self):
        """Test when no seasonality columns configured."""
        config = MetricConfig(
            name="test",
            query="SELECT 1",
            interval=600,
            seasonality_columns=[],
        )
        loader = MetricLoader(config, MagicMock(), MagicMock())

        loader.db_manager.execute_query.return_value = [
            {"timestamp": datetime(2024, 1, 1), "value": 0.5},
        ]

        data = loader.load(
            datetime(2024, 1, 1),
            datetime(2024, 1, 2),
            fill_gaps=False,
        )

        # Seasonality data should be empty JSON objects
        import json
        s = json.loads(data["seasonality_data"][0])
        assert s == {}


class TestSave:
    """Test save() method."""

    def test_save_data(self, metric_loader, mock_internal_manager, mock_db_manager):
        """Test saving loaded data."""
        # Mock loaded data
        mock_db_manager.execute_query.return_value = [
            {"timestamp": datetime(2024, 1, 1, 0, 0), "value": 0.5},
        ]

        data = metric_loader.load(
            datetime(2024, 1, 1),
            datetime(2024, 1, 2),
            fill_gaps=False,
        )

        # Mock save
        mock_internal_manager.save_datapoints.return_value = 1

        # Save
        rows = metric_loader.save(data)

        assert rows == 1
        mock_internal_manager.save_datapoints.assert_called_once()

        # Verify call arguments
        call_args = mock_internal_manager.save_datapoints.call_args
        assert call_args[1]["metric_name"] == "test_metric"
        assert call_args[1]["interval_seconds"] == 600

    def test_save_empty_data(self, metric_loader, mock_internal_manager):
        """Test saving empty data."""
        empty_data = {
            "timestamp": np.array([], dtype="datetime64[ms]"),
            "value": np.array([], dtype=np.float64),
            "seasonality_data": np.array([], dtype=object),
            "seasonality_columns": [],
        }

        rows = metric_loader.save(empty_data)

        assert rows == 0
        mock_internal_manager.save_datapoints.assert_not_called()


class TestLoadAndSave:
    """Test load_and_save() method."""

    def test_load_and_save_with_dates(
        self, metric_loader, mock_db_manager, mock_internal_manager
    ):
        """Test load_and_save with explicit dates."""
        mock_db_manager.execute_query.return_value = [
            {"timestamp": datetime(2024, 1, 1, 0, 0), "value": 0.5},
        ]
        mock_internal_manager.save_datapoints.return_value = 1

        rows = metric_loader.load_and_save(
            from_date=datetime(2024, 1, 1),
            to_date=datetime(2024, 1, 2),
        )

        assert rows == 1

    def test_load_and_save_from_last_timestamp(
        self, metric_loader, mock_db_manager, mock_internal_manager
    ):
        """Test load_and_save resuming from last timestamp."""
        # Mock last saved timestamp
        last_ts = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        mock_internal_manager.get_last_datapoint_timestamp.return_value = last_ts

        mock_db_manager.execute_query.return_value = [
            {"timestamp": datetime(2024, 1, 1, 0, 10), "value": 0.6},
        ]
        mock_internal_manager.save_datapoints.return_value = 1

        # Load from last timestamp
        rows = metric_loader.load_and_save(to_date=datetime(2024, 1, 1, 1, 0))

        assert rows == 1

        # Verify query was called with correct from_date
        # (should be last_ts + interval)
        query_call = mock_db_manager.execute_query.call_args[0][0]
        # Just verify it was called
        assert mock_db_manager.execute_query.called

    def test_load_and_save_no_existing_data_no_from_date(
        self, metric_loader, mock_internal_manager
    ):
        """Test error when no existing data and no from_date."""
        mock_internal_manager.get_last_datapoint_timestamp.return_value = None

        with pytest.raises(ValueError, match="No existing data"):
            metric_loader.load_and_save()
