"""Fixtures del modelo Favorite."""
import pytest

from app.extensions import db
from app.models import Favorite


@pytest.fixture()
def favorite_factory(app):
    def make(user, product):
        favorite = Favorite(user_id=user.id, product_id=product.id)
        db.session.add(favorite)
        db.session.commit()
        return favorite

    return make


@pytest.fixture()
def favorite(favorite_factory, client_user, drink):
    return favorite_factory(client_user, drink)
