"""Modelo Favorite: productos guardados por cada cliente."""
from datetime import datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Favorite


def count():
    return db.session.scalar(select(func.count(Favorite.id)))


class TestToggle:
    def test_marks_then_unmarks(self, client_user, drink):
        assert Favorite.toggle(client_user, drink) is True
        assert count() == 1
        assert Favorite.toggle(client_user, drink) is False
        assert count() == 0

    def test_favorites_are_per_user(self, client_user, silver_user, drink):
        Favorite.toggle(client_user, drink)
        assert Favorite.toggle(silver_user, drink) is True
        assert count() == 2
        Favorite.toggle(client_user, drink)
        assert Favorite.ids_for(silver_user) == {drink.id}

    def test_persists_across_sessions(self, client_user, drink):
        Favorite.toggle(client_user, drink)
        db.session.expire_all()
        assert Favorite.ids_for(client_user) == {drink.id}


class TestIdsFor:
    def test_guest_has_no_favorites(self, app):
        assert Favorite.ids_for(None) == set()

    def test_user_without_favorites(self, client_user):
        assert Favorite.ids_for(client_user) == set()

    def test_returns_product_ids(self, client_user, drink, pastry, favorite_factory):
        favorite_factory(client_user, drink)
        favorite_factory(client_user, pastry)
        assert Favorite.ids_for(client_user) == {drink.id, pastry.id}


class TestProductsFor:
    def test_newest_first(self, client_user, drink, pastry, favorite_factory):
        old = favorite_factory(client_user, drink)
        new = favorite_factory(client_user, pastry)
        old.created_at, new.created_at = datetime(2026, 1, 1), datetime(2026, 2, 1)
        db.session.commit()
        assert Favorite.products_for(client_user) == [pastry, drink]

    def test_excludes_inactive_products(self, client_user, drink, inactive_product, favorite_factory):
        favorite_factory(client_user, drink)
        favorite_factory(client_user, inactive_product)
        assert Favorite.products_for(client_user) == [drink]

    def test_only_the_users_own_favorites(self, client_user, silver_user, drink, pastry, favorite_factory):
        favorite_factory(client_user, drink)
        favorite_factory(silver_user, pastry)
        assert Favorite.products_for(client_user) == [drink]

    def test_empty(self, client_user):
        assert Favorite.products_for(client_user) == []


class TestConstraints:
    def test_a_product_can_only_be_favorited_once_per_user(self, client_user, drink, favorite_factory):
        favorite_factory(client_user, drink)
        with pytest.raises(IntegrityError):
            favorite_factory(client_user, drink)
        db.session.rollback()

    def test_fixture(self, favorite, client_user, drink):
        assert (favorite.user_id, favorite.product_id) == (client_user.id, drink.id)
        assert favorite.created_at is not None
