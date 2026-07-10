"""
Tests for metric configuration validator.
"""

from pathlib import Path

import pytest

from detectkit.config.validator import (
    discover_metric_files,
    is_discoverable_metric_file,
    validate_metric_uniqueness,
    validate_project_metrics,
)


class TestValidateMetricUniqueness:
    """Tests for validate_metric_uniqueness function."""

    def test_single_metric_valid(self, tmp_path: Path):
        """Test validation with a single valid metric."""
        # Create metric file
        metric_file = tmp_path / "cpu.yml"
        metric_file.write_text(
            """
name: cpu_usage
interval: 1min
query: "SELECT * FROM metrics"
"""
        )

        # Validate
        result = validate_metric_uniqueness([metric_file])

        assert len(result) == 1
        path, config = result[0]
        assert path == metric_file
        assert config.name == "cpu_usage"

    def test_multiple_metrics_unique_names(self, tmp_path: Path):
        """Test validation with multiple metrics with unique names."""
        # Create metric files
        cpu_file = tmp_path / "cpu.yml"
        cpu_file.write_text(
            """
name: cpu_usage
interval: 1min
query: "SELECT * FROM cpu_metrics"
"""
        )

        mem_file = tmp_path / "memory.yml"
        mem_file.write_text(
            """
name: memory_usage
interval: 1min
query: "SELECT * FROM memory_metrics"
"""
        )

        # Validate
        result = validate_metric_uniqueness([cpu_file, mem_file])

        assert len(result) == 2
        names = {config.name for _, config in result}
        assert names == {"cpu_usage", "memory_usage"}

    def test_duplicate_names_raises_error(self, tmp_path: Path):
        """Test that duplicate metric names raise ValueError."""
        # Create metric files with same name
        api_cpu = tmp_path / "api_cpu.yml"
        api_cpu.write_text(
            """
name: cpu_usage
interval: 1min
query: "SELECT * FROM api_metrics"
"""
        )

        system_cpu = tmp_path / "system_cpu.yml"
        system_cpu.write_text(
            """
name: cpu_usage
interval: 1min
query: "SELECT * FROM system_metrics"
"""
        )

        # Validate - should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            validate_metric_uniqueness([api_cpu, system_cpu])

        error_msg = str(exc_info.value)
        assert "Duplicate metric name 'cpu_usage' found" in error_msg
        assert str(api_cpu) in error_msg
        assert str(system_cpu) in error_msg

    def test_invalid_yaml_raises_error(self, tmp_path: Path):
        """Test that invalid YAML raises ValueError."""
        # Create invalid YAML file (malformed YAML syntax)
        invalid_file = tmp_path / "invalid.yml"
        invalid_file.write_text(
            """
name: cpu_usage
interval: "10min
query: "SELECT * FROM metrics"
"""
        )

        # Validate - should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            validate_metric_uniqueness([invalid_file])

        error_msg = str(exc_info.value)
        assert "Failed to parse metric config" in error_msg
        assert str(invalid_file) in error_msg

    def test_missing_required_fields_raises_error(self, tmp_path: Path):
        """Test that missing required fields raise ValueError."""
        # Create file without required fields
        incomplete_file = tmp_path / "incomplete.yml"
        incomplete_file.write_text(
            """
name: cpu_usage
# Missing interval and query
"""
        )

        # Validate - should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            validate_metric_uniqueness([incomplete_file])

        error_msg = str(exc_info.value)
        assert "Failed to parse metric config" in error_msg

    def test_empty_list_returns_empty(self):
        """Test that empty list returns empty result."""
        result = validate_metric_uniqueness([])
        assert result == []

    def test_duplicate_in_subdirectories(self, tmp_path: Path):
        """Test duplicate detection across subdirectories."""
        # Create subdirectories
        api_dir = tmp_path / "api"
        api_dir.mkdir()
        system_dir = tmp_path / "system"
        system_dir.mkdir()

        # Create metrics with same name in different dirs
        api_metric = api_dir / "cpu.yml"
        api_metric.write_text(
            """
name: cpu_usage
interval: 1min
query: "SELECT * FROM api_metrics"
"""
        )

        system_metric = system_dir / "cpu.yml"
        system_metric.write_text(
            """
name: cpu_usage
interval: 1min
query: "SELECT * FROM system_metrics"
"""
        )

        # Validate - should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            validate_metric_uniqueness([api_metric, system_metric])

        error_msg = str(exc_info.value)
        assert "Duplicate metric name 'cpu_usage' found" in error_msg
        assert "data corruption" in error_msg.lower()


