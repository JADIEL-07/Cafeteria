"""Modelo User: alta, autenticación, roles, Moka Club y estadísticas."""
from datetime import datetime

import pytest
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash

from app.extensions import db
from app.models import DomainError, User
from tests.fixtures.users import DEFAULT_PASSWORD


class TestCreate:
    def test_normalizes_email_and_hashes_password(self, app):
        user = User.create("  Elena Rostova ", "  ELENA@Correo.COM ", "clave12345")
        assert user.email == "elena@correo.com"
        assert user.name == "Elena Rostova"
        assert user.password_hash != "clave12345"
        assert check_password_hash(user.password_hash, "clave12345")
        assert (user.role, user.beans, user.is_active_account) == ("cliente", 0, True)
        assert user.id is not None and user.created_at is not None and user.last_login_at is None

    def test_accepts_role_beans_and_created_at(self, app):
        when = datetime(2024, 1, 5, 9, 30)
        user = User.create("Mateo", "mateo@moka.com", "clave12345", role="barista", beans=40, created_at=when)
        assert (user.role, user.beans, user.created_at) == ("barista", 40, when)

    @pytest.mark.parametrize("name", ["", " ", "A", "  B  "])
    def test_rejects_short_names(self, app, name):
        with pytest.raises(DomainError, match="nombre"):
            User.create(name, "a@correo.com", "clave12345")

    @pytest.mark.parametrize("email", ["", "sin-arroba", "a@b", "a@b.", "x" * 160 + "@correo.com"])
    def test_rejects_invalid_emails(self, app, email):
        with pytest.raises(DomainError, match="correo"):
            User.create("Ana", email, "clave12345")

    @pytest.mark.parametrize("password", ["", "corta", "1234567"])
    def test_rejects_short_passwords(self, app, password):
        with pytest.raises(DomainError, match="al menos 8"):
            User.create("Ana", "ana@correo.com", password)

    def test_rejects_unknown_role(self, app):
        with pytest.raises(DomainError, match="Rol"):
            User.create("Ana", "ana@correo.com", "clave12345", role="dios")

    def test_rejects_duplicate_email_regardless_of_case(self, client_user):
        with pytest.raises(DomainError, match="Ya existe"):
            User.create("Otra Elena", "ELENA@correo.com", "clave12345")

    def test_commit_false_only_flushes(self, app):
        user = User.create("Ana", "ana@correo.com", "clave12345", commit=False)
        assert user.id is not None
        db.session.rollback()
        assert User.get_by_email("ana@correo.com") is None

    def test_database_enforces_unique_email(self, client_user):
        db.session.add(User(name="Clon", email=client_user.email, password_hash="x"))
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


class TestLookupAndAuthentication:
    def test_get_by_email_normalizes(self, client_user):
        assert User.get_by_email("  ELENA@correo.com ") == client_user
        assert User.get_by_email("nadie@correo.com") is None
        assert User.get_by_email(None) is None

    def test_authenticate_success_records_last_login(self, client_user):
        assert client_user.last_login_at is None
        assert User.authenticate("Elena@Correo.com", DEFAULT_PASSWORD) == client_user
        assert client_user.last_login_at is not None

    @pytest.mark.parametrize("email, password", [("elena@correo.com", "incorrecta"), ("elena@correo.com", ""), ("elena@correo.com", None), ("nadie@correo.com", DEFAULT_PASSWORD)])
    def test_authenticate_failures(self, client_user, email, password):
        assert User.authenticate(email, password) is None
        assert client_user.last_login_at is None

    def test_suspended_accounts_cannot_authenticate(self, inactive_user):
        assert User.authenticate(inactive_user.email, DEFAULT_PASSWORD) is None

    def test_set_password(self, client_user):
        old = client_user.password_hash
        client_user.set_password("nueva-clave-1")
        assert client_user.password_hash != old
        assert check_password_hash(client_user.password_hash, "nueva-clave-1")
        with pytest.raises(DomainError, match="al menos 8"):
            client_user.set_password("corta")
        assert check_password_hash(client_user.password_hash, "nueva-clave-1")


