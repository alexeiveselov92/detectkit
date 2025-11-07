"""Database managers for detectk."""

from detectkit.database.manager import BaseDatabaseManager
from detectkit.database.clickhouse_manager import ClickHouseDatabaseManager
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.database.tables import (
    TABLE_DATAPOINTS,
    TABLE_DETECTIONS,
    TABLE_TASKS,
    INTERNAL_TABLES,
    get_datapoints_table_model,
    get_detections_table_model,
    get_tasks_table_model,
)

__all__ = [
    "BaseDatabaseManager",
    "ClickHouseDatabaseManager",
    "InternalTablesManager",
    "TABLE_DATAPOINTS",
    "TABLE_DETECTIONS",
    "TABLE_TASKS",
    "INTERNAL_TABLES",
    "get_datapoints_table_model",
    "get_detections_table_model",
    "get_tasks_table_model",
]
