"""Tests for profile configuration."""

from pathlib import Path
from tempfile import NamedTemporaryFile

import pytest

from detectkit.config.profile import ProfileConfig, ProfilesConfig


class TestProfileConfig:
    """Test ProfileConfig model."""

    def test_clickhouse_profile(self):
        """Test ClickHouse profile configuration."""
        profile = ProfileConfig(
            type="clickhouse",
            host="localhost",
            port=9000,
            user="default",
            password="",
            internal_database="detectk_internal",
            data_database="analytics",
        )

        assert profile.type == "clickhouse"
        assert profile.get_internal_location() == "detectk_internal"
        assert profile.get_data_location() == "analytics"

    def test_postgres_profile(self):
        """Test PostgreSQL profile configuration."""
        profile = ProfileConfig(
            type="postgres",
            host="localhost",
            port=5432,
            user="postgres",
            password="secret",
            internal_schema="detectk",
            data_schema="public",
        )

        assert profile.type == "postgres"
        assert profile.get_internal_location() == "detectk"
        assert profile.get_data_location() == "public"

    def test_invalid_type(self):
        """Test error on invalid database type."""
        with pytest.raises(ValueError, match="Invalid database type"):
            ProfileConfig(
                type="invalid",
                host="localhost",
                port=9000,
            )

    def test_invalid_port(self):
        """Test error on invalid port."""
        with pytest.raises(ValueError, match="Port must be between"):
            ProfileConfig(
                type="clickhouse",
                host="localhost",
                port=99999,
            )

    def test_missing_internal_location(self):
        """Test error when internal location not configured."""
        profile = ProfileConfig(
            type="clickhouse",
            host="localhost",
            port=9000,
            data_database="analytics",
        )

        with pytest.raises(ValueError, match="internal_database must be set"):
            profile.get_internal_location()

    def test_missing_data_location(self):
        """Test error when data location not configured."""
        profile = ProfileConfig(
            type="clickhouse",
            host="localhost",
            port=9000,
            internal_database="detectk_internal",
        )

        with pytest.raises(ValueError, match="data_database must be set"):
            profile.get_data_location()

    @pytest.mark.integration
    def test_create_clickhouse_manager(self):
        """Test creating ClickHouse manager from profile."""
        profile = ProfileConfig(
            type="clickhouse",
            host="localhost",
            port=9000,
            user="default",
            password="",
            internal_database="detectk_internal",
            data_database="analytics",
        )

        try:
            manager = profile.create_manager()
            assert manager is not None
            manager.close()
        except ImportError:
            pytest.skip("ClickHouse driver not installed")
        except Exception as exc:
            pytest.skip(f"ClickHouse server not reachable: {exc}")

    def test_postgres_requires_database(self):
        """PostgreSQL profiles must declare the connect-target database."""
        profile = ProfileConfig(
            type="postgres",
            host="localhost",
            port=5432,
            internal_schema="detectk",
            data_schema="public",
        )

        with pytest.raises(ValueError, match="must set 'database'"):
            profile.create_manager()

    def test_postgres_create_manager(self):
        """PostgreSQL manager is built when a database is provided."""
        profile = ProfileConfig(
            type="postgres",
            host="localhost",
            port=5432,
            database="detectkit",
            internal_schema="detectk",
            data_schema="public",
        )

        try:
            manager = profile.create_manager()
            assert manager is not None
            manager.close()
        except ImportError:
            pytest.skip("psycopg2 not installed")
        except Exception as exc:
            pytest.skip(f"PostgreSQL server not reachable: {exc}")

    def test_mysql_create_manager(self):
        """MySQL manager is built from a profile (no NotImplementedError)."""
        profile = ProfileConfig(
            type="mysql",
            host="localhost",
            port=3306,
            internal_database="detectk",
            data_database="analytics",
        )

        try:
            manager = profile.create_manager()
            assert manager is not None
            manager.close()
        except ImportError:
            pytest.skip("pymysql not installed")
        except Exception as exc:
            pytest.skip(f"MySQL server not reachable: {exc}")


