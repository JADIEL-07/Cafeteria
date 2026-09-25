"""Constantes y ayudantes compartidos por las pruebas de integración."""
from sqlalchemy import select

from app.extensions import db
from app.models import Product

ADMIN = ("admin@moka.com", "admin1234")
BARISTA = ("barista@moka.com", "barista1234")
CLIENT = ("cliente@correo.com", "cliente1234")
OTHER = ("otro@correo.com", "otro12345")


def login(client, credentials):
    """Inicia sesión con el cliente HTTP de pruebas y comprueba que fue exitoso."""
    response = client.post("/login", data={"email": credentials[0], "password": credentials[1]})
    assert response.status_code == 302, response.get_data(as_text=True)[:500]
    return response


def product_id(slug):
    return db.session.scalar(select(Product.id).where(Product.slug == slug))


def add_to_cart(client, slug, **fields):
    """Añade un producto (por slug) al carrito del cliente HTTP de pruebas."""
    return client.post("/carrito/agregar", data={"product_id": product_id(slug), **fields})
