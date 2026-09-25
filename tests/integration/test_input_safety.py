"""Entradas que la base de datos no acepta deben dar 400, nunca 500 (PostgreSQL es más estricto que SQLite)."""
import pytest
from sqlalchemy.exc import DataError

from tests.helpers import login, ADMIN


class TestNulBytes:
    @pytest.mark.parametrize("url", ["/menu?q=a%00b", "/menu?cat=%00", "/menu/caramel%00", "/login?next=%00"])
    def test_get_requests_with_nul_are_rejected(self, client, url):
        assert client.get(url).status_code == 400

    def test_form_values_with_nul_are_rejected(self, client):
        response = client.post("/login", data={"email": "a\x00b@moka.com", "password": "x"})
        assert response.status_code == 400

    def test_form_keys_with_nul_are_rejected(self, client):
        assert client.post("/login", data={"email\x00": "x"}).status_code == 400

    def test_admin_forms_are_covered_too(self, client):
        login(client, ADMIN)
        response = client.post("/admin/usuarios/1/granos", data={"amount": "5\x00"})
        assert response.status_code == 400

    def test_normal_text_with_accents_and_emoji_still_works(self, client):
        assert client.get("/menu?q=café☕ñ").status_code == 200

    def test_the_error_page_is_a_friendly_html_page(self, client):
        response = client.get("/menu?q=%00")
        assert "Solicitud no válida" in response.get_data(as_text=True)


class TestDatabaseDataErrors:
    def test_a_data_error_is_a_client_error_and_leaves_the_session_usable(self, app, client):
        @app.get("/_boom")
        def boom():
            raise DataError("INSERT ...", {}, Exception("value too long for type character varying(120)"))

        response = client.get("/_boom")
        assert response.status_code == 400
        assert "Datos no válidos" in response.get_data(as_text=True)
        assert client.get("/menu").status_code == 200

    def test_json_clients_get_json(self, app, client):
        @app.get("/_boom_json")
        def boom():
            raise DataError("INSERT ...", {}, Exception("integer out of range"))

        response = client.get("/_boom_json", headers={"X-Requested-With": "fetch"})
        assert response.status_code == 400
        assert response.get_json()["error"] == "Datos no válidos"
