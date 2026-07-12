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

    def test_invalid_type_message_lists_mariadb(self):
        """The allowed-types list in the error message includes mariadb."""
        with pytest.raises(ValueError, match="mariadb"):
            ProfileConfig(
                type="invalid",
                host="localhost",
                port=9000,
            )

    def test_invalid_type_message_lists_duckdb(self):
        """The allowed-types list in the error message includes duckdb."""
        with pytest.raises(ValueError, match="duckdb"):
            ProfileConfig(
                type="invalid",
                host="localhost",
                port=9000,
            )

    def test_mariadb_profile(self):
        """MariaDB is a first-class alias of the MySQL profile shape."""
        profile = ProfileConfig(
            type="mariadb",
            host="localhost",
            port=3306,
            internal_database="detectk",
            data_database="analytics",
        )

        assert profile.type == "mariadb"
        assert profile.get_internal_location() == "detectk"
        assert profile.get_data_location() == "analytics"

    def test_duckdb_profile_no_port_required(self):
        """DuckDB is an in-process file DB — no port is required."""
        profile = ProfileConfig(type="duckdb", path="./detectkit.duckdb")

        assert profile.type == "duckdb"
        assert profile.port is None

    def test_duckdb_profile_location_defaults(self):
        """Unset internal_schema/data_schema fall back to DuckDB's own defaults."""
        profile = ProfileConfig(type="duckdb", path="./detectkit.duckdb")

        assert profile.get_internal_location() == "detectkit"
        assert profile.get_data_location() == "main"

    def test_duckdb_profile_location_overrides(self):
        """Explicit internal_schema/data_schema are honored over the defaults."""
        profile = ProfileConfig(
            type="duckdb",
            path="./detectkit.duckdb",
            internal_schema="dtk_internal",
            data_schema="dtk_data",
        )

        assert profile.get_internal_location() == "dtk_internal"
        assert profile.get_data_location() == "dtk_data"

    def test_duckdb_missing_path_raises(self):
        """DuckDB profiles must set 'path' (create_manager() names the field)."""
        profile = ProfileConfig(type="duckdb")

        with pytest.raises(ValueError, match="'path'"):
            profile.create_manager()

    def test_duckdb_ignores_unused_connection_fields(self):
        """host/user/password (always non-empty defaults) don't block a duckdb profile."""
        profile = ProfileConfig(
            type="duckdb",
            path="./detectkit.duckdb",
            host="localhost",
            user="default",
            password="unused",
            database="unused",
        )

        assert profile.type == "duckdb"
        assert profile.path == "./detectkit.duckdb"

    def test_duckdb_create_manager(self, tmp_path):
        """DuckDB manager is built from a profile (real engine, no mocking)."""
        pytest.importorskip("duckdb")

        profile = ProfileConfig(type="duckdb", path=str(tmp_path / "profile_test.duckdb"))

        manager = profile.create_manager()
        try:
            assert type(manager).__name__ == "DuckDBDatabaseManager"
        finally:
            manager.close()

    def test_duckdb_create_manager_dispatch_is_mocked(self, monkeypatch):
        """``create_manager()`` dispatches "duckdb" to DuckDBDatabaseManager.

        Deterministic version of the test above: the manager class itself is
        mocked so this asserts the dispatch (no real driver needed) and the
        exact kwargs passed through.
        """
        import detectkit.database.duckdb_manager as duckdb_mod

        captured: dict = {}

        class FakeDuckDBDatabaseManager:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(duckdb_mod, "DuckDBDatabaseManager", FakeDuckDBDatabaseManager)

        profile = ProfileConfig(
            type="duckdb",
            path="./detectkit.duckdb",
            settings={"memory_limit": "512MB"},
        )
        manager = profile.create_manager()

        assert isinstance(manager, FakeDuckDBDatabaseManager)
        assert captured["path"] == "./detectkit.duckdb"
        assert captured["internal_schema"] == "detectkit"
        assert captured["data_schema"] == "main"
        assert captured["settings"] == {"memory_limit": "512MB"}
        assert captured["read_only"] is False
        # host/port/user/password/database are not passed through at all.
        assert "host" not in captured
        assert "port" not in captured
        assert "user" not in captured
        assert "password" not in captured

    def test_duckdb_read_only_passes_through(self, monkeypatch):
        """``read_only: true`` in the profile reaches the manager constructor."""
        import detectkit.database.duckdb_manager as duckdb_mod

        captured: dict = {}

        class FakeDuckDBDatabaseManager:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(duckdb_mod, "DuckDBDatabaseManager", FakeDuckDBDatabaseManager)

        profile = ProfileConfig(type="duckdb", path="./detectkit.duckdb", read_only=True)
        profile.create_manager()

        assert captured["read_only"] is True
        assert "database" not in captured

    def test_non_duckdb_missing_port_raises(self):
        """Every backend except DuckDB requires a port."""
        with pytest.raises(ValueError, match="port is required"):
            ProfileConfig(
                type="clickhouse",
                host="localhost",
                internal_database="detectk_internal",
                data_database="analytics",
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

    def test_mariadb_create_manager(self):
        """A ``type: mariadb`` profile dispatches to MySQLDatabaseManager too."""
        profile = ProfileConfig(
            type="mariadb",
            host="localhost",
            port=3306,
            internal_database="detectk",
            data_database="analytics",
        )

        try:
            manager = profile.create_manager()
            assert manager is not None
            assert type(manager).__name__ == "MySQLDatabaseManager"
            manager.close()
        except ImportError:
            pytest.skip("pymysql not installed")
        except Exception as exc:
            pytest.skip(f"MySQL server not reachable: {exc}")

    def test_mariadb_create_manager_dispatch_is_mocked(self, monkeypatch):
        """``create_manager()`` dispatches "mariadb" to MySQLDatabaseManager.

        Deterministic version of the test above: the manager class itself is
        mocked so this asserts the dispatch (no real driver / server needed).
        """
        import detectkit.database.mysql_manager as mysql_mod

        captured: dict = {}

        class FakeMySQLDatabaseManager:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        monkeypatch.setattr(mysql_mod, "MySQLDatabaseManager", FakeMySQLDatabaseManager)

        profile = ProfileConfig(
            type="mariadb",
            host="localhost",
            port=3306,
            internal_database="detectk",
            data_database="analytics",
        )
        manager = profile.create_manager()

        assert isinstance(manager, FakeMySQLDatabaseManager)
        assert captured["internal_database"] == "detectk"
        assert captured["data_database"] == "analytics"


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
