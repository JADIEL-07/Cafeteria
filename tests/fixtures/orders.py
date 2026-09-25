"""Fixtures de Order y OrderItem: una "cocina" con recetas y stock, y pedidos en cada etapa del ciclo."""
from types import SimpleNamespace

import pytest

from app.extensions import db
from app.models import Cart, Order


@pytest.fixture()
def kitchen(drink, pastry, drink_modifiers, recipe_factory, coffee_item, milk_item, cup_item, butter_item):
    """Bebida y pastel con receta, opciones ligadas a insumos y stock disponible.

    Receta bebida: 0.018 kg de café + 1 vaso (+0.25 briks si lleva leche de avena, +0.018 kg con shot extra).
    Receta pastel: 0.05 kg de mantequilla.
    """
    recipe_factory(drink, coffee_item, 0.018)
    recipe_factory(drink, cup_item, 1)
    recipe_factory(pastry, butter_item, 0.05)
    oat = drink_modifiers.milk["oat"]
    oat.inventory_item_id, oat.inventory_qty = milk_item.id, 0.25
    shot = drink_modifiers.extra["shot"]
    shot.inventory_item_id, shot.inventory_qty = coffee_item.id, 0.018
    db.session.commit()
    return SimpleNamespace(
        drink=drink, pastry=pastry, modifiers=drink_modifiers, coffee=coffee_item, milk=milk_item, cup=cup_item, butter=butter_item
    )


@pytest.fixture()
def order_factory(kitchen, client_user, fixed_coupon):
    """``order_factory(method="tarjeta", drinks=1, pastries=2, coupon=False, ...)`` -> Order.

    Con los valores por defecto: subtotal $13.80, IVA $1.04, total $14.84 (comisión de tarjeta $0.36, 14 granos).
    """

    def make(method="tarjeta", drinks=1, pastries=2, coupon=False, fulfillment="barra", table=None, notes=None, at=None, user=None):
        cart = Cart(store={})
        if drinks:
            cart.add(kitchen.drink, qty=drinks)
        if pastries:
            cart.add(kitchen.pastry, qty=pastries)
        if coupon:
            cart.apply_coupon(fixed_coupon.code)
        return Order.create_from_cart(user or client_user, cart.summary(), method, fulfillment, table, notes, at=at)

    return make


@pytest.fixture()
def card_order(order_factory):
    """Pagado con tarjeta: estado "nuevo", pago "pagado"."""
    return order_factory("tarjeta")


@pytest.fixture()
def cash_order(order_factory):
    """En efectivo: pago "pendiente" hasta que barra lo valide."""
    return order_factory("efectivo")


@pytest.fixture()
def accepted_order(card_order, barista_user):
    card_order.accept(barista_user)
    return card_order


@pytest.fixture()
def ready_order(accepted_order):
    accepted_order.mark_ready()
    return accepted_order


@pytest.fixture()
def delivered_order(ready_order):
    ready_order.mark_delivered()
    return ready_order


@pytest.fixture()
def cancelled_paid_order(card_order, barista_user):
    card_order.cancel(by=barista_user, reason="Cliente canceló")
    return card_order


@pytest.fixture()
def cancelled_unpaid_order(cash_order):
    cash_order.cancel(reason="No se presentó")
    return cash_order
