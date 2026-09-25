"""Modelo Modifier: opciones de personalización de una bebida."""
from app.models import Modifier
from app.models.product import MODIFIER_GROUP_LABELS, MODIFIER_GROUPS


def test_defaults(modifier_factory):
    modifier = modifier_factory("size", "Chico")
    assert (modifier.price_delta_cents, modifier.is_default, modifier.is_active, modifier.sort_order) == (0, False, True, 0)
    assert (modifier.inventory_item_id, modifier.inventory_qty) == (None, 0)


def test_every_group_has_a_label():
    assert set(MODIFIER_GROUP_LABELS) == set(MODIFIER_GROUPS)


class TestByGroup:
    def test_empty_still_lists_every_group(self, app):
        grouped = Modifier.by_group()
        assert set(grouped) == set(MODIFIER_GROUPS)
        assert all(options == [] for options in grouped.values())

    def test_groups_options_in_order(self, drink_modifiers):
        grouped = Modifier.by_group()
        assert [m.name for m in grouped["size"]] == ["Chico", "Mediano", "Grande"]
        assert [m.name for m in grouped["milk"]] == ["Entera Fresca de Granja", "Leche de Avena Barista", "Almendras Tostadas"]
        assert len(grouped["extra"]) == 3

    def test_only_active_options(self, modifier_factory):
        modifier_factory("size", "Chico")
        modifier_factory("size", "Retirado", is_active=False)
        assert [m.name for m in Modifier.by_group()["size"]] == ["Chico"]

    def test_sort_order_then_id(self, modifier_factory):
        second = modifier_factory("size", "B", sort_order=2)
        first = modifier_factory("size", "A", sort_order=1)
        tie_a = modifier_factory("size", "C", sort_order=2)
        assert Modifier.by_group()["size"] == [first, second, tie_a]


class TestDefaultFor:
    def test_flagged_default_wins(self, drink_modifiers):
        assert Modifier.default_for("size") == drink_modifiers.size["mediano"]
        assert Modifier.default_for("milk") == drink_modifiers.milk["oat"]

    def test_falls_back_to_first_by_sort_order(self, modifier_factory):
        modifier_factory("sweetness", "Segundo", sort_order=2)
        first = modifier_factory("sweetness", "Primero", sort_order=1)
        assert Modifier.default_for("sweetness") == first

    def test_inactive_options_are_ignored(self, modifier_factory):
        modifier_factory("size", "Retirado", is_default=True, is_active=False)
        active = modifier_factory("size", "Vigente")
        assert Modifier.default_for("size") == active

    def test_none_when_the_group_is_empty(self, app):
        assert Modifier.default_for("size") is None


def test_inventory_link(modifier_factory, milk_item):
    modifier = modifier_factory("milk", "Avena", 60, inventory_item=milk_item, inventory_qty=0.25)
    assert modifier.inventory_item == milk_item
    assert modifier.inventory_qty == 0.25
