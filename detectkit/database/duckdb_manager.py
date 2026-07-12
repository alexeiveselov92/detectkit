"""DuckDB database manager implementation.

Implements :class:`BaseDatabaseManager` for `DuckDB <https://duckdb.org/>`_ on
top of the shared :class:`SQLDatabaseManager`. DuckDB is an **in-process,
single-file** analytical database — there is no server, no host/port/user/
password, and no notion of a client connecting over the network; the
"connection" is just a handle onto one on-disk (or in-memory) file. The
internal/data *locations* are DuckDB **schemas** inside that one file,
created with ``CREATE SCHEMA IF NOT EXISTS`` (``main`` always exists and is
never explicitly created).

**Operational model — read this before pointing a scheduled `dtk run` and a
long-lived `dtk ui` at the same file.** A DuckDB file is held read-write by
**one process at a time**: a second *process* attempting a read-write attach
fails. (Within the single writing process DuckDB itself allows further
connections — they share the cached database instance and may write
concurrently under MVCC with optimistic-conflict errors, and a same-process
``read_only=True`` attach fails on the config mismatch rather than the lock —
but every detectkit entry point runs in its own process, so the process rule
is the one that matters in practice.) Multiple *processes* may open the file
as **readers**, but only when every one of them opens with
``read_only=True`` — a reader process and the writer process cannot coexist.
Concretely:
`dtk ui` holds a long-lived connection for the lifetime of its localhost
server, so a `dtk run`/`dtk autotune`/`dtk clean` invoked against the *same*
DuckDB file while `dtk ui` is open will fail to connect (or vice versa, if
`dtk ui` is started second). The supported pattern is **run-then-look**: run
the pipeline to completion (closing its connection), *then* open `dtk ui` (or
any other reader) against the resulting file — not both at once. This is a
property of the storage engine, not a detectkit limitation.

DuckDB's Python API does not accept ``pyformat`` (``%(name)s``) placeholders
the way psycopg2/pymysql do — it takes ``$name`` for named parameters and
``?`` for positional ones, and it autocommits every statement instead of
requiring an explicit ``commit()``. Reusing :class:`SQLDatabaseManager`'s
DB-API-2.0-shaped flow (hand-written ``%(name)s`` queries throughout
``detectkit/database/internal_tables/``, ``cursor()`` as a context manager,
explicit ``commit()``/``rollback()`` bracketing multi-statement operations)
without forking it therefore requires a small **DB-API adapter** in front of
``duckdb.connect(...)`` — see :class:`_DuckDBConnectionAdapter` and
:class:`_DuckDBCursorAdapter` below. It is the one seam that makes the shared
base class (and every internal-tables query, written once against the
pyformat/cursor contract) work against DuckDB completely unmodified.

Dedup for the ``ReplacingMergeTree`` tables is reproduced the same way as
PostgreSQL: an enforced primary key plus a version-aware
``INSERT ... ON CONFLICT DO UPDATE ... WHERE <table>.<version> <= excluded.<version>``
(DuckDB's ``ON CONFLICT`` syntax mirrors PostgreSQL's — the "existing row"
qualifier in the ``WHERE`` clause is the bare table name, verified against a
real DuckDB engine, same as PostgreSQL; no dialect deviation was needed).
DuckDB's cursor does not report a reliable ``rowcount`` for ``DELETE``
(always ``-1``); a ``DELETE`` instead returns a one-row result set shaped
``(deleted_count,)``, so :meth:`DuckDBDatabaseManager.delete_rows` is
overridden to read that row instead of trusting ``cursor.rowcount``.
"""

from __future__ import annotations

import re
from typing import Any

from detectkit.database._sql_manager import SQLDatabaseManager

try:
    import duckdb

    DUCKDB_AVAILABLE = True
except ImportError:
    DUCKDB_AVAILABLE = False

# Rewrites hand-written `%(name)s` (pyformat) placeholders into DuckDB's
# `$name` named-parameter syntax. Used only on the `execute()` path — the
# insert path (`_build_insert_sql`) emits `?` (qmark) placeholders directly,
# so it never needs translation.
_PYFORMAT_PARAM_RE = re.compile(r"%\((\w+)\)s")


