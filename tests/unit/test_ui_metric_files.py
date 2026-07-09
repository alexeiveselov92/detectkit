"""Tests for the `dtk ui` metric-file CRUD seam (detectkit/ui/metric_files.py).

Style mirrors ``tests/unit/test_tune_config_writer.py`` — a pure filesystem +
validation module, exercised with real ``tmp_path`` projects (no server, no DB).
"""

from pathlib import Path

import pytest

from detectkit.config import metric_io
from detectkit.config.metric_config import MetricConfig
from detectkit.ui import metric_files
from detectkit.ui.metric_files import (
    create_metric_file,
    delete_metric_file,
    parse_metric_text,
    update_metric_file,
)

_VALID_FLAT = """name: orders
interval: 1h
query: "SELECT timestamp, value FROM t"
"""

_VALID_NESTED = """metric:
  name: orders
  interval: 1h
  query: "SELECT timestamp, value FROM t"
"""

_INVALID_YAML_SYNTAX = "name: orders\ninterval: 1h\nquery: 'unterminated\n"

_NON_MAPPING = "- 1\n- 2\n"

_MISSING_REQUIRED = "name: orders\n"  # no interval, no query

# threshold <= 0 fails WindowedStatDetector._validate_params ("threshold must
# be positive") — a genuinely invalid param for a factory-known detector type.
_BAD_DETECTOR_PARAMS = """name: orders
interval: 1h
query: "SELECT 1"
detectors:
  - type: mad
    params:
      threshold: -1
"""


def _write_project(tmp_path: Path, text: str = _VALID_FLAT, name: str = "orders") -> Path:
    """Create ``metrics/<name>.yml`` with *text* and return its path."""
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    path = metrics_dir / f"{name}.yml"
    path.write_text(text, encoding="utf-8")
    return path


def _metric_yaml(name: str, extra: str = "") -> str:
    return f'name: {name}\ninterval: 1h\nquery: "SELECT 1"\n{extra}'


# ── parse_metric_text ────────────────────────────────────────────────────────


def test_parse_valid_flat_config():
    config = parse_metric_text(_VALID_FLAT)
    assert isinstance(config, MetricConfig)
    assert config.name == "orders"
    assert config.get_interval().seconds == 3600


def test_parse_valid_nested_metric_form():
    config = parse_metric_text(_VALID_NESTED)
    assert config.name == "orders"


def test_parse_invalid_yaml_syntax_raises():
    with pytest.raises(ValueError, match="invalid YAML"):
        parse_metric_text(_INVALID_YAML_SYNTAX)


def test_parse_non_mapping_raises():
    with pytest.raises(ValueError, match="mapping"):
        parse_metric_text(_NON_MAPPING)


def test_parse_missing_required_field_raises():
    with pytest.raises(ValueError, match="invalid metric config"):
        parse_metric_text(_MISSING_REQUIRED)


def test_parse_bad_detector_params_names_the_detector():
    with pytest.raises(ValueError, match=r"detector #1 \(mad\).*threshold"):
        parse_metric_text(_BAD_DETECTOR_PARAMS)


# ── create_metric_file ───────────────────────────────────────────────────────


def test_create_writes_exact_text_and_returns_config(tmp_path):
    written = create_metric_file(project_root=tmp_path, text=_VALID_FLAT)
    assert written.path == tmp_path / "metrics" / "orders.yml"
    assert written.path.read_text(encoding="utf-8") == _VALID_FLAT
    assert written.config.name == "orders"
    assert written.archived is None


def test_create_normalizes_missing_trailing_newline(tmp_path):
    text_no_newline = _VALID_FLAT.rstrip("\n")
    assert not text_no_newline.endswith("\n")
    written = create_metric_file(project_root=tmp_path, text=text_no_newline)
    assert written.path.read_text(encoding="utf-8") == text_no_newline + "\n"


def test_create_in_subfolder(tmp_path):
    written = create_metric_file(project_root=tmp_path, text=_VALID_FLAT, folder="sub")
    assert written.path == tmp_path / "metrics" / "sub" / "orders.yml"
    assert written.path.exists()


def test_create_folder_with_dotdot_rejected(tmp_path):
    with pytest.raises(ValueError):
        create_metric_file(project_root=tmp_path, text=_VALID_FLAT, folder="../evil")
    assert not (tmp_path / "metrics").exists()


def test_create_folder_with_hidden_component_rejected(tmp_path):
    with pytest.raises(ValueError):
        create_metric_file(project_root=tmp_path, text=_VALID_FLAT, folder=".hidden")
    assert not (tmp_path / "metrics").exists()


