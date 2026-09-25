"""Usuarios: clientes, baristas y administradores (con programa Moka Club)."""
from datetime import datetime

from flask import current_app
from sqlalchemy import func, select
from werkzeug.security import check_password_hash, generate_password_hash

from ..extensions import db
from .base import DomainError

ROLE_CLIENT = "cliente"
ROLE_BARISTA = "barista"
ROLE_ADMIN = "admin"
ROLES = (ROLE_CLIENT, ROLE_BARISTA, ROLE_ADMIN)
STAFF_ROLES = (ROLE_BARISTA, ROLE_ADMIN)
ROLE_LABELS = {ROLE_CLIENT: "Cliente", ROLE_BARISTA: "Barista", ROLE_ADMIN: "Administrador"}

VIP_BEANS = 100      # a partir de aquí: Granos Dorados VIP
SILVER_BEANS = 25    # a partir de aquí: Grano Plata
MIN_PASSWORD = 8


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(160), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_CLIENT, index=True)
    beans = db.Column(db.Integer, nullable=False, default=0)
    is_active_account = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)
    last_login_at = db.Column(db.DateTime)

    # ---- creación / autenticación ----------------------------------------
    @classmethod
    def normalize_email(cls, email):
        return (email or "").strip().lower()

    @classmethod
    def get_by_email(cls, email):
        return db.session.scalar(select(cls).where(cls.email == cls.normalize_email(email)))

    @classmethod
    def create(cls, name, email, password, role=ROLE_CLIENT, beans=0, created_at=None, commit=True):
        name = (name or "").strip()
        email = cls.normalize_email(email)
        if len(name) < 2:
            raise DomainError("Escribe tu nombre completo.")
        if "@" not in email or "." not in email.rsplit("@", 1)[-1] or len(email) > 160:
            raise DomainError("Escribe un correo electrónico válido.")
        if len(password or "") < MIN_PASSWORD:
            raise DomainError(f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres.")
        if role not in ROLES:
            raise DomainError("Rol no válido.")
        if cls.get_by_email(email):
            raise DomainError("Ya existe una cuenta con ese correo.")
        user = cls(name=name, email=email, role=role, beans=beans, password_hash=generate_password_hash(password))
        if created_at:
            user.created_at = created_at
        db.session.add(user)
        if commit:
            db.session.commit()
        else:
            db.session.flush()
        return user

    @classmethod
    def authenticate(cls, email, password):
        user = cls.get_by_email(email)
        if user and user.is_active_account and check_password_hash(user.password_hash, password or ""):
            user.last_login_at = datetime.now()
            db.session.commit()
            return user
        return None

    def set_password(self, password):
        if len(password or "") < MIN_PASSWORD:
            raise DomainError(f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres.")
        self.password_hash = generate_password_hash(password)

    # ---- roles ------------------------------------------------------------
    @property
    def is_staff(self):
        return self.role in STAFF_ROLES

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    @property
    def role_label(self):
        return ROLE_LABELS.get(self.role, self.role)

    # ---- presentación -------------------------------------------------------
    @property
    def first_name(self):
        return self.name.split()[0] if self.name else ""

    @property
    def initials(self):
        parts = [p for p in self.name.split() if p]
        return "".join(p[0] for p in parts[:2]).upper() or "?"

    # ---- Moka Club ------------------------------------------------------------
    @property
    def tier(self):
        if self.role != ROLE_CLIENT:
            return "Equipo Moka"
        if self.beans >= VIP_BEANS:
            return "Granos Dorados VIP"
        if self.beans >= SILVER_BEANS:
            return "Grano Plata"
        return "Grano Bronce"

    @property
    def is_vip(self):
        return self.role == ROLE_CLIENT and self.beans >= VIP_BEANS

    @property
    def reward_goal(self):
        return current_app.config["REWARD_BEANS"]

    @property
    def reward_progress(self):
        return min(100, round(self.beans * 100 / self.reward_goal))

    @property
    def beans_to_reward(self):
        return max(self.reward_goal - self.beans, 0)

    def add_beans(self, amount):
        """Suma (o resta) granos sin dejar el saldo por debajo de cero."""
        self.beans = max(0, int(self.beans or 0) + int(amount))

    # ---- estadísticas (ficha de cliente en el panel) --------------------------
    def order_stats(self):
        from .order import ST_CANCELLED, Order  # import diferido: evita ciclos

        row = db.session.execute(
            select(func.count(Order.id), func.coalesce(func.sum(Order.total_cents), 0), func.max(Order.created_at)).where(
                Order.user_id == self.id, Order.status != ST_CANCELLED
            )
        ).one()
        count, total, last = row
        return {"count": count, "total_cents": total, "avg_cents": round(total / count) if count else 0, "last": last}

    def favorite_products(self, limit=3):
        from .order import ST_CANCELLED, Order, OrderItem

        rows = db.session.execute(
            select(OrderItem.name, func.sum(OrderItem.qty).label("n"))
            .join(Order, Order.id == OrderItem.order_id)
            .where(Order.user_id == self.id, Order.status != ST_CANCELLED)
            .group_by(OrderItem.name)
            .order_by(func.sum(OrderItem.qty).desc(), OrderItem.name)
            .limit(limit)
        ).all()
        return [name for name, _ in rows]

    def __repr__(self):
        return f"<User {self.email} ({self.role})>"
