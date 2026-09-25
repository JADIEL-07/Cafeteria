"""Modelo Cart: carrito en sesión, opciones, cupones y valorización (sin peticiones HTTP)."""
import json

import pytest

from app.extensions import db
from app.models import Cart, CartError
from app.models.cart import MAX_LINE_QTY, MAX_LINES, MAX_NOTE


class TestStore:
    def test_a_new_cart_is_empty(self, cart):
        assert cart.count() == 0
        assert cart.mode_info() == ("barra", "")
        summary = cart.summary()
        assert summary.is_empty and summary.total_cents == 0 and summary.count == 0

    def test_garbage_in_the_store_is_ignored(self, cart_store):
        cart_store["cart"] = "basura"
        assert Cart(store=cart_store).count() == 0

    def test_invalid_mode_and_long_table_are_sanitized(self, cart_store):
        cart_store["cart"] = {"lines": [], "mode": "hackeado", "table": "x" * 50}
        assert Cart(store=cart_store).mode_info() == ("barra", "x" * 10)

    def test_non_dict_lines_are_dropped(self, cart_store):
        cart_store["cart"] = {"lines": ["x", 3, None, {"key": "a", "pid": 1, "mods": [], "notes": "", "qty": 2}]}
        assert Cart(store=cart_store).count() == 2

    def test_clear(self, filled_cart, cart_store):
        filled_cart.clear()
        assert "cart" not in cart_store and filled_cart.count() == 0
        filled_cart.clear()      # idempotente

    def test_the_stored_state_is_json_serializable(self, filled_cart, cart_store):
        assert json.loads(json.dumps(cart_store))["cart"]["lines"][0]["pid"]


class TestLineKey:
    def test_is_deterministic_and_short(self):
        key = Cart.line_key(1, [3, 2], "sin azúcar")
        assert key == Cart.line_key(1, [3, 2], "sin azúcar")
        assert len(key) == 10 and int(key, 16) >= 0

    def test_option_order_does_not_matter(self):
        assert Cart.line_key(1, [1, 2, 3], "") == Cart.line_key(1, [3, 1, 2], "")

    @pytest.mark.parametrize("args", [(2, [1], ""), (1, [2], ""), (1, [1, 2], ""), (1, [1], "nota")])
    def test_any_difference_changes_the_key(self, args):
        assert Cart.line_key(*args) != Cart.line_key(1, [1], "")


class TestResolveModifiers:
    def names(self, modifiers):
        return [m.name for m in modifiers]

    def test_defaults_follow_the_product_group_order(self, drink, drink_modifiers):
        chosen = Cart.resolve_modifiers(drink, {}, [])
        assert self.names(chosen) == ["Mediano", "Caliente", "Leche de Avena Barista", "Normal (100%)"]

    def test_explicit_choices_override_defaults(self, drink, drink_modifiers):
        m = drink_modifiers
        chosen = Cart.resolve_modifiers(drink, {"size": m.size["grande"].id, "milk": str(m.milk["almond"].id)}, [])
        assert self.names(chosen) == ["Grande", "Caliente", "Almendras Tostadas", "Normal (100%)"]

    def test_empty_choice_means_default(self, drink, drink_modifiers):
        assert self.names(Cart.resolve_modifiers(drink, {"size": ""}, []))[0] == "Mediano"

    def test_extras_are_sorted_and_deduplicated(self, drink, drink_modifiers):
        shot, cream = drink_modifiers.extra["shot"], drink_modifiers.extra["cream"]
        chosen = Cart.resolve_modifiers(drink, {}, [cream.id, str(shot.id), shot.id])
        assert self.names(chosen)[-2:] == ["Shot Extra de Espresso", "Nube de Crema Batida"]

    def test_product_without_option_groups_has_no_modifiers(self, pastry, drink_modifiers):
        assert Cart.resolve_modifiers(pastry, {"size": drink_modifiers.size["grande"].id}, [drink_modifiers.extra["shot"].id]) == []

    def test_groups_without_options_are_skipped(self, drink):
        assert Cart.resolve_modifiers(drink, {}, []) == []

    @pytest.mark.parametrize("bad_size", [99999, "abc", "9" * 400, -1, 0.5])
    def test_invalid_single_choices_are_rejected(self, drink, drink_modifiers, bad_size):
        with pytest.raises(CartError):
            Cart.resolve_modifiers(drink, {"size": bad_size}, [])

    def test_option_from_another_group_is_rejected(self, drink, drink_modifiers):
        with pytest.raises(CartError):
            Cart.resolve_modifiers(drink, {"size": drink_modifiers.milk["oat"].id}, [])

    def test_inactive_option_is_rejected(self, drink, drink_modifiers):
        grande = drink_modifiers.size["grande"]
        grande.is_active = False
        db.session.commit()
        with pytest.raises(CartError):
            Cart.resolve_modifiers(drink, {"size": grande.id}, [])

    @pytest.mark.parametrize("extras", [["abc"], ["1", "x"], [None], ["9" * 400], [99999]])
    def test_invalid_extras_are_rejected(self, drink, drink_modifiers, extras):
        with pytest.raises(CartError):
            Cart.resolve_modifiers(drink, {}, extras)

    def test_extra_from_another_group_is_rejected(self, drink, drink_modifiers):
        with pytest.raises(CartError, match="extras"):
            Cart.resolve_modifiers(drink, {}, [drink_modifiers.size["grande"].id])

    def test_too_many_extras(self, drink, drink_modifiers):
        with pytest.raises(CartError, match="Demasiados"):
            Cart.resolve_modifiers(drink, {}, list(range(1, 12)))