def test_create_duplicate_name_elsewhere_in_tree_rejected(tmp_path):
    # An existing metric under a DIFFERENT filename already uses the name "dup".
    _write_project(tmp_path, text=_metric_yaml("dup"), name="existing_file")
    new_text = _metric_yaml("dup")
    with pytest.raises(ValueError, match="already used"):
        create_metric_file(project_root=tmp_path, text=new_text, folder="sub")
    # nothing written under the new (would-be) location
    assert not (tmp_path / "metrics" / "sub").exists()


def test_create_target_file_already_exists_rejected(tmp_path):
    existing = _write_project(tmp_path, text=_metric_yaml("other"), name="dup")
    before = existing.read_text(encoding="utf-8")
    new_text = _metric_yaml("dup")  # config.name -> filename "dup.yml", already taken
    with pytest.raises(ValueError, match="already exists"):
        create_metric_file(project_root=tmp_path, text=new_text)
    assert existing.read_text(encoding="utf-8") == before  # untouched


def test_create_name_with_slash_rejected_by_config_validation(tmp_path):
    # '/' isn't allowed in MetricConfig.name at all — rejected before any
    # filesystem charset guard is even reached.
    text = _metric_yaml("bad/name")
    with pytest.raises(ValueError):
        create_metric_file(project_root=tmp_path, text=text)
    assert not (tmp_path / "metrics").exists()


def test_create_name_with_leading_dash_gets_sanitized_filename(tmp_path):
    # A leading dash passes MetricConfig.validate_name (alnum/_/- allowed
    # anywhere); rather than refusing a valid metric, the filename stem is
    # sanitized (leading dots/dashes stripped) while the YAML name is kept.
    (tmp_path / "metrics").mkdir()
    text = _metric_yaml("-oops")
    written = create_metric_file(project_root=tmp_path, text=text)
    assert written.path == tmp_path / "metrics" / "oops.yml"
    assert written.config.name == "-oops"
    assert written.path.read_text() == text


# ── update_metric_file ───────────────────────────────────────────────────────


def test_update_overwrites_in_place_and_archives_original(tmp_path, monkeypatch):
    monkeypatch.setattr(metric_io, "metric_stamp", lambda *a, **kw: "20260624T101530Z")
    path = _write_project(tmp_path, text=_VALID_FLAT)
    new_text = _metric_yaml("orders", extra="description: updated\n")

    written = update_metric_file(project_root=tmp_path, path=path, text=new_text)

    assert path.read_text(encoding="utf-8") == metric_files._normalized(new_text)
    assert written.archived == tmp_path / "metrics" / ".history" / "orders" / (
        "orders-20260624T101530Z.yml"
    )
    assert written.archived.read_text(encoding="utf-8") == _VALID_FLAT  # verbatim original


def test_update_rename_works_and_archive_keyed_by_old_name(tmp_path, monkeypatch):
    monkeypatch.setattr(metric_io, "metric_stamp", lambda *a, **kw: "20260624T101530Z")
    path = _write_project(tmp_path, text=_metric_yaml("orders"), name="orders")

    written = update_metric_file(project_root=tmp_path, path=path, text=_metric_yaml("orders_v2"))

    assert written.config.name == "orders_v2"
    # archived under the OLD name, not the new one
    assert written.archived.parent == tmp_path / "metrics" / ".history" / "orders"
    assert not (tmp_path / "metrics" / ".history" / "orders_v2").exists()
    # the file itself keeps its original path/filename; only the YAML content changed
    assert path.exists()
    assert MetricConfig.from_yaml_file(path).name == "orders_v2"


def test_update_rename_conflict_with_other_live_metric_rejected(tmp_path):
    orders_path = _write_project(tmp_path, text=_metric_yaml("orders"), name="orders")
    _write_project(tmp_path, text=_metric_yaml("other"), name="other")
    before = orders_path.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="already used"):
        update_metric_file(project_root=tmp_path, path=orders_path, text=_metric_yaml("other"))

    assert orders_path.read_text(encoding="utf-8") == before  # unchanged
    assert not (tmp_path / "metrics" / ".history").exists()  # no archive written


def test_update_invalid_text_rejected_leaves_file_and_writes_no_archive(tmp_path):
    path = _write_project(tmp_path, text=_VALID_FLAT)
    before = path.read_text(encoding="utf-8")

    with pytest.raises(ValueError):
        update_metric_file(project_root=tmp_path, path=path, text=_MISSING_REQUIRED)

    assert path.read_text(encoding="utf-8") == before
    assert not (tmp_path / "metrics" / ".history").exists()


def test_update_refuses_path_under_history_archive(tmp_path):
    hist_path = tmp_path / "metrics" / ".history" / "orders" / "orders-20260101T000000Z.yml"
    hist_path.parent.mkdir(parents=True, exist_ok=True)
    hist_path.write_text(_VALID_FLAT, encoding="utf-8")

    with pytest.raises(ValueError, match="archived/hidden"):
        update_metric_file(project_root=tmp_path, path=hist_path, text=_VALID_FLAT)


