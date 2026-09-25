"""Modelo ProductIngredient: la receta (insumos por unidad vendida)."""
from sqlalchemy import select

from app.extensions import db
from app.models import ProductIngredient


def test_links_product_and_item(recipe_factory, drink, coffee_item):
    ingredient = recipe_factory(drink, coffee_item, 0.018)
    assert (ingredient.product, ingredient.item, ingredient.qty) == (drink, coffee_item, 0.018)
    assert drink.ingredients == [ingredient]


def test_a_product_can_have_many_ingredients(recipe_factory, drink, coffee_item, cup_item):
    recipe_factory(drink, coffee_item, 0.018)
    recipe_factory(drink, cup_item, 1)
    assert sorted(i.item.sku for i in drink.ingredients) == ["MOK-CF-01", "MOK-PKG-01"]


def test_recipes_are_per_product(recipe_factory, drink, pastry, coffee_item, butter_item):
    recipe_factory(drink, coffee_item, 0.018)
    recipe_factory(pastry, butter_item, 0.05)
    assert [i.item.sku for i in drink.ingredients] == ["MOK-CF-01"]
    assert [i.item.sku for i in pastry.ingredients] == ["MOK-OB-01"]


def test_deleting_a_product_removes_its_recipe(recipe_factory, drink, coffee_item):
    recipe_factory(drink, coffee_item, 0.018)
    db.session.delete(drink)
    db.session.commit()
    assert db.session.scalars(select(ProductIngredient)).all() == []


def test_removing_an_ingredient_from_the_recipe_deletes_it(recipe_factory, drink, coffee_item):
    ingredient = recipe_factory(drink, coffee_item, 0.018)
    drink.ingredients.remove(ingredient)
    db.session.commit()
    assert db.session.scalars(select(ProductIngredient)).all() == []
