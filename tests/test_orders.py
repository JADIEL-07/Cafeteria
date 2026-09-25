"""Ciclo de vida del pedido: pago, aceptación, inventario, cartera y cancelaciones."""
import pytest
from sqlalchemy import select

from app.extensions import db
from app.models import InventoryItem, LedgerEntry, Modifier, Order, OrderStateError, User
from app.models.base import InsufficientStock

from .conftest import ADMIN, BARISTA, CLIENT, OTHER, add_to_cart, login


def item(sku):
    db.session.expire_all()
    return db.session.scalar(select(InventoryItem).where(InventoryItem.sku == sku))


def user(credentials):
    db.session.expire_all()
    return User.get_by_email(credentials[0])


def checkout(client, payment="tarjeta", cart=True, **extra):
    """Carrito estándar (caramel + 2 croissants + cupón) y checkout. Devuelve el pedido."""
    if cart:
        add_to_cart(client, "caramel-macchiato-insignia")
        add_to_cart(client, "croissant-de-almendras", qty=2)
        client.post("/carrito/cupon", data={"code": "CAFELOVER"})
    response = client.post("/checkout", data={"payment": payment, **extra})
    assert response.status_code == 302, response.get_data(as_text=True)[:400]
    db.session.expire_all()
    return db.session.scalar(select(Order).order_by(Order.id.desc()))


def test_checkout_requires_login(client):
    add_to_cart(client, "croissant-de-almendras")
    response = client.post("/checkout", data={"payment": "tarjeta"})
    assert response.status_code == 302 and "/login" in response.headers["Location"]
    assert db.session.scalar(select(Order.id)) is None


def test_card_order_is_paid_immediately(client, stocked):
    login(client, CLIENT)
    order = checkout(client, "tarjeta")
    assert order.code == f"MK-{8000 + order.id}"
    assert (order.subtotal_cents, order.discount_cents, order.tax_cents, order.total_cents) == (1380, 200, 89, 1269)
    assert order.payment_status == "pagado" and order.status == "nuevo"
    assert order.fee_cents == 30                      # 2.4 % de 12.69
    assert order.beans_earned == 12
    assert user(CLIENT).beans == 12
    assert [i.qty for i in order.items] == [1, 2]
    assert order.items[0].options_text.startswith("Mediano")
    # cartera: una venta con su comisión
    sale = db.session.scalar(select(LedgerEntry).where(LedgerEntry.concept == "venta"))
    assert (sale.kind, sale.amount_cents, sale.fee_cents, sale.method) == ("ingreso", 1269, 30, "tarjeta")
    # el carrito se vacía y se registra el cupón usado
    with client.session_transaction() as sess:
        assert "cart" not in sess


def app_client_for(client, credentials):
    """Segundo cliente HTTP (otra sesión) autenticado con otras credenciales."""
    other = client.application.test_client()
    login(other, credentials)
    return other


def test_cash_order_is_locked_until_payment_is_confirmed(client, stocked):
    login(client, CLIENT)
    order = checkout(client, "efectivo")
    assert order.payment_status == "pendiente" and order.stage == "pending_payment"
    assert order.fee_cents == 0 and user(CLIENT).beans == 0
    assert db.session.scalar(select(LedgerEntry).where(LedgerEntry.concept == "venta")) is None

    # La barista intenta aceptar sin cobro -> bloqueado (regla de negocio), en el modelo y en el panel
    coffee_before = item("MOK-CF-01").stock
    with pytest.raises(OrderStateError):
        order.accept(user(BARISTA))
    staff = app_client_for(client, BARISTA)
    response = staff.post(f"/admin/pedidos/{order.id}/aceptar", follow_redirects=True)
    assert "Bloqueado" in response.get_data(as_text=True)
    db.session.expire_all()
    assert db.session.get(Order, order.id).status == "nuevo"
    assert item("MOK-CF-01").stock == coffee_before   # nada se descontó

    # Se valida el cobro en barra y ahora sí se puede aceptar
    staff.post(f"/admin/pedidos/{order.id}/validar-pago")
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert order.payment_status == "pagado" and order.transaction_ref.startswith("EF-")
    assert user(CLIENT).beans == 12
    sale = db.session.scalar(select(LedgerEntry).where(LedgerEntry.concept == "venta"))
    assert (sale.method, sale.fee_cents, sale.amount_cents) == ("efectivo", 0, 1269)
    # validar dos veces (doble clic) no duplica el ingreso
    staff.post(f"/admin/pedidos/{order.id}/validar-pago")
    assert len(db.session.scalars(select(LedgerEntry).where(LedgerEntry.concept == "venta")).all()) == 1
    assert user(CLIENT).beans == 12
    staff.post(f"/admin/pedidos/{order.id}/aceptar")
    db.session.expire_all()
    assert db.session.get(Order, order.id).status == "en_barra"