class TestAdd:
    def test_adds_a_line_and_returns_its_key(self, cart, drink, drink_modifiers):
        key = cart.add(drink)
        assert cart.count() == 1
        line = cart.summary().lines[0]
        assert (line.key, line.qty, line.product) == (key, 1, drink)

    @pytest.mark.parametrize("qty, expected", [(0, 1), (-5, 1), (1, 1), (7, 7), (20, 20), (999, MAX_LINE_QTY)])
    def test_quantity_is_clamped(self, cart, pastry, qty, expected):
        cart.add(pastry, qty=qty)
        assert cart.count() == expected

    def test_notes_are_stripped_and_truncated(self, cart, pastry):
        cart.add(pastry, notes="  " + "x" * 400 + "  ")
        assert cart.summary().lines[0].notes == "x" * MAX_NOTE

    def test_identical_lines_merge_up_to_the_cap(self, cart, pastry):
        for _ in range(3):
            cart.add(pastry, qty=10)
        summary = cart.summary()
        assert len(summary.lines) == 1 and summary.lines[0].qty == MAX_LINE_QTY

    def test_different_notes_or_options_make_separate_lines(self, cart, drink, drink_modifiers):
        cart.add(drink)
        cart.add(drink, notes="poco hielo")
        cart.add(drink, selections={"size": drink_modifiers.size["grande"].id})
        assert len(cart.summary().lines) == 3

    def test_inactive_or_missing_products_are_rejected(self, cart, inactive_product):
        with pytest.raises(CartError, match="ya no está disponible"):
            cart.add(inactive_product)
        with pytest.raises(CartError):
            cart.add(None)
        assert cart.count() == 0

    def test_invalid_options_add_nothing(self, cart, drink, drink_modifiers):
        with pytest.raises(CartError):
            cart.add(drink, selections={"size": 99999})
        assert cart.count() == 0

    def test_line_limit(self, cart, pastry):
        for n in range(MAX_LINES):
            cart.add(pastry, notes=f"nota {n}")
        with pytest.raises(CartError, match="demasiados"):
            cart.add(pastry, notes="una más")
        cart.add(pastry, notes="nota 0")             # una línea existente sí puede crecer
        assert cart.count() == MAX_LINES + 1


class TestQuantities:
    def test_set_qty(self, cart, pastry):
        key = cart.add(pastry)
        cart.set_qty(key, 5)
        assert cart.count() == 5
        cart.set_qty(key, 999)
        assert cart.count() == MAX_LINE_QTY

    def test_set_qty_zero_removes_the_line(self, cart, pastry):
        key = cart.add(pastry)
        cart.set_qty(key, 0)
        assert cart.summary().is_empty

    def test_change_qty_never_drops_below_one(self, cart, pastry):
        key = cart.add(pastry, qty=2)
        cart.change_qty(key, -1)
        cart.change_qty(key, -1)
        cart.change_qty(key, -5)
        assert cart.count() == 1
        cart.change_qty(key, +3)
        assert cart.count() == 4

    def test_unknown_keys_are_ignored(self, cart, pastry):
        cart.add(pastry)
        cart.set_qty("nope", 9)
        cart.change_qty("nope", 1)
        cart.remove("nope")
        assert cart.count() == 1

    def test_remove(self, cart, pastry, drink, drink_modifiers):
        keep = cart.add(pastry)
        drop = cart.add(drink)
        cart.remove(drop)
        assert [line.key for line in cart.summary().lines] == [keep]


class TestDeliveryMode:
    def test_table_service_keeps_a_trimmed_table(self, cart):
        cart.set_mode("mesa", "  4  ")
        assert cart.mode_info() == ("mesa", "4")
        cart.set_mode("mesa", "1234567890123")
        assert cart.mode_info() == ("mesa", "1234567890")

    def test_counter_pickup_clears_the_table(self, cart):
        cart.set_mode("mesa", "4")
        cart.set_mode("barra", "9")
        assert cart.mode_info() == ("barra", "")

    def test_unknown_mode(self, cart):
        with pytest.raises(CartError):
            cart.set_mode("dron")
        assert cart.mode_info() == ("barra", "")

    def test_summary_carries_the_mode(self, cart):
        cart.set_mode("mesa", "7")
        summary = cart.summary()
        assert (summary.mode, summary.table) == ("mesa", "7")


