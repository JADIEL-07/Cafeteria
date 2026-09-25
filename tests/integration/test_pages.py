"""Recorre todas las pantallas con datos demo: ninguna debe fallar al renderizar."""
import re

import pytest
from sqlalchemy import select

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import Order, Product

from tests.helpers import login

DEMO_ADMIN = ("admin@moka.com", "admin1234")
DEMO_CLIENT = ("elena@correo.com", "moka1234")


@pytest.fixture()
def demo_app():
    """Tienda con datos demo. Es de función (no de módulo): con PostgreSQL todas las apps comparten la misma base."""
    class DemoConfig(TestConfig):
        SEED_ON_FIRST_RUN = True
        DEMO_DATA = True

    application = create_app(DemoConfig)
    with application.app_context():
        yield application
        db.session.remove()
        db.engine.dispose()


def test_public_pages(demo_app):
    client = demo_app.test_client()
    slugs = [p.slug for p in db.session.scalars(select(Product))]
    urls = ["/", "/menu", "/menu?cat=cafe", "/menu?cat=panaderia&dieta=vegan&orden=precio_desc", "/menu?q=caramel", "/menu?q=zzzz",
            "/menu?orden=nuevo", "/menu?cat=inventado", "/carrito", "/login", "/login?tab=register"] + [f"/menu/{s}" for s in slugs]
    for url in urls:
        response = client.get(url, follow_redirects=True)
        assert response.status_code == 200, url
    html = client.get("/menu?q=zzzz").get_data(as_text=True)
    assert "No encontramos productos" in html
    catalog = client.get("/menu").get_data(as_text=True)
    assert "Caramel Macchiato Insignia" in catalog and "Bolsa Etiopía Yirgacheffe 250g" in catalog
    assert "Carta de Temporada" in catalog


def test_customer_pages_and_own_orders(demo_app):
    client = demo_app.test_client()
    login(client, DEMO_CLIENT)
    assert client.get("/perfil").status_code == 200
    assert client.get("/favoritos").status_code == 200
    orders = db.session.scalars(select(Order).join(Order.user).where(Order.user.has(email=DEMO_CLIENT[0]))).all()
    assert orders
    for order in orders[:6]:
        response = client.get(f"/pedidos/{order.code}")
        assert response.status_code == 200 and order.code in response.get_data(as_text=True)


def test_admin_pages_with_demo_data(demo_app):
    client = demo_app.test_client()
    login(client, DEMO_ADMIN)
    urls = ["/admin/pedidos"] + [f"/admin/pedidos?estado={e}" for e in ("activas", "pendiente", "pagado", "en_barra", "listo", "cerrados", "todas")]
    urls += ["/admin/pedidos?q=elena", "/admin/pedidos?estado=cerrados&page=3", "/admin/inventario/", "/admin/inventario/?cat=obrador",
             "/admin/cartera/", "/admin/cartera/?periodo=hoy", "/admin/cartera/?periodo=semana", "/admin/cartera/?periodo=mes",
             "/admin/cartera/?periodo=todo&page=2", "/admin/usuarios/", "/admin/usuarios/?rol=clientes&page=1"]
    for url in urls:
        assert client.get(url).status_code == 200, url


def test_demo_dataset_is_coherent(demo_app):
    """Los números demo cumplen las reglas de negocio (cartera = ventas - compras)."""
    from app.models import InventoryItem, LedgerEntry
    from app.models.order import PAY_PAID

    db.session.expire_all()
    s = LedgerEntry.summary()
    assert s["invested"] > 0 and s["recovered"] > 0
    assert s["profit"] == s["recovered"] - s["invested"] + s["adjustments"]
    # todo pedido cobrado (y no cancelado) tiene su venta en la cartera, y viceversa
    paid_total = sum(o.total_cents for o in db.session.scalars(select(Order).where(Order.payment_status == PAY_PAID)))
    refunded_total = sum(o.total_cents for o in db.session.scalars(select(Order).where(Order.payment_status == "reembolsado")))
    assert s["gross_sales"] == paid_total + refunded_total
    assert s["refunds"] == refunded_total
    # nunca hay stock negativo y los insumos bajos generan sugerencias
    assert all(i.stock >= 0 for i in db.session.scalars(select(InventoryItem)))
    assert InventoryItem.restock_suggestions()
    # hoy hay pedidos en cada etapa de la pizarra
    counts = Order.filter_counts()
    assert counts["pendiente"] >= 1 and counts["pagado"] >= 1 and counts["en_barra"] >= 1


def test_first_run_seeds_a_usable_shop():
    class FirstRun(TestConfig):
        SEED_ON_FIRST_RUN = True
        DEMO_DATA = False

    application = create_app(FirstRun)
    with application.app_context():
        assert db.session.scalar(select(Order.id)) is None
        client = application.test_client()
        assert client.get("/menu").status_code == 200
        assert client.post("/login", data={"email": "admin@moka.com", "password": "admin1234"}).status_code == 302
        assert client.get("/admin/inventario/").status_code == 200
        db.session.remove()
        db.engine.dispose()


def test_html_has_no_unrendered_template_syntax(demo_app):
    client = demo_app.test_client()
    login(client, DEMO_ADMIN)
    for url in ("/menu", "/menu/caramel-macchiato-insignia", "/carrito", "/admin/pedidos", "/admin/inventario/", "/admin/cartera/", "/admin/usuarios/"):
        html = client.get(url).get_data(as_text=True)
        visible = re.sub(r"<(script|style).*?</>", "", html, flags=re.S)
        assert "{{" not in visible and "{%" not in visible, url
        assert ">None<" not in visible and "Undefined" not in visible, url
