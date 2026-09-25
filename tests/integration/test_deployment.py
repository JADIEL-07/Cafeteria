"""Piezas de despliegue: /healthz, proxy de confianza y la guarda de la contraseña de admin por defecto."""
import pytest
from flask import jsonify, request
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app import create_app
from app.config import DEFAULT_ADMIN_PASSWORD, TestConfig, _int_env
from app.extensions import db
from app.models import User


@pytest.fixture()
def make_app():
    """Fábrica de apps con ajustes propios; cierra sus conexiones al terminar la prueba."""
    created = []

    def make(**settings):
        application = create_app(type("DeployConfig", (TestConfig,), settings))
        created.append(application)
        return application

    yield make
    for application in created:
        with application.app_context():
            db.session.remove()
            db.engine.dispose()


class TestHealthCheck:
    def test_reports_ok_without_logging_in(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok"}

    def test_reports_unavailable_when_the_database_is_down(self, client, monkeypatch):
        def down(*args, **kwargs):
            raise OperationalError("SELECT 1", {}, Exception("connection refused"))

        with monkeypatch.context() as patch:
            patch.setattr(db.session, "execute", down)
            response = client.get("/healthz")
        assert response.status_code == 503
        assert response.get_json() == {"status": "error"}

    def test_recovers_once_the_database_is_back(self, client, monkeypatch):
        with monkeypatch.context() as patch:
            patch.setattr(db.session, "execute", lambda *a, **k: (_ for _ in ()).throw(OperationalError("SELECT 1", {}, Exception("down"))))
            assert client.get("/healthz").status_code == 503
        assert client.get("/healthz").status_code == 200

    def test_is_not_cached(self, client):
        assert client.get("/healthz").headers["Cache-Control"] == "no-store"


class TestProxy:
    @staticmethod
    def add_probe(application):
        @application.get("/_who")
        def who():
            return jsonify(ip=request.remote_addr, https=request.is_secure)

    HEADERS = {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"}

    def test_without_a_proxy_forwarded_headers_are_ignored(self, make_app):
        application = make_app()
        self.add_probe(application)
        data = application.test_client().get("/_who", headers=self.HEADERS).get_json()
        assert data == {"ip": "127.0.0.1", "https": False}      # un cliente no puede fingir su IP

    def test_with_one_trusted_proxy_the_real_client_is_seen(self, make_app):
        application = make_app(PROXY_HOPS=1)
        self.add_probe(application)
        data = application.test_client().get("/_who", headers=self.HEADERS).get_json()
        assert data == {"ip": "203.0.113.9", "https": True}

    def test_a_spoofed_first_address_is_not_trusted(self, make_app):
        """El cliente añade 1.1.1.1; el proxy de confianza añade la dirección real al final."""
        application = make_app(PROXY_HOPS=1)
        self.add_probe(application)
        headers = {"X-Forwarded-For": "1.1.1.1, 203.0.113.9"}
        assert application.test_client().get("/_who", headers=headers).get_json()["ip"] == "203.0.113.9"

    @pytest.mark.parametrize("value, expected", [("2", 2), ("0", 0), ("-3", 0), ("abc", 0), ("", 0)])
    def test_hops_setting_is_read_defensively(self, monkeypatch, value, expected):
        monkeypatch.setenv("CAFE_PROXY_HOPS", value)
        assert _int_env("CAFE_PROXY_HOPS") == expected

    def test_hops_default_to_zero(self, monkeypatch):
        monkeypatch.delenv("CAFE_PROXY_HOPS", raising=False)
        assert _int_env("CAFE_PROXY_HOPS") == 0


class TestDefaultAdminPasswordGuard:
    FIRST_RUN = dict(SEED_ON_FIRST_RUN=True, DEMO_DATA=False, ADMIN_EMAIL="admin@moka.com")

    def test_production_refuses_to_seed_the_default_password(self, make_app):
        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
            make_app(SESSION_COOKIE_SECURE=True, ADMIN_PASSWORD=DEFAULT_ADMIN_PASSWORD, **self.FIRST_RUN)

    def test_production_accepts_a_custom_password(self, make_app):
        application = make_app(SESSION_COOKIE_SECURE=True, ADMIN_PASSWORD="una-clave-larga-1", **self.FIRST_RUN)
        with application.app_context():
            assert User.authenticate("admin@moka.com", "una-clave-larga-1") is not None

    def test_local_development_keeps_the_default_password(self, make_app):
        application = make_app(SESSION_COOKIE_SECURE=False, ADMIN_PASSWORD=DEFAULT_ADMIN_PASSWORD, **self.FIRST_RUN)
        with application.app_context():
            assert db.session.scalar(select(User.id).where(User.email == "admin@moka.com")) is not None

    def test_an_existing_database_is_never_blocked(self, make_app, tmp_path):
        """La guarda sólo actúa al sembrar: reiniciar contra una base con datos no falla.

        Usa un archivo SQLite compartido (con base en memoria cada arranque vería una base vacía).
        """
        shared = dict(SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'shop.db'}", SQLALCHEMY_ENGINE_OPTIONS={}, SESSION_COOKIE_SECURE=True, **self.FIRST_RUN)
        make_app(ADMIN_PASSWORD="una-clave-larga-1", **shared)                         # primer arranque: siembra
        application = make_app(ADMIN_PASSWORD=DEFAULT_ADMIN_PASSWORD, **shared)       # reinicio: base con datos
        with application.app_context():
            assert User.authenticate("admin@moka.com", "una-clave-larga-1") is not None


class TestEnvironmentIsolation:
    def test_the_test_config_pins_everything_the_suite_depends_on(self):
        """Un .env local (ADMIN_PASSWORD propia, CAFE_HTTPS…) no puede cambiar el resultado de las pruebas."""
        for name in ("SECRET_KEY", "SQLALCHEMY_DATABASE_URI", "ADMIN_EMAIL", "ADMIN_PASSWORD", "SESSION_COOKIE_SECURE", "PROXY_HOPS"):
            assert name in vars(TestConfig), f"TestConfig debe fijar {name}"
