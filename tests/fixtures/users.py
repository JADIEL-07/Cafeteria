"""Fixtures del modelo User: fábrica y una cuenta lista para cada rol / nivel de Moka Club."""
import itertools

import pytest

from app.extensions import db
from app.models import User
from app.models.user import ROLE_ADMIN, ROLE_BARISTA, ROLE_CLIENT

DEFAULT_PASSWORD = "clave12345"


@pytest.fixture()
def user_factory(app):
    """``user_factory(name=..., email=..., role=..., beans=..., active=True)`` crea un usuario único."""
    counter = itertools.count(1)

    def make(name=None, email=None, password=DEFAULT_PASSWORD, role=ROLE_CLIENT, beans=0, active=True, **extra):
        n = next(counter)
        user = User.create(name or f"Usuario {n}", email or f"usuario{n}@correo.com", password, role=role, beans=beans, **extra)
        if not active:
            user.is_active_account = False
            db.session.commit()
        return user

    return make


@pytest.fixture()
def client_user(user_factory):
    return user_factory(name="Elena Rostova", email="elena@correo.com")


@pytest.fixture()
def barista_user(user_factory):
    return user_factory(name="Mateo Gómez", email="mateo@moka.com", role=ROLE_BARISTA)


@pytest.fixture()
def admin_user(user_factory):
    return user_factory(name="Administrador Moka", email="admin@moka.com", role=ROLE_ADMIN)


@pytest.fixture()
def silver_user(user_factory):
    """Cliente con 30 granos: nivel Grano Plata."""
    return user_factory(name="Sofía Alarcón", email="sofia@correo.com", beans=30)


@pytest.fixture()
def vip_user(user_factory):
    """Cliente con 120 granos: Granos Dorados VIP."""
    return user_factory(name="Valeria Morales", email="valeria@correo.com", beans=120)


@pytest.fixture()
def inactive_user(user_factory):
    return user_factory(name="Cuenta Suspendida", email="suspendida@correo.com", active=False)
