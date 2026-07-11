"""Tests for the OSI (Open Semantic Interchange) interop layer (`detectkit/semantic/`).

Covers the isolated converter — model parsing, the safe ClickHouse/Cube query
compilation (allowlist + hard-refuse), the `dtk osi import` scaffold, and the
`dtk osi export` round-trip. The ClickHouse target needs sqlglot (the `[osi]`
extra); those tests `importorskip` it so the suite still runs without it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from detectkit.config.metric_config import MetricConfig
from detectkit.semantic import (
    export_metric_to_osi,
    export_models,
    import_osi_metric,
    load_osi_models,
    parse_osi_models,
)
from detectkit.semantic.errors import OsiParseError, OsiUnsupportedMetric
from detectkit.semantic.osi_model import (
    DETECTKIT_VENDOR,
    OsiExpression,
    find_metric,
    normalize_ai_context,
)

OSI_TEXT = """
semantic_model:
  - name: ecommerce
    ai_context:
      instructions: "Revenue net of refunds, UTC."
    datasets:
      - name: store_sales
        source: analytics.store_sales
        custom_extensions:
          - vendor_name: detectkit
            data: '{"where": "amt > 0"}'
        fields:
          - name: sold_at
            dimension: {is_time: true}
    metrics:
      - name: total_sales
        description: Total sales revenue
        ai_context:
          synonyms: ["total revenue", "gross sales"]
        expression:
          dialects:
            - {dialect: ANSI_SQL, expression: "SUM(store_sales.ss_ext_sales_price)"}
      - name: aov
        expression:
          dialects:
            - {dialect: ANSI_SQL, expression: "SUM(store_sales.amt) / NULLIF(COUNT(DISTINCT store_sales.oid), 0)"}
      - name: running_total
        expression:
          dialects:
            - {dialect: ANSI_SQL, expression: "SUM(x) OVER (ORDER BY t)"}
      - name: raw_col
        expression:
          dialects:
            - {dialect: ANSI_SQL, expression: "store_sales.amt"}
