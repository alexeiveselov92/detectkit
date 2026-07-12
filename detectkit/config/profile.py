"""
Profile configuration for detectk.

Manages database connections and locations (similar to dbt profiles).
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from detectkit.database.clickhouse_manager import ClickHouseDatabaseManager
from detectkit.database.manager import BaseDatabaseManager
from detectkit.utils.env_interpolation import interpolate_env_vars


class ProfileConfig(BaseModel):
    """
    Single profile configuration.

    Defines connection parameters and database locations for a specific
    environment (dev, prod, etc.).

    Attributes:
        type: Database type ("clickhouse", "postgres", "mysql", "mariadb", "duckdb")
        host: Database host (unused for DuckDB — it is an in-process, file-backed
            database with no network endpoint)
        port: Database port (unused for DuckDB; required for every other backend)
        user: Database user (unused for DuckDB)
        password: Database password (unused for DuckDB)
        database: Connection-target database (PostgreSQL/MySQL/MariaDB; unused
            for DuckDB — use `path` instead)
        path: Path to the DuckDB database file, or ":memory:" for a transient
            in-process database (DuckDB only)
        internal_database: Database/schema for internal tables
        internal_schema: Schema for internal tables (PostgreSQL/DuckDB only)
        data_database: Database for user data tables
        data_schema: Schema for user data (PostgreSQL/DuckDB only)
        settings: Additional database-specific settings
    """

    type: str = Field(..., description="Database type")
    host: str = Field(default="localhost", description="Database host (unused for DuckDB)")
    # No default: required for every backend except DuckDB (enforced below by
    # `_validate_port_required`, since DuckDB has no network port at all).
    port: int | None = Field(default=None, description="Database port (unused for DuckDB)")
    user: str = Field(default="default", description="Database user (unused for DuckDB)")
    password: str = Field(default="", description="Database password (unused for DuckDB)")

    # Connection-target database. Required for PostgreSQL (the database to
    # connect to, inside which internal_schema/data_schema live); optional for
    # MySQL/MariaDB; unused for ClickHouse and DuckDB.
    database: str | None = Field(
        default=None, description="Database to connect to (PostgreSQL/MySQL/MariaDB)"
    )

    # DuckDB-only: the database file path (or ":memory:"). host/port/user/
    # password/database above are simply ignored for this backend rather than
    # rejected, since e.g. `host` always carries its "localhost" default.
    path: str | None = Field(
        default=None,
        description="Database file path, or ':memory:' for a transient in-process database (DuckDB only)",
    )
    read_only: bool = Field(
        default=False,
        description=(
            "Open the database read-only (DuckDB only) — lets a reader profile "
            "coexist with the one process holding the file read-write"
        ),
    )

    # Internal location for _dtk_* tables
    internal_database: str | None = Field(
        default=None, description="Database for internal tables (ClickHouse/MySQL/MariaDB)"
    )
    internal_schema: str | None = Field(
        default=None, description="Schema for internal tables (PostgreSQL/DuckDB)"
    )

    # Data location for user tables
    data_database: str | None = Field(
        default=None, description="Database for user data tables (ClickHouse/MySQL/MariaDB)"
    )
    data_schema: str | None = Field(
        default=None, description="Schema for user data (PostgreSQL/DuckDB)"
    )

    settings: dict[str, Any] = Field(
        default_factory=dict, description="Additional database settings"
    )

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate database type."""
        allowed_types = {"clickhouse", "postgres", "mysql", "mariadb", "duckdb"}
        if v not in allowed_types:
            raise ValueError(
                f"Invalid database type: {v}. " f"Allowed types: {', '.join(allowed_types)}"
            )
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int | None) -> int | None:
        """Validate port number (when set — DuckDB profiles may omit it)."""
        if v is None:
            return v
        if not (1 <= v <= 65535):
            raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v

    @model_validator(mode="after")
    def _validate_port_required(self) -> "ProfileConfig":
        """Every backend but DuckDB needs a port; DuckDB has no network endpoint."""
        if self.type != "duckdb" and self.port is None:
            raise ValueError(f"port is required for database type '{self.type}'")
        return self

    def get_internal_location(self) -> str:
        """
        Get internal location (database or schema).

        Returns:
            Internal database/schema name

        Raises:
            ValueError: If location not configured
        """
        if self.type == "clickhouse":
            if not self.internal_database:
                raise ValueError("internal_database must be set for ClickHouse")
            return self.internal_database
        elif self.type == "postgres":
            if not self.internal_schema:
                raise ValueError("internal_schema must be set for PostgreSQL")
            return self.internal_schema
        elif self.type in ("mysql", "mariadb"):
            if not self.internal_database:
                raise ValueError("internal_database must be set for MySQL/MariaDB")
            return self.internal_database
        elif self.type == "duckdb":
            # Mirrors DuckDBDatabaseManager's own default (unlike PostgreSQL,
            # an unset internal_schema doesn't need to be an error here).
            return self.internal_schema or "detectkit"
        else:
            raise ValueError(f"Unsupported database type: {self.type}")

    def get_data_location(self) -> str:
        """
        Get data location (database or schema).

        Returns:
            Data database/schema name

        Raises:
            ValueError: If location not configured
        """
        if self.type == "clickhouse":
            if not self.data_database:
                raise ValueError("data_database must be set for ClickHouse")
            return self.data_database
        elif self.type == "postgres":
            if not self.data_schema:
                raise ValueError("data_schema must be set for PostgreSQL")
            return self.data_schema
        elif self.type in ("mysql", "mariadb"):
            if not self.data_database:
                raise ValueError("data_database must be set for MySQL/MariaDB")
            return self.data_database
        elif self.type == "duckdb":
            # Mirrors DuckDBDatabaseManager's own default data_schema ("main",
            # DuckDB's always-present default schema).
            return self.data_schema or "main"
        else:
            raise ValueError(f"Unsupported database type: {self.type}")

    def create_manager(self, ensure_locations: bool = True) -> BaseDatabaseManager:
        """
        Create database manager from profile configuration.

        Args:
            ensure_locations: When False, skip creating the internal/data
                database(s)/schema(s) as a side effect of connecting — a
                strict read-only probe. For DuckDB this additionally forces
                a read-only attach (see :class:`DuckDBDatabaseManager`), so
                the connect itself can never create a missing state file.
                Used by the read-only MCP server, which must never run DDL
                at startup.

        Returns:
            Database manager instance

        Raises:
            ValueError: If the database type is unsupported, or required
                connection fields (e.g. PostgreSQL ``database``, DuckDB
                ``path``) are missing
            ImportError: If the backend's driver is not installed
        """
        if self.type == "clickhouse":
            # `port` is guaranteed non-None here by `_validate_port_required`
            # (every type but "duckdb" requires it at construction time).
            assert self.port is not None
            return ClickHouseDatabaseManager(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                internal_database=self.get_internal_location(),
                data_database=self.get_data_location(),
                settings=self.settings,
                ensure_locations=ensure_locations,
            )
        elif self.type == "postgres":
            from detectkit.database.postgres_manager import PostgresDatabaseManager

            if not self.database:
                raise ValueError(
                    "PostgreSQL profiles must set 'database' (the database to "
                    "connect to, inside which internal_schema/data_schema live)"
                )
            assert self.port is not None
            return PostgresDatabaseManager(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                internal_schema=self.get_internal_location(),
                data_schema=self.get_data_location(),
                settings=self.settings,
                ensure_locations=ensure_locations,
            )
        elif self.type in ("mysql", "mariadb"):
            # MariaDB is served by the same manager; it detects the vendor at
            # connect time and adjusts the upsert SQL it generates accordingly.
            from detectkit.database.mysql_manager import MySQLDatabaseManager

            assert self.port is not None
            return MySQLDatabaseManager(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                database=self.database,
                internal_database=self.get_internal_location(),
                data_database=self.get_data_location(),
                settings=self.settings,
                ensure_locations=ensure_locations,
            )
        elif self.type == "duckdb":
            # In-process, file-backed database: host/port/user/password/database
            # are meaningless for it and are simply not read here (rather than
            # rejected — `host`/`user`/`password` always carry non-empty
            # defaults, so rejecting them would punish every duckdb profile).
            from detectkit.database.duckdb_manager import DuckDBDatabaseManager

            if not self.path:
                raise ValueError(
                    "DuckDB profiles must set 'path' (the database file path, "
                    "or ':memory:' for a transient, tests/preview-only "
                    "in-process database)"
                )
            return DuckDBDatabaseManager(
                path=self.path,
                internal_schema=self.get_internal_location(),
                data_schema=self.get_data_location(),
                read_only=self.read_only,
                settings=self.settings,
                ensure_locations=ensure_locations,
            )
        else:
            raise ValueError(f"Unsupported database type: {self.type}")