class _DuckDBCursorAdapter:
    """DB-API-2.0-shaped cursor over a shared :class:`_DuckDBConnectionAdapter`.

    DuckDB's ``DuckDBPyConnection`` already exposes ``execute``/``fetchall``/
    ``description`` directly (it plays the role of both connection and
    cursor), so this adapter does not open a separate native DuckDB cursor —
    it forwards every call onto the *same* underlying connection its parent
    :class:`_DuckDBConnectionAdapter` wraps, which is what lets an explicit
    transaction started by one statement stay open for a later statement
    issued through a different ``with conn.cursor() as cur:`` block (e.g. the
    DELETE-then-INSERT pair in ``upsert_record``).
    """

    def __init__(self, connection: _DuckDBConnectionAdapter) -> None:
        self._connection = connection
        self._rowcount = -1

    def __enter__(self) -> _DuckDBCursorAdapter:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        return None

    def execute(self, sql: str, params: dict[str, Any] | None = None) -> _DuckDBCursorAdapter:
        """Execute *sql*, translating any ``%(name)s`` placeholders to ``$name``."""
        self._connection._begin_if_needed()
        raw = self._connection.raw
        if params:
            translated = _PYFORMAT_PARAM_RE.sub(r"$\1", sql)
            raw.execute(translated, params)
        else:
            raw.execute(sql)
        self._rowcount = -1
        return self

    def executemany(self, sql: str, seq_of_tuples: list[tuple[Any, ...]]) -> _DuckDBCursorAdapter:
        """Execute *sql* once per row of ``?``-placeholder tuples.

        ``sql`` is expected to already use ``?`` (qmark) placeholders — the
        shape :meth:`DuckDBDatabaseManager._build_insert_sql` emits — so no
        placeholder translation happens here.
        """
        self._connection._begin_if_needed()
        rows = list(seq_of_tuples)
        self._connection.raw.executemany(sql, rows)
        self._rowcount = len(rows)
        return self

    @property
    def description(self) -> Any:
        return self._connection.raw.description

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._connection.raw.fetchall())

    @property
    def rowcount(self) -> int:
        return self._rowcount


class _DuckDBConnectionAdapter:
    """DB-API-2.0-shaped connection wrapping one ``duckdb.DuckDBPyConnection``.

    DuckDB autocommits every statement by default, but the shared
    :class:`SQLDatabaseManager` flow relies on ``commit()``/``rollback()``
    bracketing multi-statement operations (``upsert_record`` = DELETE +
    INSERT must be atomic). This adapter gives the connection **lazy
    explicit transactions**: the first statement issued after a
    ``commit()``/``rollback()`` (or on a fresh connection) opens a
    transaction; ``commit()``/``rollback()`` close it (a no-op when no
    transaction is open, mirroring a plain DB-API connection that was never
    written to).
    """

    def __init__(self, raw: Any) -> None:
        self.raw = raw
        self._in_transaction = False

    def _begin_if_needed(self) -> None:
        if not self._in_transaction:
            self.raw.begin()
            self._in_transaction = True

    def cursor(self) -> _DuckDBCursorAdapter:
        return _DuckDBCursorAdapter(self)

    def commit(self) -> None:
        if self._in_transaction:
            self.raw.commit()
            self._in_transaction = False

    def rollback(self) -> None:
        if self._in_transaction:
            self.raw.rollback()
            self._in_transaction = False

    def close(self) -> None:
        self.raw.close()


