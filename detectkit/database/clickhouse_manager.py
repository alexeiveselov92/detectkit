"""
ClickHouse database manager implementation.

Implements BaseDatabaseManager for ClickHouse using universal methods.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np

try:
    from clickhouse_driver import Client
    CLICKHOUSE_AVAILABLE = True
except ImportError:
    CLICKHOUSE_AVAILABLE = False

from detectkit.core.models import ColumnDefinition, TableModel
from detectkit.database.manager import BaseDatabaseManager


class ClickHouseDatabaseManager(BaseDatabaseManager):
    """
    ClickHouse implementation of BaseDatabaseManager.

    Uses universal methods - does NOT hardcode internal table logic.

    Args:
        host: ClickHouse host
        port: ClickHouse port (default: 9000 for native protocol)
        user: Database user
        password: Database password
        internal_database: Database for internal tables (_dtk_*)
        data_database: Database for user data tables
        settings: Optional ClickHouse settings
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9000,
        user: str = "default",
        password: str = "",
        internal_database: str = "detectk_internal",
        data_database: str = "default",
        settings: Optional[Dict[str, Any]] = None,
    ):
        """Initialize ClickHouse manager."""
        if not CLICKHOUSE_AVAILABLE:
            raise ImportError(
                "clickhouse-driver is not installed. "
                "Install with: pip install detectk[clickhouse]"
            )

        self._internal_database = internal_database
        self._data_database = data_database

        # Create client
        self._client = Client(
            host=host,
            port=port,
            user=user,
            password=password,
            settings=settings or {},
        )

        # Ensure databases exist
        self._ensure_databases()

    def _ensure_databases(self) -> None:
        """Create internal and data databases if they don't exist."""
        for db in [self._internal_database, self._data_database]:
            self._client.execute(f"CREATE DATABASE IF NOT EXISTS {db}")

    def execute_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute SQL query and return results as list of dictionaries.

        Args:
            query: SQL query to execute
            params: Optional query parameters

        Returns:
            List of dictionaries where each dict represents a row
        """
        # Execute query with or without parameters
        if params:
            result = self._client.execute(query, params, with_column_types=True)
        else:
            result = self._client.execute(query, with_column_types=True)

        # result is tuple: (rows, columns_with_types)
        # columns_with_types is list of tuples: (name, type)
        rows, columns_with_types = result
        column_names = [col[0] for col in columns_with_types]

        # Convert to list of dicts
        return [
            dict(zip(column_names, row))
            for row in rows
        ]

    def create_table(
        self,
        table_name: str,
        table_model: TableModel,
        if_not_exists: bool = True
    ) -> None:
        """
        Create ClickHouse table from TableModel.

        Converts generic TableModel to ClickHouse-specific DDL.

        Args:
            table_name: Name of table to create
            table_model: Table schema definition
            if_not_exists: Add IF NOT EXISTS clause
        """
        # Build column definitions
        col_defs = []
        for col in table_model.columns:
            col_def = f"{col.name} {col.type}"
            if col.default is not None:
                col_def += f" DEFAULT {self._format_default(col.default)}"
            col_defs.append(col_def)

        columns_sql = ",\n    ".join(col_defs)

        # Build CREATE TABLE statement
        if_not_exists_clause = "IF NOT EXISTS " if if_not_exists else ""

        # For ClickHouse, use engine and order_by from table_model
        engine = table_model.engine or "MergeTree"
        order_by = table_model.order_by or table_model.primary_key

        order_by_clause = ", ".join(order_by)

        # Add parentheses only if engine doesn't already have them
        if "(" in engine:
            engine_clause = engine
        else:
            engine_clause = f"{engine}()"

        ddl = f"""
        CREATE TABLE {if_not_exists_clause}{table_name} (
            {columns_sql}
        )
        ENGINE = {engine_clause}
        ORDER BY ({order_by_clause})
        """.strip()

        self._client.execute(ddl)

    def _format_default(self, value: Any) -> str:
        """Format default value for SQL."""
        if isinstance(value, str):
            return f"'{value}'"
        elif isinstance(value, (int, float)):
            return str(value)
        elif value is None:
            return "NULL"
        else:
            return str(value)

    def table_exists(
        self,
        table_name: str,
        schema: Optional[str] = None
    ) -> bool:
        """
        Check if table exists in ClickHouse.

        Args:
            table_name: Name of table to check
            schema: Database name (if None, check both internal and data databases)

        Returns:
            True if table exists
        """
        if schema:
            databases = [schema]
        else:
            databases = [self._internal_database, self._data_database]

        for db in databases:
            query = """
            SELECT 1
            FROM system.tables
            WHERE database = %(database)s
              AND name = %(table)s
            """
            result = self.execute_query(
                query,
                {"database": db, "table": table_name}
            )
            if result:
                return True

        return False

    def insert_batch(
        self,
        table_name: str,
        data: Dict[str, np.ndarray],
        conflict_strategy: str = "ignore"
    ) -> int:
        """
        Insert batch of data into ClickHouse table.

        Args:
            table_name: Table to insert into
            data: Dictionary mapping column names to numpy arrays
            conflict_strategy: "ignore" or "replace" (ClickHouse doesn't support REPLACE)

        Returns:
            Number of rows inserted
        """
        if not data:
            return 0

        # Validate all arrays have same length
        lengths = [len(arr) for arr in data.values()]
        if len(set(lengths)) > 1:
            raise ValueError(
                f"All arrays must have same length, got: {dict(zip(data.keys(), lengths))}"
            )

        num_rows = lengths[0]
        if num_rows == 0:
            return 0

        # Convert numpy arrays to lists for ClickHouse driver
        column_names = list(data.keys())
        rows = []

        for i in range(num_rows):
            row = []
            for col_name in column_names:
                value = data[col_name][i]

                # Convert numpy types to Python types
                if isinstance(value, (np.datetime64, np.timedelta64)):
                    # Convert numpy datetime64 to Python datetime
                    value = self._convert_numpy_datetime(value)
                elif isinstance(value, np.ndarray):
                    value = value.tolist()
                elif isinstance(value, (np.integer, np.floating)):
                    value = value.item()
                elif value is None or (isinstance(value, float) and np.isnan(value)):
                    value = None

                row.append(value)
            rows.append(row)

        # For ClickHouse, conflict_strategy="ignore" is handled by PRIMARY KEY
        # Duplicates are silently ignored by MergeTree
        # Note: For ReplacingMergeTree, use conflict_strategy="replace"

        # Insert data
        self._client.execute(
            f"INSERT INTO {table_name} ({', '.join(column_names)}) VALUES",
            rows
        )

        return num_rows

    def _convert_numpy_datetime(self, dt: np.datetime64) -> datetime:
        """Convert numpy datetime64 to Python datetime with UTC timezone."""
        # Convert to timestamp
        timestamp = (dt - np.datetime64('1970-01-01T00:00:00')) / np.timedelta64(1, 's')
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)

    def get_last_timestamp(
        self,
        table_name: str,
        metric_name: str,
        timestamp_column: str = "timestamp"
    ) -> Optional[datetime]:
        """
        Get last timestamp for a metric in a table.

        Args:
            table_name: Table to query
            metric_name: Metric name to filter by
            timestamp_column: Name of timestamp column

        Returns:
            Last timestamp or None if no data
        """
        query = f"""
        SELECT max({timestamp_column}) as last_ts
        FROM {table_name}
        WHERE metric_name = %(metric_name)s
        """

        result = self.execute_query(query, {"metric_name": metric_name})

        if result and result[0]["last_ts"]:
            return result[0]["last_ts"]

        return None

    def upsert_task_status(
        self,
        metric_name: str,
        detector_id: str,
        process_type: str,
        status: str,
        last_processed_timestamp: Optional[datetime] = None,
        error_message: Optional[str] = None,
        timeout_seconds: int = 3600
    ) -> None:
        """
        Update or insert task status in ClickHouse.

        ClickHouse doesn't have native UPSERT, so we use DELETE + INSERT pattern.

        Args:
            metric_name: Metric identifier
            detector_id: Detector identifier
            process_type: Process type
            status: Task status
            last_processed_timestamp: Last processed timestamp
            error_message: Error message if failed
            timeout_seconds: Timeout in seconds
        """
        from detectkit.database.tables import TABLE_TASKS

        # Get current UTC time
        now = datetime.now(timezone.utc)

        # First, delete existing record (if any)
        delete_query = f"""
        ALTER TABLE {self.get_full_table_name(TABLE_TASKS, use_internal=True)}
        DELETE WHERE metric_name = %(metric_name)s
          AND detector_id = %(detector_id)s
          AND process_type = %(process_type)s
        """

        self._client.execute(
            delete_query,
            {
                "metric_name": metric_name,
                "detector_id": detector_id,
                "process_type": process_type,
            }
        )

        # Then insert new record
        insert_data = {
            "metric_name": np.array([metric_name]),
            "detector_id": np.array([detector_id]),
            "process_type": np.array([process_type]),
            "status": np.array([status]),
            "started_at": np.array([now], dtype="datetime64[ms]"),
            "updated_at": np.array([now], dtype="datetime64[ms]"),
            "last_processed_timestamp": np.array([last_processed_timestamp], dtype="datetime64[ms]") if last_processed_timestamp else np.array([None]),
            "error_message": np.array([error_message]),
            "timeout_seconds": np.array([timeout_seconds], dtype=np.int32),
        }

        self.insert_batch(
            self.get_full_table_name(TABLE_TASKS, use_internal=True),
            insert_data,
            conflict_strategy="ignore"
        )

    @property
    def internal_location(self) -> str:
        """Get internal database name."""
        return self._internal_database

    @property
    def data_location(self) -> str:
        """Get data database name."""
        return self._data_database

    def close(self) -> None:
        """Close ClickHouse connection."""
        if hasattr(self, "_client"):
            self._client.disconnect()
