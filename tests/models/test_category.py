"""Modelo Category."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Category


def test_defaults(app):
    category = Category(slug="tes", name="Tés & Matcha")
    db.session.add(category)
    db.session.commit()
    assert (category.icon, category.sort_order) == ("restaurant_menu", 0)


def test_all_sorted_by_sort_order_then_name(category_factory):
    category_factory("z", "Zeta", sort_order=1)
    category_factory("b", "Beta", sort_order=2)
    category_factory("a", "Alfa", sort_order=2)
    category_factory("c", "Cero", sort_order=0)
    assert [c.name for c in Category.all_sorted()] == ["Cero", "Zeta", "Alfa", "Beta"]


def test_all_sorted_empty(app):
    assert Category.all_sorted() == []


def test_slug_is_unique(category_factory):
    category_factory("cafe", "Café")
    with pytest.raises(IntegrityError):
        category_factory("cafe", "Otro café")
    db.session.rollback()


def test_products_relationship(category, drink, product_factory):
    other = product_factory(name="Otro", slug="otro")
    assert {p.id for p in category.products} == {drink.id, other.id}
    assert drink.category == category
