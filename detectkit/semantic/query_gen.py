"""Compile an OSI metric expression into a detectkit time-bucketed series query.

This is the deliberately-narrow, **safe** bridge from "an OSI aggregate over a
dataset" to "one numeric value per fixed interval on a complete time grid" (the
contract detectkit's loader + gap-fill expect). Two targets:

- ``clickhouse`` — a direct ``toStartOfInterval(...) GROUP BY`` query against the
  dataset's physical ``source``. The ANSI measure expression is transpiled with
  **sqlglot** (an optional dependency, the ``[osi]`` extra) rather than a
  hand-rolled normalizer.
- ``cube`` — a Cube **SQL API** query (``MEASURE(...)`` + ``DATE_TRUNC`` on a time
  dimension) so detectkit alerts on the SAME governed series a Cube-backed
  dashboard shows (number-parity). The metric just points at a Postgres profile
  on Cube's SQL port.

**Safety by allowlist, not best-effort.** Only provably per-bucket-additive
shapes compile — ``SUM`` / ``COUNT`` / ``COUNT(DISTINCT)`` / ``AVG`` / ``MIN`` /
``MAX`` and ratios of them. Window functions, non-aggregate expressions and
unsupported aggregates are **hard-refused** (``OsiUnsupportedMetric``) instead of
emitting a plausible-but-wrong series — a wrong monitored number is worse than no
integration. Semi-additive measures (balances, "last in period") have no marker
in OSI, so the generated SQL is always printed for human review before commit.

Every generated query is a **Jinja template** carrying ``{{ dtk_start_time }}`` /
``{{ dtk_end_time }}`` — the existing loader injects the window unchanged.
"""

from __future__ import annotations

import hashlib
from typing import Any

from detectkit.semantic.errors import OsiDependencyMissing, OsiUnsupportedMetric

# OSI dialect name (verified enum) → sqlglot read dialect. The non-SQL members
# (MDX/TABLEAU/MAQL) have no SQL to transpile. ClickHouse is intentionally absent
# from OSI — a ClickHouse override rides in custom_extensions[detectkit], not here.
_OSI_TO_SQLGLOT = {
    "ANSI_SQL": None,  # generic SQL — sqlglot's default reader
    "SNOWFLAKE": "snowflake",
    "DATABRICKS": "databricks",
}
# Aggregates that are safe to compute independently per time bucket. (Count covers
# COUNT(DISTINCT) — still one value per bucket.) Everything else is refused.
_ALLOWED_AGGS = {"Sum", "Count", "Avg", "Min", "Max"}

# Standard Cube SQL-API DATE_TRUNC granularities → seconds. A metric interval must
# map to one of these for the cube target (Cube SQL has no arbitrary-N-minute bin).
_CUBE_GRANULARITY = {
    60: "minute",
    3600: "hour",
    86400: "day",
    604800: "week",
    2592000: "month",
}


def _sqlglot() -> Any:
    """Import sqlglot lazily so the core library has no hard dependency on it."""
    try:
        import sqlglot  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - exercised via OsiDependencyMissing
        raise OsiDependencyMissing(
            "OSI compilation needs sqlglot — install the extra: pip install 'detectkit[osi]'"
        ) from exc
    return sqlglot


def _read_dialect(osi_dialect: str | None) -> str | None:
    """Map an OSI dialect name to a sqlglot read dialect (None = generic SQL)."""
    if osi_dialect is None:
        return None
    name = osi_dialect.upper()
    if name not in _OSI_TO_SQLGLOT:
        raise OsiUnsupportedMetric(
            f"OSI dialect '{osi_dialect}' is not SQL-transpilable. Provide an ANSI_SQL "
            f"expression, or a ClickHouse override in custom_extensions[detectkit]."
        )
    return _OSI_TO_SQLGLOT[name]


def parse_expr(expr: str, osi_dialect: str | None) -> Any:
    """Parse a bare SQL expression with sqlglot (raises OsiUnsupportedMetric on junk)."""
    sqlglot = _sqlglot()
    try:
        tree = sqlglot.parse_one(expr, read=_read_dialect(osi_dialect))
    except Exception as exc:  # sqlglot.ParseError + friends
        raise OsiUnsupportedMetric(f"could not parse expression {expr!r}: {exc}") from exc
    if tree is None:
        raise OsiUnsupportedMetric(f"empty/unparseable expression: {expr!r}")
    return tree


def assert_additive(expr: str, osi_dialect: str | None) -> None:
    """Refuse any expression that isn't a per-bucket-additive aggregate (or a ratio of them).

    This is the line between a correct monitored series and a silently-wrong one:
    window functions, raw columns / no aggregate, and unsupported aggregates are
    rejected with a clear reason rather than compiled.
    """
    from sqlglot import exp  # local import: sqlglot is optional

    tree = parse_expr(expr, osi_dialect)

    if list(tree.find_all(exp.Window)):
        raise OsiUnsupportedMetric(
            "window functions (OVER ...) aren't per-bucket additive — not monitorable as a "
            "single series. Use query_file: to hand-write this metric."
        )
    aggs = list(tree.find_all(exp.AggFunc))
    if not aggs:
        raise OsiUnsupportedMetric(
            "no aggregate found — a detectkit series needs one value per bucket "
            "(SUM/COUNT/AVG/MIN/MAX or a ratio of them). Use query_file: instead."
        )
    bad = sorted({type(a).__name__ for a in aggs} - _ALLOWED_AGGS)
    if bad:
        raise OsiUnsupportedMetric(
            f"aggregate(s) {bad} aren't known to be per-bucket additive. Allowed: "
            f"{sorted(_ALLOWED_AGGS)}. Use query_file: for anything else."
        )


