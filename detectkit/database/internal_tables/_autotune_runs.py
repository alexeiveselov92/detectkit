"""Autotune-runs mixin: ``_dtk_autotune_runs`` writes / reads.

Records one row per ``dtk autotune`` run — an audit trail of which inputs
(training period, labels, scoring metric) produced which outputs (chosen
seasonality, detector + params, score, generated config). Informational only:
never read by the load/detect/alert logic, and deliberately not pruned by
``dtk clean --orphaned-metrics``.

Backend-agnostic: the save path is a single ``insert_batch``; reads go through
``execute_query`` and ``self._manager.final_modifier`` (never a literal
``FINAL`` or ClickHouse-only SQL).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import numpy as np

from detectkit.database.internal_tables._base import _InternalTablesBase
from detectkit.database.tables import TABLE_AUTOTUNE_RUNS
from detectkit.utils.datetime_utils import now_utc_naive
from detectkit.utils.json_utils import json_dumps_sorted


class _AutotuneRunsMixin(_InternalTablesBase):
    def save_autotune_run(
        self,
        *,
        metric_name: str,
        run_id: str,
        training_period_start: datetime | None,
        training_period_end: datetime | None,
        interval_seconds: int,
        labels: Any,
        mode: str,
        scoring_metric: str,
        score: float | None,
        chosen_seasonality: Any,
        chosen_detector_type: str | None,
        chosen_detector_params: Any,
        winning_detector_id: str | None,
        candidate_detector_ids: Any,
        decision_log: Any,
        generated_config_path: str | None,
        generated_config_text: str,
        status: str,
        error_message: str | None = None,
    ) -> int:
        """Persist one autotune run as a single row.

        ``labels`` / ``chosen_seasonality`` / ``chosen_detector_params`` /
        ``candidate_detector_ids`` / ``decision_log`` are arbitrary
        JSON-serialisable values stored as JSON strings (sorted keys), matching
        the ``detector_params`` / ``tags`` convention elsewhere.
        """
        full_table_name = self._manager.get_full_table_name(TABLE_AUTOTUNE_RUNS, use_internal=True)
        data = {
            "metric_name": np.array([metric_name], dtype=object),
            "run_id": np.array([run_id], dtype=object),
            "created_at": np.array([now_utc_naive()], dtype="datetime64[ms]"),
            "training_period_start": (
                np.array([training_period_start], dtype="datetime64[ms]")
                if training_period_start is not None
                else np.array([None])
            ),
            "training_period_end": (
                np.array([training_period_end], dtype="datetime64[ms]")
                if training_period_end is not None
                else np.array([None])
            ),
            "interval_seconds": np.array([interval_seconds], dtype=np.int32),
            "labels_json": np.array([json_dumps_sorted(labels)], dtype=object),
            "mode": np.array([mode], dtype=object),
            "scoring_metric": np.array([scoring_metric], dtype=object),
            "score": (
                np.array([score], dtype=np.float64) if score is not None else np.array([None])
            ),
            "chosen_seasonality_json": np.array(
                [json_dumps_sorted(chosen_seasonality)], dtype=object
            ),
            "chosen_detector_type": np.array([chosen_detector_type], dtype=object),
            "chosen_detector_params_json": np.array(
                [json_dumps_sorted(chosen_detector_params)], dtype=object
            ),
            "winning_detector_id": np.array([winning_detector_id], dtype=object),
            "candidate_detector_ids_json": np.array(
                [json_dumps_sorted(candidate_detector_ids)], dtype=object
            ),
            "decision_log_json": np.array([json_dumps_sorted(decision_log)], dtype=object),
            "generated_config_path": np.array([generated_config_path], dtype=object),
            "generated_config_text": np.array([generated_config_text], dtype=object),
            "status": np.array([status], dtype=object),
            "error_message": np.array([error_message], dtype=object),
        }
        return self._manager.insert_batch(full_table_name, data, conflict_strategy="ignore")

    def get_autotune_runs(self, metric_name: str) -> list[dict]:
        """Return every stored run for *metric_name*, newest first."""
        full_table_name = self._manager.get_full_table_name(TABLE_AUTOTUNE_RUNS, use_internal=True)
        query = f"""
        SELECT *
        FROM {full_table_name}{self._manager.final_modifier}
        WHERE metric_name = %(metric_name)s
        ORDER BY created_at DESC
        """
        return self._manager.execute_query(query, {"metric_name": metric_name})

    def get_last_autotune_run(self, metric_name: str) -> dict | None:
        """Return the most recent run for *metric_name*, or ``None``."""
        rows = self.get_autotune_runs(metric_name)
        return rows[0] if rows else None
