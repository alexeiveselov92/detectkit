"""
Source-only database manager interface.

Hybrid mode (``source_profile``) runs a metric's **load** SQL against a
different profile's database while all ``_dtk_*`` state stays in the state
profile. The load path needs exactly two things from that source database:
executing a read query and closing the connection at run end. This module
defines that minimal contract, so a backend can be supported as a *source*
(a read-only query endpoint) without implementing any of the state machinery
(DDL, upserts, locks, internal-table locations).

Two kinds of managers satisfy it:

- Every full backend: :class:`~detectkit.database.manager.BaseDatabaseManager`
  subclasses this interface, so ClickHouse/PostgreSQL/MySQL/MariaDB/DuckDB
  profiles keep working as sources unchanged.
- Source-only backends (e.g. Snowflake), which implement *only* this
  interface and are refused as a state profile by
  :meth:`ProfileConfig.create_manager`.
"""

from abc import ABC, abstractmethod
from typing import Any


class SourceDatabaseManager(ABC):
    """
    Minimal read-only database interface for hybrid-mode source profiles.

    The load step is the only pipeline stage that touches a source database;
    it calls :meth:`execute_query` with the metric's rendered SQL and the
    run-level pool calls :meth:`close` once at run end. Implementations must
    not create databases/schemas/tables as a side effect of connecting — a
    source is someone else's warehouse.
    """

    @abstractmethod
    def execute_query(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """
        Execute a read query and return all rows.

        Args:
            query: SQL query text (already fully rendered — the loader
                interpolates Jinja variables before calling this)
            params: Optional query parameters (driver-native named style)

        Returns:
            List of row dicts keyed by the result-set column names
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """Close the database connection."""
        pass

    def __enter__(self) -> "SourceDatabaseManager":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Context manager exit - close connection."""
        self.close()
