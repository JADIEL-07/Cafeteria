"""Fixtures del modelo Coupon."""
import pytest

from app.extensions import db
from app.models import Coupon


@pytest.fixture()
def coupon_factory(app):
    def make(code="PROMO", kind="fijo", value=200, min_subtotal_cents=0, max_uses=None, uses_count=0, is_active=True, description=None):
        coupon = Coupon(
            code=code, kind=kind, value=value, min_subtotal_cents=min_subtotal_cents, max_uses=max_uses,
            uses_count=uses_count, is_active=is_active, description=description,
        )
        db.session.add(coupon)
        db.session.commit()
        return coupon

    return make


@pytest.fixture()
def fixed_coupon(coupon_factory):
    """CAFELOVER: -$2.00 con subtotal mínimo de $5.00."""
    return coupon_factory("CAFELOVER", "fijo", 200, min_subtotal_cents=500, description="Beneficio comunidad Moka")


@pytest.fixture()
def percent_coupon(coupon_factory):
    """PROMO10: 10 % de descuento, sin mínimo."""
    return coupon_factory("PROMO10", "porcentaje", 10)


@pytest.fixture()
def inactive_coupon(coupon_factory):
    return coupon_factory("VIEJO", "fijo", 100, is_active=False)


@pytest.fixture()
def exhausted_coupon(coupon_factory):
    return coupon_factory("AGOTADO", "fijo", 100, max_uses=1, uses_count=1)
