"""Import an OSI metric into a native detectkit metric (the "enhanced init").

``dtk osi import`` reads a governed OSI model, resolves one metric, and scaffolds
a **normal native metric YAML** — SQL query, interval, seasonality, a starter
detector, and the metric's ``ai_context`` carried over. The output is reviewed by
a human and committed like any hand-written metric: there is **no runtime
dependency on OSI** and the load/detect/alert pipeline is untouched. This is the
cheap, reversible hedge — author the KPI once in OSI, bootstrap a detector here.

Two targets (``--target``): ``clickhouse`` compiles a direct ClickHouse series
query from the dataset's physical ``source``; ``cube`` compiles a Cube SQL-API
query so detectkit alerts on the same governed numbers as a Cube dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from detectkit.config.metric_config import MetricConfig
from detectkit.semantic import query_gen
from detectkit.semantic.errors import OsiParseError, OsiUnsupportedMetric
from detectkit.semantic.osi_model import (
    DETECTKIT_VENDOR,
    OsiSemanticModel,
    find_metric,
    normalize_ai_context,
)

# ANSI is the portable canonical dialect; we prefer it, then other SQL dialects.
_PREFERRED_DIALECTS = ("ANSI_SQL", "SNOWFLAKE", "DATABRICKS")


@dataclass
class ImportResult:
    """The outcome of importing one OSI metric."""

    metric_name: str
    metric: dict[str, Any]  # the native metric body (validated through MetricConfig)
    sql: str
    fingerprint: str
    target: str
    warnings: list[str] = field(default_factory=list)


def _opt(*values: Any) -> Any:
    """First non-empty value (explicit arg > metric ext > dataset ext > default)."""
    for v in values:
        if v:
            return v
    return None


def _resolve_dialect_expr(expr_obj: Any) -> tuple[str | None, str | None]:
    """Pick (dialect_name, expression) from an OSI expression, preferring ANSI_SQL."""
    if expr_obj is None:
        return None, None
    chosen = expr_obj.for_dialect(*_PREFERRED_DIALECTS)
    if chosen is None:
        return None, None
    # Recover which dialect name we landed on (for the sqlglot read mapping).
    for name in _PREFERRED_DIALECTS:
        if expr_obj.for_dialect(name) == chosen:
            return name, chosen
    first = next((d for d in expr_obj.dialects if d.expression), None)
    return (first.dialect if first else None), chosen


def import_osi_metric(
    *,
    models: list[OsiSemanticModel],
    metric_name: str,
    interval: int | str,
    target: str = "clickhouse",
    dataset: str | None = None,
    time_field: str | None = None,
    where: str | None = None,
    cube: str | None = None,
    cube_measure: str | None = None,
    time_dimension: str | None = None,
    seasonality: list[str] | None = None,
    detector_type: str = "mad",
) -> ImportResult:
    """Resolve *metric_name* across *models* and scaffold a native metric body.

    Returns an :class:`ImportResult`; the metric body is validated through
    :class:`MetricConfig` before return, so an unparseable/unsupported metric
    raises (writing nothing). ``interval`` is required because OSI is
    grain-agnostic — the grain is a detectkit choice.
    """
    if target not in ("clickhouse", "cube"):
        raise OsiUnsupportedMetric(f"unknown target '{target}' (use clickhouse or cube)")

    model, metric = find_metric(models, metric_name)
    mext = metric.extension(DETECTKIT_VENDOR)
    warnings: list[str] = []

    if target == "cube":
        sql, fp, more = _build_cube(
            metric=metric,
            mext=mext,
            interval=interval,
            cube=cube,
            cube_measure=cube_measure,
            time_dimension=time_dimension,
            where=where,
        )
    else:
        sql, fp, more = _build_clickhouse(
            model=model,
            metric=metric,
            mext=mext,
            interval=interval,
            dataset=dataset,
            time_field=time_field,
            where=where,
        )
    warnings.extend(more)

    # ai_context: metric-level, falling back to the model's instructions.
    ai_ctx = normalize_ai_context(metric.ai_context)
    if ai_ctx is None:
        model_ctx = normalize_ai_context(model.ai_context)
        if model_ctx and model_ctx.get("instructions"):
            ai_ctx = {"instructions": model_ctx["instructions"]}

    body: dict[str, Any] = {
        "name": metric.name,
        "interval": interval,
        "query": sql + "\n",
        "detectors": [{"type": detector_type, "params": {"threshold": 3.0}}],
    }
    if metric.description:
        body["description"] = metric.description
    if ai_ctx:
        body["ai_context"] = ai_ctx
    if seasonality:
        body["seasonality_columns"] = list(seasonality)

    # Validate-before-write: the scaffold must be a valid MetricConfig (and the
    # query a real string). Surfaces a bad compile as an error, not a broken file.
    try:
        MetricConfig.model_validate(body)
    except Exception as exc:
        raise OsiParseError(f"generated metric for '{metric_name}' is invalid: {exc}") from exc

    warnings.append(
        "Review the generated SQL before committing. OSI carries no aggregation-type "
        "marker, so verify the measure is additive per bucket (semi-additive measures "
        "like balances/last-in-period must be hand-written)."
    )
    return ImportResult(
        metric_name=metric.name,
        metric=body,
        sql=sql,
        fingerprint=fp,
        target=target,
        warnings=warnings,
    )


def _build_clickhouse(
    *,
    model: OsiSemanticModel,
    metric: Any,
    mext: dict[str, Any],
    interval: int | str,
    dataset: str | None,
    time_field: str | None,
    where: str | None,
) -> tuple[str, str, list[str]]:
    warnings: list[str] = []
    # Resolve the dataset: explicit arg > metric ext > the single dataset.
    ds_name = _opt(dataset, mext.get("dataset"))
    if ds_name:
        ds = model.dataset(ds_name)
        if ds is None:
            raise OsiParseError(f"dataset '{ds_name}' not found in model '{model.name}'")
    elif len(model.datasets) == 1:
        ds = model.datasets[0]
    else:
        names = ", ".join(d.name for d in model.datasets)
        raise OsiParseError(
            f"metric references no single dataset and the model has several ({names}); "
            f"pass --dataset (or set it in custom_extensions[detectkit])."
        )
    dext = ds.extension(DETECTKIT_VENDOR)

    source = _opt(mext.get("source"), dext.get("source"), mext.get("clickhouse_table"), ds.source)
    if not source:
        raise OsiParseError(
            f"dataset '{ds.name}' has no `source` (and no detectkit override) — "
            f"can't build a FROM clause."
        )

    # Time grain column: explicit arg > ext > a dataset field flagged is_time.
    tf = _opt(time_field, mext.get("time_field"), dext.get("time_field"))
    if not tf:
        time_dim_field = next(
            (f for f in ds.fields if f.dimension and f.dimension.is_time),
            None,
        )
        if time_dim_field is None:
            raise OsiParseError(
                f"no time field — pass --time-field, set it in custom_extensions[detectkit], "
                f"or mark a field with dimension.is_time in dataset '{ds.name}'."
            )
        tf = time_dim_field.name
    # If the time field names an OSI field with its own expression, use that.
    tf_field = ds.field(tf)
    if tf_field is not None and tf_field.expression is not None:
        _, time_expr = _resolve_dialect_expr(tf_field.expression)
        time_expr = time_expr or tf
    else:
        time_expr = tf

    dialect, measure_expr = _resolve_dialect_expr(metric.expression)
    ch_override = _opt(mext.get("clickhouse_expression"))
    if not measure_expr and not ch_override:
        raise OsiUnsupportedMetric(
            f"metric '{metric.name}' has no usable expression (and no ClickHouse override)."
        )

    sql = query_gen.build_clickhouse_series_sql(
        source=source,
        dataset_alias=ds.name,
        time_expr=time_expr,
        measure_expr=measure_expr or "",
        osi_dialect=dialect,
        interval_seconds=_interval_seconds(interval),
        where=_opt(where, mext.get("where"), dext.get("where")),
        clickhouse_measure_override=ch_override,
    )
    if ch_override:
        warnings.append("Used the custom_extensions[detectkit] ClickHouse override verbatim.")
    return sql, query_gen.fingerprint(sql), warnings


def _build_cube(
    *,
    metric: Any,
    mext: dict[str, Any],
    interval: int | str,
    cube: str | None,
    cube_measure: str | None,
    time_dimension: str | None,
    where: str | None,
) -> tuple[str, str, list[str]]:
    cube_name = _opt(cube, mext.get("cube"))
    if not cube_name:
        raise OsiParseError(
            "cube target needs a cube name — pass --cube or set `cube` in "
            "custom_extensions[detectkit]."
        )
    measure = _opt(cube_measure, mext.get("cube_measure"), metric.name)
    td = _opt(time_dimension, mext.get("time_dimension"), mext.get("time_field"))
    if not td:
        raise OsiParseError(
            "cube target needs a time dimension — pass --time-field or set "
            "`time_dimension` in custom_extensions[detectkit]."
        )
    sql = query_gen.build_cube_series_sql(
        cube=cube_name,
        measure=measure,
        time_dimension=td,
        interval_seconds=_interval_seconds(interval),
        where=_opt(where, mext.get("where")),
    )
    note = [
        "Point this metric's profile at a Postgres connection on Cube's SQL API port "
        "(CUBEJS_PG_SQL_PORT) so the MEASURE(...) query runs through Cube — the alert "
        "then matches the dashboard number by construction."
    ]
    return sql, query_gen.fingerprint(sql), note


def _interval_seconds(interval: int | str) -> int:
    """Parse a metric interval to seconds via the canonical Interval parser."""
    from detectkit.core.interval import Interval

    return Interval(interval).seconds
