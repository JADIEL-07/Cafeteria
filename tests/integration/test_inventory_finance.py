"""Inventario y cartera: compras (egresos), ajustes, ganancias y exportación."""
import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import DomainError, InventoryItem, InventoryMovement, LedgerEntry, Order, User
from app.models.inventory import MOV_ADJUSTMENT, MOV_WASTE
from app.utils.timefmt import period_range

from tests.helpers import ADMIN, BARISTA, CLIENT, add_to_cart, login


def item(sku):
    db.session.expire_all()
    return db.session.scalar(select(InventoryItem).where(InventoryItem.sku == sku))


def admin_user():
    return User.get_by_email(ADMIN[0])


def test_purchase_raises_stock_and_records_an_expense(app):
    coffee = item("MOK-CF-01")
    assert coffee.stock == 0
    movement = coffee.purchase(10, 2900, supplier="Proveedor X", user=admin_user())
    assert (movement.kind, movement.qty, movement.total_cost_cents, movement.stock_after) == ("compra", 10, 29000, 10)
    coffee = item("MOK-CF-01")
    assert coffee.stock == 10 and coffee.unit_cost_cents == 2900 and coffee.supplier == "Proveedor X"
    entry = db.session.scalar(select(LedgerEntry).where(LedgerEntry.concept == "compra_inventario"))
    assert (entry.kind, entry.amount_cents, entry.party) == ("egreso", 29000, "Proveedor X")
    assert LedgerEntry.summary()["invested"] == 29000


def test_purchase_validation(app):
    coffee = item("MOK-CF-01")
    with pytest.raises(DomainError):
        coffee.purchase(0, 100)
    with pytest.raises(DomainError):
        coffee.purchase(-3, 100)
    with pytest.raises(DomainError):
        coffee.purchase(1, -100)
    assert item("MOK-CF-01").stock == 0
    assert db.session.scalar(select(LedgerEntry.id)) is None


def test_adjustments_and_waste_do_not_touch_the_ledger(app):
    milk = item("MOK-LK-01")
    milk.purchase(24, 210, user=admin_user())
    invested = LedgerEntry.summary()["invested"]
    milk = item("MOK-LK-01")
    milk.adjust(20, kind=MOV_ADJUSTMENT, note="Conteo", user=admin_user())
    milk = item("MOK-LK-01")
    milk.adjust(18, kind=MOV_WASTE, note="Caducado", user=admin_user())
    milk = item("MOK-LK-01")
    assert milk.stock == 18
    kinds = [m.kind for m in db.session.scalars(select(InventoryMovement).order_by(InventoryMovement.id))]
    assert kinds == ["compra", "ajuste", "merma"]
    assert LedgerEntry.summary()["invested"] == invested
    with pytest.raises(DomainError):
        milk.adjust(18)              # sin cambios
    with pytest.raises(DomainError):
        milk.adjust(30, kind=MOV_WASTE)   # una merma no puede subir el stock
    with pytest.raises(DomainError):
        milk.adjust(-1)
    with pytest.raises(DomainError):
        milk.adjust(5, kind="regalo")


def test_status_thresholds_and_restock_suggestions(app):
    milk = item("MOK-LK-01")     # mínimo 10 briks
    milk.stock = 10
    assert milk.status == "optimo"
    milk.stock = 9
    assert milk.status == "alerta"
    milk.stock = 5
    assert milk.status == "critico"
    db.session.commit()
    milk.stock = 4
    db.session.commit()
    suggestions = {s["item"].sku: s for s in InventoryItem.restock_suggestions()}
    # todo lo demás está en 0 (crítico); la leche de avena necesita llegar a 2x mínimo = 20
    assert suggestions["MOK-LK-01"]["qty"] == 16
    assert suggestions["MOK-LK-01"]["cost_cents"] == 16 * 210
    coffee = suggestions["MOK-CF-01"]           # 2 kg mínimo -> 4 kg (pasos de 0.5)
    assert coffee["qty"] == 4
    assert InventoryItem.kpis()["low_count"] == len(suggestions)


