"""Piezas comunes de la capa de modelos."""
from contextlib import contextmanager

from ..extensions import db


class DomainError(Exception):
    """Regla de negocio incumplida. El mensaje se puede mostrar al usuario."""


class OrderStateError(DomainError):
    """Transición de estado de pedido no permitida."""


class InsufficientStock(DomainError):
    """Falta inventario para preparar un pedido."""

    def __init__(self, shortages):
        self.shortages = shortages  # [(nombre, necesario, disponible, unidad)]
        detail = ", ".join(f"{name} (necesita {need:g} {unit}, hay {have:g})" for name, need, have, unit in shortages)
        super().__init__(f"Inventario insuficiente: {detail}. Registra una compra o ajusta el stock.")


class CartError(DomainError):
    """Problema con el carrito o con las opciones elegidas."""


@contextmanager
def unit_of_work():
    """Agrupa varias escrituras en una sola transacción (todo o nada)."""
    try:
        yield
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
