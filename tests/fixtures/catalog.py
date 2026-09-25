"""Fixtures del catálogo: Category, Product, Modifier y ProductIngredient."""
import itertools
from types import SimpleNamespace

import pytest

from app.extensions import db
from app.models import Category, Modifier, Product, ProductIngredient

DRINK_GROUPS = "size,temperature,milk,sweetness,extra"


# ---- Category ---------------------------------------------------------------------------
@pytest.fixture()
def category_factory(app):
    counter = itertools.count(1)

    def make(slug=None, name=None, icon="coffee", sort_order=None):
        n = next(counter)
        category = Category(slug=slug or f"categoria-{n}", name=name or f"Categoría {n}", icon=icon, sort_order=n if sort_order is None else sort_order)
        db.session.add(category)
        db.session.commit()
        return category

    return make


@pytest.fixture()
def category(category_factory):
    return category_factory("cafe", "Café de Especialidad", "coffee", 1)


@pytest.fixture()
def bakery_category(category_factory):
    return category_factory("panaderia", "Panadería & Viennoiserie", "bakery_dining", 2)


# ---- Product ----------------------------------------------------------------------------
@pytest.fixture()
def product_factory(app, category):
    """``product_factory(category=None, name=..., price_cents=..., **campos)``; por defecto va en la categoría "cafe"."""
    counter = itertools.count(1)
    default_category = category

    def make(category=None, name=None, slug=None, price_cents=400, **fields):
        n = next(counter)
        fields.setdefault("description", "Descripción de prueba")
        product = Product(
            category_id=(category or default_category).id,
            name=name or f"Producto {n}",
            slug=slug or f"producto-{n}",
            price_cents=price_cents,
            **fields,
        )
        db.session.add(product)
        db.session.commit()
        return product

    return make


@pytest.fixture()
def drink(product_factory):
    """Bebida personalizable (tamaño, temperatura, leche, dulzor y extras) de $4.80."""
    return product_factory(
        name="Caramel Macchiato Insignia",
        slug="caramel-macchiato-insignia",
        price_cents=480,
        option_groups=DRINK_GROUPS,
        tags="organic",
        badge="Bebida Insignia",
        calories=180,
        caffeine_mg=145,
    )


@pytest.fixture()
def pastry(product_factory, bakery_category):
    """Producto sin opciones de personalización, en panadería: $3.95."""
    return product_factory(category=bakery_category, name="Croissant de Almendras", slug="croissant-de-almendras", price_cents=395, tags="")


@pytest.fixture()
def inactive_product(product_factory):
    return product_factory(name="Producto Retirado", slug="producto-retirado", is_active=False)


# ---- Modifier ---------------------------------------------------------------------------
@pytest.fixture()
def modifier_factory(app):
    def make(group, name, price_delta_cents=0, is_default=False, sort_order=0, is_active=True, inventory_item=None, inventory_qty=0, **fields):
        modifier = Modifier(
            group=group,
            name=name,
            price_delta_cents=price_delta_cents,
            is_default=is_default,
            sort_order=sort_order,
            is_active=is_active,
            inventory_item_id=inventory_item.id if inventory_item else None,
            inventory_qty=inventory_qty,
            **fields,
        )
        db.session.add(modifier)
        db.session.commit()
        return modifier

    return make


@pytest.fixture()
def drink_modifiers(modifier_factory):
    """Opciones de una bebida, por grupo. Por defecto: Mediano (+$0.50), Caliente, Avena (+$0.60), Normal."""
    return SimpleNamespace(
        size={
            "chico": modifier_factory("size", "Chico", 0, sort_order=1),
            "mediano": modifier_factory("size", "Mediano", 50, is_default=True, sort_order=2),
            "grande": modifier_factory("size", "Grande", 100, sort_order=3),
        },
        temperature={
            "hot": modifier_factory("temperature", "Caliente", 0, is_default=True, sort_order=1),
            "iced": modifier_factory("temperature", "Iced / Con Hielo", 0, sort_order=2),
        },
        milk={
            "whole": modifier_factory("milk", "Entera Fresca de Granja", 0, sort_order=1),
            "oat": modifier_factory("milk", "Leche de Avena Barista", 60, is_default=True, sort_order=2),
            "almond": modifier_factory("milk", "Almendras Tostadas", 60, sort_order=3),
        },
        sweetness={
            "normal": modifier_factory("sweetness", "Normal (100%)", 0, is_default=True, sort_order=1),
            "light": modifier_factory("sweetness", "Ligero (50%)", 0, sort_order=2),
        },
        extra={
            "shot": modifier_factory("extra", "Shot Extra de Espresso", 90, sort_order=1),
            "cream": modifier_factory("extra", "Nube de Crema Batida", 50, sort_order=2),
            "cinnamon": modifier_factory("extra", "Canela de Ceilán", 0, sort_order=3),
        },
    )


# ---- ProductIngredient ------------------------------------------------------------------
@pytest.fixture()
def recipe_factory(app):
    """``recipe_factory(producto, insumo, cantidad_por_unidad)`` agrega un ingrediente a la receta."""

    def make(product, item, qty):
        ingredient = ProductIngredient(product_id=product.id, item_id=item.id, qty=qty)
        db.session.add(ingredient)
        db.session.commit()
        return ingredient

    return make