def test_archive_collision_within_same_second_gets_dash_one_suffix(tmp_path, monkeypatch):
    monkeypatch.setattr(metric_io, "metric_stamp", lambda *a, **kw: "20260624T101530Z")
    path = _write_project(tmp_path, text=_metric_yaml("orders"), name="orders")

    first = update_metric_file(
        project_root=tmp_path, path=path, text=_metric_yaml("orders", "description: v2\n")
    )
    second = update_metric_file(
        project_root=tmp_path, path=path, text=_metric_yaml("orders", "description: v3\n")
    )

    hist_dir = tmp_path / "metrics" / ".history" / "orders"
    assert first.archived == hist_dir / "orders-20260624T101530Z.yml"
    assert second.archived == hist_dir / "orders-20260624T101530Z-1.yml"
    assert first.archived.exists() and second.archived.exists()
    assert first.archived.read_text(encoding="utf-8") == _metric_yaml("orders")
    assert second.archived.read_text(encoding="utf-8") == metric_files._normalized(
        _metric_yaml("orders", "description: v2\n")
    )


# ── delete_metric_file ───────────────────────────────────────────────────────


def test_delete_removes_file_and_archives_verbatim(tmp_path, monkeypatch):
    monkeypatch.setattr(metric_io, "metric_stamp", lambda *a, **kw: "20260624T101530Z")
    path = _write_project(tmp_path, text=_VALID_FLAT)

    archived = delete_metric_file(project_root=tmp_path, path=path)

    assert not path.exists()
    assert archived == tmp_path / "metrics" / ".history" / "orders" / (
        "orders-20260624T101530Z-deleted.yml"
    )
    assert archived.read_text(encoding="utf-8") == _VALID_FLAT


def test_delete_path_outside_metrics_dir_rejected(tmp_path):
    (tmp_path / "metrics").mkdir()
    outside = tmp_path / "elsewhere.yml"
    outside.write_text(_VALID_FLAT, encoding="utf-8")

    with pytest.raises(ValueError):
        delete_metric_file(project_root=tmp_path, path=outside)

    assert outside.exists()  # untouched


# ── optimistic concurrency (expected_digest) ─────────────────────────────────


def test_update_with_matching_digest_succeeds(tmp_path):
    path = _write_project(tmp_path, text=_VALID_FLAT)
    digest = metric_files.text_digest(_VALID_FLAT)

    written = update_metric_file(
        project_root=tmp_path,
        path=path,
        text=_metric_yaml("orders", extra="description: v2\n"),
        expected_digest=digest,
    )
    assert "description: v2" in written.path.read_text(encoding="utf-8")


def test_update_with_stale_digest_refused_and_writes_nothing(tmp_path):
    path = _write_project(tmp_path, text=_VALID_FLAT)
    stale = metric_files.text_digest("something that was never on disk")

    with pytest.raises(ValueError, match="changed on disk"):
        update_metric_file(
            project_root=tmp_path,
            path=path,
            text=_metric_yaml("orders", extra="description: v2\n"),
            expected_digest=stale,
        )

    assert path.read_text(encoding="utf-8") == _VALID_FLAT  # untouched
    assert not (tmp_path / "metrics" / ".history").exists()  # no archive either


# ── archive-key sanitization ─────────────────────────────────────────────────


def test_delete_sanitizes_hostile_on_disk_name_for_archive_key(tmp_path):
    # The on-disk `name:` is free text at delete time (an external edit can
    # change it after boot) — it must never steer the archive path outside
    # metrics/.history/ via `..` or an absolute component.
    hostile = 'name: ../../escape\ninterval: 1h\nquery: "SELECT 1"\n'
    path = _write_project(tmp_path, text=hostile, name="victim")

    archived = delete_metric_file(project_root=tmp_path, path=path)

    history = (tmp_path / "metrics" / ".history").resolve()
    assert archived.resolve().is_relative_to(history)
    assert not path.exists()
    assert archived.read_text(encoding="utf-8") == hostile
    assert not (tmp_path.parent / "escape").exists()


def test_create_unicode_name_gets_sanitized_filename(tmp_path):
    # validate_name accepts unicode alphanumerics; the filename stem replaces
    # them rather than refusing the metric.
    (tmp_path / "metrics").mkdir()
    text = _metric_yaml("метрика")

    written = create_metric_file(project_root=tmp_path, text=text)

    assert written.config.name == "метрика"
    assert written.path.parent == tmp_path / "metrics"
    assert written.path.name.endswith(".yml")
    assert "/" not in written.path.stem and written.path.stem != ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
