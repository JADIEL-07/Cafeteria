"""Fixtures de la aplicación: app Flask vacía (sin datos), cliente HTTP y sesión de base de datos."""
import pytest

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.utils.throttle import login_limiter


@pytest.fixture()
def app():
    """App con base SQLite en memoria, vacía, y con su contexto de aplicación abierto."""
    application = create_app(TestConfig)
    with application.app_context():
        login_limiter.reset()
        yield application
        db.session.remove()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def session(app):
    """La sesión de SQLAlchemy de la prueba (atajo de ``db.session``)."""
    return db.session
