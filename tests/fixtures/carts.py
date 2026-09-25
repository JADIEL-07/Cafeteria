"""Fixtures del carrito en sesión (Cart): usa un dict como almacén, sin necesitar peticiones HTTP."""
import pytest

from app.models import Cart


@pytest.fixture()
def cart_store():
    """El "session" del carrito: un dict simple."""
    return {}


@pytest.fixture()
def cart(app, cart_store):
    return Cart(store=cart_store)


@pytest.fixture()
def filled_cart(cart, drink, pastry, drink_modifiers):
    """1 bebida con opciones por defecto ($5.90) + 2 croissants ($7.90): subtotal $13.80."""
    cart.add(drink)
    cart.add(pastry, qty=2)
    return cart


@pytest.fixture()
def cart_summary(filled_cart):
    return filled_cart.summary()