class TestRoles:
    @pytest.mark.parametrize(
        "fixture, is_staff, is_admin, label",
        [("client_user", False, False, "Cliente"), ("barista_user", True, False, "Barista"), ("admin_user", True, True, "Administrador")],
    )
    def test_role_flags(self, request, fixture, is_staff, is_admin, label):
        user = request.getfixturevalue(fixture)
        assert (user.is_staff, user.is_admin, user.role_label) == (is_staff, is_admin, label)


class TestPresentation:
    @pytest.mark.parametrize(
        "name, first_name, initials",
        [("Elena Rostova", "Elena", "ER"), ("Mateo", "Mateo", "M"), ("  ana   maría  gómez ", "ana", "AM"), ("juan carlos de la vega", "juan", "JC")],
    )
    def test_first_name_and_initials(self, name, first_name, initials):
        user = User(name=name)
        assert (user.first_name, user.initials) == (first_name, initials)

    def test_blank_name_has_safe_fallbacks(self):
        user = User(name="   ")
        assert user.first_name == ""
        assert user.initials == "?"

    def test_repr(self, client_user):
        assert repr(client_user) == "<User elena@correo.com (cliente)>"


class TestMokaClub:
    @pytest.mark.parametrize(
        "beans, tier, is_vip",
        [(0, "Grano Bronce", False), (24, "Grano Bronce", False), (25, "Grano Plata", False), (99, "Grano Plata", False), (100, "Granos Dorados VIP", True), (500, "Granos Dorados VIP", True)],
    )
    def test_tiers(self, user_factory, beans, tier, is_vip):
        user = user_factory(beans=beans)
        assert (user.tier, user.is_vip) == (tier, is_vip)

    def test_staff_are_never_vip_and_have_their_own_tier(self, user_factory):
        barista = user_factory(role="barista", beans=999)
        assert (barista.tier, barista.is_vip) == ("Equipo Moka", False)

    @pytest.mark.parametrize("beans, progress, missing", [(0, 0, 150), (75, 50, 75), (150, 100, 0), (300, 100, 0)])
    def test_reward_progress(self, user_factory, beans, progress, missing):
        user = user_factory(beans=beans)
        assert user.reward_goal == 150
        assert (user.reward_progress, user.beans_to_reward) == (progress, missing)

    def test_add_beans_never_goes_below_zero(self, client_user):
        client_user.add_beans(30)
        assert client_user.beans == 30
        client_user.add_beans(-10)
        assert client_user.beans == 20
        client_user.add_beans(-500)
        assert client_user.beans == 0


class TestOrderStats:
    def test_without_orders(self, client_user):
        assert client_user.order_stats() == {"count": 0, "total_cents": 0, "avg_cents": 0, "last": None}
        assert client_user.favorite_products() == []

    def test_counts_orders_but_not_cancelled_ones(self, client_user, order_factory):
        first = order_factory("tarjeta")                       # $14.84
        order_factory("tarjeta", drinks=0, pastries=1)         # $4.25
        order_factory("efectivo").cancel()                     # cancelado: no cuenta
        stats = client_user.order_stats()
        assert stats["count"] == 2
        assert stats["total_cents"] == first.total_cents + 425
        assert stats["avg_cents"] == round(stats["total_cents"] / 2)
        assert stats["last"] is not None

    def test_stats_are_per_user(self, client_user, silver_user, order_factory):
        order_factory("tarjeta")
        assert silver_user.order_stats()["count"] == 0

    def test_favorite_products_by_quantity(self, client_user, order_factory):
        order_factory("tarjeta", drinks=1, pastries=4)
        order_factory("tarjeta", drinks=2, pastries=0)
        order_factory("efectivo", drinks=5, pastries=0).cancel()   # cancelado: no cuenta
        assert client_user.favorite_products(limit=2) == ["Croissant de Almendras", "Caramel Macchiato Insignia"]
        assert client_user.favorite_products(limit=1) == ["Croissant de Almendras"]