class TestValidateProjectMetrics:
    """Tests for validate_project_metrics function."""

    def test_valid_project(self, tmp_path: Path):
        """Test validation of valid project structure."""
        # Create metrics directory
        metrics_dir = tmp_path / "metrics"
        metrics_dir.mkdir()

        # Create metric files
        (metrics_dir / "cpu.yml").write_text(
            """
name: cpu_usage
interval: 1min
query: "SELECT * FROM metrics"
"""
        )

        (metrics_dir / "memory.yml").write_text(
            """
name: memory_usage
interval: 1min
query: "SELECT * FROM metrics"
"""
        )

        # Validate project
        result = validate_project_metrics(tmp_path)

        assert len(result) == 2
        names = {config.name for _, config in result}
        assert names == {"cpu_usage", "memory_usage"}

    def test_missing_metrics_dir_raises_error(self, tmp_path: Path):
        """Test that missing metrics directory raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError) as exc_info:
            validate_project_metrics(tmp_path)

        error_msg = str(exc_info.value)
        assert "Metrics directory not found" in error_msg
        assert str(tmp_path / "metrics") in error_msg

    def test_empty_metrics_dir_raises_error(self, tmp_path: Path):
        """Test that empty metrics directory raises ValueError."""
        # Create empty metrics directory
        metrics_dir = tmp_path / "metrics"
        metrics_dir.mkdir()

        with pytest.raises(ValueError) as exc_info:
            validate_project_metrics(tmp_path)

        error_msg = str(exc_info.value)
        assert "No metric files found" in error_msg

    def test_yaml_extension_supported(self, tmp_path: Path):
        """Test that .yaml extension is supported."""
        # Create metrics directory
        metrics_dir = tmp_path / "metrics"
        metrics_dir.mkdir()

        # Create metric with .yaml extension
        (metrics_dir / "cpu.yaml").write_text(
            """
name: cpu_usage
interval: 1min
query: "SELECT * FROM metrics"
"""
        )

        # Validate project
        result = validate_project_metrics(tmp_path)

        assert len(result) == 1
        assert result[0][1].name == "cpu_usage"

    def test_recursive_search(self, tmp_path: Path):
        """Test that validation searches subdirectories recursively."""
        # Create metrics directory with subdirectories
        metrics_dir = tmp_path / "metrics"
        metrics_dir.mkdir()

        api_dir = metrics_dir / "api"
        api_dir.mkdir()

        # Create metrics in different locations
        (metrics_dir / "cpu.yml").write_text(
            """
name: cpu_usage
interval: 1min
query: "SELECT * FROM metrics"
"""
        )

        (api_dir / "latency.yml").write_text(
            """
name: api_latency
interval: 1min
query: "SELECT * FROM api_metrics"
"""
        )

        # Validate project
        result = validate_project_metrics(tmp_path)

        assert len(result) == 2
        names = {config.name for _, config in result}
        assert names == {"cpu_usage", "api_latency"}

    def test_duplicate_in_project_raises_error(self, tmp_path: Path):
        """Test that duplicate names in project raise ValueError."""
        # Create metrics directory
        metrics_dir = tmp_path / "metrics"
        metrics_dir.mkdir()

        # Create metrics with duplicate names
        (metrics_dir / "cpu1.yml").write_text(
            """
name: cpu_usage
interval: 1min
query: "SELECT * FROM metrics1"
"""
        )

        (metrics_dir / "cpu2.yml").write_text(
            """
name: cpu_usage
interval: 1min
query: "SELECT * FROM metrics2"
"""
        )

        # Validate project - should raise ValueError
        with pytest.raises(ValueError) as exc_info:
            validate_project_metrics(tmp_path)

        error_msg = str(exc_info.value)
        assert "Duplicate metric name 'cpu_usage' found" in error_msg


class TestHistoryArchiveExcludedFromDiscovery:
    """The metrics/.history/ archive (dtk tune's previous-config snapshots) keeps the
    original name: and must NOT be discovered — otherwise a tuned metric collides with
    its own archived copies as a duplicate name (the reported production bug)."""

    def _metric_yaml(self, name: str, q: str) -> str:
        return f'name: {name}\ninterval: 1min\nquery: "SELECT * FROM {q}"\n'

    def test_history_snapshots_not_discovered(self, tmp_path: Path):
        metrics_dir = tmp_path / "metrics"
        metrics_dir.mkdir()
        (metrics_dir / "cpu.yml").write_text(self._metric_yaml("cpu_usage", "live"))
        # two archived snapshots of the same metric (as dtk tune writes them)
        hist = metrics_dir / ".history" / "cpu_usage"
        hist.mkdir(parents=True)
        (hist / "cpu_usage-20260627T143935Z.yml").write_text(self._metric_yaml("cpu_usage", "old1"))
        (hist / "cpu_usage-20260628T142047Z.yml").write_text(self._metric_yaml("cpu_usage", "old2"))

        # discovery skips the archive entirely
        found = discover_metric_files(metrics_dir)
        assert found == [metrics_dir / "cpu.yml"]

        # ...so project validation does NOT raise a duplicate-name error
        result = validate_project_metrics(tmp_path)
        assert len(result) == 1
        assert result[0][1].name == "cpu_usage"

    def test_is_discoverable_predicate(self, tmp_path: Path):
        metrics_dir = tmp_path / "metrics"
        live = metrics_dir / "cpu.yml"
        archived = metrics_dir / ".history" / "cpu_usage" / "cpu_usage-20260627T143935Z.yml"
        archived.parent.mkdir(parents=True)
        live.write_text(self._metric_yaml("cpu_usage", "live"))
        archived.write_text(self._metric_yaml("cpu_usage", "old"))
        assert is_discoverable_metric_file(live, metrics_dir) is True
        assert is_discoverable_metric_file(archived, metrics_dir) is False
        # a project rooted under a dot-directory is unaffected (only parts BELOW
        # metrics/ are checked), and autotune's top-level __tuned_ files stay visible
        tuned = metrics_dir / "cpu__tuned_abc123.yml"
        tuned.write_text(self._metric_yaml("cpu_usage_tuned", "tuned"))
        assert is_discoverable_metric_file(tuned, metrics_dir) is True