class DuckDBDatabaseManager(SQLDatabaseManager):
    """DuckDB implementation of :class:`BaseDatabaseManager`.

    DuckDB is an in-process, single-file analytical database: one
    ``DuckDBDatabaseManager`` instance owns one connection onto one file (or
    ``:memory:``), there is no server, and the file is held read-write by
    one **process** at a time. See the module docstring for the full
    operational model (one read-write process at a time; reader processes
    need ``read_only=True``; `dtk ui` and a concurrently spawned `dtk run`
    against the same file will conflict — run-then-look, not both at once).

    Args:
        path: Path to the DuckDB database file (created if it doesn't exist),
            or the literal string ``":memory:"`` for a transient in-process
            database. ``:memory:`` is **tests/preview-only** — its state is
            not persisted to disk and is lost when the process exits, which
            breaks detectkit's resume-from-last-timestamp idempotency across
            runs; use a real file path for anything but a one-off test.
        internal_schema: Schema for internal ``_dtk_*`` tables.
        data_schema: Schema for user data tables. Defaults to ``"main"``,
            DuckDB's always-present default schema.
        read_only: Open the file read-only. Required when another process
            already holds the file read-write (DuckDB allows many concurrent
            *readers*, never a reader alongside a writer). A read-only
            connection cannot create schemas/tables, so it assumes the
            internal/data schemas already exist.
        settings: Extra ``duckdb.connect`` ``config`` options (e.g.
            ``{"memory_limit": "512MB"}``).
        ensure_locations: When False, skip creating the internal/data
            schemas as a side effect of connecting (a strict read-only
            probe — see
            :class:`~detectkit.database._sql_manager.SQLDatabaseManager`)
            **and** force a read-only attach regardless of ``read_only``,
            for a real file path. Skipping schema creation alone is not
            enough for DuckDB: a plain read-write ``duckdb.connect`` against
            a *missing* file path creates that file as a side effect of
            connecting, before any DDL runs — forcing ``read_only=True``
            is what actually prevents that. ``":memory:"`` is exempted from
            the forced read-only attach (it has no file to create, and
            DuckDB rejects a read-only in-memory connection outright).

    Raises:
        ImportError: If the ``duckdb`` package is not installed.
        ValueError: If ``path`` is empty/falsy.
    """

    _TYPE_MAP = {
        "datetime": "TIMESTAMP",
        "float": "DOUBLE",
        "int": "BIGINT",
        "bool": "BOOLEAN",
        "string": "VARCHAR",
    }

    def __init__(
        self,
        path: str,
        internal_schema: str = "detectkit",
        data_schema: str = "main",
        read_only: bool = False,
        settings: dict[str, Any] | None = None,
        ensure_locations: bool = True,
    ) -> None:
        if not DUCKDB_AVAILABLE:
            raise ImportError(
                "duckdb is not installed. Install with: pip install detectkit[duckdb]"
            )
        if not path:
            raise ValueError(
                "DuckDBDatabaseManager requires a non-empty `path` (a database file "
                "path, or ':memory:' for a transient, tests/preview-only in-process "
                "database whose state is lost between runs)."
            )
        # `ensure_locations=False` is a strict read-only PROBE (see
        # `SQLDatabaseManager.__init__`): skipping `_ensure_locations()` is
        # not enough on its own for DuckDB, because a plain read-write
        # `duckdb.connect` against a MISSING file creates that file as a
        # side effect of connecting, before any DDL runs. Force a read-only
        # attach so the connect itself can never create the file/schemas.
        # ":memory:" is exempted — it has no file to create in the first
        # place, and DuckDB rejects a read-only in-memory connection outright
        # (`CatalogException: Cannot launch in-memory database in read-only
        # mode!`), so forcing it there would break rather than protect.
        self._read_only = True if (not ensure_locations and path != ":memory:") else read_only
        # Kept separately (and typed `str`, not `str | None`) from the base
        # class's `self._database` so `_connect()` doesn't need to narrow an
        # Optional it knows — by the ValueError check above — can't be None.
        self._path = path
        # host/port/user/password are meaningless for an in-process, file-backed
        # database and are deliberately not part of this constructor's signature;
        # the base class keeps its own defaults for them unused.
        super().__init__(
            internal_location=internal_schema,
            data_location=data_schema,
            database=path,
            settings=settings,
            ensure_locations=ensure_locations,
        )

    def _connect(self) -> Any:
        raw = duckdb.connect(self._path, read_only=self._read_only, config=self._settings or {})
        return _DuckDBConnectionAdapter(raw)

    def _ensure_locations(self) -> None:
        if self._read_only:
            # DDL is rejected on a read-only attachment; the schemas must
            # already exist, created by an earlier read-write connection.
            return
        for location in (self._internal_location, self._data_location):
            if location == "main":
                continue  # DuckDB's default schema always exists.
            self.execute_query(f"CREATE SCHEMA IF NOT EXISTS {location}")

    def _build_insert_sql(
        self,
        table_name: str,
        columns: list[str],
        primary_key: list[str],
        version_column: str | None,
        conflict_strategy: str,
    ) -> str:
        placeholders = ", ".join(["?"] * len(columns))
        col_list = ", ".join(self._q(c) for c in columns)
        base = f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders})"

        if conflict_strategy == "fail" or not primary_key:
            return base

        pk_target = f"ON CONFLICT ({', '.join(self._q(c) for c in primary_key)})"
        if conflict_strategy == "ignore" and version_column is None:
            return f"{base} {pk_target} DO NOTHING"

        non_pk = [c for c in columns if c not in primary_key]
        if not non_pk:
            return f"{base} {pk_target} DO NOTHING"

        set_clause = ", ".join(f"{self._q(c)} = excluded.{self._q(c)}" for c in non_pk)
        stmt = f"{base} {pk_target} DO UPDATE SET {set_clause}"
        # Versioned "ignore" == last-writer-wins: only overwrite when the
        # incoming row's version is newer-or-equal (mirrors ReplacingMergeTree).
        # Verified against a real DuckDB engine: like PostgreSQL, the existing
        # row in the DO UPDATE ... WHERE clause is referenced by the bare table
        # name (no special alias needed), so no dialect deviation from
        # postgres_manager.py's shape.
        if version_column is not None and conflict_strategy == "ignore":
            bare = table_name.split(".")[-1]
            ver = self._q(version_column)
            stmt += f" WHERE {bare}.{ver} <= excluded.{ver}"
        return stmt

    def delete_rows(
        self,
        table_name: str,
        where_clause: str,
        params: dict[str, Any] | None = None,
        sync: bool = False,
    ) -> int:
        """Delete rows with a plain ``DELETE FROM`` (``sync`` is a no-op here).

        Overridden because DuckDB's cursor never reports a usable
        ``rowcount`` for ``DELETE`` (always ``-1``); instead, a ``DELETE``
        returns a one-row result set shaped ``(deleted_count,)``, which this
        reads directly instead of trusting ``cursor.rowcount``.
        """
        try:
            with self._conn.cursor() as cur:
                cur.execute(
                    f"DELETE FROM {table_name} WHERE {where_clause}",
                    params if params else None,
                )
                rows = cur.fetchall()
            self._conn.commit()
            return int(rows[0][0]) if rows else 0
        except Exception:
            self._conn.rollback()
            raise
