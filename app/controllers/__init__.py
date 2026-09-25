"""Capa de controladores (C de MVC): un blueprint por área funcional."""
from . import (
    admin_finance_controller,
    admin_inventory_controller,
    admin_orders_controller,
    admin_users_controller,
    auth_controller,
    cart_controller,
    menu_controller,
    orders_controller,
)

BLUEPRINTS = (
    auth_controller.bp,
    menu_controller.bp,
    cart_controller.bp,
    orders_controller.bp,
    admin_orders_controller.bp,
    admin_inventory_controller.bp,
    admin_finance_controller.bp,
    admin_users_controller.bp,
)


def register_blueprints(app):
    for blueprint in BLUEPRINTS:
        app.register_blueprint(blueprint)