class ProfilesConfig(BaseModel):
    """
    Container for multiple profile configurations.

    Loaded from profiles.yml file.

    Attributes:
        profiles: Dictionary mapping profile names to configurations
        default_profile: Name of default profile to use
        alert_channels: Dictionary mapping channel names to configurations
    """

    profiles: dict[str, ProfileConfig]
    default_profile: str | None = None
    alert_channels: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="Alert channel configurations"
    )

    @field_validator("default_profile")
    @classmethod
    def validate_default_profile(cls, v: str | None, info) -> str | None:
        """Validate default profile exists."""
        if v is not None:
            profiles = info.data.get("profiles", {})
            if v not in profiles:
                raise ValueError(
                    f"default_profile '{v}' not found in profiles. "
                    f"Available profiles: {', '.join(profiles.keys())}"
                )
        return v

    @classmethod
    def from_yaml(cls, path: Path) -> "ProfilesConfig":
        """
        Load profiles from YAML file.

        Args:
            path: Path to profiles.yml

        Returns:
            ProfilesConfig instance

        Raises:
            FileNotFoundError: If file doesn't exist
            ValueError: If YAML is invalid
        """
        if not path.exists():
            raise FileNotFoundError(f"Profiles file not found: {path}")

        with open(path) as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError("Profiles file is empty")

        # Resolve ${VAR} / {{ env_var('VAR') }} placeholders before validation
        # so that secrets (DB passwords, webhook URLs) are not stored in YAML.
        data = interpolate_env_vars(data)

        return cls.model_validate(data)

    def get_profile(self, name: str | None = None) -> ProfileConfig:
        """
        Get profile configuration by name.

        Args:
            name: Profile name (if None, use default_profile)

        Returns:
            ProfileConfig instance

        Raises:
            ValueError: If profile not found or no default set
        """
        if name is None:
            if self.default_profile is None:
                raise ValueError(
                    "No profile name specified and no default_profile set. "
                    f"Available profiles: {', '.join(self.profiles.keys())}"
                )
            name = self.default_profile

        if name not in self.profiles:
            raise ValueError(
                f"Profile '{name}' not found. "
                f"Available profiles: {', '.join(self.profiles.keys())}"
            )

        return self.profiles[name]

    def create_manager(
        self, profile_name: str | None = None, ensure_locations: bool = True
    ) -> BaseDatabaseManager:
        """
        Create database manager for a profile.

        Args:
            profile_name: Profile name (if None, use default)
            ensure_locations: Passed through to
                :meth:`ProfileConfig.create_manager` — False for a strict
                read-only probe that never runs DDL as a side effect of
                connecting.

        Returns:
            Database manager instance
        """
        profile = self.get_profile(profile_name)
        return profile.create_manager(ensure_locations=ensure_locations)

    def get_alert_channel_config(self, channel_name: str) -> dict[str, Any]:
        """
        Get alert channel configuration by name.

        Args:
            channel_name: Channel name

        Returns:
            Channel configuration dictionary

        Raises:
            ValueError: If channel not found
        """
        if channel_name not in self.alert_channels:
            available = ", ".join(sorted(self.alert_channels.keys()))
            raise ValueError(
                f"Alert channel '{channel_name}' not found. " f"Available channels: {available}"
            )

        return self.alert_channels[channel_name]
