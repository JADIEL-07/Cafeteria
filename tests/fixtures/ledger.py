"""Fixtures de LedgerEntry (cartera)."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.extensions import db
from app.models import LedgerEntry

DAY = datetime(2026, 3, 10)


@pytest.fixture()
def ledger_factory(app):
    def make(
        kind="ingreso",
        concept="venta",
        amount_cents=1000,
        fee_cents=0,
        method="efectivo",
        party="Cliente",
        description="Movimiento de prueba",
        created_at=DAY + timedelta(hours=12),
        **fields,
    ):
        entry = LedgerEntry(
            kind=kind, concept=concept, amount_cents=amount_cents, fee_cents=fee_cents, method=method,
            party=party, description=description, created_at=created_at, **fields,
        )
        db.session.add(entry)
        db.session.commit()
        return entry

    return make


@pytest.fixture()
def sale_entry(ledger_factory):
    """Venta con tarjeta de $10.00 y comisión de $0.24."""
    return ledger_factory("ingreso", "venta", 1000, fee_cents=24, method="tarjeta")


@pytest.fixture()
def refund_entry(ledger_factory):
    return ledger_factory("egreso", "reembolso", 1000, method="tarjeta")


@pytest.fixture()
def purchase_entry(ledger_factory):
    return ledger_factory("egreso", "compra_inventario", 5000, method=None, party="Proveedor X")


@pytest.fixture()
def adjustment_in_entry(ledger_factory):
    return ledger_factory("ingreso", "ajuste", 300, method="efectivo")


@pytest.fixture()
def adjustment_out_entry(ledger_factory):
    return ledger_factory("egreso", "ajuste", 200, method="tarjeta")


def _at(hour, minute=0):
    return DAY + timedelta(hours=hour, minutes=minute)


@pytest.fixture()
def ledger_dataset(ledger_factory):
    """Un día completo de movimientos con totales conocidos (ver ``expected``).

    Periodo ``[start, end)`` = 10-mar-2026. Además hay una venta el día anterior y otra a las 00:00 del día
    siguiente que NO deben contarse (el fin del periodo es exclusivo).
    """
    ledger_factory("ingreso", "venta", 1000, fee_cents=24, method="tarjeta", created_at=_at(6, 30))
    ledger_factory("ingreso", "venta", 2000, fee_cents=48, method="tarjeta", created_at=_at(9, 15))
    ledger_factory("ingreso", "venta", 1500, method="efectivo", created_at=_at(9, 45))
    ledger_factory("ingreso", "venta", 500, method="efectivo", created_at=_at(21, 59))
    ledger_factory("egreso", "reembolso", 1000, method="tarjeta", created_at=_at(10))
    ledger_factory("egreso", "reembolso", 500, method="efectivo", created_at=_at(12))
    ledger_factory("egreso", "compra_inventario", 3000, method=None, created_at=_at(8))
    ledger_factory("egreso", "compra_inventario", 1000, method=None, created_at=_at(8, 30))
    ledger_factory("ingreso", "ajuste", 300, method="efectivo", created_at=_at(13))
    ledger_factory("egreso", "ajuste", 200, method="tarjeta", created_at=_at(14))
    ledger_factory("ingreso", "venta", 9999, method="efectivo", created_at=DAY - timedelta(hours=12))  # día anterior
    ledger_factory("ingreso", "venta", 7777, method="efectivo", created_at=DAY + timedelta(days=1))    # 00:00 del siguiente
    return SimpleNamespace(
        start=DAY,
        end=DAY + timedelta(days=1),
        expected={
            "gross_sales": 5000, "fees": 72, "refunds": 1500, "invested": 4000, "adjustments": 100,
            "recovered": 3428, "profit": -472, "sales_count": 4, "purchases_count": 2,
            "recovery_pct": 85.7, "margin_pct": -13.8,
            "tarjeta_net": 1728, "tarjeta_sales": 3000, "efectivo_net": 1800, "efectivo_sales": 2000,
        },
    )