def test_accept_consumes_inventory_once(client, stocked):
    login(client, CLIENT)
    order = checkout(client, "tarjeta")
    before = {sku: item(sku).stock for sku in ("MOK-CF-01", "MOK-OB-06", "MOK-PKG-01", "MOK-LK-01", "MOK-OB-01", "MOK-OB-02", "MOK-OB-04")}
    barista = user(BARISTA)
    order.accept(barista)
    after = {sku: item(sku).stock for sku in before}
    used = {sku: round(before[sku] - after[sku], 3) for sku in before}
    assert used == {
        "MOK-CF-01": 0.018,   # espresso del macchiato
        "MOK-OB-06": 0.03,    # caramelo
        "MOK-PKG-01": 1,      # vaso
        "MOK-LK-01": 0.25,    # leche de avena (opción por defecto)
        "MOK-OB-01": 0.1,     # mantequilla: 2 croissants
        "MOK-OB-02": 0.12,    # harina
        "MOK-OB-04": 0.02,    # almendra
    }
    assert order.status == "en_barra" and order.accepted_by_id == barista.id
    # aceptar por segunda vez (doble clic) no vuelve a descontar
    with pytest.raises(OrderStateError):
        order.accept(barista)
    assert {sku: item(sku).stock for sku in before} == after


def test_chosen_milk_and_extras_consume_their_own_inputs(client, stocked):
    login(client, CLIENT)
    almond = db.session.scalar(select(Modifier).where(Modifier.name == "Almendras Tostadas"))
    shot = db.session.scalar(select(Modifier).where(Modifier.name == "Shot Extra de Espresso"))
    add_to_cart(client, "flat-white-doble-origen", milk=almond.id, extras=[shot.id])
    order = checkout(client, "tarjeta", cart=False)
    order.accept(user(BARISTA))
    assert item("MOK-LK-02").stock == pytest.approx(100 - 0.25)      # leche de almendras
    assert item("MOK-LK-01").stock == 100                              # la de avena no se toca
    assert item("MOK-CF-01").stock == pytest.approx(100 - 0.018 * 2)   # espresso base + shot extra


def test_insufficient_stock_blocks_acceptance_and_changes_nothing(client):
    """Sin compras de inventario el stock es 0: no se puede aceptar."""
    login(client, CLIENT)
    order = checkout(client, "tarjeta")
    with pytest.raises(InsufficientStock) as info:
        order.accept(user(BARISTA))
    assert "Inventario insuficiente" in str(info.value)
    db.session.expire_all()
    assert db.session.get(Order, order.id).status == "nuevo"
    assert db.session.scalar(select(LedgerEntry).where(LedgerEntry.concept == "venta")) is not None


def test_full_lifecycle_through_the_panel(client, stocked):
    login(client, CLIENT)
    order = checkout(client, "tarjeta")
    staff = app_client_for(client, BARISTA)
    staff.post(f"/admin/pedidos/{order.id}/aceptar")
    staff.post(f"/admin/pedidos/{order.id}/entregar")            # no se puede saltar "listo"
    db.session.expire_all()
    assert db.session.get(Order, order.id).status == "en_barra"
    staff.post(f"/admin/pedidos/{order.id}/listo")
    staff.post(f"/admin/pedidos/{order.id}/entregar")
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert order.status == "entregado" and order.stage == "delivered"
    assert [label for label, _, _ in order.events][0] == "Pedido recibido"
    # el cliente ve su pedido
    html = client.get(f"/pedidos/{order.code}").get_data(as_text=True)
    assert order.code in html and "ENTREGADO" in html


def test_cancel_unpaid_order_has_no_money_movement(client, stocked):
    login(client, CLIENT)
    order = checkout(client, "efectivo")
    client.post(f"/pedidos/{order.code}/cancelar")
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert order.status == "cancelado" and order.payment_status == "pendiente"
    assert db.session.scalar(select(LedgerEntry).where(LedgerEntry.concept.in_(("venta", "reembolso")))) is None


def test_cancel_paid_order_refunds_and_reverses_beans(client, stocked):
    login(client, CLIENT)
    order = checkout(client, "tarjeta")
    assert user(CLIENT).beans == 12
    client.post(f"/pedidos/{order.code}/cancelar")
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert order.status == "cancelado" and order.payment_status == "reembolsado"
    assert user(CLIENT).beans == 0
    refund = db.session.scalar(select(LedgerEntry).where(LedgerEntry.concept == "reembolso"))
    assert (refund.kind, refund.amount_cents, refund.method) == ("egreso", 1269, "tarjeta")
    summary = LedgerEntry.summary()
    # la comisión de la pasarela no se recupera: lo "recuperado" queda en -30
    assert summary["gross_sales"] == 1269 and summary["refunds"] == 1269 and summary["recovered"] == -30


