"""
Profile configuration for detectk.

Manages database connections and locations (similar to dbt profiles).
"""

from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field, field_validator

from detectkit.database.clickhouse_manager import ClickHouseDatabaseManager
from detectkit.database.manager import BaseDatabaseManager


class ProfileConfig(BaseModel):
    """
    Single profile configuration.

    Defines connection parameters and database locations for a specific
    environment (dev, prod, etc.).

    Attributes:
        type: Database type ("clickhouse", "postgres", "mysql")
        host: Database host
        port: Database port
        user: Database user
        password: Database password
        internal_database: Database/schema for internal tables
        internal_schema: Schema for internal tables (PostgreSQL only)
        data_database: Database for user data tables
        data_schema: Schema for user data (PostgreSQL only)
        settings: Additional database-specific settings
    """

    type: str = Field(..., description="Database type")
    host: str = Field(default="localhost", description="Database host")
    port: int = Field(..., description="Database port")
    user: str = Field(default="default", description="Database user")
    password: str = Field(default="", description="Database password")

    # Internal location for _dtk_* tables
    internal_database: Optional[str] = Field(
        default=None,
        description="Database for internal tables (ClickHouse/MySQL)"
    )
    internal_schema: Optional[str] = Field(
        default=None,
        description="Schema for internal tables (PostgreSQL)"
    )

    # Data location for user tables
    data_database: Optional[str] = Field(
        default=None,
        description="Database for user data tables (ClickHouse/MySQL)"
    )
    data_schema: Optional[str] = Field(
        default=None,
        description="Schema for user data (PostgreSQL)"
    )

    settings: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional database settings"
    )

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        """Validate database type."""
        allowed_types = {"clickhouse", "postgres", "mysql"}
        if v not in allowed_types:
            raise ValueError(
                f"Invalid database type: {v}. "
                f"Allowed types: {', '.join(allowed_types)}"
            )
        return v

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate port number."""
        if not (1 <= v <= 65535):
            raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v

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
        elif self.type == "mysql":
            if not self.internal_database:
                raise ValueError("internal_database must be set for MySQL")
            return self.internal_database
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
        elif self.type == "mysql":
            if not self.data_database:
                raise ValueError("data_database must be set for MySQL")
            return self.data_database
        else:
            raise ValueError(f"Unsupported database type: {self.type}")

    def create_manager(self) -> BaseDatabaseManager:
        """
        Create database manager from profile configuration.

        Returns:
            Database manager instance

        Raises:
            NotImplementedError: If database type not yet implemented
        """
        if self.type == "clickhouse":
            return ClickHouseDatabaseManager(
                host=self.host,
                port=self.port,
                user=self.user,
                password=self.password,
                internal_database=self.get_internal_location(),
                data_database=self.get_data_location(),
                settings=self.settings,
            )
        elif self.type == "postgres":
            raise NotImplementedError("PostgreSQL support coming soon")
        elif self.type == "mysql":
            raise NotImplementedError("MySQL support coming soon")
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

    profiles: Dict[str, ProfileConfig]
    default_profile: Optional[str] = None
    alert_channels: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict, description="Alert channel configurations"
    )

    @field_validator("default_profile")
    @classmethod
    def validate_default_profile(cls, v: Optional[str], info) -> Optional[str]:
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

        with open(path, "r") as f:
            data = yaml.safe_load(f)

        if not data:
            raise ValueError("Profiles file is empty")

        return cls.model_validate(data)

    def get_profile(self, name: Optional[str] = None) -> ProfileConfig:
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

    def create_manager(self, profile_name: Optional[str] = None) -> BaseDatabaseManager:
        """
        Create database manager for a profile.

        Args:
            profile_name: Profile name (if None, use default)

        Returns:
            Database manager instance
        """
        profile = self.get_profile(profile_name)
        return profile.create_manager()

    def get_alert_channel_config(self, channel_name: str) -> Dict[str, Any]:
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
                f"Alert channel '{channel_name}' not found. "
                f"Available channels: {available}"
            )

        return self.alert_channels[channel_name]