class TestSummary:
    def test_totals(self, cart_summary):
        assert [line.unit_cents for line in cart_summary.lines] == [590, 395]
        assert [line.line_cents for line in cart_summary.lines] == [590, 790]
        assert (cart_summary.subtotal_cents, cart_summary.discount_cents, cart_summary.tax_cents, cart_summary.total_cents) == (1380, 0, 104, 1484)
        assert (cart_summary.count, cart_summary.beans_estimate, cart_summary.tax_percent) == (3, 14, 7.5)
        assert cart_summary.coupon is None and cart_summary.coupon_error is None

    def test_line_helpers(self, cart_summary):
        drink_line = cart_summary.lines[0]
        assert drink_line.options_text == "Mediano • Caliente • Leche de Avena Barista • Normal (100%)"
        assert len(drink_line.option_ids) == 4
        assert cart_summary.lines[1].options_text == "" and cart_summary.lines[1].option_ids == []

    def test_options_change_the_unit_price(self, cart, drink, drink_modifiers):
        m = drink_modifiers
        cart.add(drink, selections={"size": m.size["grande"].id, "milk": m.milk["almond"].id}, extras=[m.extra["shot"].id, m.extra["cream"].id], qty=2)
        line = cart.summary().lines[0]
        assert line.unit_cents == 480 + 100 + 60 + 90 + 50
        assert line.line_cents == 2 * 780

    def test_tax_is_charged_after_the_discount(self, filled_cart, fixed_coupon):
        filled_cart.apply_coupon("CAFELOVER")
        summary = filled_cart.summary()
        assert (summary.subtotal_cents, summary.discount_cents, summary.tax_cents, summary.total_cents) == (1380, 200, 89, 1269)
        assert summary.coupon == fixed_coupon

    def test_products_deactivated_after_adding_are_skipped(self, filled_cart, drink):
        drink.is_active = False
        db.session.commit()
        summary = filled_cart.summary()
        assert [line.product.name for line in summary.lines] == ["Croissant de Almendras"]
        assert summary.subtotal_cents == 790

    def test_deleted_options_are_ignored(self, filled_cart, drink_modifiers):
        db.session.delete(drink_modifiers.milk["oat"])
        db.session.commit()
        line = filled_cart.summary().lines[0]
        assert line.unit_cents == 480 + 50
        assert "Avena" not in line.options_text


class TestCoupons:
    def test_apply_and_remove(self, filled_cart, fixed_coupon):
        assert filled_cart.apply_coupon("  cafelover ") == fixed_coupon
        assert filled_cart.summary().discount_cents == 200
        filled_cart.remove_coupon()
        assert filled_cart.summary().coupon is None

    def test_unknown_coupon(self, filled_cart):
        with pytest.raises(CartError, match="no existe"):
            filled_cart.apply_coupon("FANTASMA")

    def test_minimum_subtotal_is_checked_when_applying(self, cart, product_factory, fixed_coupon):
        cart.add(product_factory(price_cents=300))
        with pytest.raises(CartError, match=r"\$5\.00"):
            cart.apply_coupon("CAFELOVER")
        assert cart.summary().coupon is None

    def test_inactive_and_exhausted_coupons(self, filled_cart, inactive_coupon, exhausted_coupon):
        with pytest.raises(CartError, match="disponible"):
            filled_cart.apply_coupon("VIEJO")
        with pytest.raises(CartError, match="límite"):
            filled_cart.apply_coupon("AGOTADO")

    def test_percent_coupon(self, filled_cart, percent_coupon):
        filled_cart.apply_coupon("PROMO10")
        assert filled_cart.summary().discount_cents == 138

    def test_coupon_is_dropped_when_it_stops_applying(self, cart, pastry, product_factory, fixed_coupon):
        key = cart.add(pastry, qty=2)                     # $7.90 >= $5.00
        cart.apply_coupon("CAFELOVER")
        assert cart.summary().discount_cents == 200
        cart.remove(key)
        cart.add(product_factory(price_cents=300))        # ahora $3.00 < mínimo
        summary = cart.summary()
        assert (summary.coupon, summary.discount_cents) == (None, 0)
        assert "subtotal mínimo" in summary.coupon_error

    def test_coupon_deleted_after_being_applied(self, filled_cart, fixed_coupon):
        filled_cart.apply_coupon("CAFELOVER")
        db.session.delete(fixed_coupon)
        db.session.commit()
        summary = filled_cart.summary()
        assert summary.coupon is None and summary.coupon_error == "El cupón ya no existe."
        assert summary.discount_cents == 0