def test_restock_endpoint_buys_selected_items(client, app):
    login(client, ADMIN)
    milk_id, coffee_id = item("MOK-LK-01").id, item("MOK-CF-01").id
    response = client.post("/admin/inventario/reabastecer", data={"item_id": [milk_id, coffee_id]}, follow_redirects=True)
    assert "2 compra(s) registradas" in response.get_data(as_text=True)
    assert item("MOK-LK-01").stock == 20 and item("MOK-CF-01").stock == 4
    assert LedgerEntry.summary()["invested"] == 20 * 210 + 4 * 2850
    # ya no hay que reponer esos dos
    again = client.post("/admin/inventario/reabastecer", data={"item_id": [milk_id]}, follow_redirects=True)
    assert "No hay insumos por reponer" in again.get_data(as_text=True)


def test_purchase_endpoint_and_bad_input(client, app):
    login(client, BARISTA)
    coffee_id = item("MOK-CF-01").id
    ok = client.post("/admin/inventario/compra", data={"item_id": coffee_id, "qty": "2,5", "unit_cost": "30.00", "supplier": "Café Sur"}, follow_redirects=True)
    assert "Compra registrada" in ok.get_data(as_text=True)
    coffee = item("MOK-CF-01")
    assert coffee.stock == 2.5 and coffee.unit_cost_cents == 3000
    assert LedgerEntry.summary()["invested"] == 7500
    for data in ({"qty": "abc", "unit_cost": "1"}, {"qty": "0", "unit_cost": "1"}, {"qty": "1", "unit_cost": "-4"}, {"qty": "1", "unit_cost": ""}):
        bad = client.post("/admin/inventario/compra", data={"item_id": coffee_id, **data}, follow_redirects=True)
        assert "Compra registrada" not in bad.get_data(as_text=True)
    assert item("MOK-CF-01").stock == 2.5
    missing = client.post("/admin/inventario/compra", data={"item_id": 9999, "qty": "1", "unit_cost": "1"}, follow_redirects=True)
    assert "no existe" in missing.get_data(as_text=True)


def test_create_and_edit_item(client, app):
    login(client, ADMIN)
    client.post("/admin/inventario/nuevo", data={"name": "Leche de coco", "category": "leches", "unit": "L", "min_stock": "4", "unit_cost": "2.20", "initial_stock": "10", "supplier": "Coco SA"})
    coco = db.session.scalar(select(InventoryItem).where(InventoryItem.name == "Leche de coco"))
    assert coco.sku.startswith("MOK-LK-") and coco.stock == 10 and coco.min_stock == 4
    assert LedgerEntry.summary()["invested"] == 2200          # el stock inicial es una compra
    dup = client.post("/admin/inventario/nuevo", data={"name": "Otra", "category": "leches", "unit": "L", "sku": coco.sku}, follow_redirects=True)
    assert "Ya existe un insumo con el SKU" in dup.get_data(as_text=True)
    client.post("/admin/inventario/editar", data={"item_id": coco.id, "name": "Leche de coco 1L", "category": "leches", "min_stock": "6", "unit_cost": "2.50", "supplier": ""})
    coco = item(coco.sku)
    assert (coco.name, coco.min_stock, coco.unit_cost_cents, coco.supplier) == ("Leche de coco 1L", 6, 250, None)
    assert coco.stock == 10 and coco.unit == "L"              # editar no cambia stock ni unidad


def test_manual_ledger_adjustments(client, app):
    login(client, ADMIN)
    client.post("/admin/cartera/ajuste", data={"kind": "egreso", "amount": "25.50", "description": "Faltante de caja", "method": "efectivo"})
    client.post("/admin/cartera/ajuste", data={"kind": "ingreso", "amount": "10", "description": "Propina", "method": "tarjeta"})
    bad = client.post("/admin/cartera/ajuste", data={"kind": "ingreso", "amount": "0", "description": "Nada"}, follow_redirects=True)
    assert "importe válido" in bad.get_data(as_text=True)
    short = client.post("/admin/cartera/ajuste", data={"kind": "ingreso", "amount": "5", "description": "x"}, follow_redirects=True)
    assert "motivo" in short.get_data(as_text=True)
    s = LedgerEntry.summary()
    assert s["adjustments"] == 1000 - 2550 and s["profit"] == 1000 - 2550
    start, end = period_range("hoy")
    drawer = LedgerEntry.cash_drawer(start, end)
    assert drawer["collected"] == -2550 and drawer["expected"] == 20000 - 2550