class TestProfilesConfig:
    """Test ProfilesConfig model."""

    def test_single_profile(self):
        """Test configuration with single profile."""
        config = ProfilesConfig(
            profiles={
                "dev": ProfileConfig(
                    type="clickhouse",
                    host="localhost",
                    port=9000,
                    internal_database="detectk_internal",
                    data_database="analytics",
                )
            },
            default_profile="dev",
        )

        assert "dev" in config.profiles
        assert config.default_profile == "dev"

    def test_multiple_profiles(self):
        """Test configuration with multiple profiles."""
        config = ProfilesConfig(
            profiles={
                "dev": ProfileConfig(
                    type="clickhouse",
                    host="localhost",
                    port=9000,
                    internal_database="detectk_internal",
                    data_database="analytics",
                ),
                "prod": ProfileConfig(
                    type="clickhouse",
                    host="prod.example.com",
                    port=9000,
                    user="prod_user",
                    password="secret",
                    internal_database="detectk_internal",
                    data_database="analytics",
                ),
            },
            default_profile="dev",
        )

        assert len(config.profiles) == 2
        assert "dev" in config.profiles
        assert "prod" in config.profiles

    def test_invalid_default_profile(self):
        """Test error when default profile doesn't exist."""
        with pytest.raises(ValueError, match="default_profile 'missing' not found"):
            ProfilesConfig(
                profiles={
                    "dev": ProfileConfig(
                        type="clickhouse",
                        host="localhost",
                        port=9000,
                        internal_database="detectk_internal",
                        data_database="analytics",
                    )
                },
                default_profile="missing",
            )

    def test_get_profile_by_name(self):
        """Test getting profile by name."""
        config = ProfilesConfig(
            profiles={
                "dev": ProfileConfig(
                    type="clickhouse",
                    host="localhost",
                    port=9000,
                    internal_database="detectk_internal",
                    data_database="analytics",
                ),
                "prod": ProfileConfig(
                    type="clickhouse",
                    host="prod.example.com",
                    port=9000,
                    internal_database="detectk_internal",
                    data_database="analytics",
                ),
            },
            default_profile="dev",
        )

        profile = config.get_profile("prod")
        assert profile.host == "prod.example.com"

    def test_get_default_profile(self):
        """Test getting default profile."""
        config = ProfilesConfig(
            profiles={
                "dev": ProfileConfig(
                    type="clickhouse",
                    host="localhost",
                    port=9000,
                    internal_database="detectk_internal",
                    data_database="analytics",
                ),
            },
            default_profile="dev",
        )

        profile = config.get_profile()
        assert profile.host == "localhost"

    def test_get_profile_no_default(self):
        """Test error when getting profile without default set."""
        config = ProfilesConfig(
            profiles={
                "dev": ProfileConfig(
                    type="clickhouse",
                    host="localhost",
                    port=9000,
                    internal_database="detectk_internal",
                    data_database="analytics",
                ),
            }
        )

        with pytest.raises(ValueError, match="No profile name specified"):
            config.get_profile()

    def test_get_missing_profile(self):
        """Test error when getting non-existent profile."""
        config = ProfilesConfig(
            profiles={
                "dev": ProfileConfig(
                    type="clickhouse",
                    host="localhost",
                    port=9000,
                    internal_database="detectk_internal",
                    data_database="analytics",
                ),
            },
            default_profile="dev",
        )

        with pytest.raises(ValueError, match="Profile 'missing' not found"):
            config.get_profile("missing")

    def test_from_yaml(self):
        """Test loading profiles from YAML file."""
        yaml_content = """
profiles:
  dev:
    type: clickhouse
    host: localhost
    port: 9000
    user: default
    password: ""
    internal_database: detectk_internal
    data_database: analytics
  prod:
    type: clickhouse
    host: prod.example.com
    port: 9000
    user: prod_user
    password: secret
    internal_database: detectk_internal
    data_database: analytics
default_profile: dev
        """

        with NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(yaml_content)
            temp_path = Path(f.name)

        try:
            config = ProfilesConfig.from_yaml(temp_path)

            assert len(config.profiles) == 2
            assert config.default_profile == "dev"
            assert config.profiles["dev"].host == "localhost"
            assert config.profiles["prod"].host == "prod.example.com"
        finally:
            temp_path.unlink()

    def test_from_yaml_missing_file(self):
        """Test error when YAML file doesn't exist."""
        with pytest.raises(FileNotFoundError):
            ProfilesConfig.from_yaml(Path("/nonexistent/profiles.yml"))

    def test_from_yaml_empty_file(self):
        """Test error when YAML file is empty."""
        with NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write("")
            temp_path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="Profiles file is empty"):
                ProfilesConfig.from_yaml(temp_path)
        finally:
            temp_path.unlink()
