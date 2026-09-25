"""Capa de base de datos: cadenas de Supabase, opciones del pool, arranque idempotente y RLS."""
import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from app.config import Config, TestConfig
from app.database import database_name, engine_options, init_database, is_postgres, normalize_database_url, seed_once
from app.extensions import db
from app.models import User

on_postgres = is_postgres(TestConfig.SQLALCHEMY_DATABASE_URI)

SUPABASE_POOLER = "aws-0-us-east-1.pooler.supabase.com"


class TestNormalizeUrl:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("postgresql://postgres.abc:pw@host:5432/postgres", "postgresql+psycopg://postgres.abc:pw@host:5432/postgres"),
            ("postgres://postgres:pw@host:6543/postgres", "postgresql+psycopg://postgres:pw@host:6543/postgres"),
            ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
            ("  postgresql://u:p@h/db \n", "postgresql+psycopg://u:p@h/db"),
            ("sqlite:///cafeteria.db", "sqlite:///cafeteria.db"),
            ("sqlite://", "sqlite://"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalize(self, raw, expected):
        assert normalize_database_url(raw) == expected

    def test_is_postgres(self):
        assert is_postgres("postgresql+psycopg://u:p@h/db")
        assert not is_postgres("sqlite:///x.db") and not is_postgres("sqlite://")

    def test_database_name(self):
        assert database_name("postgresql+psycopg://u:p@h:5432/cafeteria_test") == "cafeteria_test"
        assert database_name("postgresql+psycopg://u:p@h") == ""


class TestEngineOptions:
    def test_sqlite_needs_nothing_special(self):
        assert engine_options("sqlite:///cafeteria.db") == {}
        assert engine_options("sqlite://") == {}

    def test_supabase_pooler(self):
        options = engine_options(f"postgresql+psycopg://postgres.abc:pw@{SUPABASE_POOLER}:6543/postgres")
        assert options["pool_pre_ping"] is True
        assert options["pool_recycle"] < 300                       # el pooler cierra las conexiones inactivas
        assert options["connect_args"]["prepare_threshold"] is None  # el modo transacción no admite sentencias preparadas
        assert options["connect_args"]["sslmode"] == "require"      # Supabase sólo acepta conexiones cifradas

    @pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
    def test_local_postgres_does_not_force_ssl(self, host):
        options = engine_options(f"postgresql+psycopg://postgres:pw@{host}:5432/cafeteria")
        assert "sslmode" not in options["connect_args"]
        assert options["connect_args"]["prepare_threshold"] is None

    def test_an_explicit_sslmode_in_the_url_is_respected(self):
        options = engine_options(f"postgresql+psycopg://u:p@{SUPABASE_POOLER}:5432/postgres?sslmode=verify-full")
        assert "sslmode" not in options["connect_args"]            # ya viene en la URL

    def test_pool_is_small_enough_for_a_free_plan(self):
        options = engine_options(f"postgresql+psycopg://u:p@{SUPABASE_POOLER}:5432/postgres")
        assert options["pool_size"] + options["max_overflow"] <= 10


class TestConfigSelection:
    def test_defaults_to_sqlite_in_instance_folder(self):
        assert Config.SQLALCHEMY_DATABASE_URI.startswith(("sqlite:///", "postgresql+psycopg://"))

    def test_tests_never_use_database_url(self, monkeypatch):
        monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:secret@db.prod.supabase.co:5432/postgres")
        assert "supabase" not in TestConfig.SQLALCHEMY_DATABASE_URI


class TestInitDatabase:
    def test_creates_every_table(self, app):
        assert set(db.metadata.tables) <= set(inspect(db.engine).get_table_names())

    def test_is_idempotent(self, app):
        init_database()
        init_database()
        assert db.session.scalar(select(User.id)) is None

    def test_keeps_existing_data(self, app, client_user):
        init_database()
        assert db.session.get(User, client_user.id) is not None

    @pytest.mark.skipif(not on_postgres, reason="RLS sólo existe en PostgreSQL")
    def test_row_level_security_is_enabled_on_every_table(self, app):
        rows = db.session.execute(
            text("SELECT relname, relrowsecurity FROM pg_class WHERE relkind = 'r' AND relnamespace = current_schema()::regnamespace")
        ).all()
        secured = {name: enabled for name, enabled in rows if name in db.metadata.tables}
        assert set(secured) == set(db.metadata.tables)
        assert all(secured.values()), [name for name, enabled in secured.items() if not enabled]

    @pytest.mark.skipif(not on_postgres, reason="RLS sólo existe en PostgreSQL")
    def test_the_app_can_still_read_and_write_with_rls_on(self, app, client_user):
        assert db.session.scalar(select(User.email).where(User.id == client_user.id)) == client_user.email


class TestSeedOnce:
    def test_seeds_an_empty_database_once(self, app):
        calls = []

        def seed():
            calls.append(1)
            User.create("Ada", "ada@moka.com", "clave-larga-1")

        assert seed_once(seed) is True
        assert seed_once(seed) is False
        assert calls == [1]

    def test_tolerates_a_concurrent_worker_seeding_first(self, app):
        def racing_seed():
            raise IntegrityError("INSERT INTO users", {}, Exception("duplicate key"))

        assert seed_once(racing_seed) is False
        assert db.session.scalar(select(User.id)) is None         # la sesión quedó usable tras el rollback


class TestResetDbCommand:
    """``flask reset-db`` borra todo: en bases remotas (Supabase) pide confirmación."""

    def run(self, app, *args, **kwargs):
        # El reset reutiliza los ids y, en PostgreSQL, DROP TABLE espera a que nadie tenga la tabla en uso:
        # se cierra la sesión de la prueba (como en la CLI real, que arranca sin transacciones abiertas).
        db.session.remove()
        return app.test_cli_runner().invoke(args=["reset-db", "--no-demo", *args], **kwargs)

    @pytest.mark.skipif(on_postgres, reason="con PostgreSQL siempre pide confirmación")
    def test_sqlite_resets_without_asking(self, app, client_user):
        email = client_user.email                                       # antes: el id 1 lo ocupará el admin sembrado
        result = self.run(app)
        assert result.exit_code == 0 and "reiniciada" in result.output
        db.session.expire_all()
        assert User.get_by_email(app.config["ADMIN_EMAIL"]) is not None
        assert User.get_by_email(email) is None

    @pytest.mark.skipif(not on_postgres, reason="la confirmación sólo aplica a bases que no son SQLite")
    def test_postgres_asks_first_and_aborts_by_default(self, app, client_user):
        email = client_user.email
        result = self.run(app, input="n\n")
        assert result.exit_code != 0 and "TODAS las tablas" in result.output
        assert database_name(TestConfig.SQLALCHEMY_DATABASE_URI) in result.output      # muestra a qué base apunta
        password = make_url(TestConfig.SQLALCHEMY_DATABASE_URI).password
        if password:                                                                   # y nunca la contraseña (en CI vale "postgres")
            assert f":{password}@" not in result.output and ":***@" in result.output
        assert User.get_by_email(email) is not None                                   # no se borró nada

    @pytest.mark.skipif(not on_postgres, reason="la confirmación sólo aplica a bases que no son SQLite")
    def test_postgres_resets_when_confirmed(self, app, client_user):
        email = client_user.email
        result = self.run(app, "--yes")
        assert result.exit_code == 0 and "reiniciada" in result.output
        db.session.expire_all()
        assert User.get_by_email(email) is None
        assert User.get_by_email(app.config["ADMIN_EMAIL"]) is not None
