"""MySQL database manager implementation.

Implements :class:`BaseDatabaseManager` for MySQL on top of the shared
:class:`SQLDatabaseManager`. MySQL has no schema-vs-database distinction, so the
internal/data *locations* are real **databases** (``CREATE DATABASE IF NOT
EXISTS``). Dedup for the ``ReplacingMergeTree`` tables is reproduced with an
enforced primary key plus a version-aware ``INSERT ... ON DUPLICATE KEY UPDATE``
(row-alias form, MySQL 8.0.19+).

**MariaDB is also supported** through this manager (there is no separate
class): the server vendor is detected once at connect time (``SELECT
VERSION()``), and if it reports MariaDB, upserts fall back to the classic
``VALUES()`` function form instead of the row-alias form, which MariaDB never
adopted.

MySQL cannot index ``TEXT`` columns in a primary key without a prefix length, so
``String`` columns that are part of the primary key are rendered as
``VARCHAR(255)`` while the rest stay ``TEXT``.
"""

from __future__ import annotations

from typing import Any

from detectkit.database._sql_manager import SQLDatabaseManager

try:
    import pymysql  # type: ignore[import-untyped]

    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False


class MySQLDatabaseManager(SQLDatabaseManager):
    """MySQL implementation of :class:`BaseDatabaseManager`.

    Args:
        host: MySQL host.
        port: MySQL port (default 3306).
        user: Database user.
        password: Database password.
        internal_database: Database for internal ``_dtk_*`` tables.
        data_database: Database for user data tables.
        database: Optional default database for the connection.
        settings: Extra ``pymysql.connect`` keyword arguments.
    """

    _TYPE_MAP = {
        "datetime": "DATETIME(3)",
        "float": "DOUBLE",
        "int": "INT",
        "bool": "TINYINT(1)",
        "string": "TEXT",
    }

    # MySQL quotes identifiers with backticks (``interval`` etc. are reserved).
    _IDENT_QUOTE = "`"

    # Set from `_connect()` via `_detect_mariadb()`. Declared at class level (not
    # only in `__init__`) so `_build_insert_sql` can read it safely even when a
    # test stubs out `_connect` entirely and never sets an instance value.
    _is_mariadb: bool = False

    def __init__(
        self,
        host: str = "localhost",
        port: int = 3306,
        user: str = "root",
        password: str = "",
        internal_database: str = "detectkit",
        data_database: str = "analytics",
        database: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        if not PYMYSQL_AVAILABLE:
            raise ImportError(
                "pymysql is not installed. Install with: pip install detectkit[mysql]"
            )
        super().__init__(
            host=host,
            port=port,
            user=user,
            password=password,
            internal_location=internal_database,
            data_location=data_database,
            database=database,
            settings=settings,
        )

    def _connect(self) -> Any:
        conn = pymysql.connect(
            host=self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            database=self._database,
            charset="utf8mb4",
            **self._settings,
        )
        self._is_mariadb = self._detect_mariadb(conn)
        return conn

    @staticmethod
    def _detect_mariadb(conn: Any) -> bool:
        """Return whether ``conn``'s server reports itself as MariaDB.

        Best-effort: any failure to query the version (a locked-down user, a
        transport hiccup) is treated as "not MariaDB" rather than raised, since
        the row-alias upsert form is the safe default for stock MySQL.
        """
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT VERSION()")
                row = cur.fetchone()
            return bool(row) and "mariadb" in str(row[0]).lower()
        except Exception:
            return False

    def _ensure_locations(self) -> None:
        for db in (self._internal_location, self._data_location):
            self.execute_query(f"CREATE DATABASE IF NOT EXISTS {db}")

    def _string_type(self, in_primary_key: bool) -> str:
        # TEXT cannot be part of a PRIMARY KEY without a prefix length.
        return "VARCHAR(255)" if in_primary_key else "TEXT"

    def _build_insert_sql(
        self,
        table_name: str,
        columns: list[str],
        primary_key: list[str],
        version_column: str | None,
        conflict_strategy: str,
    ) -> str:
        placeholders = ", ".join(["%s"] * len(columns))
        cols = ", ".join(self._q(c) for c in columns)
        plain = f"INSERT INTO {table_name} ({cols}) VALUES ({placeholders})"

        if conflict_strategy == "fail" or not primary_key:
            return plain

        non_pk = [c for c in columns if c not in primary_key]
        if conflict_strategy == "ignore" and (version_column is None or not non_pk):
            return f"INSERT IGNORE INTO {table_name} ({cols}) VALUES ({placeholders})"

        tbl = self._q(table_name.split(".")[-1])

        if self._is_mariadb:
            # MariaDB never adopted MySQL 8.0.19's row-alias upsert, so the
            # pending row is referenced with the classic VALUES() function
            # instead (deprecated on MySQL, but MariaDB has no replacement).
            if conflict_strategy == "replace":
                sets = ", ".join(f"{self._q(c)} = VALUES({self._q(c)})" for c in non_pk)
            else:  # versioned "ignore" -> last-writer-wins by version column
                ver = self._q(version_column) if version_column else None
                sets = ", ".join(
                    f"{self._q(c)} = IF(VALUES({ver}) >= {tbl}.{ver}, "
                    f"VALUES({self._q(c)}), {tbl}.{self._q(c)})"
                    for c in non_pk
                )
            return f"{plain} ON DUPLICATE KEY UPDATE {sets}"

        # Row-alias form (MySQL 8.0.19+) avoids the deprecated VALUES() function.
        # Existing-row references are qualified with the table name: with the
        # `AS new` alias in scope, an unqualified column in the UPDATE expression
        # is ambiguous ("Column '…' in field list is ambiguous").
        aliased = f"{plain} AS new"
        if conflict_strategy == "replace":
            sets = ", ".join(f"{self._q(c)} = new.{self._q(c)}" for c in non_pk)
        else:  # versioned "ignore" -> last-writer-wins by version column
            ver = self._q(version_column) if version_column else None
            sets = ", ".join(
                f"{self._q(c)} = IF(new.{ver} >= {tbl}.{ver}, new.{self._q(c)}, {tbl}.{self._q(c)})"
                for c in non_pk
            )
        return f"{aliased} ON DUPLICATE KEY UPDATE {sets}"
