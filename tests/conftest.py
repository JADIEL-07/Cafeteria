import pytest
from sqlalchemy import select

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import InventoryItem, Product, User
from app.models.user import ROLE_ADMIN, ROLE_BARISTA
from app.seed import seed_catalog
from app.utils.throttle import login_limiter

ADMIN = ("admin@moka.com", "admin1234")
BARISTA = ("barista@moka.com", "barista1234")
CLIENT = ("cliente@correo.com", "cliente1234")
OTHER = ("otro@correo.com", "otro12345")


@pytest.fixture()
def app():
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


@pytest.fixture()
def client(app):
    return app.test_client()


def login(client, credentials):
    response = client.post("/login", data={"email": credentials[0], "password": credentials[1]})
    assert response.status_code == 302, response.get_data(as_text=True)[:500]
    return response


@pytest.fixture()
def stocked(app):
    """Compra 100 unidades de cada insumo (con su costo) para poder aceptar pedidos."""
    with app.app_context():
        admin = User.get_by_email(ADMIN[0])
        for item in db.session.scalars(select(InventoryItem)):
            item.purchase(100, item.unit_cost_cents, supplier=item.supplier, user=admin)


def product_id(slug):
    return db.session.scalar(select(Product.id).where(Product.slug == slug))


def add_to_cart(client, slug, **fields):
    data = {"product_id": product_id(slug), **fields}
    return client.post("/carrito/agregar", data=data)
