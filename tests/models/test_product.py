"""Modelo Product: propiedades, catálogo filtrable, ranking por ventas y sugerencias."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Product
from app.models.product import DIET_TAGS, MODIFIER_GROUPS, SORT_OPTIONS


class TestProperties:
    def test_defaults(self, product_factory):
        product = product_factory()
        assert (product.is_active, product.featured, product.prep_minutes, product.tags, product.option_groups) == (True, False, 5, "", "")
        assert product.created_at is not None

    @pytest.mark.parametrize("raw, expected", [("", []), ("vegan", ["vegan"]), (" vegan , organic ,, ", ["vegan", "organic"])])
    def test_tag_list(self, product_factory, raw, expected):
        assert product_factory(tags=raw).tag_list == expected

    def test_option_groups_ignore_unknown_names(self, product_factory):
        product = product_factory(option_groups="size, milk ,inventado,extra")
        assert product.option_group_list == ["size", "milk", "extra"]
        assert product.is_customizable is True

    def test_not_customizable_without_valid_groups(self, product_factory):
        assert product_factory(option_groups="").is_customizable is False
        assert product_factory(option_groups="inventado").is_customizable is False

    def test_tasting_notes(self, product_factory):
        assert product_factory(tasting_notes="Jazmín, Vainilla ,").tasting_note_list == ["Jazmín", "Vainilla"]
        assert product_factory(tasting_notes=None).tasting_note_list == []

    @pytest.mark.parametrize("price, beans", [(0, 0), (99, 0), (100, 1), (480, 4), (1400, 14)])
    def test_beans_are_one_per_dollar(self, product_factory, price, beans):
        assert product_factory(price_cents=price).beans == beans

    def test_slug_is_unique(self, product_factory):
        product_factory(slug="croissant")
        with pytest.raises(IntegrityError):
            product_factory(slug="croissant")
        db.session.rollback()

    def test_repr(self, drink):
        assert repr(drink) == "<Product caramel-macchiato-insignia>"

    def test_constants_are_consistent(self):
        assert set(MODIFIER_GROUPS) == {"size", "temperature", "milk", "sweetness", "extra"}
        assert set(DIET_TAGS) == {"vegan", "gluten-free", "decaf", "organic"}
        assert set(SORT_OPTIONS) == {"popular", "nuevo", "precio_asc", "precio_desc"}


class TestCatalog:
    @pytest.fixture()
    def menu(self, product_factory, bakery_category):
        return {
            "latte": product_factory(name="Latte de Vainilla", slug="latte", price_cents=450, subtitle="Suave", tags="vegan,organic"),
            "espresso": product_factory(name="Espresso Doble", slug="espresso", price_cents=280, description="Ristretto intenso", tags="organic,gluten-free"),
            "croissant": product_factory(category=bakery_category, name="Croissant", slug="croissant", price_cents=395, description="Mantequilla y almendras"),
            "retirado": product_factory(name="Retirado", slug="retirado", price_cents=100, is_active=False),
        }

    def names(self, products):
        return [p.name for p in products]

    def test_only_active_products(self, menu):
        assert "Retirado" not in self.names(Product.catalog(sort="precio_asc"))
        assert len(Product.catalog()) == 3

    def test_filter_by_category_slug(self, menu):
        assert self.names(Product.catalog(category_slug="panaderia")) == ["Croissant"]
        assert Product.catalog(category_slug="no-existe") == []

    @pytest.mark.parametrize("query, expected", [("latte", ["Latte de Vainilla"]), ("RISTRETTO", ["Espresso Doble"]), ("suave", ["Latte de Vainilla"]), ("almendras", ["Croissant"]), ("zzz", [])])
    def test_search_matches_name_description_and_subtitle_case_insensitively(self, menu, query, expected):
        assert self.names(Product.catalog(query=query)) == expected

    @pytest.mark.parametrize("query", ["%", "_", "100%", "a_b", "\\"])
    def test_search_wildcards_are_literals(self, menu, query):
        assert Product.catalog(query=query) == []

    def test_tags_require_all_of_them(self, menu):
        assert self.names(Product.catalog(tags=("organic",), sort="precio_asc")) == ["Espresso Doble", "Latte de Vainilla"]
        assert self.names(Product.catalog(tags=("organic", "vegan"))) == ["Latte de Vainilla"]
        assert Product.catalog(tags=("vegan", "gluten-free")) == []

    def test_sort_by_price(self, menu):
        assert self.names(Product.catalog(sort="precio_asc")) == ["Espresso Doble", "Croissant", "Latte de Vainilla"]
        assert self.names(Product.catalog(sort="precio_desc")) == ["Latte de Vainilla", "Croissant", "Espresso Doble"]

    def test_sort_by_newest(self, product_factory):
        now = datetime(2026, 3, 1)
        product_factory(name="Viejo", slug="viejo", created_at=now)
        product_factory(name="Nuevo", slug="nuevo", created_at=now + timedelta(days=5))
        product_factory(name="Medio", slug="medio", created_at=now + timedelta(days=2))
        assert self.names(Product.catalog(sort="nuevo")) == ["Nuevo", "Medio", "Viejo"]

    def test_popular_sort_uses_paid_sales_then_name(self, kitchen, order_factory):
        # Sin ventas: orden alfabético
        assert self.names(Product.catalog()) == ["Caramel Macchiato Insignia", "Croissant de Almendras"]
        order_factory("tarjeta", drinks=0, pastries=3)         # pagado: el croissant suma 3
        assert self.names(Product.catalog()) == ["Croissant de Almendras", "Caramel Macchiato Insignia"]

    def test_unknown_sort_falls_back_to_popular(self, menu):
        assert self.names(Product.catalog(sort="raro")) == self.names(Product.catalog(sort="popular"))


class TestSoldMap:
    def test_empty(self, app):
        assert Product.sold_map() == {}

    def test_counts_only_paid_and_not_cancelled_orders(self, kitchen, order_factory):
        order_factory("tarjeta", drinks=1, pastries=2)                       # pagado
        order_factory("efectivo", drinks=4, pastries=0)                      # sin cobrar: no cuenta
        order_factory("tarjeta", drinks=0, pastries=5).cancel()              # reembolsado: no cuenta
        assert Product.sold_map() == {kitchen.drink.id: 1, kitchen.pastry.id: 2}

    def test_cash_order_counts_once_payment_is_confirmed(self, kitchen, order_factory):
        cash = order_factory("efectivo", drinks=2, pastries=0)
        assert Product.sold_map() == {}
        cash.confirm_payment()
        assert Product.sold_map() == {kitchen.drink.id: 2}


class TestQueries:
    def test_category_counts_only_active(self, drink, pastry, inactive_product, category, bakery_category):
        assert Product.category_counts() == {"cafe": 1, "panaderia": 1}

    def test_get_active_by_slug(self, drink, inactive_product):
        assert Product.get_active_by_slug("caramel-macchiato-insignia") == drink
        assert Product.get_active_by_slug("producto-retirado") is None
        assert Product.get_active_by_slug("no-existe") is None

    def test_featured_product(self, product_factory):
        assert Product.featured_product() is None
        product_factory(name="Normal", slug="normal")
        product_factory(name="Retirado destacado", slug="retirado-destacado", featured=True, is_active=False)
        first = product_factory(name="Destacado 1", slug="destacado-1", featured=True)
        product_factory(name="Destacado 2", slug="destacado-2", featured=True)
        assert Product.featured_product() == first

    def test_pairings_are_other_bakery_items(self, drink, pastry, product_factory, bakery_category):
        cookie = product_factory(category=bakery_category, name="Cookie", slug="cookie")
        product_factory(category=bakery_category, name="Retirada", slug="retirada", is_active=False)
        assert drink.pairings(limit=5) == [pastry, cookie]
        assert drink.pairings(limit=1) == [pastry]
        assert pastry.pairings(limit=5) == [cookie]      # nunca se sugiere a sí mismo

    def test_pairings_empty_without_bakery(self, drink):
        assert drink.pairings() == []

    def test_related_drinks_need_options_and_exclude_self(self, drink, pastry, product_factory):
        matcha = product_factory(name="Matcha", slug="matcha", option_groups="size,milk")
        product_factory(name="Bebida retirada", slug="retirada", option_groups="size", is_active=False)
        assert drink.related_drinks(limit=3) == [matcha]
        assert matcha.related_drinks(limit=3) == [drink]
        assert pastry.related_drinks(limit=3) == [drink, matcha]
