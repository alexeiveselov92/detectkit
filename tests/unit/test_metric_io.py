"""Tests for the shared metric-YAML seams (detectkit/config/metric_io.py)."""

import pytest

from detectkit.config import metric_io
from detectkit.config.metric_io import (
    archive_metric_text,
    safe_metric_stem,
    unwrap_metric_mapping,
)

# ── unwrap_metric_mapping ────────────────────────────────────────────────────


def test_unwrap_flat_form_returns_same_object():
    data = {"name": "m", "interval": "1h"}
    assert unwrap_metric_mapping(data) is data


def test_unwrap_nested_form_returns_body_reference():
    body = {"name": "m", "interval": "1h"}
    data = {"metric": body}
    unwrapped = unwrap_metric_mapping(data)
    assert unwrapped is body
    # in-place edits land inside the original document (the tune write-back
    # relies on this to re-emit the nested form intact)
    unwrapped["detectors"] = []
    assert data["metric"]["detectors"] == []


def test_unwrap_non_dict_metric_key_is_flat():
    # `metric: some_name` (the labels-file shape) is NOT the nested config form
    data = {"metric": "a_name", "name": "m"}
    assert unwrap_metric_mapping(data) is data


# ── safe_metric_stem ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("orders", "orders"),
        ("-oops", "oops"),
        ("..sneaky", "sneaky"),
        ("../../escape", "_.._escape"),  # separators replaced -> one component
        ("/etc/cron.d/evil", "_etc_cron.d_evil"),
        ("a b\\c", "a_b_c"),
    ],
)
def test_safe_metric_stem(name, expected):
    stem = safe_metric_stem(name)
    assert stem == expected
    assert "/" not in stem and "\\" not in stem
    assert not stem.startswith((".", "-"))


def test_safe_metric_stem_never_empty():
    assert safe_metric_stem("---") == "metric"
    assert safe_metric_stem("метрика")  # unicode sanitizes to something non-empty


# ── archive_metric_text ──────────────────────────────────────────────────────


def test_archive_same_second_writes_keep_both(tmp_path, monkeypatch):
    """Two archives within one UTC second (e.g. a tune Apply + a UI save) both survive."""
    monkeypatch.setattr(metric_io, "metric_stamp", lambda *a, **kw: "20260624T101530Z")

    first = archive_metric_text(tmp_path, "orders", "v1\n")
    second = archive_metric_text(tmp_path, "orders", "v2\n")

    assert first != second
    assert first.read_text() == "v1\n"
    assert second.read_text() == "v2\n"
    assert second.name == "orders-20260624T101530Z-1.yml"


def test_archive_explicit_stamp_used_in_filename(tmp_path):
    path = archive_metric_text(tmp_path, "orders", "x\n", stamp="20990101T000000Z")
    assert path == tmp_path / "metrics" / ".history" / "orders" / "orders-20990101T000000Z.yml"


def test_archive_hostile_name_stays_inside_history(tmp_path):
    path = archive_metric_text(tmp_path, "../../escape", "x\n")
    history = (tmp_path / "metrics" / ".history").resolve()
    assert path.resolve().is_relative_to(history)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