def test_profit_equals_recovered_minus_invested(client, app):
    """Escenario completo: compra de insumos + una venta con tarjeta y otra en efectivo."""
    admin = admin_user()
    item("MOK-CF-01").purchase(2, 2850, user=admin)     # $57.00
    item("MOK-OB-01").purchase(1, 1420, user=admin)     # $14.20
    login(client, CLIENT)
    add_to_cart(client, "croissant-de-almendras", qty=2)
    client.post("/checkout", data={"payment": "tarjeta"})          # 790 + 59 = 849 ; comisión 20
    add_to_cart(client, "croissant-de-almendras")
    client.post("/checkout", data={"payment": "efectivo"})         # 395 + 30 = 425
    db.session.expire_all()
    cash = db.session.scalar(select(Order).where(Order.payment_method == "efectivo"))
    card = db.session.scalar(select(Order).where(Order.payment_method == "tarjeta"))
    assert (card.total_cents, card.fee_cents, cash.total_cents) == (849, 20, 425)
    before_cash = LedgerEntry.summary()
    assert before_cash["gross_sales"] == 849 and before_cash["recovered"] == 829      # el efectivo aún no cuenta
    cash.confirm_payment()
    s = LedgerEntry.summary()
    assert s["invested"] == 5700 + 1420
    assert s["gross_sales"] == 849 + 425 and s["fees"] == 20
    assert s["recovered"] == 849 + 425 - 20
    assert s["profit"] == s["recovered"] - s["invested"]
    assert s["tarjeta_net"] == 829 and s["efectivo_net"] == 425
    assert s["recovery_pct"] == round(s["recovered"] * 100 / s["invested"], 1)


def test_pending_cash_orders_are_reported_but_not_counted(client, app):
    login(client, CLIENT)
    add_to_cart(client, "croissant-de-almendras")
    client.post("/checkout", data={"payment": "efectivo"})
    assert Order.pending_payments() == (1, 425)
    assert LedgerEntry.summary()["recovered"] == 0


def test_finance_page_and_filters(client, app):
    admin = admin_user()
    item("MOK-CF-01").purchase(1, 2850, user=admin)
    LedgerEntry.record_adjustment("ingreso", 500, "Propina", method="efectivo", user=admin)
    login(client, ADMIN)
    html = client.get("/admin/cartera/?periodo=todo").get_data(as_text=True)
    assert "$28.50" in html and "Compra: Café en Grano Etiopía Yirgacheffe" in html
    assert "Ajuste manual" in html
    only_sales = client.get("/admin/cartera/?periodo=todo&tipo=venta").get_data(as_text=True)
    assert "No hay movimientos con estos filtros" in only_sales
    assert client.get("/admin/cartera/?periodo=raro&metodo=raro&tipo=raro&page=abc").status_code == 200


def test_csv_export_blocks_formula_injection(client, app):
    admin = admin_user()
    admin.name = "=HYPERLINK(\"http://malo\")"
    db.session.commit()
    LedgerEntry.record_adjustment("ingreso", 100, "+cmd|' /C calc'!A0", method="efectivo", user=admin)
    login(client, ADMIN)
    response = client.get("/admin/cartera/exportar.csv?periodo=todo")
    assert response.mimetype == "text/csv"
    body = response.get_data(as_text=True)
    assert "'+cmd" in body and "'=HYPERLINK" in body
    assert ",+cmd" not in body and ",=HYPERLINK" not in body
    users = client.get("/admin/usuarios/exportar.csv").get_data(as_text=True)
    assert "'=HYPERLINK" in users
