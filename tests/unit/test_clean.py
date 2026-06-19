"""Tests for `dtk clean` — drift pruning, orphaned-metric GC, and DB helpers."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from detectkit.cli.commands import clean as clean_cmd
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.database.internal_tables._maintenance import METRIC_KEYED_TABLES
from detectkit.database.tables import TABLE_ALERT_STATES, TABLE_DETECTIONS
from detectkit.detectors.factory import DetectorFactory
from detectkit.orchestration.task_manager._types import make_alert_config_id

# ── DB helper tests (mock manager, mirroring test_internal_tables.py) ────────


@pytest.fixture
def mock_manager():
    manager = MagicMock()
    manager.get_full_table_name = lambda name, use_internal: f"detectk_internal.{name}"
    return manager


@pytest.fixture
def internal_manager(mock_manager):
    return InternalTablesManager(mock_manager)


class TestListDetectorIds:
    def test_parses_group_by_rows(self, internal_manager, mock_manager):
        mock_manager.execute_query.return_value = [
            {"detector_id": "abc", "cnt": 10},
            {"detector_id": "def", "cnt": 3},
        ]
        result = internal_manager.list_detector_ids("cpu_usage")
        assert result == {"abc": 10, "def": 3}
        query = mock_manager.execute_query.call_args[0][0]
        assert TABLE_DETECTIONS in query
        assert "GROUP BY detector_id" in query

    def test_skips_empty_detector_id(self, internal_manager, mock_manager):
        mock_manager.execute_query.return_value = [{"detector_id": None, "cnt": 5}]
        assert internal_manager.list_detector_ids("cpu_usage") == {}


class TestDeleteDetectionsSync:
    def test_no_sync_by_default(self, internal_manager, mock_manager):
        internal_manager.delete_detections("cpu_usage", detector_id="abc")
        # Deletes go through the generic delete_rows primitive, not raw SQL.
        assert mock_manager.delete_rows.call_args.kwargs["sync"] is False

    def test_sync_appends_settings(self, internal_manager, mock_manager):
        internal_manager.delete_detections("cpu_usage", detector_id="abc", mutations_sync=True)
        table, where_clause = mock_manager.delete_rows.call_args[0][:2]
        assert TABLE_DETECTIONS in table
        assert mock_manager.delete_rows.call_args.kwargs["sync"] is True
        assert "detector_id = %(detector_id)s" in where_clause


class TestAlertStateHelpers:
    def test_list_alert_config_ids(self, internal_manager, mock_manager):
        mock_manager.execute_query.return_value = [
            {"alert_config_id": "a1"},
            {"alert_config_id": "a2"},
        ]
        assert internal_manager.list_alert_config_ids("cpu_usage") == ["a1", "a2"]

    def test_delete_alert_state(self, internal_manager, mock_manager):
        internal_manager.delete_alert_state("cpu_usage", "a1")
        table, where_clause, params = mock_manager.delete_rows.call_args[0][:3]
        assert TABLE_ALERT_STATES in table
        assert mock_manager.delete_rows.call_args.kwargs["sync"] is True
        assert "metric_name = %(metric_name)s" in where_clause
        assert params == {"metric_name": "cpu_usage", "alert_config_id": "a1"}


class TestMaintenanceHelpers:
    def test_list_known_metric_names_unions_all_tables(self, internal_manager, mock_manager):
        # Each table returns its own distinct set; the union is reported.
        per_table = iter(
            [
                [{"metric_name": "a"}, {"metric_name": "b"}],  # datapoints
                [{"metric_name": "b"}],  # detections
                [{"metric_name": "c"}],  # tasks
                [],  # alert_states
                [{"metric_name": None}],  # metrics (NULL skipped)
            ]
        )
        mock_manager.execute_query.side_effect = lambda *a, **k: next(per_table)
        names = internal_manager.list_known_metric_names()
        assert names == {"a", "b", "c"}
        assert mock_manager.execute_query.call_count == len(METRIC_KEYED_TABLES)

    def test_count_metric_rows(self, internal_manager, mock_manager):
        mock_manager.execute_query.side_effect = lambda *a, **k: [{"cnt": 7}]
        counts = internal_manager.count_metric_rows("gone")
        assert set(counts.keys()) == set(METRIC_KEYED_TABLES)
        assert all(v == 7 for v in counts.values())

    def test_purge_metric_deletes_every_table(self, internal_manager, mock_manager):
        internal_manager.purge_metric("gone")
        assert mock_manager.delete_rows.call_count == len(METRIC_KEYED_TABLES)
        for call in mock_manager.delete_rows.call_args_list:
            assert "metric_name = %(m)s" in call[0][1]
            assert call.kwargs["sync"] is True


# ── valid-hash helpers (use the real factory / hashing) ──────────────────────


def _fake_detector_config(detector_type, params=None, seasonality=None):
    return SimpleNamespace(
        type=detector_type,
        get_algorithm_params=lambda: dict(params or {}),
        get_seasonality_components=lambda: seasonality,
    )


def _fake_alerting(channels, **kw):
    defaults = {
        "channels": channels,
        "min_detectors": 1,
        "direction": "both",
        "consecutive_anomalies": 3,
        "alert_cooldown": None,
        "cooldown_reset_on_recovery": False,
    }
    defaults.update(kw)
    return SimpleNamespace(**defaults)


class TestValidHashHelpers:
    def test_valid_detector_ids_match_factory(self):
        dc = _fake_detector_config("zscore", {"threshold": 3.0})
        config = SimpleNamespace(detectors=[dc], alerting=None)
        expected = DetectorFactory.create_from_config(
            {"type": "zscore", "params": {"threshold": 3.0}}
        ).get_detector_id()
        assert clean_cmd._valid_detector_ids(config) == {expected}

    def test_seasonality_changes_the_id(self):
        plain = _fake_detector_config("zscore", {"threshold": 3.0})
        seasonal = _fake_detector_config("zscore", {"threshold": 3.0}, seasonality=["hour"])
        id_plain = clean_cmd._valid_detector_ids(SimpleNamespace(detectors=[plain], alerting=None))
        id_seasonal = clean_cmd._valid_detector_ids(
            SimpleNamespace(detectors=[seasonal], alerting=None)
        )
        assert id_plain != id_seasonal

    def test_empty_detectors_gives_empty_set(self):
        assert clean_cmd._valid_detector_ids(SimpleNamespace(detectors=[], alerting=None)) == set()

    def test_valid_alert_ids_match_make_alert_config_id(self):
        alert = _fake_alerting(["mattermost"])
        config = SimpleNamespace(detectors=None, alerting=[alert])
        assert clean_cmd._valid_alert_config_ids(config) == {make_alert_config_id(alert)}


# ── command-level tests (run_clean) ──────────────────────────────────────────


@pytest.fixture
def patched_env(monkeypatch):
    """Patch project discovery + manager creation; return the mock internal manager."""
    monkeypatch.setattr(clean_cmd, "find_project_root", lambda: Path("/proj"))
    internal = MagicMock()
    monkeypatch.setattr(clean_cmd, "_create_internal_manager", lambda root, profile: internal)
    return internal


def _run(**overrides):
    kwargs = {
        "select": None,
        "orphaned_metrics": False,
        "execute": False,
        "yes": False,
        "profile": None,
    }
    kwargs.update(overrides)
    clean_cmd.run_clean(**kwargs)


class TestModeValidation:
    def test_neither_mode_errors(self, capsys, patched_env):
        _run()
        assert "exactly one of --select or --orphaned-metrics" in capsys.readouterr().out

    def test_both_modes_error(self, capsys, patched_env):
        _run(select="cpu", orphaned_metrics=True)
        assert "exactly one of --select or --orphaned-metrics" in capsys.readouterr().out


class TestDriftMode:
    def _setup(self, monkeypatch, patched_env):
        config = SimpleNamespace(name="cpu_usage", detectors=[], alerting=[])
        monkeypatch.setattr(clean_cmd, "select_metrics", lambda s, root: [(Path("x.yml"), config)])
        monkeypatch.setattr(clean_cmd, "_valid_detector_ids", lambda c: {"keep_det"})
        monkeypatch.setattr(clean_cmd, "_valid_alert_config_ids", lambda c: {"keep_alert"})
        patched_env.list_detector_ids.return_value = {"keep_det": 10, "orphan_det": 5}
        patched_env.list_alert_config_ids.return_value = ["keep_alert", "orphan_alert"]
        return patched_env

    def test_dry_run_reports_without_deleting(self, capsys, monkeypatch, patched_env):
        internal = self._setup(monkeypatch, patched_env)
        _run(select="cpu_usage", execute=False)
        out = capsys.readouterr().out
        assert "DRY-RUN" in out
        assert "orphan_det" in out and "orphan_alert" in out
        assert "keep_det" not in out  # valid hashes are not flagged
        internal.delete_detections.assert_not_called()
        internal.delete_alert_state.assert_not_called()

    def test_execute_deletes_only_orphans(self, capsys, monkeypatch, patched_env):
        internal = self._setup(monkeypatch, patched_env)
        _run(select="cpu_usage", execute=True)
        internal.delete_detections.assert_called_once_with(
            metric_name="cpu_usage", detector_id="orphan_det", mutations_sync=True
        )
        internal.delete_alert_state.assert_called_once_with("cpu_usage", "orphan_alert")

    def test_no_metrics_matched(self, capsys, monkeypatch, patched_env):
        monkeypatch.setattr(clean_cmd, "select_metrics", lambda s, root: [])
        _run(select="nope", execute=True)
        assert "No metrics found matching selector" in capsys.readouterr().out
        patched_env.delete_detections.assert_not_called()


class TestOrphanedMetricsMode:
    def test_dry_run_lists_orphans(self, capsys, monkeypatch, patched_env):
        keep = SimpleNamespace(name="keep")
        monkeypatch.setattr(
            clean_cmd, "validate_project_metrics", lambda root: [(Path("k.yml"), keep)]
        )
        patched_env.list_known_metric_names.return_value = {"keep", "gone"}
        patched_env.count_metric_rows.return_value = {TABLE_DETECTIONS: 4}
        _run(orphaned_metrics=True, execute=False)
        out = capsys.readouterr().out
        assert "gone" in out and "keep" not in out.split("YAML in the project")[-1]
        patched_env.purge_metric.assert_not_called()

    def test_execute_purges_orphans(self, monkeypatch, patched_env):
        keep = SimpleNamespace(name="keep")
        monkeypatch.setattr(
            clean_cmd, "validate_project_metrics", lambda root: [(Path("k.yml"), keep)]
        )
        patched_env.list_known_metric_names.return_value = {"keep", "gone"}
        patched_env.count_metric_rows.return_value = {TABLE_DETECTIONS: 4}
        _run(orphaned_metrics=True, execute=True, yes=True)
        patched_env.purge_metric.assert_called_once_with("gone")

    def test_nothing_to_clean(self, capsys, monkeypatch, patched_env):
        keep = SimpleNamespace(name="keep")
        monkeypatch.setattr(
            clean_cmd, "validate_project_metrics", lambda root: [(Path("k.yml"), keep)]
        )
        patched_env.list_known_metric_names.return_value = {"keep"}
        _run(orphaned_metrics=True, execute=True, yes=True)
        assert "No orphaned metrics" in capsys.readouterr().out
        patched_env.purge_metric.assert_not_called()

    def test_empty_project_blocks_execute_without_yes(self, capsys, monkeypatch, patched_env):
        def _raise(root):
            raise FileNotFoundError("no metrics dir")

        monkeypatch.setattr(clean_cmd, "validate_project_metrics", _raise)
        patched_env.list_known_metric_names.return_value = {"a", "b"}
        patched_env.count_metric_rows.return_value = {TABLE_DETECTIONS: 1}
        _run(orphaned_metrics=True, execute=True, yes=False)
        assert "Refusing to purge" in capsys.readouterr().out
        patched_env.purge_metric.assert_not_called()

    def test_invalid_project_aborts(self, capsys, monkeypatch, patched_env):
        def _raise(root):
            raise ValueError("Duplicate metric name 'x'")

        monkeypatch.setattr(clean_cmd, "validate_project_metrics", _raise)
        _run(orphaned_metrics=True, execute=True, yes=True)
        out = capsys.readouterr().out
        assert "cannot determine project metrics" in out
        patched_env.list_known_metric_names.assert_not_called()
        patched_env.purge_metric.assert_not_called()
