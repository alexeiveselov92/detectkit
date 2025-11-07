"""
Base database manager interface.

Provides universal methods for database operations WITHOUT hardcoding
specific table logic (e.g., _dtk_datapoints, _dtk_detections).

The manager is database-agnostic and provides generic operations:
- execute_query(): Run SQL and return results
- create_table(): Create table from TableModel
- table_exists(): Check if table exists
- insert_batch(): Insert batch of data
- get_last_timestamp(): Get last timestamp for a metric
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np

from detectkit.core.models import TableModel


class BaseDatabaseManager(ABC):
    """
    Universal database manager interface.

    This class provides GENERIC methods for database operations.
    It does NOT hardcode logic for internal tables (_dtk_datapoints, etc.).

    Internal table management is handled by higher-level classes that
    use these generic methods.

    Key Design Principles:
    1. Universal methods (not table-specific)
    2. Works with any table via table_name parameter
    3. Type conversion handled internally
    4. Connection pooling and error handling
    """

    @abstractmethod
    def execute_query(
        self,
        query: str,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute SQL query and return results as list of dictionaries.

        Args:
            query: SQL query to execute
            params: Optional query parameters for parameterized queries

        Returns:
            List of dictionaries where each dict represents a row

        Raises:
            DatabaseError: If query execution fails

        Example:
            >>> results = manager.execute_query(
            ...     "SELECT * FROM metrics WHERE name = %(name)s",
            ...     {"name": "cpu_usage"}
            ... )
            >>> for row in results:
            ...     print(row['timestamp'], row['value'])
        """
        pass

    @abstractmethod
    def create_table(
        self,
        table_name: str,
        table_model: TableModel,
        if_not_exists: bool = True
    ) -> None:
        """
        Create table from TableModel definition.

        Converts database-agnostic TableModel into database-specific DDL.

        Args:
            table_name: Name of table to create
            table_model: Table schema definition
            if_not_exists: Add IF NOT EXISTS clause

        Raises:
            DatabaseError: If table creation fails

        Example:
            >>> model = TableModel(
            ...     columns=[
            ...         ColumnDefinition("id", "Int32"),
            ...         ColumnDefinition("value", "Float64", nullable=True),
            ...     ],
            ...     primary_key=["id"],
            ...     engine="MergeTree",
            ...     order_by=["id"]
            ... )
            >>> manager.create_table("my_metrics", model)
        """
        pass

    @abstractmethod
    def table_exists(
        self,
        table_name: str,
        schema: Optional[str] = None
    ) -> bool:
        """
        Check if table exists in database.

        Args:
            table_name: Name of table to check
            schema: Optional schema/database name (if None, use default)

        Returns:
            True if table exists, False otherwise

        Example:
            >>> if not manager.table_exists("_dtk_datapoints"):
            ...     manager.create_table("_dtk_datapoints", datapoints_model)
        """
        pass

    @abstractmethod
    def insert_batch(
        self,
        table_name: str,
        data: Dict[str, np.ndarray],
        conflict_strategy: str = "ignore"
    ) -> int:
        """
        Insert batch of data into table.

        Universal method that works with any table - NOT specific to
        internal tables.

        Args:
            table_name: Name of table to insert into
            data: Dictionary mapping column names to numpy arrays
                 All arrays must have same length
            conflict_strategy: How to handle conflicts:
                - "ignore": Skip rows with duplicate primary keys
                - "replace": Replace existing rows
                - "fail": Raise error on conflict

        Returns:
            Number of rows inserted (may be less than input if conflicts ignored)

        Raises:
            ValueError: If arrays have different lengths
            DatabaseError: If insertion fails

        Example:
            >>> data = {
            ...     "metric_name": np.array(["cpu", "cpu"]),
            ...     "timestamp": np.array([dt1, dt2]),
            ...     "value": np.array([0.5, 0.6]),
            ... }
            >>> rows_inserted = manager.insert_batch(
            ...     "_dtk_datapoints", data, conflict_strategy="ignore"
            ... )
        """
        pass

    @abstractmethod
    def get_last_timestamp(
        self,
        table_name: str,
        metric_name: str,
        timestamp_column: str = "timestamp"
    ) -> Optional[datetime]:
        """
        Get last timestamp for a specific metric in a table.

        Universal method that works with any table containing metric_name
        and timestamp columns.

        Args:
            table_name: Table to query
            metric_name: Value to filter by metric_name column
            timestamp_column: Name of timestamp column (default: "timestamp")

        Returns:
            Last timestamp or None if no data found

        Example:
            >>> last_ts = manager.get_last_timestamp(
            ...     "_dtk_datapoints", "cpu_usage"
            ... )
            >>> if last_ts:
            ...     print(f"Last data point at {last_ts}")
        """
        pass

    @abstractmethod
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
        Update or insert task status (for locking and idempotency).

        This method is critical for:
        1. Task locking: Prevent concurrent runs of same task
        2. Idempotency: Store last_processed_timestamp to resume from interruptions

        Implementation varies by database:
        - ClickHouse: DELETE + INSERT (no native UPSERT)
        - PostgreSQL: INSERT ... ON CONFLICT DO UPDATE
        - MySQL: INSERT ... ON DUPLICATE KEY UPDATE

        Args:
            metric_name: Metric identifier
            detector_id: Detector identifier (or "load" for loading tasks)
            process_type: Type of process ("load" or "detect")
            status: Task status ("running", "completed", "failed")
            last_processed_timestamp: Last successfully processed timestamp
            error_message: Error message if status is "failed"
            timeout_seconds: Task timeout in seconds

        Example:
            >>> # Start task
            >>> manager.upsert_task_status(
            ...     "cpu_usage", "load", "load", "running",
            ...     timeout_seconds=3600
            ... )
            >>> # Update progress
            >>> manager.upsert_task_status(
            ...     "cpu_usage", "load", "load", "running",
            ...     last_processed_timestamp=datetime(2024, 1, 1, 12, 0)
            ... )
            >>> # Complete task
            >>> manager.upsert_task_status(
            ...     "cpu_usage", "load", "load", "completed",
            ...     last_processed_timestamp=datetime(2024, 1, 1, 23, 59)
            ... )
        """
        pass

    @property
    @abstractmethod
    def internal_location(self) -> str:
        """
        Get full location path for internal tables.

        Format depends on database:
        - ClickHouse: "database_name"
        - PostgreSQL: "schema_name"

        Returns:
            Full path to internal schema/database

        Example:
            >>> manager.internal_location
            'detectk_internal'
        """
        pass

    @property
    @abstractmethod
    def data_location(self) -> str:
        """
        Get full location path for user data tables.

        Format depends on database:
        - ClickHouse: "database_name"
        - PostgreSQL: "schema_name"

        Returns:
            Full path to data schema/database

        Example:
            >>> manager.data_location
            'analytics'
        """
        pass

    def get_full_table_name(
        self,
        table_name: str,
        use_internal: bool = True
    ) -> str:
        """
        Get fully qualified table name.

        Args:
            table_name: Table name
            use_internal: If True, use internal_location, else data_location

        Returns:
            Fully qualified table name

        Example:
            >>> manager.get_full_table_name("_dtk_datapoints", use_internal=True)
            'detectk_internal._dtk_datapoints'
        """
        location = self.internal_location if use_internal else self.data_location
        return f"{location}.{table_name}"

    @abstractmethod
    def close(self) -> None:
        """
        Close database connection and cleanup resources.

        Example:
            >>> manager.close()
        """
        pass

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close connection."""
        self.close()
