"""Snowflake **source-only** database manager.

Snowflake is supported as a hybrid-mode *source* (a metric's ``load`` SQL runs
against it) but **not** as a state backend: it implements only the minimal
:class:`~detectkit.database.source_manager.SourceDatabaseManager` contract
(connect + :meth:`execute_query` + :meth:`close`), with no DDL, upsert, lock or
internal-table machinery. :meth:`ProfileConfig.create_manager` refuses a
``snowflake`` profile as state and routes it here via
:meth:`ProfileConfig.create_source_manager`; the ``_dtk_*`` state lives in a
cheaper local backend (DuckDB/PostgreSQL/ClickHouse).

Three behaviors are deliberate and load-bearing:

- **Session TIMEZONE pinned to UTC.** Snowflake otherwise coerces
  ``TIMESTAMP_LTZ`` / ``CURRENT_TIMESTAMP`` through the session default
  (``America/Los_Angeles``); pinning ``TIMEZONE = UTC`` in ``session_parameters``
  keeps the loader's timestamps aligned (tz-aware UTC results are handled by the
  loader since v0.62.0). A user ``settings`` dict merges *over* this pin, so an
  explicit ``TIMEZONE`` choice wins.
- **Column-name folding.** Snowflake uppercases unquoted identifiers, so a
  result column named all-uppercase is folded to lowercase in the returned row
  dicts (the loader reads ``row["timestamp"]`` / ``row["value"]``);
  deliberately-quoted mixed-case names pass through unchanged. The rule is
  ``name.lower() if name.isupper() else name``.
- **Key-pair auth is first-class.** A PEM ``private_key_path`` (optionally
  passphrase-encrypted) is loaded to DER PKCS8 bytes and passed as
  ``private_key=``; recommended for service accounts as Snowflake retires
  single-factor passwords. A plain ``password`` is supported too.

Billing note: every query resumes the warehouse with a 60-second minimum bill,
so frequent small monitoring queries are expensive — the whole point of hybrid
mode is to load from Snowflake and keep cheap state elsewhere.
"""

from __future__ import annotations

from typing import Any

from detectkit.database.source_manager import SourceDatabaseManager


class SnowflakeSourceManager(SourceDatabaseManager):
    """Read-only Snowflake connection for hybrid-mode source profiles.

    Connects eagerly at construction (like every other backend manager). See
    the module docstring for the TIMEZONE pin, the column-name fold rule and
    the key-pair auth path.

    Args:
        account: Snowflake account identifier (e.g. ``"myorg-myaccount"``)
        user: Login name
        password: Password auth (used only when ``private_key_path`` is unset)
        private_key_path: Path to a PEM private key for key-pair auth
        private_key_passphrase: Passphrase of the private key, when encrypted
        warehouse: Virtual warehouse to run queries on (default warehouse when unset)
        database: Session default database (unset -> queries must qualify names)
        schema: Session default schema
        role: Session role (user's default role when unset)
        settings: Extra ``session_parameters`` merged over the UTC TIMEZONE pin
    """

    def __init__(
        self,
        account: str,
        user: str,
        password: str | None = None,
        private_key_path: str | None = None,
        private_key_passphrase: str | None = None,
        warehouse: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        role: str | None = None,
        settings: dict[str, Any] | None = None,
    ) -> None:
        try:
            import snowflake.connector
        except ImportError as exc:
            raise ImportError(
                "snowflake-connector-python is not installed. "
                "Install with: pip install detectkit[snowflake]"
            ) from exc

        self._account = account
        self._user = user
        self._password = password
        self._private_key_path = private_key_path
        self._private_key_passphrase = private_key_passphrase
        self._warehouse = warehouse
        self._database = database
        self._schema = schema
        self._role = role
        self._settings = settings or {}

        self._closed = False
        self._conn = snowflake.connector.connect(**self._connect_kwargs())

    def _connect_kwargs(self) -> dict[str, Any]:
        """Build ``snowflake.connector.connect(...)`` kwargs without connecting.

        The testable seam: it resolves auth (key-pair vs password), merges the
        UTC TIMEZONE pin with the user ``settings`` (settings wins on a key
        collision) and includes warehouse/database/schema/role only when set.
        """
        kwargs: dict[str, Any] = {
            "account": self._account,
            "user": self._user,
            "session_parameters": {"TIMEZONE": "UTC", **self._settings},
        }

        if self._private_key_path is not None:
            kwargs["private_key"] = self._load_private_key_der()
        else:
            kwargs["password"] = self._password

        if self._warehouse is not None:
            kwargs["warehouse"] = self._warehouse
        if self._database is not None:
            kwargs["database"] = self._database
        if self._schema is not None:
            kwargs["schema"] = self._schema
        if self._role is not None:
            kwargs["role"] = self._role

        return kwargs

    def _load_private_key_der(self) -> bytes:
        """Load the PEM private key at ``private_key_path`` to DER PKCS8 bytes.

        Uses ``cryptography`` (a snowflake-connector dependency), imported
        lazily so the module still imports without the extra installed.
        """
        from cryptography.hazmat.primitives import serialization

        assert self._private_key_path is not None
        passphrase = (
            self._private_key_passphrase.encode()
            if self._private_key_passphrase is not None
            else None
        )
        with open(self._private_key_path, "rb") as fh:
            private_key = serialization.load_pem_private_key(fh.read(), password=passphrase)
        return private_key.private_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

    @staticmethod
    def _fold_column(name: str) -> str:
        """Fold an all-uppercase Snowflake column name to lowercase.

        Snowflake uppercases unquoted identifiers; a deliberately-quoted
        mixed-case name is left unchanged.
        """
        return name.lower() if name.isupper() else name

    def execute_query(
        self, query: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a read query and return all rows as column-keyed dicts.

        Column names are folded per :meth:`_fold_column`. The cursor is always
        closed. The ``description is None`` branch is a defensive fallback
        only — Snowflake DDL/DML actually return a status/row-count result
        set — and this manager is only ever handed SELECTs by the loader.
        """
        cursor = self._conn.cursor()
        try:
            cursor.execute(query, params or None)
            if cursor.description is None:
                return []
            columns = [self._fold_column(col[0]) for col in cursor.description]
            return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        finally:
            cursor.close()

    def close(self) -> None:
        """Close the connection. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        self._conn.close()
