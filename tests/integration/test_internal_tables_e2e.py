"""End-to-end checks against a real ClickHouse server.

Smoke-level coverage: schema creation, datapoint round-trips, and that
SQL injection attempts via crafted ``metric_name`` values are neutralised
by the parameterised queries we now use everywhere.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

pytestmark = pytest.mark.integration


def _make_datapoints(metric_name: str, n: int = 5) -> dict:
    base = datetime(2024, 1, 1, 0, 0, 0)
    return {
        "timestamp": np.array(
            [base + timedelta(minutes=i) for i in range(n)],
            dtype="datetime64[ms]",
        ),
        "value": np.linspace(0.1, 0.5, n, dtype=np.float64),
        "seasonality_data": np.array(["{}"] * n, dtype=object),
    }


def test_save_and_load_datapoints_roundtrip(internal_tables):
    rows = internal_tables.save_datapoints(
        metric_name="cpu_usage",
        data=_make_datapoints("cpu_usage"),
        interval_seconds=60,
        seasonality_columns=[],
    )
    assert rows == 5

    loaded = internal_tables.load_datapoints("cpu_usage")
    assert len(loaded["timestamp"]) == 5
    assert np.allclose(loaded["value"], np.linspace(0.1, 0.5, 5))


def test_get_last_datapoint_timestamp_returns_none_when_empty(internal_tables):
    # Different metric → ``MAX(timestamp)`` returns the epoch sentinel,
    # which the helper must normalise to ``None``.
    assert internal_tables.get_last_datapoint_timestamp("never_seen") is None


def test_reinsert_newer_version_keeps_latest_value(internal_tables):
    """Re-saving the same (metric, timestamp) with a newer version must surface
    the latest value — last-writer-wins, reproducing ReplacingMergeTree."""
    base = datetime(2024, 6, 1, 0, 0, 0)
    ts = np.array([base], dtype="datetime64[ms]")

    internal_tables.save_datapoints(
        metric_name="reinsert",
        data={
            "timestamp": ts,
            "value": np.array([1.0], dtype=np.float64),
            "seasonality_data": np.array(["{}"], dtype=object),
        },
        interval_seconds=60,
        seasonality_columns=[],
    )
    internal_tables.save_datapoints(
        metric_name="reinsert",
        data={
            "timestamp": ts,
            "value": np.array([2.0], dtype=np.float64),
            "seasonality_data": np.array(["{}"], dtype=object),
        },
        interval_seconds=60,
        seasonality_columns=[],
    )

    loaded = internal_tables.load_datapoints("reinsert")
    values = list(loaded["value"])
    if type(internal_tables._manager).__name__ == "ClickHouseDatabaseManager":
        # ClickHouse dedup is eventual (no FINAL on the load path); the latest
        # value must at least be present.
        assert 2.0 in values
    else:
        # SQL backends enforce the primary key: exactly one row, latest value.
        assert values == [2.0]


def test_metric_name_with_quotes_is_safe(internal_tables):
    """Crafted metric_name must never run as SQL — verifies parameterisation."""
    payload = "x'); DROP TABLE _dtk_datapoints; --"
    internal_tables.save_datapoints(
        metric_name=payload,
        data=_make_datapoints(payload, n=2),
        interval_seconds=60,
        seasonality_columns=[],
    )
    loaded = internal_tables.load_datapoints(payload)
    assert len(loaded["timestamp"]) == 2

    # Sanity: original table still exists and a normal metric still works.
    internal_tables.save_datapoints(
        metric_name="post_attack",
        data=_make_datapoints("post_attack", n=1),
        interval_seconds=60,
        seasonality_columns=[],
    )
    assert internal_tables.get_last_datapoint_timestamp("post_attack") is not None
