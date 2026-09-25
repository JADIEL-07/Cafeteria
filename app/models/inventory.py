"""Inventario: insumos, movimientos de stock y sugerencias de reposición.

Cada compra genera un egreso en la cartera (ver ``ledger.py``); cada pedido
aceptado descuenta los insumos de su receta.
"""
import math
from datetime import datetime

from sqlalchemy import func, or_, select

from ..extensions import db
from ..utils.money import line_cost
from .base import DomainError, InsufficientStock, unit_of_work
from .ledger import LedgerEntry

CAT_COFFEE = "cafe"
CAT_MILK = "leches"
CAT_BAKERY = "obrador"
CAT_PACKAGING = "empaques"
CATEGORIES = {
    CAT_COFFEE: "Café & Té",
    CAT_MILK: "Leches & Cremas",
    CAT_BAKERY: "Obrador & Repostería",
    CAT_PACKAGING: "Empaques Compostables",
}
UNITS = ("kg", "L", "briks", "uds")
COUNTABLE_UNITS = ("uds", "briks")

MOV_PURCHASE = "compra"
MOV_CONSUMPTION = "consumo"
MOV_ADJUSTMENT = "ajuste"
MOV_WASTE = "merma"
MOVEMENT_LABELS = {
    MOV_PURCHASE: "Compra",
    MOV_CONSUMPTION: "Consumo",
    MOV_ADJUSTMENT: "Ajuste de conteo",
    MOV_WASTE: "Merma",
}

STATUS_CRITICAL = "critico"
STATUS_WARNING = "alerta"
STATUS_OK = "optimo"
STATUS_LABELS = {STATUS_CRITICAL: "Crítico", STATUS_WARNING: "Alerta", STATUS_OK: "Óptimo"}


