"""Fixtures de InventoryItem e InventoryMovement."""
import itertools

import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import InventoryItem, InventoryMovement
from app.models.inventory import MOV_ADJUSTMENT, MOV_WASTE


@pytest.fixture()
def item_factory(app):
    """Crea un insumo directamente (sin movimiento ni egreso en la cartera): ideal para armar escenarios."""
    counter = itertools.count(1)

    def make(name=None, category="cafe", unit="kg", stock=0, min_stock=0, unit_cost_cents=0, supplier=None, sku=None, is_active=True):
        n = next(counter)
        item = InventoryItem(
            sku=sku or f"TST-{n:03d}",
            name=name or f"Insumo {n}",
            category=category,
            unit=unit,
            stock=stock,
            min_stock=min_stock,
            unit_cost_cents=unit_cost_cents,
            supplier=supplier,
            is_active=is_active,
        )
        db.session.add(item)
        db.session.commit()
        return item

    return make


@pytest.fixture()
def coffee_item(item_factory):
    return item_factory(
        "Café en Grano Etiopía", "cafe", "kg", stock=10, min_stock=2, unit_cost_cents=2850,
        supplier="Importadora Cafés del Valle", sku="MOK-CF-01",
    )


@pytest.fixture()
def milk_item(item_factory):
    """Contable (briks): sirve para probar redondeos a enteros."""
    return item_factory(
        "Leche de Avena Barista", "leches", "briks", stock=24, min_stock=10, unit_cost_cents=210,
        supplier="Distribuidora Oatly", sku="MOK-LK-01",
    )


@pytest.fixture()
def cup_item(item_factory):
    return item_factory("Vasos Compostables 12oz", "empaques", "uds", stock=500, min_stock=150, unit_cost_cents=9, sku="MOK-PKG-01")


@pytest.fixture()
def butter_item(item_factory):
    return item_factory("Mantequilla AOP Francesa", "obrador", "kg", stock=20, min_stock=4, unit_cost_cents=1420, sku="MOK-OB-01")


@pytest.fixture()
def warning_item(item_factory):
    """Bajo el mínimo pero sobre su mitad: estado "alerta"."""
    return item_factory("Crema para Batir", "leches", "L", stock=6, min_stock=8, unit_cost_cents=450)


@pytest.fixture()
def critical_item(item_factory):
    """En la mitad del mínimo o menos: estado "crítico"."""
    return item_factory("Chocolate Valrhona", "obrador", "kg", stock=1, min_stock=8, unit_cost_cents=2640)


@pytest.fixture()
def purchase_movement(coffee_item, admin_user):
    """Compra de 5 kg a $29.00/kg (proveedor "Proveedor X"): devuelve el InventoryMovement."""
    return coffee_item.purchase(5, 2900, supplier="Proveedor X", user=admin_user)


@pytest.fixture()
def adjustment_movement(coffee_item, admin_user):
    """Conteo físico: el stock baja de 10 a 8 kg."""
    return coffee_item.adjust(8, kind=MOV_ADJUSTMENT, note="Conteo del cierre", user=admin_user)


@pytest.fixture()
def waste_movement(coffee_item, admin_user):
    """Merma: descarta 0.5 kg respecto al stock que haya en ese momento."""
    return coffee_item.adjust(round(coffee_item.stock - 0.5, 3), kind=MOV_WASTE, note="Derrame", user=admin_user)


@pytest.fixture()
def consumption_movement(coffee_item):
    """Consumo por el pedido MK-8001: -0.5 kg."""
    InventoryItem.consume({coffee_item.id: 0.5}, reference="MK-8001")
    db.session.commit()
    return db.session.scalar(select(InventoryMovement).order_by(InventoryMovement.id.desc()))
