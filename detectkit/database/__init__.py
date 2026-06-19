"""Database managers for detectk."""

from detectkit.database._sql_manager import SQLDatabaseManager
from detectkit.database.clickhouse_manager import ClickHouseDatabaseManager
from detectkit.database.internal_tables import InternalTablesManager
from detectkit.database.manager import BaseDatabaseManager
from detectkit.database.mysql_manager import MySQLDatabaseManager
from detectkit.database.postgres_manager import PostgresDatabaseManager
from detectkit.database.tables import (
    INTERNAL_TABLES,
    TABLE_DATAPOINTS,
    TABLE_DETECTIONS,
    TABLE_TASKS,
    get_datapoints_table_model,
    get_detections_table_model,
    get_tasks_table_model,
)

__all__ = [
    "BaseDatabaseManager",
    "ClickHouseDatabaseManager",
    "SQLDatabaseManager",
    "PostgresDatabaseManager",
    "MySQLDatabaseManager",
    "InternalTablesManager",
    "TABLE_DATAPOINTS",
    "TABLE_DETECTIONS",
    "TABLE_TASKS",
    "INTERNAL_TABLES",
    "get_datapoints_table_model",
    "get_detections_table_model",
    "get_tasks_table_model",
]
