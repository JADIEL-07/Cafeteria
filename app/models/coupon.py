"""Cupones de descuento."""
from sqlalchemy import select

from ..extensions import db
from ..utils.money import format_money
from .base import DomainError

KIND_FIXED = "fijo"
KIND_PERCENT = "porcentaje"


class Coupon(db.Model):
    __tablename__ = "coupons"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(30), nullable=False, unique=True)
    description = db.Column(db.String(160))
    kind = db.Column(db.String(12), nullable=False, default=KIND_FIXED)
    value = db.Column(db.Integer, nullable=False)  # centavos (fijo) o % entero (porcentaje)
    min_subtotal_cents = db.Column(db.Integer, nullable=False, default=0)
    max_uses = db.Column(db.Integer)  # None = ilimitado
    uses_count = db.Column(db.Integer, nullable=False, default=0)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    @classmethod
    def normalize(cls, code):
        return (code or "").strip().upper()

    @classmethod
    def find(cls, code):
        code = cls.normalize(code)
        if not code:
            return None
        return db.session.scalar(select(cls).where(cls.code == code))

    def check(self, subtotal_cents):
        """Lanza ``DomainError`` si el cupón no se puede usar con este subtotal."""
        if not self.is_active:
            raise DomainError("Este cupón ya no está disponible.")
        if self.max_uses is not None and self.uses_count >= self.max_uses:
            raise DomainError("Este cupón alcanzó su límite de usos.")
        if subtotal_cents < self.min_subtotal_cents:
            raise DomainError(f"Este cupón requiere un subtotal mínimo de {format_money(self.min_subtotal_cents)}.")

    def discount_for(self, subtotal_cents):
        if self.kind == KIND_PERCENT:
            amount = (subtotal_cents * self.value + 50) // 100
        else:
            amount = self.value
        return max(0, min(amount, subtotal_cents))

    @property
    def label(self):
        return f"{self.value}%" if self.kind == KIND_PERCENT else format_money(self.value)
