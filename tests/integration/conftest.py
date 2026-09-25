"""Fixtures de integración: tienda ya sembrada (catálogo + cuentas) y stock disponible."""
import pytest
from sqlalchemy import select

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import InventoryItem, User
from app.models.user import ROLE_ADMIN, ROLE_BARISTA
from app.seed import seed_catalog
from app.utils.throttle import login_limiter
from tests.helpers import ADMIN, BARISTA, CLIENT, OTHER


@pytest.fixture()
def app():
    """Sobrescribe el ``app`` vacío de los fixtures: aquí la tienda viene con catálogo y cuentas."""
    application = create_app(TestConfig)
    with application.app_context():
        seed_catalog()
        User.create("Admin Test", ADMIN[0], ADMIN[1], role=ROLE_ADMIN)
        User.create("Barista Test", BARISTA[0], BARISTA[1], role=ROLE_BARISTA)
        User.create("Cliente Test", CLIENT[0], CLIENT[1])
        User.create("Otro Cliente", OTHER[0], OTHER[1])
        login_limiter.reset()
        yield application
        db.session.remove()
        db.engine.dispose()


@pytest.fixture()
def stocked(app):
    """Compra 100 unidades de cada insumo (con su costo) para poder aceptar pedidos."""
    admin = User.get_by_email(ADMIN[0])
    for item in db.session.scalars(select(InventoryItem)).all():
        item.purchase(100, item.unit_cost_cents, supplier=item.supplier, user=admin)
