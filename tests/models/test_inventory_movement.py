"""Modelo InventoryMovement: bitácora de entradas y salidas de stock."""
import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import InventoryMovement
from app.models.inventory import MOVEMENT_LABELS


class TestKinds:
    @pytest.mark.parametrize("kind, label", [("compra", "Compra"), ("consumo", "Consumo"), ("ajuste", "Ajuste de conteo"), ("merma", "Merma")])
    def test_kind_labels(self, kind, label):
        assert InventoryMovement(kind=kind).kind_label == label

    def test_unknown_kind_falls_back_to_the_key(self):
        assert InventoryMovement(kind="raro").kind_label == "raro"

    def test_every_kind_has_a_label(self):
        assert set(MOVEMENT_LABELS) == {"compra", "consumo", "ajuste", "merma"}


class TestFixtures:
    def test_purchase_movement(self, purchase_movement, coffee_item, admin_user):
        assert (purchase_movement.kind, purchase_movement.qty, purchase_movement.stock_after) == ("compra", 5, 15)
        assert (purchase_movement.item, purchase_movement.user) == (coffee_item, admin_user)
        assert purchase_movement.total_cost_cents == 14500

    def test_consumption_movement(self, consumption_movement):
        assert (consumption_movement.kind, consumption_movement.qty, consumption_movement.reference) == ("consumo", -0.5, "MK-8001")
        assert consumption_movement.stock_after == 9.5
        assert consumption_movement.user is None

    def test_adjustment_and_waste_movements(self, adjustment_movement, waste_movement):
        assert (adjustment_movement.kind, adjustment_movement.qty) == ("ajuste", -2)
        assert (waste_movement.kind, waste_movement.qty) == ("merma", -0.5)


class TestRecent:
    def test_empty(self, app):
        assert InventoryMovement.recent() == []

    def test_newest_first_and_limited(self, coffee_item):
        for qty in range(1, 6):
            coffee_item.purchase(qty, 100)
        recent = InventoryMovement.recent(limit=3)
        assert [m.qty for m in recent] == [5, 4, 3]

    def test_item_lists_its_movements_newest_first(self, coffee_item):
        coffee_item.purchase(1, 100)
        coffee_item.purchase(2, 100)
        assert [m.qty for m in coffee_item.movements] == [2, 1]

    def test_movements_are_kept_per_item(self, coffee_item, milk_item):
        coffee_item.purchase(1, 100)
        milk_item.purchase(9, 100)
        assert [m.qty for m in coffee_item.movements] == [1]
        assert len(db.session.scalars(select(InventoryMovement)).all()) == 2
