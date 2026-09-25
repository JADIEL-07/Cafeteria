"""Panel de usuarios: filtros, granos, roles y altas."""
from app.extensions import db
from app.models import User

from tests.helpers import ADMIN, BARISTA, CLIENT, OTHER, add_to_cart, login


def user(credentials):
    db.session.expire_all()
    return User.get_by_email(credentials[0])


def test_bonus_and_deduct_beans(client):
    login(client, ADMIN)
    target = user(CLIENT)
    client.post(f"/admin/usuarios/{target.id}/granos", data={"amount": "25"})
    assert user(CLIENT).beans == 25 and user(CLIENT).tier == "Grano Plata"
    client.post(f"/admin/usuarios/{target.id}/granos", data={"amount": "80"})
    assert user(CLIENT).is_vip
    client.post(f"/admin/usuarios/{target.id}/granos", data={"amount": "-500"})
    assert user(CLIENT).beans == 0                                   # nunca negativo
    for bad in ("0", "501", "abc", ""):
        response = client.post(f"/admin/usuarios/{target.id}/granos", data={"amount": bad}, follow_redirects=True)
        assert "entre -500 y 500" in response.get_data(as_text=True)
    staff = user(BARISTA)
    response = client.post(f"/admin/usuarios/{staff.id}/granos", data={"amount": "10"}, follow_redirects=True)
    assert "Sólo los clientes" in response.get_data(as_text=True) and user(BARISTA).beans == 0


def test_edit_role_and_toggle_active(client):
    login(client, ADMIN)
    target = user(CLIENT)
    client.post(f"/admin/usuarios/{target.id}/editar", data={"name": "Cliente Barista", "role": "barista"})
    assert (user(CLIENT).name, user(CLIENT).role) == ("Cliente Barista", "barista")
    bad = client.post(f"/admin/usuarios/{target.id}/editar", data={"name": "X", "role": "barista"}, follow_redirects=True)
    assert "nombre completo" in bad.get_data(as_text=True)
    bad_role = client.post(f"/admin/usuarios/{target.id}/editar", data={"name": "Cliente Barista", "role": "dios"}, follow_redirects=True)
    assert "Rol no válido" in bad_role.get_data(as_text=True) and user(CLIENT).role == "barista"
    client.post(f"/admin/usuarios/{target.id}/estado")
    assert user(CLIENT).is_active_account is False
    client.post(f"/admin/usuarios/{target.id}/estado")
    assert user(CLIENT).is_active_account is True
    assert client.post("/admin/usuarios/9999/estado").status_code == 404


def test_invite_collaborator(client):
    login(client, ADMIN)
    client.post("/admin/usuarios/nuevo", data={"name": "Nueva Barista", "email": "nueva@moka.com", "role": "barista", "password": "clave12345"})
    created = User.get_by_email("nueva@moka.com")
    assert created.role == "barista"
    fresh = client.application.test_client()
    assert fresh.post("/login", data={"email": "nueva@moka.com", "password": "clave12345"}).headers["Location"] == "/admin/pedidos"
    dup = client.post("/admin/usuarios/nuevo", data={"name": "Otra", "email": "NUEVA@moka.com", "role": "barista", "password": "clave12345"}, follow_redirects=True)
    assert "Ya existe una cuenta" in dup.get_data(as_text=True)
    bad_role = client.post("/admin/usuarios/nuevo", data={"name": "Otra", "email": "otra@moka.com", "role": "root", "password": "clave12345"}, follow_redirects=True)
    assert "Elige un rol" in bad_role.get_data(as_text=True)
    assert User.get_by_email("otra@moka.com") is None


def test_filters_search_and_kpis(client):
    login(client, ADMIN)
    vip = user(OTHER)
    vip.beans = 150
    db.session.commit()
    everyone = client.get("/admin/usuarios/").get_data(as_text=True)
    for name in ("Admin Test", "Barista Test", "Cliente Test", "Otro Cliente"):
        assert name in everyone
    only_vip = client.get("/admin/usuarios/?rol=vip").get_data(as_text=True)
    assert "Otro Cliente" in only_vip and "Cliente Test" not in only_vip
    staff = client.get("/admin/usuarios/?rol=baristas").get_data(as_text=True)
    assert "Barista Test" in staff and "Otro Cliente" not in staff
    found = client.get("/admin/usuarios/?q=otro@").get_data(as_text=True)
    assert "Otro Cliente" in found and "Cliente Test" not in found
    assert client.get("/admin/usuarios/?q=%25%5F").status_code == 200        # comodines LIKE escapados
    assert client.get("/admin/usuarios/?rol=inventado&page=9&ver=abc").status_code == 200
    assert client.get("/admin/usuarios/?ver=99999").status_code == 200


def test_customer_card_shows_order_stats(client):
    customer = client.application.test_client()
    login(customer, CLIENT)
    add_to_cart(customer, "croissant-de-almendras", qty=2)
    customer.post("/checkout", data={"payment": "tarjeta"})
    login(client, ADMIN)
    target = user(CLIENT)
    html = client.get(f"/admin/usuarios/?ver={target.id}").get_data(as_text=True)
    assert "Croissant de Almendras" in html                # producto favorito
    assert "$8.49" in html                                 # ticket promedio
    stats = target.order_stats()
    assert stats["count"] == 1 and stats["total_cents"] == 849
    assert target.beans == 8                               # 8.49 -> 8 granos