"""


@pytest.fixture
def model_file(tmp_path: Path) -> Path:
    p = tmp_path / "ecommerce.osi.yml"
    p.write_text(OSI_TEXT)
    return p


# --------------------------------------------------------------------------
# osi_model — parsing, lookup, extensions, ai_context
# --------------------------------------------------------------------------
class TestModel:
    def test_load_and_find(self, model_file: Path):
        models = load_osi_models(model_file)
        assert len(models) == 1
        model, metric = find_metric(models, "total_sales")
        assert model.name == "ecommerce"
        assert metric.description == "Total sales revenue"

    def test_missing_metric_raises(self, model_file: Path):
        models = load_osi_models(model_file)
        with pytest.raises(OsiParseError, match="not found"):
            find_metric(models, "nope")

    def test_custom_extension_json_decoded(self, model_file: Path):
        models = load_osi_models(model_file)
        ds = models[0].dataset("store_sales")
        assert ds is not None
        assert ds.extension(DETECTKIT_VENDOR) == {"where": "amt > 0"}
        # absent vendor → {}
        assert ds.extension("other") == {}

    def test_empty_file_raises(self, tmp_path: Path):
        p = tmp_path / "empty.yml"
        p.write_text("")
        with pytest.raises(OsiParseError):
            load_osi_models(p)

    def test_for_dialect_prefers_then_falls_back(self):
        expr = OsiExpression(
            dialects=[
                {"dialect": "SNOWFLAKE", "expression": "snow"},
                {"dialect": "ANSI_SQL", "expression": "ansi"},
            ]
        )
        assert expr.for_dialect("ANSI_SQL", "SNOWFLAKE") == "ansi"
        assert expr.for_dialect("DATABRICKS") == "snow"  # falls back to first available

    def test_normalize_ai_context(self):
        assert normalize_ai_context(None) is None
        assert normalize_ai_context("  meaning ") == {"instructions": "meaning"}
        assert normalize_ai_context({"synonyms": ["a", " ", "b"]}) == {"synonyms": ["a", "b"]}
        assert normalize_ai_context({"instructions": "  "}) is None


# --------------------------------------------------------------------------
# osi_model — parse_osi_models, the text seam behind load_osi_models (powers
# the `dtk ui` Builder's "From OSI" paste box, which has no file on disk)
# --------------------------------------------------------------------------
class TestParseOsiModelsText:
    def test_parses_same_as_the_file_variant(self, model_file: Path):
        models = parse_osi_models(OSI_TEXT)
        assert len(models) == 1
        model, metric = find_metric(models, "total_sales")
        assert model.name == "ecommerce"
        assert metric.description == "Total sales revenue"
        # same content the path variant reads from disk
        assert [m.name for m in models] == [m.name for m in load_osi_models(model_file)]

    def test_error_message_carries_the_source_marker_not_a_path(self):
        with pytest.raises(OsiParseError, match=r"<pasted OSI model>"):
            parse_osi_models("not: [valid : yaml", source="<pasted OSI model>")

    def test_empty_text_raises_with_default_source(self):
        with pytest.raises(OsiParseError, match=r"<input>"):
            parse_osi_models("")

    def test_no_semantic_model_found_names_source(self):
        with pytest.raises(OsiParseError, match=r"no semantic_model found in <pasted OSI model>"):
            parse_osi_models("just_a_string", source="<pasted OSI model>")


# --------------------------------------------------------------------------
# query_gen — safe compilation (ClickHouse needs sqlglot)
# --------------------------------------------------------------------------
class TestQueryGenClickHouse:
    @pytest.fixture(autouse=True)
    def _need_sqlglot(self):
        pytest.importorskip("sqlglot")

    def test_additive_sum_compiles(self, model_file: Path):
        models = load_osi_models(model_file)
        r = import_osi_metric(models=models, metric_name="total_sales", interval="1h")
        assert "toStartOfInterval(sold_at, INTERVAL 3600 SECOND) AS timestamp" in r.sql
        assert "AS value" in r.sql
        assert "FROM analytics.store_sales AS store_sales" in r.sql
        assert "{{ dtk_start_time }}" in r.sql and "{{ dtk_end_time }}" in r.sql
        # dataset-level detectkit `where` is applied
        assert "amt > 0" in r.sql

    def test_ratio_with_nullif_and_distinct(self, model_file: Path):
        models = load_osi_models(model_file)
        r = import_osi_metric(models=models, metric_name="aov", interval="1d")
        assert "nullIf" in r.sql or "NULLIF" in r.sql
        assert "DISTINCT" in r.sql.upper()

    def test_window_function_refused(self, model_file: Path):
        models = load_osi_models(model_file)
        with pytest.raises(OsiUnsupportedMetric, match="window"):
            import_osi_metric(models=models, metric_name="running_total", interval="1h")

    def test_no_aggregate_refused(self, model_file: Path):
        models = load_osi_models(model_file)
        with pytest.raises(OsiUnsupportedMetric, match="no aggregate"):
            import_osi_metric(models=models, metric_name="raw_col", interval="1h")

    def test_scaffold_is_valid_metric_config(self, model_file: Path):
        models = load_osi_models(model_file)
        r = import_osi_metric(models=models, metric_name="total_sales", interval="1h")
        MetricConfig.model_validate(r.metric)  # raises if invalid
        assert r.metric["ai_context"]["synonyms"] == ["total revenue", "gross sales"]
        assert r.fingerprint and len(r.fingerprint) == 12

    def test_fingerprint_changes_with_sql(self, model_file: Path):
        from detectkit.semantic.query_gen import fingerprint

        assert fingerprint("a") != fingerprint("b")
        assert fingerprint("a") == fingerprint("a")


# --------------------------------------------------------------------------
# Cube target — no sqlglot needed
# --------------------------------------------------------------------------
class TestCubeTarget:
    def test_cube_measure_query(self, model_file: Path):
        models = load_osi_models(model_file)
        r = import_osi_metric(
            models=models,
            metric_name="total_sales",
            interval="1h",
            target="cube",
            cube="store_sales",
            time_dimension="sold_at",
        )
        assert "MEASURE(store_sales.total_sales) AS value" in r.sql
        assert "DATE_TRUNC('hour', store_sales.sold_at)" in r.sql
        assert r.target == "cube"

    def test_cube_requires_cube_name(self, model_file: Path):
        models = load_osi_models(model_file)
        with pytest.raises(OsiParseError, match="cube name"):
            import_osi_metric(
                models=models,
                metric_name="total_sales",
                interval="1h",
                target="cube",
                time_dimension="sold_at",
            )

    def test_cube_nonstandard_interval_refused(self, model_file: Path):
        models = load_osi_models(model_file)
        with pytest.raises(OsiUnsupportedMetric, match="granularity"):
            import_osi_metric(
                models=models,
                metric_name="total_sales",
                interval="10min",
                target="cube",
                cube="store_sales",
                time_dimension="sold_at",
            )


# --------------------------------------------------------------------------
# exporter — OSI fragment + lossless custom_extensions[detectkit]
# --------------------------------------------------------------------------
class TestExport:
    def _cfg(self) -> MetricConfig:
        return MetricConfig(
            name="rev",
            interval="1h",
            query="SELECT timestamp, value FROM t",
            detectors=[{"type": "mad", "params": {"threshold": 2.5, "window_size": 200}}],
            alerting=[{"channels": ["ops"], "consecutive_anomalies": 2}],
            ai_context={"synonyms": ["revenue"], "instructions": "net revenue"},
            tags=["critical"],
        )

    def test_metric_entry_shape(self):
        entry = export_metric_to_osi(self._cfg())
        assert entry["name"] == "rev"
        assert entry["ai_context"]["synonyms"] == ["revenue"]
        # the portable measure is a placeholder; the real def is in the extension
        assert entry["expression"]["dialects"][0]["dialect"] == "ANSI_SQL"
        ext = entry["custom_extensions"][0]
        assert ext["vendor_name"] == DETECTKIT_VENDOR
        payload = json.loads(ext["data"])
        assert payload["detectors"][0]["params"]["threshold"] == 2.5
        assert payload["alerting"][0]["channels"] == ["ops"]
        assert payload["query"].startswith("SELECT")
        assert payload["tags"] == ["critical"]

    def test_export_models_document(self):
        doc = export_models([self._cfg()], model_name="my_export")
        assert doc["semantic_model"][0]["name"] == "my_export"
        assert len(doc["semantic_model"][0]["metrics"]) == 1

    def test_no_ai_context_omitted(self):
        cfg = MetricConfig(name="x", interval="1h", query="SELECT timestamp, value FROM t")
        entry = export_metric_to_osi(cfg)
        assert "ai_context" not in entry
