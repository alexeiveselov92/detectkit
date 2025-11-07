"""Tests for Interval class."""

import pytest

from detectkit.core.interval import Interval


class TestInterval:
    """Test Interval parsing and handling."""

    def test_from_integer(self):
        """Test creating interval from integer (seconds)."""
        interval = Interval(600)
        assert interval.seconds == 600

    def test_from_string_minutes(self):
        """Test parsing minutes format."""
        interval = Interval("10min")
        assert interval.seconds == 600

        interval = Interval("1m")
        assert interval.seconds == 60

    def test_from_string_hours(self):
        """Test parsing hours format."""
        interval = Interval("1h")
        assert interval.seconds == 3600

        interval = Interval("2hour")
        assert interval.seconds == 7200

    def test_from_string_days(self):
        """Test parsing days format."""
        interval = Interval("1d")
        assert interval.seconds == 86400

        interval = Interval("7days")
        assert interval.seconds == 604800

    def test_from_string_seconds(self):
        """Test parsing seconds format."""
        interval = Interval("30s")
        assert interval.seconds == 30

        interval = Interval("120sec")
        assert interval.seconds == 120

    def test_case_insensitive(self):
        """Test that parsing is case insensitive."""
        assert Interval("10MIN").seconds == 600
        assert Interval("1H").seconds == 3600
        assert Interval("1D").seconds == 86400

    def test_invalid_format(self):
        """Test error on invalid format."""
        with pytest.raises(ValueError, match="Invalid interval format"):
            Interval("invalid")

        with pytest.raises(ValueError, match="Invalid interval format"):
            Interval("10")  # Missing unit

        with pytest.raises(ValueError, match="Invalid interval format"):
            Interval("min10")  # Wrong order

    def test_invalid_unit(self):
        """Test error on unknown unit."""
        with pytest.raises(ValueError, match="Unknown time unit"):
            Interval("10xyz")

    def test_negative_value(self):
        """Test error on negative value."""
        with pytest.raises(ValueError, match="must be positive"):
            Interval(-600)

        with pytest.raises(ValueError, match="must be positive"):
            Interval("0min")

    def test_invalid_type(self):
        """Test error on invalid type."""
        with pytest.raises(TypeError):
            Interval(60.5)  # Float not allowed

        with pytest.raises(TypeError):
            Interval(None)

    def test_equality(self):
        """Test interval equality."""
        assert Interval(600) == Interval("10min")
        assert Interval("1h") == Interval(3600)
        assert Interval("1d") != Interval("1h")

    def test_hash(self):
        """Test interval hashing."""
        intervals = {Interval(600), Interval("10min"), Interval(3600)}
        assert len(intervals) == 2  # 600 and 3600

    def test_str_representation(self):
        """Test string representation."""
        assert str(Interval(60)) == "1min"
        assert str(Interval(3600)) == "1h"
        assert str(Interval(86400)) == "1d"
        assert str(Interval(90)) == "90s"  # Not divisible by 60

    def test_repr(self):
        """Test repr."""
        interval = Interval(600)
        assert repr(interval) == "Interval(600)"
