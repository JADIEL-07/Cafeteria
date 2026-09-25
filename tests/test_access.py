"""Autenticación, permisos por rol, CSRF y redirecciones seguras."""
import re

import pytest
from sqlalchemy import select

from app import create_app
from app.config import TestConfig
from app.extensions import db
from app.models import Favorite, Product, User
from app.seed import seed_catalog
from app.utils.throttle import login_limiter

from .conftest import ADMIN, BARISTA, CLIENT, login

ADMIN_ONLY = ["/admin/cartera/", "/admin/cartera/exportar.csv", "/admin/usuarios/", "/admin/usuarios/exportar.csv"]
STAFF_PAGES = ["/admin/pedidos", "/admin/pedidos/senal", "/admin/inventario/"]


def test_guest_is_sent_to_login_with_return_url(client):
    for url in STAFF_PAGES + ADMIN_ONLY + ["/perfil", "/favoritos"]:
        response = client.get(url)
        assert response.status_code == 302, url
        assert "/login?next=" in response.headers["Location"], url


def test_customer_cannot_enter_the_panel(client):
    login(client, CLIENT)
    for url in STAFF_PAGES + ADMIN_ONLY + ["/admin/"]:
        assert client.get(url).status_code == 403, url
    assert client.post("/admin/cartera/ajuste", data={"kind": "ingreso", "amount": "5", "description": "hack"}).status_code == 403
    assert client.post("/admin/pedidos/1/aceptar").status_code == 403
    assert client.post("/admin/usuarios/1/granos", data={"amount": "500"}).status_code == 403


def test_barista_sees_orders_and_inventory_only(client):
    login(client, BARISTA)
    for url in STAFF_PAGES:
        assert client.get(url).status_code == 200, url
    for url in ADMIN_ONLY:
        assert client.get(url).status_code == 403, url
    admin_id = User.get_by_email(ADMIN[0]).id
    assert client.post(f"/admin/usuarios/{admin_id}/editar", data={"name": "X", "role": "cliente"}).status_code == 403
    assert client.post("/admin/cartera/ajuste", data={"kind": "egreso", "amount": "5", "description": "robo"}).status_code == 403
    html = client.get("/admin/pedidos").get_data(as_text=True)
    assert "Cartera &amp; Finanzas" not in html and "Usuarios &amp; Clientes" not in html   # ni siquiera en el menú


def test_admin_sees_everything(client):
    login(client, ADMIN)
    for url in STAFF_PAGES + ADMIN_ONLY:
        assert client.get(url).status_code == 200, url
    html = client.get("/admin/pedidos").get_data(as_text=True)
    assert "Cartera &amp; Finanzas" in html and "Usuarios &amp; Clientes" in html


def test_wrong_password_and_unknown_user(client):
    for email, password in [(CLIENT[0], "mala"), ("nadie@correo.com", "cliente1234"), ("", "")]:
        response = client.post("/login", data={"email": email, "password": password})
        assert response.status_code == 401
        assert "incorrectos" in response.get_data(as_text=True)
    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_login_is_case_insensitive_on_email_and_remembers(client):
    response = client.post("/login", data={"email": "  CLIENTE@correo.COM ", "password": CLIENT[1], "remember": "on"})
    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert sess.permanent is True


def test_login_attempts_are_throttled(client):
    for _ in range(8):
        assert client.post("/login", data={"email": CLIENT[0], "password": "mala"}).status_code == 401
    blocked = client.post("/login", data={"email": CLIENT[0], "password": CLIENT[1]})
    assert blocked.status_code == 429            # ni siquiera con la contraseña correcta
    login_limiter.reset()
    assert client.post("/login", data={"email": CLIENT[0], "password": CLIENT[1]}).status_code == 302


@pytest.mark.parametrize("target", ["//evil.com", "https://evil.com", "http://evil.com/x", "/\\evil.com", "javascript:alert(1)", "evil"])
def test_open_redirect_is_blocked(client, target):
    response = client.post("/login", data={"email": CLIENT[0], "password": CLIENT[1], "next": target})
    assert response.status_code == 302
    assert response.headers["Location"] == "/menu"


def test_safe_next_is_honoured(client):
    response = client.post("/login", data={"email": CLIENT[0], "password": CLIENT[1], "next": "/carrito"})
    assert response.headers["Location"] == "/carrito"


def test_staff_land_on_the_panel(client):
    assert login(client, BARISTA).headers["Location"] == "/admin/pedidos"
    assert client.get("/admin/").headers["Location"] == "/admin/pedidos"


def test_registration_flow_and_validation(client):
    ok = client.post("/registro", data={"name": "Nuevo Cliente", "email": "Nuevo@Correo.com", "password": "clave12345"})
    assert ok.status_code == 302
    user = User.get_by_email("nuevo@correo.com")
    assert user.role == "cliente" and user.beans == 0 and user.password_hash != "clave12345"
    assert client.get("/perfil").status_code == 200           # ya quedó con sesión iniciada
    other = client.application.test_client()
    for data, message in [
        ({"name": "Ana", "email": "nuevo@correo.com", "password": "clave12345"}, "Ya existe una cuenta"),
        ({"name": "Ana", "email": "ana@correo.com", "password": "corta"}, "al menos 8"),
        ({"name": "A", "email": "ana@correo.com", "password": "clave12345"}, "nombre"),
        ({"name": "Ana", "email": "no-es-correo", "password": "clave12345"}, "correo electrónico válido"),
    ]:
        response = other.post("/registro", data=data)
        assert response.status_code == 400 and message in response.get_data(as_text=True)


