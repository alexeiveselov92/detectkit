"""Tests for `select_metrics` selector resolution — especially the glob branch
robustness against `.gitkeep`, non-YAML files, and directories (the bug behind
`dtk clean --select "*"` crashing on a fresh project)."""

from pathlib import Path

import pytest

from detectkit.cli.commands.run import select_metrics


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project whose metrics/ looks like one created by `dtk init` + edits."""
    metrics = tmp_path / "metrics"
    (metrics / "ru").mkdir(parents=True)
    (metrics / ".gitkeep").write_text("")  # empty stub from `dtk init`
    (metrics / "notes.txt").write_text("not a metric")  # stray non-YAML file
    (metrics / "sessions.yml").write_text('name: sessions\ninterval: 1min\nquery: "SELECT 1"\n')
    (metrics / "logins.yaml").write_text('name: logins\ninterval: 1min\nquery: "SELECT 1"\n')
    (metrics / "ru" / "region.yml").write_text('name: region\ninterval: 1min\nquery: "SELECT 1"\n')
    return tmp_path


def _names(result):
    return sorted(config.name for _, config in result)


class TestStarSelector:
    def test_star_returns_all_metrics_recursively(self, project):
        # The crash repro: "*" must not choke on .gitkeep / notes.txt / the ru/ dir,
        # and must include the nested metric.
        assert _names(select_metrics("*", project)) == ["logins", "region", "sessions"]

    def test_star_skips_non_metric_entries(self, project):
        paths = {p.name for p, _ in select_metrics("*", project)}
        assert ".gitkeep" not in paths
        assert "notes.txt" not in paths


class TestGlobPatterns:
    def test_top_level_glob_filters_junk(self, project):
        # "metrics/*" hits .gitkeep, notes.txt and the ru/ directory in raw glob;
        # they must be filtered out, leaving only top-level metric files.
        assert _names(select_metrics("metrics/*", project)) == ["logins", "sessions"]

    def test_recursive_yaml_glob(self, project):
        assert _names(select_metrics("metrics/**/*.yml", project)) == ["region", "sessions"]

    def test_folder_glob(self, project):
        assert _names(select_metrics("metrics/ru/*", project)) == ["region"]

    def test_extension_is_normalized_in(self, project):
        # selector without leading "metrics/" still resolves under metrics/
        assert _names(select_metrics("*.yaml", project)) == ["logins"]


class TestNoMatch:
    def test_unmatched_glob_returns_empty(self, project):
        assert select_metrics("metrics/nope/*.yml", project) == []

    def test_empty_metrics_dir(self, tmp_path):
        (tmp_path / "metrics").mkdir()
        assert select_metrics("*", tmp_path) == []
