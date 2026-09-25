"""Modelo Coupon: búsqueda, validación y cálculo del descuento."""
import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import Coupon, DomainError


class TestLookup:
    @pytest.mark.parametrize("raw, expected", [(" promo ", "PROMO"), ("CaféLover", "CAFÉLOVER"), ("", ""), (None, "")])
    def test_normalize(self, raw, expected):
        assert Coupon.normalize(raw) == expected

    def test_find_is_case_insensitive(self, fixed_coupon):
        assert Coupon.find("cafelover") == fixed_coupon
        assert Coupon.find("  CafeLover ") == fixed_coupon

    @pytest.mark.parametrize("code", ["", "   ", None, "NOEXISTE"])
    def test_find_returns_none_when_missing(self, fixed_coupon, code):
        assert Coupon.find(code) is None

    def test_code_is_unique(self, fixed_coupon, coupon_factory):
        with pytest.raises(IntegrityError):
            coupon_factory("CAFELOVER")
        db.session.rollback()

    def test_defaults(self, coupon_factory):
        coupon = coupon_factory("BASICO")
        assert (coupon.uses_count, coupon.is_active, coupon.max_uses, coupon.min_subtotal_cents) == (0, True, None, 0)


class TestCheck:
    def test_valid_coupon_passes(self, fixed_coupon):
        fixed_coupon.check(1380)

    def test_minimum_subtotal_is_inclusive(self, fixed_coupon):
        fixed_coupon.check(500)
        with pytest.raises(DomainError, match=r"subtotal mínimo de \$5\.00"):
            fixed_coupon.check(499)

    def test_inactive_coupon(self, inactive_coupon):
        with pytest.raises(DomainError, match="ya no está disponible"):
            inactive_coupon.check(5000)

    def test_exhausted_coupon(self, exhausted_coupon):
        with pytest.raises(DomainError, match="límite de usos"):
            exhausted_coupon.check(5000)

    def test_limited_coupon_with_uses_left(self, coupon_factory):
        coupon_factory("QUEDAN", max_uses=3, uses_count=2).check(100)

    def test_unlimited_coupon_never_runs_out(self, coupon_factory):
        coupon_factory("SIEMPRE", uses_count=10_000).check(100)


class TestDiscount:
    @pytest.mark.parametrize("subtotal, expected", [(1380, 200), (500, 200), (150, 150), (0, 0)])
    def test_fixed_discount_is_capped_at_the_subtotal(self, fixed_coupon, subtotal, expected):
        assert fixed_coupon.discount_for(subtotal) == expected

    @pytest.mark.parametrize("subtotal, expected", [(1380, 138), (1000, 100), (333, 33), (0, 0)])
    def test_percent_discount(self, percent_coupon, subtotal, expected):
        assert percent_coupon.discount_for(subtotal) == expected

    def test_percent_rounds_half_up(self, coupon_factory):
        assert coupon_factory("QUINCE", "porcentaje", 15).discount_for(333) == 50    # 49.95 -> 50
        assert coupon_factory("CINCO", "porcentaje", 5).discount_for(10) == 1        # 0.5 -> 1

    @pytest.mark.parametrize("percent", [100, 150])
    def test_percent_never_exceeds_the_subtotal(self, coupon_factory, percent):
        assert coupon_factory(f"P{percent}", "porcentaje", percent).discount_for(800) == 800


class TestLabel:
    def test_fixed_label_is_money(self, fixed_coupon):
        assert fixed_coupon.label == "$2.00"

    def test_percent_label(self, percent_coupon):
        assert percent_coupon.label == "10%"
