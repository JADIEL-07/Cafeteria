"""Modelo OrderItem: líneas de un pedido como foto del carrito al momento de comprar."""
import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Cart, Order, OrderItem


class TestSnapshot:
    def test_fields_come_from_the_cart_line(self, card_order, kitchen):
        drink_item = card_order.items[0]
        assert drink_item.order == card_order
        assert drink_item.product == kitchen.drink
        assert (drink_item.name, drink_item.qty) == ("Caramel Macchiato Insignia", 1)
        assert (drink_item.unit_price_cents, drink_item.line_total_cents) == (590, 590)

    def test_line_total_is_unit_price_times_quantity(self, card_order):
        pastry_item = card_order.items[1]
        assert (pastry_item.qty, pastry_item.unit_price_cents, pastry_item.line_total_cents) == (2, 395, 790)
        assert sum(item.line_total_cents for item in card_order.items) == card_order.subtotal_cents

    def test_selected_options_are_stored_as_ids_and_as_text(self, card_order, kitchen):
        item = card_order.items[0]
        stored = json.loads(item.options_json)
        assert stored == sorted(stored) and len(stored) == 4
        assert kitchen.modifiers.milk["oat"].id in stored
        assert item.options_text == "Mediano • Caliente • Leche de Avena Barista • Normal (100%)"

    def test_products_without_options_have_empty_defaults(self, card_order):
        item = card_order.items[1]
        assert json.loads(item.options_json) == []
        assert not item.options_text

    def test_extras_are_part_of_the_price_and_the_text(self, client_user, kitchen):
        plain = Cart(store={})
        plain.add(kitchen.drink)
        base = plain.summary().lines[0].unit_cents
        cart = Cart(store={})
        cart.add(kitchen.drink, extras=[kitchen.modifiers.extra["shot"].id], qty=2)
        item = Order.create_from_cart(client_user, cart.summary(), "efectivo").items[0]
        assert item.qty == 2
        assert item.unit_price_cents == base + 90
        assert item.line_total_cents == item.unit_price_cents * 2
        assert "Shot Extra de Espresso" in item.options_text

    def test_notes_default_to_empty(self, card_order):
        assert all(not item.notes for item in card_order.items)


class TestRelationships:
    def test_order_owns_its_items_in_insertion_order(self, card_order):
        assert [item.name for item in card_order.items] == ["Caramel Macchiato Insignia", "Croissant de Almendras"]
        assert all(item.order_id == card_order.id for item in card_order.items)

    def test_items_can_be_reloaded(self, card_order):
        db.session.expire_all()
        reloaded = db.session.get(Order, card_order.id)
        assert len(reloaded.items) == 2
        assert reloaded.item_count == 3

    def test_each_order_only_sees_its_own_items(self, order_factory):
        first = order_factory("tarjeta", drinks=1, pastries=0)
        second = order_factory("tarjeta", drinks=0, pastries=2)
        assert [i.qty for i in first.items] == [1]
        assert [i.qty for i in second.items] == [2]
        assert db.session.scalar(select(func.count(OrderItem.id))) == 2

    def test_item_count_sums_quantities(self, order_factory):
        assert order_factory("efectivo", drinks=2, pastries=3).item_count == 5


class TestConstraints:
    @pytest.mark.parametrize("missing", ["order_id", "product_id", "name", "unit_price_cents", "line_total_cents"])
    def test_required_columns(self, card_order, kitchen, missing):
        values = {
            "order_id": card_order.id, "product_id": kitchen.drink.id, "name": "X",
            "unit_price_cents": 100, "qty": 1, "line_total_cents": 100,
        }
        values[missing] = None
        db.session.add(OrderItem(**values))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_quantity_defaults_to_one(self, card_order, kitchen):
        item = OrderItem(order_id=card_order.id, product_id=kitchen.drink.id, name="X", unit_price_cents=100, line_total_cents=100)
        db.session.add(item)
        db.session.commit()
        assert (item.qty, item.options_json) == (1, "[]")
