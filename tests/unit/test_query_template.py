"""Tests for QueryTemplate."""

from datetime import datetime

import pytest
from jinja2 import TemplateSyntaxError

from detectkit.loaders.query_template import QueryTemplate


class TestQueryTemplate:
    """Test QueryTemplate rendering."""

    def test_simple_variable_substitution(self):
        """Test basic variable substitution."""
        template = QueryTemplate()
        query = "SELECT * FROM {{ table_name }}"

        rendered = template.render(query, context={"table_name": "metrics"})

        assert rendered == "SELECT * FROM metrics"

    def test_multiple_variables(self):
        """Test multiple variable substitution."""
        template = QueryTemplate()
        query = """
        SELECT {{ column1 }}, {{ column2 }}
        FROM {{ table_name }}
        """

        rendered = template.render(
            query,
            context={
                "table_name": "cpu_metrics",
                "column1": "timestamp",
                "column2": "value"
            }
        )

        assert "timestamp" in rendered
        assert "value" in rendered
        assert "cpu_metrics" in rendered

    def test_built_in_dtk_start_time(self):
        """Test built-in dtk_start_time variable."""
        template = QueryTemplate()
        query = "SELECT * FROM metrics WHERE timestamp >= '{{ dtk_start_time }}'"

        dtk_start_time = datetime(2024, 1, 1, 0, 0, 0)
        rendered = template.render(query, dtk_start_time=dtk_start_time)

        assert "2024-01-01 00:00:00" in rendered

    def test_built_in_dtk_end_time(self):
        """Test built-in dtk_end_time variable."""
        template = QueryTemplate()
        query = "SELECT * FROM metrics WHERE timestamp < '{{ dtk_end_time }}'"

        dtk_end_time = datetime(2024, 1, 2, 0, 0, 0)
        rendered = template.render(query, dtk_end_time=dtk_end_time)

        assert "2024-01-02 00:00:00" in rendered

    def test_built_in_interval_seconds(self):
        """Test built-in interval_seconds variable."""
        template = QueryTemplate()
        query = "SELECT * FROM metrics WHERE interval = {{ interval_seconds }}"

        rendered = template.render(query, interval_seconds=600)

        assert "interval = 600" in rendered

    def test_all_built_in_variables(self):
        """Test all built-in variables together."""
        template = QueryTemplate()
        query = """
        SELECT *
        FROM metrics
        WHERE timestamp >= '{{ dtk_start_time }}'
          AND timestamp < '{{ dtk_end_time }}'
          AND interval = {{ interval_seconds }}
        """

        rendered = template.render(
            query,
            dtk_start_time=datetime(2024, 1, 1),
            dtk_end_time=datetime(2024, 1, 2),
            interval_seconds=600
        )

        assert "2024-01-01" in rendered
        assert "2024-01-02" in rendered
        assert "600" in rendered

    def test_custom_context_overrides_builtin(self):
        """Test that custom context can override built-in variables."""
        template = QueryTemplate()
        query = "SELECT * FROM metrics WHERE interval = {{ interval_seconds }}"

        # Built-in interval_seconds=600, but context overrides to 300
        rendered = template.render(
            query,
            context={"interval_seconds": 300},
            interval_seconds=600
        )

        assert "interval = 300" in rendered
        assert "600" not in rendered

    def test_conditional_if(self):
        """Test conditional rendering with {% if %}."""
        template = QueryTemplate()
        query = """
        SELECT *
        FROM metrics
        WHERE 1=1
        {% if filter_value is defined %}
          AND value > {{ filter_value }}
        {% endif %}
        """

        # With filter
        rendered = template.render(query, context={"filter_value": 0.5})
        assert "value > 0.5" in rendered

        # Without filter - use is defined check
        rendered = template.render(query, context={})
        assert "value >" not in rendered

    def test_conditional_else(self):
        """Test conditional with else clause."""
        template = QueryTemplate()
        query = """
        SELECT *
        FROM {% if use_cache %}cache_metrics{% else %}metrics{% endif %}
        """

        # use_cache = True
        rendered = template.render(query, context={"use_cache": True})
        assert "cache_metrics" in rendered
        assert "FROM metrics" not in rendered

        # use_cache = False
        rendered = template.render(query, context={"use_cache": False})
        assert "FROM metrics" in rendered
        assert "cache_metrics" not in rendered

    def test_loop(self):
        """Test loop rendering with {% for %}."""
        template = QueryTemplate()
        query = """
        SELECT *
        FROM metrics
        WHERE metric_name IN (
        {%- for name in metric_names -%}
          '{{ name }}'{% if not loop.last %},{% endif %}
        {%- endfor -%}
        )
        """

        rendered = template.render(
            query,
            context={"metric_names": ["cpu", "memory", "disk"]}
        )

        assert "'cpu'" in rendered
        assert "'memory'" in rendered
        assert "'disk'" in rendered

    def test_nested_conditions(self):
        """Test nested conditional rendering."""
        template = QueryTemplate()
        query = """
        SELECT *
        FROM metrics
        WHERE 1=1
        {% if filter_enabled %}
          {% if min_value %}
            AND value >= {{ min_value }}
          {% endif %}
          {% if max_value %}
            AND value <= {{ max_value }}
          {% endif %}
        {% endif %}
        """

        rendered = template.render(
            query,
            context={
                "filter_enabled": True,
                "min_value": 0.1,
                "max_value": 0.9
            }
        )

        assert "value >= 0.1" in rendered
        assert "value <= 0.9" in rendered

    def test_invalid_template_syntax(self):
        """Test error on invalid template syntax."""
        template = QueryTemplate()

        # Unclosed tag
        query = "SELECT * FROM {% if condition %} metrics"

        with pytest.raises(TemplateSyntaxError):
            template.render(query, context={"condition": True})

    def test_missing_variable_raises_error(self):
        """Test that missing variables raise error by default."""
        template = QueryTemplate()
        query = "SELECT * FROM {{ table_name }}"

        # Missing table_name variable
        with pytest.raises(Exception):
            template.render(query, context={})

    def test_render_with_defaults_missing_variable(self):
        """Test render_with_defaults handles missing variables with default filter."""
        template = QueryTemplate()
        query = "SELECT * FROM {{ table_name | default('metrics') }}"

        # Missing table_name, should use default value from filter
        rendered = template.render_with_defaults(query, context={})

        assert "FROM metrics" in rendered

    def test_render_with_defaults_no_default_filter(self):
        """Test render_with_defaults renders undefined as empty string."""
        template = QueryTemplate(strict=False)
        query = "SELECT * FROM metrics WHERE {{ undefined_var }} = 1"

        # Missing var without default filter renders as empty
        rendered = template.render(query, context={})

        assert "WHERE  = 1" in rendered

    def test_whitespace_control(self):
        """Test that whitespace is properly controlled."""
        template = QueryTemplate()
        query = """
        SELECT
        {%- for col in columns %}
          {{ col }}{% if not loop.last %},{% endif %}
        {%- endfor %}
        FROM metrics
        """

        rendered = template.render(
            query,
            context={"columns": ["timestamp", "value"]}
        )

        # Check both columns are present
        assert "timestamp" in rendered
        assert "value" in rendered
        assert "FROM metrics" in rendered

    def test_complex_real_world_query(self):
        """Test complex real-world query template."""
        template = QueryTemplate()
        query = """
        SELECT
            toStartOfInterval(timestamp, INTERVAL {{ interval_seconds }} SECOND) as timestamp,
            {{ aggregation }}(value) as value
        FROM {{ database }}.{{ table }}
        WHERE timestamp >= '{{ dtk_start_time }}'
          AND timestamp < '{{ dtk_end_time }}'
        {% if metric_filter %}
          AND metric_name = '{{ metric_filter }}'
        {% endif %}
        GROUP BY timestamp
        ORDER BY timestamp
        """

        rendered = template.render(
            query,
            context={
                "database": "analytics",
                "table": "metrics",
                "aggregation": "avg",
                "metric_filter": "cpu_usage"
            },
            dtk_start_time=datetime(2024, 1, 1),
            dtk_end_time=datetime(2024, 1, 2),
            interval_seconds=600
        )

        assert "analytics.metrics" in rendered
        assert "avg(value)" in rendered
        assert "cpu_usage" in rendered
        assert "2024-01-01" in rendered
        assert "600 SECOND" in rendered

    def test_empty_context(self):
        """Test rendering with empty context."""
        template = QueryTemplate()
        query = "SELECT 1 as value"

        rendered = template.render(query, context={})

        assert rendered == "SELECT 1 as value"

    def test_none_context(self):
        """Test rendering with None context."""
        template = QueryTemplate()
        query = "SELECT 1 as value"

        rendered = template.render(query, context=None)

        assert rendered == "SELECT 1 as value"

    def test_numeric_values(self):
        """Test rendering with numeric values."""
        template = QueryTemplate()
        query = """
        SELECT *
        FROM metrics
        WHERE value > {{ threshold }}
          AND interval = {{ interval }}
        """

        rendered = template.render(
            query,
            context={"threshold": 0.95, "interval": 600}
        )

        assert "value > 0.95" in rendered
        assert "interval = 600" in rendered

    def test_boolean_values(self):
        """Test rendering with boolean values."""
        template = QueryTemplate()
        query = """
        SELECT *
        FROM metrics
        WHERE is_active = {{ is_active }}
        """

        # True
        rendered = template.render(query, context={"is_active": True})
        assert "is_active = True" in rendered

        # False
        rendered = template.render(query, context={"is_active": False})
        assert "is_active = False" in rendered

    def test_list_values(self):
        """Test rendering with list values."""
        template = QueryTemplate()
        query = """
        SELECT *
        FROM metrics
        WHERE metric_name IN {{ metric_list }}
        """

        rendered = template.render(
            query,
            context={"metric_list": ["cpu", "memory", "disk"]}
        )

        assert "['cpu', 'memory', 'disk']" in rendered
