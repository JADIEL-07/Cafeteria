"""Modelo InventoryItem: estado del stock, altas, compras, ajustes y consumo."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import DomainError, InsufficientStock, InventoryItem, InventoryMovement, LedgerEntry
from app.models.inventory import CATEGORIES, MOV_ADJUSTMENT, MOV_WASTE, UNITS


def reload_item(item):
    db.session.expire_all()
    return db.session.get(InventoryItem, item.id)


class TestStatus:
    @pytest.mark.parametrize(
        "stock, status, label",
        [(0, "critico", "Crítico"), (4, "critico", "Crítico"), (5, "critico", "Crítico"), (5.01, "alerta", "Alerta"), (9.99, "alerta", "Alerta"), (10, "optimo", "Óptimo"), (50, "optimo", "Óptimo")],
    )
    def test_thresholds_with_minimum_10(self, item_factory, stock, status, label):
        item = item_factory(stock=stock, min_stock=10)
        assert (item.status, item.status_label) == (status, label)

    @pytest.mark.parametrize("stock", [0, 3])
    def test_without_a_minimum_there_is_no_alert(self, item_factory, stock):
        assert item_factory(stock=stock, min_stock=0).status == "optimo"

    def test_fixtures_cover_each_status(self, coffee_item, warning_item, critical_item):
        assert (coffee_item.status, warning_item.status, critical_item.status) == ("optimo", "alerta", "critico")


class TestProperties:
    def test_labels_and_value(self, coffee_item):
        assert coffee_item.category_label == "Café & Té"
        assert coffee_item.value_cents == 28500          # 10 kg a $28.50
        assert coffee_item.is_countable is False

    def test_unknown_category_label_falls_back_to_the_key(self, item_factory):
        assert item_factory(category="otra").category_label == "otra"

    @pytest.mark.parametrize("unit, countable", [("kg", False), ("L", False), ("briks", True), ("uds", True)])
    def test_is_countable(self, item_factory, unit, countable):
        assert item_factory(unit=unit).is_countable is countable

    def test_value_rounds_fractional_stock(self, item_factory):
        assert item_factory(stock=0.75, unit_cost_cents=3400).value_cents == 2550

    @pytest.mark.parametrize(
        "unit, stock, minimum, expected",
        [("kg", 0, 2, 4), ("kg", 1.2, 2, 3.0), ("kg", 3.9, 2, 0.5), ("kg", 4, 2, 0), ("kg", 9, 2, 0), ("briks", 4, 10, 16), ("briks", 3.5, 10, 17), ("uds", 0, 3, 6)],
    )
    def test_suggested_qty_restocks_up_to_double_the_minimum(self, item_factory, unit, stock, minimum, expected):
        assert item_factory(unit=unit, stock=stock, min_stock=minimum).suggested_qty() == expected

    def test_repr(self, coffee_item):
        assert repr(coffee_item) == "<InventoryItem MOK-CF-01>"

    def test_sku_is_unique(self, item_factory):
        item_factory(sku="MOK-X-01")
        with pytest.raises(IntegrityError):
            item_factory(sku="MOK-X-01")
        db.session.rollback()


class TestQueries:
    @pytest.fixture()
    def stock_room(self, item_factory):
        return {
            "leche": item_factory("Leche entera", "leches", "L", stock=20, min_stock=8, sku="B-1"),
            "avena": item_factory("Leche de avena", "leches", "briks", stock=2, min_stock=10, sku="B-2"),
            "cafe": item_factory("Café molido", "cafe", "kg", stock=5, min_stock=2, sku="A-1"),
            "retirado": item_factory("Retirado", "cafe", "kg", stock=0, min_stock=5, is_active=False, sku="A-2"),
        }

    def test_listing_excludes_inactive_and_orders_by_category_then_name(self, stock_room):
        assert [i.name for i in InventoryItem.listing()] == ["Café molido", "Leche de avena", "Leche entera"]

    def test_listing_by_category(self, stock_room):
        assert [i.name for i in InventoryItem.listing(category="leches")] == ["Leche de avena", "Leche entera"]
        assert len(InventoryItem.listing(category="inventada")) == 3        # categoría desconocida: sin filtro

    @pytest.mark.parametrize("query, expected", [("AVENA", ["Leche de avena"]), ("a-1", ["Café molido"]), ("leche", ["Leche de avena", "Leche entera"]), ("zzz", []), ("%", []), ("_", [])])
    def test_listing_search_by_name_or_sku(self, stock_room, query, expected):
        assert [i.name for i in InventoryItem.listing(query=query)] == expected

    def test_category_counts(self, stock_room):
        assert InventoryItem.category_counts() == {"cafe": 1, "leches": 2}

    def test_low_stock_is_ordered_by_severity_and_skips_inactive(self, stock_room, item_factory):
        item_factory("Vasos", "empaques", "uds", stock=90, min_stock=100, sku="C-1")   # 90 %
        assert [i.name for i in InventoryItem.low_stock()] == ["Leche de avena", "Vasos"]

    def test_kpis(self, stock_room):
        kpis = InventoryItem.kpis()
        assert kpis == {"total_value_cents": 0, "count": 3, "ok_count": 2, "low_count": 1, "critical_count": 1}

    def test_kpis_value_uses_last_cost(self, coffee_item, milk_item):
        # 10 kg * $28.50 + 24 briks * $2.10
        assert InventoryItem.kpis()["total_value_cents"] == 28500 + 5040

    def test_kpis_empty(self, app):
        assert InventoryItem.kpis() == {"total_value_cents": 0, "count": 0, "ok_count": 0, "low_count": 0, "critical_count": 0}

    def test_restock_suggestions(self, item_factory):
        item_factory("Avena", "leches", "briks", stock=4, min_stock=10, unit_cost_cents=210)   # 40 % del mínimo
        item_factory("Café", "cafe", "kg", stock=1, min_stock=2, unit_cost_cents=2850)         # 50 %
        item_factory("Sobrado", "cafe", "kg", stock=50, min_stock=2)
        suggestions = InventoryItem.restock_suggestions()
        assert [(s["item"].name, s["qty"], s["cost_cents"]) for s in suggestions] == [("Avena", 16, 3360), ("Café", 3.0, 8550)]


class TestCreate:
    def test_minimal_item_gets_an_automatic_sku(self, app):
        item = InventoryItem.create("Leche de coco", "leches", "L", 4, 220)
        assert (item.sku, item.stock, item.min_stock, item.unit_cost_cents, item.supplier, item.is_active) == ("MOK-LK-01", 0, 4, 220, None, True)
        assert db.session.scalar(select(LedgerEntry.id)) is None            # sin stock inicial no hay compra

    @pytest.mark.parametrize("category, prefix", [("cafe", "CF"), ("leches", "LK"), ("obrador", "OB"), ("empaques", "PKG")])
    def test_sku_prefix_by_category(self, app, category, prefix):
        assert InventoryItem.create("Algo", category, "kg", 1, 100).sku == f"MOK-{prefix}-01"

    def test_automatic_skus_never_collide(self, item_factory):
        item_factory(sku="MOK-CF-02")                       # ocupa el hueco que tocaría
        item_factory(sku="MOK-CF-01", category="obrador")   # otra categoría: no cuenta
        assert InventoryItem.create("Café A", "cafe", "kg", 1, 100).sku == "MOK-CF-03"

    def test_explicit_sku_is_normalized(self, app):
        assert InventoryItem.create("Algo", "cafe", "kg", 1, 100, sku="  mok-x-9 ").sku == "MOK-X-9"

    def test_duplicate_sku_is_rejected(self, coffee_item):
        with pytest.raises(DomainError, match="MOK-CF-01"):
            InventoryItem.create("Otro café", "cafe", "kg", 1, 100, sku="mok-cf-01")

    def test_initial_stock_is_recorded_as_a_purchase(self, admin_user):
        item = InventoryItem.create("Leche de coco", "leches", "L", 4, 220, supplier=" Coco SA ", initial_stock=10, user=admin_user)
        assert (item.stock, item.supplier) == (10, "Coco SA")
        movement = item.movements[0]
        assert (movement.kind, movement.qty, movement.total_cost_cents, movement.user_id) == ("compra", 10, 2200, admin_user.id)
        assert LedgerEntry.summary()["invested"] == 2200

    @pytest.mark.parametrize(
        "kwargs, message",
        [
            ({"name": ""}, "nombre"),
            ({"name": "A"}, "nombre"),
            ({"category": "otra"}, "Categoría"),
            ({"unit": "libras"}, "Unidad"),
            ({"min_stock": -1}, "negativas"),
            ({"unit_cost_cents": -1}, "negativas"),
            ({"initial_stock": -1}, "negativas"),
        ],
    )
    def test_validation(self, app, kwargs, message):
        args = {"name": "Leche", "category": "leches", "unit": "L", "min_stock": 1, "unit_cost_cents": 100, **kwargs}
        with pytest.raises(DomainError, match=message):
            InventoryItem.create(**args)
        assert db.session.scalar(select(InventoryItem.id)) is None

    def test_catalogs_are_consistent(self):
        assert set(UNITS) == {"kg", "L", "briks", "uds"}
        assert set(CATEGORIES) == {"cafe", "leches", "obrador", "empaques"}


class TestUpdateDetails:
    def test_updates_descriptive_fields_but_not_stock_or_unit(self, coffee_item):
        coffee_item.update_details("  Café Huila ", "obrador", 3, 3100, " Finca Sur ")
        item = reload_item(coffee_item)
        assert (item.name, item.category, item.min_stock, item.unit_cost_cents, item.supplier) == ("Café Huila", "obrador", 3, 3100, "Finca Sur")
        assert (item.stock, item.unit, item.sku) == (10, "kg", "MOK-CF-01")

    def test_blank_supplier_becomes_none(self, coffee_item):
        coffee_item.update_details("Café", "cafe", 2, 2850, "  ")
        assert reload_item(coffee_item).supplier is None

    @pytest.mark.parametrize("args, message", [(("", "cafe", 1, 1, None), "nombre"), (("Café", "otra", 1, 1, None), "Categoría"), (("Café", "cafe", -1, 1, None), "negativas"), (("Café", "cafe", 1, -1, None), "negativas")])
    def test_validation_keeps_the_previous_values(self, coffee_item, args, message):
        with pytest.raises(DomainError, match=message):
            coffee_item.update_details(*args)
        assert reload_item(coffee_item).name == "Café en Grano Etiopía"


class TestPurchase:
    def test_raises_stock_updates_cost_and_records_movement_and_expense(self, coffee_item, admin_user):
        movement = coffee_item.purchase(5, 2900, supplier="Proveedor X", user=admin_user)
        item = reload_item(coffee_item)
        assert (item.stock, item.unit_cost_cents, item.supplier) == (15, 2900, "Proveedor X")
        assert (movement.kind, movement.qty, movement.stock_after) == ("compra", 5, 15)
        assert (movement.unit_cost_cents, movement.total_cost_cents, movement.reference, movement.user_id) == (2900, 14500, "Proveedor X", admin_user.id)
        entry = db.session.scalar(select(LedgerEntry).where(LedgerEntry.movement_id == movement.id))
        assert (entry.kind, entry.concept, entry.amount_cents, entry.party) == ("egreso", "compra_inventario", 14500, "Proveedor X")
        assert entry.description == "Compra: Café en Grano Etiopía (5 kg)"

    def test_keeps_the_known_supplier_when_none_is_given(self, coffee_item):
        coffee_item.purchase(1, 2900)
        assert reload_item(coffee_item).supplier == "Importadora Cafés del Valle"

    def test_float_quantities_do_not_accumulate_error(self, item_factory):
        item = item_factory(stock=0.1)
        item.purchase(0.2, 100)
        assert reload_item(item).stock == 0.3

    def test_zero_cost_is_allowed(self, coffee_item):
        movement = coffee_item.purchase(1, 0)
        assert movement.total_cost_cents == 0

    @pytest.mark.parametrize("qty, cost", [(0, 100), (-1, 100), (1, -1)])
    def test_invalid_purchase_changes_nothing(self, coffee_item, qty, cost):
        with pytest.raises(DomainError):
            coffee_item.purchase(qty, cost)
        assert reload_item(coffee_item).stock == 10
        assert db.session.scalar(select(InventoryMovement.id)) is None
        assert db.session.scalar(select(LedgerEntry.id)) is None


class TestAdjust:
    def test_count_correction(self, coffee_item, admin_user):
        movement = coffee_item.adjust(8, kind=MOV_ADJUSTMENT, note="Conteo del cierre", user=admin_user)
        assert reload_item(coffee_item).stock == 8
        assert (movement.kind, movement.qty, movement.stock_after, movement.reference) == ("ajuste", -2, 8, "Conteo del cierre")
        assert db.session.scalar(select(LedgerEntry.id)) is None            # ajustar no toca la cartera

    def test_count_can_raise_stock(self, coffee_item):
        assert coffee_item.adjust(12.5).qty == 2.5

    def test_waste_lowers_stock(self, coffee_item):
        movement = coffee_item.adjust(9.5, kind=MOV_WASTE, note="Derrame")
        assert (movement.kind, movement.qty) == ("merma", -0.5)

    def test_long_notes_are_truncated(self, coffee_item):
        assert len(coffee_item.adjust(8, note="x" * 400).reference) == 160

    @pytest.mark.parametrize(
        "kwargs, message",
        [({"new_stock": -1}, "negativo"), ({"new_stock": 10}, "igual"), ({"new_stock": 5, "kind": "regalo"}, "no válido"), ({"new_stock": 15, "kind": MOV_WASTE}, "sólo puede reducir")],
    )
    def test_validation(self, coffee_item, kwargs, message):
        with pytest.raises(DomainError, match=message):
            coffee_item.adjust(**kwargs)
        assert reload_item(coffee_item).stock == 10


class TestConsumption:
    def test_check_available_accepts_enough_stock(self, coffee_item, milk_item):
        InventoryItem.check_available({coffee_item.id: 10, milk_item.id: 24})    # justo lo que hay
        InventoryItem.check_available({})

    def test_check_available_ignores_unknown_items(self, coffee_item):
        InventoryItem.check_available({coffee_item.id: 1, 99999: 5})

    def test_check_available_lists_every_shortage(self, coffee_item, milk_item):
        with pytest.raises(InsufficientStock) as info:
            InventoryItem.check_available({coffee_item.id: 12, milk_item.id: 30})
        assert sorted(s[0] for s in info.value.shortages) == ["Café en Grano Etiopía", "Leche de Avena Barista"]
        assert (coffee_item.name, 12, 10, "kg") in info.value.shortages

    def test_consume_lowers_stock_and_logs_negative_movements(self, coffee_item, milk_item, barista_user):
        InventoryItem.consume({coffee_item.id: 0.018, milk_item.id: 0.25}, reference="MK-8001", user=barista_user)
        db.session.commit()
        assert reload_item(coffee_item).stock == 9.982
        assert reload_item(milk_item).stock == 23.75
        moves = {m.item_id: m for m in db.session.scalars(select(InventoryMovement))}
        assert (moves[coffee_item.id].kind, moves[coffee_item.id].qty, moves[coffee_item.id].reference) == ("consumo", -0.018, "MK-8001")
        assert moves[coffee_item.id].user_id == barista_user.id
        assert moves[milk_item.id].stock_after == 23.75

    def test_consume_never_goes_below_zero(self, coffee_item):
        InventoryItem.consume({coffee_item.id: 15})
        db.session.commit()
        assert reload_item(coffee_item).stock == 0

    def test_consume_skips_unknown_items_and_non_positive_amounts(self, coffee_item):
        InventoryItem.consume({99999: 1, coffee_item.id: 0})
        db.session.commit()
        assert reload_item(coffee_item).stock == 10
        assert db.session.scalar(select(InventoryMovement.id)) is None