class InventoryItem(db.Model):
    __tablename__ = "inventory_items"

    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(30), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(200))
    category = db.Column(db.String(20), nullable=False, default=CAT_COFFEE, index=True)
    unit = db.Column(db.String(10), nullable=False, default="kg")
    stock = db.Column(db.Float, nullable=False, default=0)
    min_stock = db.Column(db.Float, nullable=False, default=0)
    unit_cost_cents = db.Column(db.Integer, nullable=False, default=0)  # último costo de compra
    supplier = db.Column(db.String(120))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now)

    movements = db.relationship("InventoryMovement", back_populates="item", order_by="InventoryMovement.id.desc()")

    # ---- estado ---------------------------------------------------------------
    @property
    def status(self):
        if self.min_stock <= 0:  # sin mínimo definido no hay alerta posible
            return STATUS_OK
        if self.stock <= self.min_stock * 0.5:
            return STATUS_CRITICAL
        if self.stock < self.min_stock:
            return STATUS_WARNING
        return STATUS_OK

    @property
    def status_label(self):
        return STATUS_LABELS[self.status]

    @property
    def category_label(self):
        return CATEGORIES.get(self.category, self.category)

    @property
    def value_cents(self):
        return line_cost(self.stock, self.unit_cost_cents)

    @property
    def is_countable(self):
        return self.unit in COUNTABLE_UNITS

    def suggested_qty(self):
        """Cantidad para volver a 2x el mínimo (enteros si es contable, medios si no)."""
        missing = max(self.min_stock * 2 - self.stock, 0)
        if self.is_countable:
            return math.ceil(missing)
        return math.ceil(missing * 2) / 2

    # ---- consultas ---------------------------------------------------------------
    @classmethod
    def listing(cls, category=None, query=None):
        stmt = select(cls).where(cls.is_active.is_(True))
        if category in CATEGORIES:
            stmt = stmt.where(cls.category == category)
        if query:
            like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            stmt = stmt.where(or_(cls.name.ilike(like, escape="\\"), cls.sku.ilike(like, escape="\\")))
        return db.session.scalars(stmt.order_by(cls.category, cls.name)).all()

    @classmethod
    def category_counts(cls):
        rows = db.session.execute(select(cls.category, func.count(cls.id)).where(cls.is_active.is_(True)).group_by(cls.category)).all()
        return dict(rows)

    @classmethod
    def low_stock(cls):
        items = db.session.scalars(select(cls).where(cls.is_active.is_(True))).all()
        low = [i for i in items if i.stock < i.min_stock]
        return sorted(low, key=lambda i: (i.stock / i.min_stock if i.min_stock else 1, i.name))

    @classmethod
    def kpis(cls):
        items = db.session.scalars(select(cls).where(cls.is_active.is_(True))).all()
        low = [i for i in items if i.stock < i.min_stock]
        return {
            "total_value_cents": sum(i.value_cents for i in items),
            "count": len(items),
            "ok_count": len(items) - len(low),
            "low_count": len(low),
            "critical_count": sum(1 for i in items if i.status == STATUS_CRITICAL),
        }

    @classmethod
    def restock_suggestions(cls):
        suggestions = []
        for item in cls.low_stock():
            qty = item.suggested_qty()
            suggestions.append({"item": item, "qty": qty, "cost_cents": line_cost(qty, item.unit_cost_cents)})
        return suggestions

    # ---- alta y edición ------------------------------------------------------------
    @classmethod
    def _next_sku(cls, category):
        prefix = {CAT_COFFEE: "CF", CAT_MILK: "LK", CAT_BAKERY: "OB", CAT_PACKAGING: "PKG"}.get(category, "IT")
        n = db.session.scalar(select(func.count(cls.id)).where(cls.category == category)) + 1
        while db.session.scalar(select(cls.id).where(cls.sku == f"MOK-{prefix}-{n:02d}")):
            n += 1
        return f"MOK-{prefix}-{n:02d}"

    @classmethod
    def create(cls, name, category, unit, min_stock, unit_cost_cents, supplier=None, sku=None, initial_stock=0, user=None, at=None):
        name = (name or "").strip()
        if len(name) < 2:
            raise DomainError("Escribe el nombre del insumo.")
        if category not in CATEGORIES:
            raise DomainError("Categoría no válida.")
        if unit not in UNITS:
            raise DomainError("Unidad no válida.")
        if min_stock < 0 or unit_cost_cents < 0 or initial_stock < 0:
            raise DomainError("Las cantidades no pueden ser negativas.")
        sku = (sku or "").strip().upper() or cls._next_sku(category)
        if db.session.scalar(select(cls.id).where(cls.sku == sku)):
            raise DomainError(f"Ya existe un insumo con el SKU {sku}.")
        with unit_of_work():
            item = cls(
                sku=sku,
                name=name,
                category=category,
                unit=unit,
                min_stock=min_stock,
                unit_cost_cents=unit_cost_cents,
                supplier=(supplier or "").strip() or None,
                stock=0,
            )
            db.session.add(item)
            db.session.flush()
            if initial_stock > 0:
                item._purchase(initial_stock, unit_cost_cents, supplier, user, at)
        return item

    def update_details(self, name, category, min_stock, unit_cost_cents, supplier):
        name = (name or "").strip()
        if len(name) < 2:
            raise DomainError("Escribe el nombre del insumo.")
        if category not in CATEGORIES:
            raise DomainError("Categoría no válida.")
        if min_stock < 0 or unit_cost_cents < 0:
            raise DomainError("Las cantidades no pueden ser negativas.")
        with unit_of_work():
            self.name = name
            self.category = category
            self.min_stock = min_stock
            self.unit_cost_cents = unit_cost_cents
            self.supplier = (supplier or "").strip() or None

    # ---- movimientos ---------------------------------------------------------------
    def _movement(self, kind, qty, reference=None, unit_cost_cents=None, total_cost_cents=None, user=None, at=None):
        movement = InventoryMovement(
            item_id=self.id,
            kind=kind,
            qty=qty,
            stock_after=self.stock,
            unit_cost_cents=unit_cost_cents,
            total_cost_cents=total_cost_cents,
            reference=reference[:160] if reference else None,
            user_id=user.id if user else None,
            created_at=at or datetime.now(),
        )
        db.session.add(movement)
        db.session.flush()
        return movement

    def _purchase(self, qty, unit_cost_cents, supplier=None, user=None, at=None):
        if qty <= 0:
            raise DomainError("La cantidad comprada debe ser mayor que cero.")
        if unit_cost_cents < 0:
            raise DomainError("El costo no puede ser negativo.")
        supplier = (supplier or "").strip() or self.supplier
        total = line_cost(qty, unit_cost_cents)
        self.stock = round(self.stock + qty, 3)
        self.unit_cost_cents = unit_cost_cents
        if supplier:
            self.supplier = supplier
        movement = self._movement(MOV_PURCHASE, qty, reference=supplier, unit_cost_cents=unit_cost_cents, total_cost_cents=total, user=user, at=at)
        LedgerEntry.record_purchase(movement, self, supplier=supplier, user=user, at=at)
        return movement

    def purchase(self, qty, unit_cost_cents, supplier=None, user=None, at=None):
        """Registra una compra: sube el stock y crea el egreso en la cartera."""
        with unit_of_work():
            return self._purchase(qty, unit_cost_cents, supplier, user, at)

    def adjust(self, new_stock, kind=MOV_ADJUSTMENT, note=None, user=None, at=None):
        """Fija el stock físico contado (ajuste) o descarta producto (merma)."""
        if new_stock < 0:
            raise DomainError("El stock no puede ser negativo.")
        if kind not in (MOV_ADJUSTMENT, MOV_WASTE):
            raise DomainError("Tipo de ajuste no válido.")
        delta = round(new_stock - self.stock, 3)
        if delta == 0:
            raise DomainError("El stock indicado es igual al actual.")
        if kind == MOV_WASTE and delta > 0:
            raise DomainError("Una merma sólo puede reducir el stock.")
        with unit_of_work():
            self.stock = round(new_stock, 3)
            return self._movement(kind, delta, reference=note, user=user, at=at)

    # ---- consumo por pedidos ---------------------------------------------------------
    @classmethod
    def check_available(cls, needs):
        """``needs`` = {item_id: cantidad}. Lanza ``InsufficientStock`` si falta algo."""
        if not needs:
            return
        items = {i.id: i for i in db.session.scalars(select(cls).where(cls.id.in_(list(needs))))}
        shortages = []
        for item_id, qty in needs.items():
            item = items.get(item_id)
            if item is not None and item.stock + 1e-9 < qty:
                shortages.append((item.name, round(qty, 3), round(item.stock, 3), item.unit))
        if shortages:
            raise InsufficientStock(shortages)

    @classmethod
    def consume(cls, needs, reference=None, user=None, at=None):
        for item_id, qty in needs.items():
            item = db.session.get(cls, item_id)
            if item is None or qty <= 0:
                continue
            item.stock = round(max(item.stock - qty, 0), 3)
            item._movement(MOV_CONSUMPTION, -round(qty, 3), reference=reference, user=user, at=at)

    def __repr__(self):
        return f"<InventoryItem {self.sku}>"


class InventoryMovement(db.Model):
    __tablename__ = "inventory_movements"

    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("inventory_items.id"), nullable=False, index=True)
    kind = db.Column(db.String(12), nullable=False)
    qty = db.Column(db.Float, nullable=False)  # con signo: + entra, - sale
    stock_after = db.Column(db.Float, nullable=False)
    unit_cost_cents = db.Column(db.Integer)
    total_cost_cents = db.Column(db.Integer)
    reference = db.Column(db.String(160))
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)

    item = db.relationship("InventoryItem", back_populates="movements")
    user = db.relationship("User")

    @property
    def kind_label(self):
        return MOVEMENT_LABELS.get(self.kind, self.kind)

    @classmethod
    def recent(cls, limit=12):
        return db.session.scalars(select(cls).order_by(cls.created_at.desc(), cls.id.desc()).limit(limit)).all()
