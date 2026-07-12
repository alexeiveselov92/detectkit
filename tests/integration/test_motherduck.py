"""Env-gated smoke test against a real MotherDuck account.

MotherDuck is a served cloud database with no emulator, so this round trip
needs a real service token: set ``MOTHERDUCK_TOKEN`` to run it (skipped
otherwise — including in CI unless the secret is configured). No Docker
involved; the file lives in ``tests/integration/`` because it talks to an
external service. The DuckDB SQL surface itself is already covered by the
real local engine in ``tests/unit/test_duckdb_manager.py`` — what this adds
is the ``md:`` attach + token auth + a real internal-tables round trip on
the served database.

The test uses the account's default database (``md:``) and its own throwaway
schemas, dropped afterwards, so it is safe to run repeatedly.
"""

from __future__ import annotations

import os
from datetime import datetime

import numpy as np
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("MOTHERDUCK_TOKEN"),
        reason="set MOTHERDUCK_TOKEN to run the MotherDuck smoke test",
    ),
]

pytest.importorskip("duckdb")

_SCHEMA = "dtk_md_smoke"


def test_internal_tables_round_trip_on_motherduck():
    from detectkit.config.profile import ProfileConfig
    from detectkit.database.internal_tables.manager import InternalTablesManager

    profile = ProfileConfig(
        type="duckdb",
        path="md:",  # the account's default database
        internal_schema=_SCHEMA,
        data_schema=_SCHEMA,
        motherduck_token=os.environ["MOTHERDUCK_TOKEN"],
    )
    manager = profile.create_manager()
    try:
        internal = InternalTablesManager(manager)
        internal.ensure_tables()

        internal.save_datapoints(
            metric_name="md_smoke",
            data={
                "timestamp": np.array([np.datetime64("2024-01-01T00:00:00", "ms")]),
                "value": np.array([1.0]),
                "seasonality_data": np.array(["{}"], dtype=object),
            },
            interval_seconds=60,
            seasonality_columns=[],
        )
        assert internal.get_last_datapoint_timestamp("md_smoke") == datetime(2024, 1, 1)
    finally:
        try:
            manager.execute_query(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE")
        finally:
            manager.close()
