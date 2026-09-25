"""models/base.py: errores de negocio y unidad de trabajo."""
import pytest

from app.extensions import db
from app.models import CartError, DomainError, InsufficientStock, OrderStateError, User
from app.models.base import unit_of_work


@pytest.mark.parametrize("error", [OrderStateError, CartError])
def test_specific_errors_are_domain_errors(error):
    assert issubclass(error, DomainError)
    assert str(error("mensaje")) == "mensaje"


def test_insufficient_stock_is_a_domain_error_with_readable_message():
    error = InsufficientStock([("Leche de Avena", 0.5, 0.25, "briks"), ("Vasos", 2, 1, "uds")])
    assert isinstance(error, DomainError)
    assert error.shortages[0] == ("Leche de Avena", 0.5, 0.25, "briks")
    message = str(error)
    assert "Inventario insuficiente" in message
    assert "Leche de Avena (necesita 0.5 briks, hay 0.25)" in message
    assert "Vasos (necesita 2 uds, hay 1)" in message
    assert "Registra una compra o ajusta el stock" in message


def test_unit_of_work_commits_on_success(app):
    with unit_of_work():
        db.session.add(User(name="Ana", email="ana@correo.com", password_hash="x"))
    db.session.rollback()  # si no hubiera commit, esto lo descartaría
    assert User.get_by_email("ana@correo.com") is not None


def test_unit_of_work_rolls_back_and_reraises_on_error(app):
    with pytest.raises(RuntimeError, match="boom"):
        with unit_of_work():
            db.session.add(User(name="Ana", email="ana@correo.com", password_hash="x"))
            db.session.flush()
            raise RuntimeError("boom")
    assert User.get_by_email("ana@correo.com") is None
