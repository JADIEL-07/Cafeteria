"""Productos favoritos de cada cliente."""
from datetime import datetime

from sqlalchemy import select

from ..extensions import db
from .product import Product


class Favorite(db.Model):
    __tablename__ = "favorites"
    __table_args__ = (db.UniqueConstraint("user_id", "product_id", name="uq_favorite_user_product"),)

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    @classmethod
    def ids_for(cls, user):
        if user is None:
            return set()
        return set(db.session.scalars(select(cls.product_id).where(cls.user_id == user.id)))

    @classmethod
    def products_for(cls, user):
        return db.session.scalars(
            select(Product)
            .join(cls, cls.product_id == Product.id)
            .where(cls.user_id == user.id, Product.is_active.is_(True))
            .order_by(cls.created_at.desc())
        ).all()

    @classmethod
    def toggle(cls, user, product):
        """Alterna el favorito y devuelve ``True`` si quedó marcado."""
        existing = db.session.scalar(select(cls).where(cls.user_id == user.id, cls.product_id == product.id))
        if existing:
            db.session.delete(existing)
            db.session.commit()
            return False
        db.session.add(cls(user_id=user.id, product_id=product.id))
        db.session.commit()
        return True