def test_cannot_cancel_after_acceptance(client, stocked):
    login(client, CLIENT)
    order = checkout(client, "tarjeta")
    order.accept(user(BARISTA))
    client.post(f"/pedidos/{order.code}/cancelar")
    db.session.expire_all()
    assert db.session.get(Order, order.id).status == "en_barra"
    with pytest.raises(OrderStateError):
        db.session.get(Order, order.id).cancel()


def test_orders_are_private(client, stocked):
    login(client, CLIENT)
    order = checkout(client, "tarjeta")
    intruder = app_client_for(client, OTHER)
    assert intruder.get(f"/pedidos/{order.code}").status_code == 404
    assert intruder.get(f"/pedidos/{order.code}/estado").status_code == 404
    assert intruder.post(f"/pedidos/{order.code}/cancelar").status_code == 404
    assert client.get(f"/pedidos/{order.code}").status_code == 200
    assert app_client_for(client, BARISTA).get(f"/pedidos/{order.code}").status_code == 200
    guest = client.application.test_client()
    assert guest.get(f"/pedidos/{order.code}").status_code == 302


def test_table_service_requires_table_number(client, stocked):
    login(client, CLIENT)
    add_to_cart(client, "croissant-de-almendras")
    client.post("/carrito/modo", data={"mode": "mesa"})
    response = client.post("/checkout", data={"payment": "tarjeta"}, follow_redirects=True)
    assert "número de mesa" in response.get_data(as_text=True)
    assert db.session.scalar(select(Order.id)) is None
    order = checkout(client, "tarjeta", cart=False, table="7")
    assert order.fulfillment == "mesa" and order.table_number == "7"
    assert order.fulfillment_label == "Servir en mesa · Mesa 7"


def test_invalid_payment_method_and_empty_cart(client):
    login(client, CLIENT)
    response = client.post("/checkout", data={"payment": "tarjeta"}, follow_redirects=True)
    assert "carrito está vacío" in response.get_data(as_text=True)
    add_to_cart(client, "croissant-de-almendras")
    response = client.post("/checkout", data={"payment": "bitcoin"}, follow_redirects=True)
    assert "método de pago" in response.get_data(as_text=True)
    assert db.session.scalar(select(Order.id)) is None


def test_arrival_notification_and_notes(client, stocked):
    login(client, CLIENT)
    order = checkout(client, "efectivo", notes="Sin azúcar")
    assert order.notes == "Sin azúcar"
    client.post(f"/pedidos/{order.code}/llegue")
    client.post(f"/pedidos/{order.code}/notas", data={"notes": "Poco hielo"})
    db.session.expire_all()
    order = db.session.get(Order, order.id)
    assert order.arrived_at is not None and order.notes == "Poco hielo"
    order.cancel()
    with pytest.raises(OrderStateError):
        order.update_notes("tarde")


def test_status_json_and_estimated_wait(client, stocked):
    login(client, CLIENT)
    order = checkout(client, "tarjeta")
    data = client.get(f"/pedidos/{order.code}/estado").get_json()
    assert data["stage"] == "paid" and data["label"] == "PAGO CONFIRMADO"
    low, high = Order.estimated_wait()
    assert (low, high) == (7, 11)         # 1 pedido en cola: 5 + 2*1
    order.accept(user(BARISTA))
    assert client.get(f"/pedidos/{order.code}/estado").get_json()["stage"] == "in_bar"


def test_board_filters_and_counts(client, stocked):
    login(client, CLIENT)
    cash = checkout(client, "efectivo")
    paid = checkout(client, "tarjeta")
    counts = Order.filter_counts()
    assert counts["pendiente"] == 1 and counts["pagado"] == 1 and counts["activas"] == 2
    assert Order.pending_payments() == (1, cash.total_cents)
    board = Order.board("pendiente")
    assert [o.id for o in board.items] == [cash.id]
    assert [o.id for o in Order.board("pagado").items] == [paid.id]
    assert [o.id for o in Order.board("todas", query=cash.code).items] == [cash.id]
    assert [o.id for o in Order.board("todas", query="Cliente Test").items] == [paid.id, cash.id]
    assert Order.board("todas", query="%").items == []          # los comodines se escapan


def test_admin_can_operate_the_board(client, stocked):
    """El administrador (no sólo el barista) puede operar la pizarra."""
    login(client, CLIENT)
    order = checkout(client, "tarjeta")
    admin = app_client_for(client, ADMIN)
    assert admin.get("/admin/pedidos").status_code == 200
    admin.post(f"/admin/pedidos/{order.id}/aceptar")
    db.session.expire_all()
    assert db.session.get(Order, order.id).accepted_by.email == ADMIN[0]
