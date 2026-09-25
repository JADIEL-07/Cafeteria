"""Fixtures de la aplicación: app Flask vacía (sin datos), cliente HTTP y sesión de base de datos.

Por omisión las pruebas usan SQLite en memoria (nace vacía en cada prueba). Con la variable
``TEST_DATABASE_URL`` corren contra PostgreSQL (el mismo motor que Supabase): la base persiste, así
que se vacía antes de cada prueba.
"""
import pytest
from sqlalchemy import create_engine, text

from app import create_app, models  # noqa: F401  (models registra las tablas)
from app.config import TestConfig
from app.database import database_name, is_postgres
from app.extensions import db
from app.utils.throttle import login_limiter


def _test_database_engine():
    """Motor propio (sin app) hacia la base de pruebas PostgreSQL; ``None`` con SQLite en memoria."""
    url = TestConfig.SQLALCHEMY_DATABASE_URI
    if not is_postgres(url):
        return None
    name = database_name(url)
    if "test" not in name.lower():
        pytest.exit(f"TEST_DATABASE_URL apunta a '{name}': por seguridad el nombre de la base de pruebas debe contener 'test'.", returncode=2)
    return create_engine(url, **TestConfig.SQLALCHEMY_ENGINE_OPTIONS)


@pytest.fixture(autouse=True)
def clean_database():
    """Con PostgreSQL la base persiste entre pruebas: se vacía (y se reinician los ids) antes de cada una.

    Corre antes de cualquier fixture de app, así las pruebas que crean su propia app (y la siembran)
    parten de una base limpia. Es destructivo, por eso sólo actúa sobre bases cuyo nombre contiene "test".
    """
    engine = _test_database_engine()
    if engine is None:
        yield
        return
    with engine.begin() as conn:
        # Una prueba que creó su propia app puede haber dejado una conexión abierta en transacción,
        # y eso bloquearía el TRUNCATE: se cierran las demás conexiones de esta base de pruebas.
        conn.execute(text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = current_database() AND pid <> pg_backend_pid()"))
        conn.execute(text("SET LOCAL lock_timeout = '10s'"))
        db.metadata.create_all(bind=conn)
        tables = ", ".join(f'"{table.name}"' for table in db.metadata.sorted_tables)
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    engine.dispose()
    yield


@pytest.fixture()
def app():
    """App con la base de pruebas vacía y con su contexto de aplicación abierto."""
    application = create_app(TestConfig)
    with application.app_context():
        login_limiter.reset()
        yield application
        db.session.remove()
        db.engine.dispose()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def session(app):
    """La sesión de SQLAlchemy de la prueba (atajo de ``db.session``)."""
    return db.session