def transpile_to_clickhouse(expr: str, osi_dialect: str | None) -> str:
    """Render *expr* as a ClickHouse expression string via sqlglot."""
    tree = parse_expr(expr, osi_dialect)
    return tree.sql(dialect="clickhouse")


def _from_clause(source: str, alias: str) -> str:
    """A FROM target from an OSI ``dataset.source`` (a table ref OR a query).

    A query source is wrapped as a sub-select; a table ref is aliased to the
    dataset name so dataset-qualified columns (``store_sales.col``) resolve.
    """
    s = source.strip().rstrip(";")
    if "select" in s.lower() and " " in s:
        return f"(\n{s}\n) AS {alias}"
    return f"{s} AS {alias}"


def build_clickhouse_series_sql(
    *,
    source: str,
    dataset_alias: str,
    time_expr: str,
    measure_expr: str,
    osi_dialect: str | None,
    interval_seconds: int,
    where: str | None = None,
    clickhouse_measure_override: str | None = None,
) -> str:
    """Compile a one-value-per-bucket ClickHouse series query (a Jinja template).

    ``clickhouse_measure_override`` (from custom_extensions[detectkit]) is used
    verbatim when present — otherwise the ANSI ``measure_expr`` is checked for
    additivity and transpiled. The result still satisfies detectkit's loader
    contract: it returns ``timestamp`` + ``value`` and leaves the
    ``{{ dtk_start_time }}`` / ``{{ dtk_end_time }}`` window for the loader.
    """
    if clickhouse_measure_override:
        measure_ch = clickhouse_measure_override
    else:
        assert_additive(measure_expr, osi_dialect)
        measure_ch = transpile_to_clickhouse(measure_expr, osi_dialect)
    time_ch = transpile_to_clickhouse(time_expr, osi_dialect)
    extra = f"\n  AND ({where})" if where else ""
    return (
        "SELECT\n"
        f"    toStartOfInterval({time_ch}, INTERVAL {int(interval_seconds)} SECOND) AS timestamp,\n"
        f"    {measure_ch} AS value\n"
        f"FROM {_from_clause(source, dataset_alias)}\n"
        f"WHERE {time_ch} >= toDateTime('{{{{ dtk_start_time }}}}')\n"
        f"  AND {time_ch} <  toDateTime('{{{{ dtk_end_time }}}}'){extra}\n"
        "GROUP BY timestamp\n"
        "ORDER BY timestamp"
    )


def interval_to_cube_granularity(interval_seconds: int) -> str:
    """Map a metric interval to a Cube SQL ``DATE_TRUNC`` granularity, or refuse."""
    gran = _CUBE_GRANULARITY.get(int(interval_seconds))
    if gran is None:
        allowed = ", ".join(f"{s}s={g}" for s, g in _CUBE_GRANULARITY.items())
        raise OsiUnsupportedMetric(
            f"interval {interval_seconds}s has no standard Cube DATE_TRUNC granularity "
            f"(supported: {allowed}). Use --target clickhouse, or pick a standard grain."
        )
    return gran


def build_cube_series_sql(
    *,
    cube: str,
    measure: str,
    time_dimension: str,
    interval_seconds: int,
    where: str | None = None,
) -> str:
    """Compile a Cube SQL-API series query (a Jinja template).

    Runs the metric through Cube's governed semantic layer (``MEASURE(...)``), so
    detectkit alerts on the SAME numbers a Cube-backed dashboard shows. The metric
    targets a Postgres profile pointed at Cube's SQL port.
    """
    gran = interval_to_cube_granularity(interval_seconds)
    td = f"{cube}.{time_dimension}"
    extra = f"\n  AND ({where})" if where else ""
    return (
        "SELECT\n"
        f"    DATE_TRUNC('{gran}', {td}) AS timestamp,\n"
        f"    MEASURE({cube}.{measure}) AS value\n"
        f"FROM {cube}\n"
        f"WHERE {td} >= '{{{{ dtk_start_time }}}}'\n"
        f"  AND {td} <  '{{{{ dtk_end_time }}}}'{extra}\n"
        "GROUP BY 1\n"
        "ORDER BY 1"
    )


def fingerprint(sql: str) -> str:
    """A short, stable hash of a generated query.

    Written into the scaffolded metric's header so a later re-import that changes
    the compiled SQL is visible as a diff — a hint to backfill/clean, since
    detectkit resumes from the last datapoint and won't recompute history on its
    own.
    """
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()[:12]
