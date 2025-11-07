"""
SQL query templating with Jinja2.

Provides templating capabilities for SQL queries with built-in variables
and custom context.
"""

from datetime import datetime
from typing import Any, Dict, Optional

from jinja2 import Environment, StrictUndefined, Template, TemplateSyntaxError, Undefined, UndefinedError


class QueryTemplate:
    """
    SQL query template renderer using Jinja2.

    Supports:
    - Variable substitution: {{ variable }}
    - Conditionals: {% if condition %}...{% endif %}
    - Loops: {% for item in items %}...{% endfor %}
    - Built-in variables: from_date, to_date, interval_seconds

    Example:
        >>> template = QueryTemplate()
        >>> query = "SELECT * FROM metrics WHERE timestamp >= '{{ from_date }}'"
        >>> rendered = template.render(
        ...     query,
        ...     {"from_date": "2024-01-01", "to_date": "2024-01-02"}
        ... )
        >>> print(rendered)
        SELECT * FROM metrics WHERE timestamp >= '2024-01-01'
    """

    def __init__(self, strict: bool = True):
        """
        Initialize Jinja2 environment.

        Args:
            strict: If True, raise error on undefined variables
        """
        self._env = Environment(
            autoescape=False,  # Don't escape SQL
            trim_blocks=True,  # Remove newlines after blocks
            lstrip_blocks=True,  # Remove leading whitespace before blocks
            undefined=StrictUndefined if strict else Undefined,  # Raise on undefined vars
        )

    def render(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        dtk_start_time: Optional[datetime] = None,
        dtk_end_time: Optional[datetime] = None,
        interval_seconds: Optional[int] = None,
    ) -> str:
        """
        Render SQL query template with context.

        Args:
            query: SQL query template string
            context: Custom variables for template
            dtk_start_time: Built-in variable for time range start
            dtk_end_time: Built-in variable for time range end
            interval_seconds: Built-in variable for interval

        Returns:
            Rendered SQL query

        Raises:
            TemplateSyntaxError: If template syntax is invalid
            Exception: If template rendering fails

        Example:
            >>> template = QueryTemplate()
            >>> query = '''
            ... SELECT
            ...     timestamp,
            ...     value
            ... FROM {{ table_name }}
            ... WHERE timestamp >= '{{ dtk_start_time }}'
            ...   AND timestamp < '{{ dtk_end_time }}'
            ... {% if interval_seconds %}
            ...   AND interval = {{ interval_seconds }}
            ... {% endif %}
            ... '''
            >>> rendered = template.render(
            ...     query,
            ...     context={"table_name": "cpu_metrics"},
            ...     dtk_start_time=datetime(2024, 1, 1),
            ...     dtk_end_time=datetime(2024, 1, 2),
            ...     interval_seconds=600
            ... )
        """
        # Build context with built-in and custom variables
        template_context = {}

        # Add built-in variables (format datetime to string for SQL compatibility)
        if dtk_start_time is not None:
            # Format as ISO 8601 "YYYY-MM-DD HH:MM:SS" - works in ClickHouse, PostgreSQL, MySQL, SQLite
            template_context["dtk_start_time"] = dtk_start_time.strftime("%Y-%m-%d %H:%M:%S")
        if dtk_end_time is not None:
            template_context["dtk_end_time"] = dtk_end_time.strftime("%Y-%m-%d %H:%M:%S")
        if interval_seconds is not None:
            template_context["interval_seconds"] = interval_seconds

        # Add custom variables (overwrites built-ins if conflict)
        if context:
            template_context.update(context)

        # Compile and render template
        try:
            template = self._env.from_string(query)
            return template.render(template_context)
        except TemplateSyntaxError as e:
            raise TemplateSyntaxError(
                f"Invalid template syntax: {e.message}", e.lineno
            )
        except Exception as e:
            raise Exception(f"Template rendering failed: {e}")

    def render_with_defaults(
        self,
        query: str,
        context: Optional[Dict[str, Any]] = None,
        dtk_start_time: Optional[datetime] = None,
        dtk_end_time: Optional[datetime] = None,
        interval_seconds: Optional[int] = None,
    ) -> str:
        """
        Render query with sensible defaults for missing variables.

        This is useful for testing and development where you might not
        have all variables defined. Use {{ var | default('value') }} syntax
        in templates.

        Args:
            query: SQL query template
            context: Custom variables
            dtk_start_time: Start time
            dtk_end_time: End time
            interval_seconds: Interval in seconds

        Returns:
            Rendered SQL query

        Example:
            >>> template = QueryTemplate()
            >>> # Use default filter for missing variables
            >>> query = "SELECT * FROM {{ table | default('metrics') }}"
            >>> rendered = template.render_with_defaults(query)
            >>> print(rendered)
            SELECT * FROM metrics
        """
        # Create non-strict environment for this render
        non_strict_template = QueryTemplate(strict=False)

        return non_strict_template.render(
            query,
            context=context,
            dtk_start_time=dtk_start_time,
            dtk_end_time=dtk_end_time,
            interval_seconds=interval_seconds,
        )
