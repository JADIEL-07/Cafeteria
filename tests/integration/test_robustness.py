"""Golpea todas las rutas con datos basura: ninguna debe terminar en error 500."""
import re

import pytest

from tests.helpers import ADMIN, CLIENT, login

FIELDS = [
    "product_id", "qty", "size", "temperature", "milk", "sweetness", "extras", "notes", "next", "mode", "table", "code",
    "action", "payment", "email", "password", "name", "role", "amount", "kind", "description", "method", "item_id",
    "new_stock", "note", "unit_cost", "supplier", "category", "unit", "min_stock", "initial_stock", "sku", "reason",
    "remember", "tab", "q", "estado", "page", "ver", "periodo", "tipo", "metodo", "cat", "dieta", "orden", "rol",
]
JUNK = ["", "0", "-1", "abc", "9" * 400, "💥ñ\u0000", "' OR 1=1 --", "<script>alert(1)</script>", "1e999", "NaN", "x" * 3000, "//evil.com"]
PATH_VALUES = {"int": ["1", "2", "999999999999"], "string": ["x", "MK-8001", "a" * 300, "caramel-macchiato-insignia"]}


def concrete_urls(rule):
    """Sustituye los parámetros de la ruta por valores de prueba."""
    urls = [rule.rule]
    for arg in sorted(rule.arguments):
        kind = "int" if rule._converters[arg].__class__.__name__ == "IntegerConverter" else "string"
        pattern = re.compile(r"<(?:[^:>]+:)?" + re.escape(arg) + r">")
        urls = [pattern.sub(value, u) for u in urls for value in PATH_VALUES[kind]]
    return urls


@pytest.fixture()
def clients(app):
    guest = app.test_client()
    customer = app.test_client()
    login(customer, CLIENT)
    admin = app.test_client()
    login(admin, ADMIN)
    return {"guest": guest, "customer": customer, "admin": admin}


def test_no_route_returns_a_server_error(app, clients):
    rules = [r for r in app.url_map.iter_rules() if r.endpoint != "static"]
    assert len(rules) > 40
    failures = []
    for role, client in clients.items():
        for rule in rules:
            for url in concrete_urls(rule):
                for method in sorted(rule.methods & {"GET", "POST"}):
                    for junk in JUNK:
                        if method == "GET":
                            response = client.get(url, query_string={f: junk for f in FIELDS})
                        else:
                            response = client.post(url, data={f: junk for f in FIELDS})
                        if response.status_code >= 500:
                            failures.append(f"{role} {method} {url} junk={junk[:20]!r} -> {response.status_code}")
    assert not failures, "\n".join(failures[:20])


def test_huge_page_numbers_are_harmless(clients):
    for url in ("/admin/pedidos", "/admin/cartera/", "/admin/usuarios/"):
        for page in ("999999999999999999999999", "-5", "0", "abc"):
            assert clients["admin"].get(url, query_string={"page": page}).status_code == 200, (url, page)


def test_out_of_range_ids_are_plain_404s(clients):
    admin = clients["admin"]
    assert admin.post("/admin/usuarios/99999999999999999999/estado").status_code == 404
    assert admin.post("/admin/pedidos/99999999999999999999/aceptar").status_code == 404
    huge = "9" * 400
    assert clients["customer"].post("/carrito/agregar", data={"product_id": huge, "size": huge, "extras": huge}).status_code == 302
    assert admin.post("/admin/inventario/compra", data={"item_id": huge, "qty": "1", "unit_cost": "1"}).status_code == 302
