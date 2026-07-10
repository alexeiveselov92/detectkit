"""Tests for `dtk init` project scaffolding (run_init)."""

import pytest

from detectkit.cli.commands.init import run_init
from detectkit.config.metric_config import MetricConfig


@pytest.mark.parametrize("db_type", ["clickhouse", "postgres", "mysql"])
def test_init_scaffolds_expected_tree(tmp_path, db_type):
    run_init("demo", str(tmp_path), db_type=db_type)
    root = tmp_path / "demo"

    assert (root / "detectkit_project.yml").is_file()
    assert (root / "profiles.yml").is_file()
    assert (root / "README.md").is_file()
    assert (root / "metrics" / "example_cpu_usage.yml").is_file()
    assert (root / "sql" / ".gitkeep").is_file()
    # incidents/ is scaffolded with an example labels file
    assert (root / "incidents").is_dir()
    assert (root / "incidents" / "example_cpu_usage.yml").is_file()


def test_init_example_metric_is_valid(tmp_path):
    run_init("demo", str(tmp_path), db_type="clickhouse")
    metric_path = tmp_path / "demo" / "metrics" / "example_cpu_usage.yml"
    config = MetricConfig.from_yaml_file(metric_path)
    assert config.name == "example_cpu_usage"


def test_init_example_incidents_file_parses(tmp_path):
    from detectkit.autotune.labels import parse_labels_file

    run_init("demo", str(tmp_path), db_type="clickhouse")
    incidents_path = tmp_path / "demo" / "incidents" / "example_cpu_usage.yml"
    labels = parse_labels_file(incidents_path, interval_seconds=60, metric_name="example_cpu_usage")
    # one interval + one point in the shipped example
    assert len(labels.intervals) == 1
    assert len(labels.points) == 1


def test_init_refuses_existing_directory(tmp_path):
    (tmp_path / "demo").mkdir()
    run_init("demo", str(tmp_path), db_type="clickhouse")
    # nothing scaffolded into the pre-existing dir
    assert not (tmp_path / "demo" / "detectkit_project.yml").exists()
