from sqlalchemy import select

from app.extensions import db
from app.models import Cart, Modifier

from tests.helpers import CLIENT, add_to_cart, login, product_id


def summary_from(client):
    """Valoriza el carrito guardado en la sesión del cliente de pruebas."""
    with client.session_transaction() as sess:
        return Cart(store=dict(sess)).summary()


def modifier(name):
    return db.session.scalar(select(Modifier).where(Modifier.name == name))


def test_default_options_price(client):
    add_to_cart(client, "caramel-macchiato-insignia")
    s = summary_from(client)
    line = s.lines[0]
    # base 4.80 + Mediano 0.50 + Avena 0.60
    assert line.unit_cents == 590
    assert line.options_text == "Mediano • Caliente • Leche de Avena Barista • Normal (100%)"
    assert s.total_cents == 590 + s.tax_cents


def test_prices_are_computed_on_the_server(client):
    """El cliente no puede mandar precios: los campos extra se ignoran."""
    add_to_cart(client, "croissant-de-almendras", price="1", unit_cents="1", total="1")
    assert summary_from(client).subtotal_cents == 395


def test_extras_and_size_change_the_price(client):
    add_to_cart(
        client,
        "caramel-macchiato-insignia",
        size=modifier("Grande").id,
        milk=modifier("Almendras Tostadas").id,
        extras=[modifier("Shot Extra de Espresso").id, modifier("Nube de Crema Batida").id],
        qty=2,
    )
    s = summary_from(client)
    # 480 + 100 (grande) + 60 (almendras) + 90 + 50 = 780 por unidad
    assert s.lines[0].unit_cents == 780
    assert s.lines[0].qty == 2
    assert s.subtotal_cents == 1560


def test_invalid_option_is_rejected(client):
    milk = db.session.scalar(select(Modifier).where(Modifier.group == "milk"))
    add_to_cart(client, "caramel-macchiato-insignia", size=milk.id)   # opción de otro grupo
    add_to_cart(client, "caramel-macchiato-insignia", size=99999)     # inexistente
    add_to_cart(client, "caramel-macchiato-insignia", size="drop table")
    add_to_cart(client, "caramel-macchiato-insignia", extras="abc")
    assert summary_from(client).is_empty


def test_unknown_product_is_rejected(client):
    response = client.post("/carrito/agregar", data={"product_id": 424242})
    assert response.status_code == 302
    assert summary_from(client).is_empty


def test_options_ignored_for_products_without_them(client):
    add_to_cart(client, "croissant-de-almendras", extras=[modifier("Shot Extra de Espresso").id])
    s = summary_from(client)
    assert s.lines[0].unit_cents == 395
    assert s.lines[0].modifiers == []


def test_same_line_merges_and_qty_is_capped(client):
    for _ in range(3):
        add_to_cart(client, "croissant-de-almendras", qty=10)
    s = summary_from(client)
    assert len(s.lines) == 1
    assert s.lines[0].qty == 20  # tope por línea


def test_quantity_controls_and_remove(client):
    add_to_cart(client, "croissant-de-almendras")
    key = summary_from(client).lines[0].key
    client.post(f"/carrito/{key}/cantidad", data={"action": "inc"})
    client.post(f"/carrito/{key}/cantidad", data={"action": "inc"})
    assert summary_from(client).lines[0].qty == 3
    for _ in range(3):
        client.post(f"/carrito/{key}/cantidad", data={"action": "dec"})  # nunca baja de 1
    assert summary_from(client).lines[0].qty == 1
    client.post(f"/carrito/{key}/eliminar")
    assert summary_from(client).is_empty


def test_coupon_and_tax_math(client):
    add_to_cart(client, "caramel-macchiato-insignia")            # 590
    add_to_cart(client, "croissant-de-almendras", qty=2)         # 790
    client.post("/carrito/cupon", data={"code": "cafelover"})    # -200 (no distingue mayúsculas)
    s = summary_from(client)
    assert s.subtotal_cents == 1380
    assert s.discount_cents == 200
    assert s.tax_cents == 89                    # 7.5 % de 1180 = 88.5 -> 89
    assert s.total_cents == 1269
    assert s.beans_estimate == 12


def test_unknown_or_unmet_coupon(client):
    add_to_cart(client, "shot-extra-espresso")                   # $0.90 (< mínimo del cupón)
    client.post("/carrito/cupon", data={"code": "NOEXISTE"})
    assert summary_from(client).coupon is None
    client.post("/carrito/cupon", data={"code": "CAFELOVER"})
    assert summary_from(client).coupon is None


def test_coupon_is_dropped_if_subtotal_falls_below_minimum(client):
    add_to_cart(client, "caramel-macchiato-insignia")
    client.post("/carrito/cupon", data={"code": "CAFELOVER"})
    assert summary_from(client).discount_cents == 200
    key = summary_from(client).lines[0].key
    client.post(f"/carrito/{key}/eliminar")
    add_to_cart(client, "shot-extra-espresso")
    s = summary_from(client)
    assert s.discount_cents == 0 and s.coupon is None and s.coupon_error


def test_cart_page_shows_totals(client):
    add_to_cart(client, "croissant-de-almendras", qty=2)
    html = client.get("/carrito").get_data(as_text=True)
    assert "Croissant de Almendras" in html
    assert "$7.90" in html               # subtotal
    assert "$8.49" in html               # 790 + 59 de IVA


def test_empty_cart_and_delivery_mode(client):
    assert "Tu carrito está vacío" in client.get("/carrito").get_data(as_text=True)
    client.post("/carrito/modo", data={"mode": "mesa", "table": "4"})
    with client.session_transaction() as sess:
        assert sess["cart"]["mode"] == "mesa" and sess["cart"]["table"] == "4"
    client.post("/carrito/modo", data={"mode": "hackeado"})
    with client.session_transaction() as sess:
        assert sess["cart"]["mode"] == "mesa"
    client.post("/carrito/modo", data={"mode": "barra", "table": "9"})
    with client.session_transaction() as sess:
        assert sess["cart"]["mode"] == "barra" and sess["cart"]["table"] == ""


def test_add_via_ajax_returns_json(client):
    pid = product_id("croissant-de-almendras")
    response = client.post("/carrito/agregar", data={"product_id": pid, "qty": 2}, headers={"X-Requested-With": "fetch"})
    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "message": "Croissant de Almendras se añadió a tu carrito.", "count": 2}
    bad = client.post("/carrito/agregar", data={"product_id": 999}, headers={"X-Requested-With": "fetch"})
    assert bad.status_code == 400 and bad.get_json()["ok"] is False


def test_cart_survives_login(client):
    add_to_cart(client, "croissant-de-almendras")
    login(client, CLIENT)
    assert summary_from(client).count == 1
