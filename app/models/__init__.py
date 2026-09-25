"""Capa de modelos (M de MVC): entidades, reglas de negocio y consultas.

Importar todo aquí garantiza que SQLAlchemy conozca todas las tablas antes de
``db.create_all()``.
"""
from .base import CartError, DomainError, InsufficientStock, OrderStateError  # noqa: F401
from .cart import Cart, CartLine, CartSummary  # noqa: F401
from .coupon import Coupon  # noqa: F401
from .favorite import Favorite  # noqa: F401
from .inventory import InventoryItem, InventoryMovement  # noqa: F401
from .ledger import LedgerEntry  # noqa: F401
from .order import Order, OrderItem  # noqa: F401
from .product import Category, Modifier, Product, ProductIngredient  # noqa: F401
from .user import User  # noqa: F401