def test_registration_cannot_choose_a_role(client):
    client.post("/registro", data={"name": "Intruso", "email": "int@correo.com", "password": "clave12345", "role": "admin"})
    assert User.get_by_email("int@correo.com").role == "cliente"


def test_logout_needs_post_and_clears_session(client):
    login(client, CLIENT)
    assert client.get("/logout").status_code == 405
    assert client.get("/perfil").status_code == 200
    client.post("/logout")
    assert client.get("/perfil").status_code == 302


def test_suspended_account_loses_access(client):
    login(client, CLIENT)
    user = User.get_by_email(CLIENT[0])
    user.is_active_account = False
    db.session.commit()
    assert client.get("/perfil").status_code == 302                  # la sesión abierta deja de servir
    fresh = client.application.test_client()
    assert fresh.post("/login", data={"email": CLIENT[0], "password": CLIENT[1]}).status_code == 401


def test_admin_cannot_lock_themselves_out(client):
    login(client, ADMIN)
    me = User.get_by_email(ADMIN[0])
    client.post(f"/admin/usuarios/{me.id}/estado")
    client.post(f"/admin/usuarios/{me.id}/editar", data={"name": "Yo", "role": "cliente"})
    db.session.expire_all()
    me = User.get_by_email(ADMIN[0])
    assert me.is_active_account and me.role == "admin"


def test_favorites_toggle(client):
    pid = db.session.scalar(select(Product.id).where(Product.slug == "croissant-de-almendras"))
    assert client.post(f"/favoritos/{pid}/toggle", headers={"X-Requested-With": "fetch"}).status_code == 401
    login(client, CLIENT)
    headers = {"X-Requested-With": "fetch"}
    assert client.post(f"/favoritos/{pid}/toggle", headers=headers).get_json() == {"favorite": True}
    assert "Croissant de Almendras" in client.get("/favoritos").get_data(as_text=True)
    assert client.post(f"/favoritos/{pid}/toggle", headers=headers).get_json() == {"favorite": False}
    assert client.post("/favoritos/9999/toggle", headers=headers).status_code == 404
    user = User.get_by_email(CLIENT[0])
    assert Favorite.ids_for(user) == set()


def test_error_pages(client):
    response = client.get("/no-existe")
    assert response.status_code == 404 and "No encontramos esa página" in response.get_data(as_text=True)
    assert client.get("/menu/no-existe").status_code == 404
    login(client, CLIENT)
    forbidden = client.get("/admin/pedidos")
    assert forbidden.status_code == 403 and "Acceso restringido" in forbidden.get_data(as_text=True)
    assert client.get("/no-existe", headers={"Accept": "application/json"}).get_json()["error"]


def test_security_headers(client):
    response = client.get("/menu")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"


def test_user_content_is_escaped_in_pages(client):
    """Un nombre malicioso no debe ejecutarse en el panel ni en el perfil."""
    payload = "<script>alert(1)</script>"
    client.post("/registro", data={"name": payload + "Eve", "email": "eve@correo.com", "password": "clave12345"})
    assert payload not in client.get("/perfil").get_data(as_text=True)
    admin = client.application.test_client()
    login(admin, ADMIN)
    assert payload not in admin.get("/admin/usuarios/?q=eve").get_data(as_text=True)


@pytest.fixture()
def csrf_client():
    class CsrfConfig(TestConfig):
        WTF_CSRF_ENABLED = True

    application = create_app(CsrfConfig)
    with application.app_context():
        seed_catalog()
        User.create("Cliente Test", CLIENT[0], CLIENT[1])
        yield application.test_client()
        db.session.remove()


def test_csrf_is_enforced(csrf_client):
    pid = db.session.scalar(select(Product.id).where(Product.slug == "croissant-de-almendras"))
    assert csrf_client.post("/carrito/agregar", data={"product_id": pid}).status_code == 400
    assert csrf_client.post("/login", data={"email": CLIENT[0], "password": CLIENT[1]}).status_code == 400
    page = csrf_client.get("/menu").get_data(as_text=True)
    token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
    assert csrf_client.post("/carrito/agregar", data={"product_id": pid, "csrf_token": token}).status_code == 302
    # también vale la cabecera que usa el JavaScript
    ajax = csrf_client.post("/carrito/agregar", data={"product_id": pid}, headers={"X-CSRFToken": token, "X-Requested-With": "fetch"})
    assert ajax.status_code == 200 and ajax.get_json()["count"] == 2
    assert csrf_client.post("/login", data={"email": CLIENT[0], "password": CLIENT[1], "csrf_token": token}).status_code == 302
