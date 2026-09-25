"""Cartera: libro de movimientos de dinero.

* ``venta``              -> ingreso por un pedido cobrado (con su comisión de pasarela)
* ``reembolso``          -> egreso por un pedido cobrado que se canceló
* ``compra_inventario``  -> egreso por una compra de insumos
* ``ajuste``             -> ingreso o egreso manual (correcciones de caja)

Con eso la cartera responde a las tres preguntas del negocio:

    Invertido  = compras de inventario
    Recuperado = ventas - comisiones - reembolsos
    Ganancia   = Recuperado - Invertido (+/- ajustes manuales)
"""
from collections import defaultdict
from datetime import datetime

from flask import current_app
from sqlalchemy import func, select

from ..extensions import db
from .base import DomainError, unit_of_work

KIND_IN = "ingreso"
KIND_OUT = "egreso"

CONCEPT_SALE = "venta"
CONCEPT_REFUND = "reembolso"
CONCEPT_PURCHASE = "compra_inventario"
CONCEPT_ADJUSTMENT = "ajuste"
CONCEPT_LABELS = {
    CONCEPT_SALE: "Venta",
    CONCEPT_REFUND: "Reembolso",
    CONCEPT_PURCHASE: "Compra de inventario",
    CONCEPT_ADJUSTMENT: "Ajuste manual",
}

METHOD_CASH = "efectivo"
METHOD_CARD = "tarjeta"
METHOD_LABELS = {METHOD_CASH: "Efectivo en barra", METHOD_CARD: "Tarjeta / Apple Pay"}

SLOT_FIRST_HOUR = 6
SLOT_LAST_HOUR = 22
SLOT_HOURS = 2


class LedgerEntry(db.Model):
    __tablename__ = "ledger_entries"

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(10), nullable=False, index=True)
    concept = db.Column(db.String(20), nullable=False, index=True)
    amount_cents = db.Column(db.Integer, nullable=False)  # siempre positivo
    fee_cents = db.Column(db.Integer, nullable=False, default=0)  # comisión de pasarela (ventas con tarjeta)
    method = db.Column(db.String(12))
    party = db.Column(db.String(120))  # cliente o proveedor
    description = db.Column(db.String(240))
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), index=True)
    movement_id = db.Column(db.Integer, db.ForeignKey("inventory_movements.id"))
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)

    order = db.relationship("Order")
    created_by = db.relationship("User")

    # ---- presentación ---------------------------------------------------------
    @property
    def tx_id(self):
        return f"TX-{self.id:05d}"

    @property
    def concept_label(self):
        return CONCEPT_LABELS.get(self.concept, self.concept)

    @property
    def method_label(self):
        return METHOD_LABELS.get(self.method, "—")

    @property
    def net_cents(self):
        """Efecto neto sobre el dinero: + entra, - sale."""
        if self.kind == KIND_IN:
            return self.amount_cents - self.fee_cents
        return -self.amount_cents

    @property
    def status(self):
        """(etiqueta, tono) para la insignia de la tabla."""
        if self.concept == CONCEPT_SALE:
            return ("Efectivo confirmado", "ok") if self.method == METHOD_CASH else ("Confirmado", "ok")
        if self.concept == CONCEPT_REFUND:
            return ("Reembolsado", "bad")
        if self.concept == CONCEPT_PURCHASE:
            return ("Compra registrada", "warn")
        return ("Ajuste manual", "neutral")

    # ---- alta de movimientos ------------------------------------------------------
    @classmethod
    def record_sale(cls, order, at=None, user=None):
        entry = cls(
            kind=KIND_IN,
            concept=CONCEPT_SALE,
            amount_cents=order.total_cents,
            fee_cents=order.fee_cents,
            method=order.payment_method,
            party=order.customer_name,
            description=f"Pedido {order.code}",
            order_id=order.id,
            created_by_id=user.id if user else None,
            created_at=at or datetime.now(),
        )
        db.session.add(entry)
        return entry

    @classmethod
    def record_refund(cls, order, at=None, user=None):
        entry = cls(
            kind=KIND_OUT,
            concept=CONCEPT_REFUND,
            amount_cents=order.total_cents,
            method=order.payment_method,
            party=order.customer_name,
            description=f"Reembolso del pedido {order.code}",
            order_id=order.id,
            created_by_id=user.id if user else None,
            created_at=at or datetime.now(),
        )
        db.session.add(entry)
        return entry

    @classmethod
    def record_purchase(cls, movement, item, supplier=None, user=None, at=None):
        qty = f"{movement.qty:g}"
        entry = cls(
            kind=KIND_OUT,
            concept=CONCEPT_PURCHASE,
            amount_cents=movement.total_cost_cents or 0,
            party=supplier,
            description=f"Compra: {item.name} ({qty} {item.unit})",
            movement_id=movement.id,
            created_by_id=user.id if user else None,
            created_at=at or datetime.now(),
        )
        db.session.add(entry)
        return entry

    @classmethod
    def record_adjustment(cls, kind, amount_cents, description, method=METHOD_CASH, user=None, at=None):
        """Ajuste manual de cuentas (correcciones de caja, otros gastos, etc.)."""
        description = (description or "").strip()
        if kind not in (KIND_IN, KIND_OUT):
            raise DomainError("Tipo de ajuste no válido.")
        if amount_cents <= 0:
            raise DomainError("El importe debe ser mayor que cero.")
        if len(description) < 3:
            raise DomainError("Explica brevemente el motivo del ajuste.")
        if method not in METHOD_LABELS:
            method = None
        with unit_of_work():
            entry = cls(
                kind=kind,
                concept=CONCEPT_ADJUSTMENT,
                amount_cents=amount_cents,
                method=method,
                party=user.name if user else None,
                description=description[:240],
                created_by_id=user.id if user else None,
                created_at=at or datetime.now(),
            )
            db.session.add(entry)
        return entry

    # ---- consultas ------------------------------------------------------------------
    @classmethod
    def _range(cls, stmt, start, end):
        if start is not None:
            stmt = stmt.where(cls.created_at >= start)
        if end is not None:
            stmt = stmt.where(cls.created_at < end)
        return stmt

    @classmethod
    def summary(cls, start=None, end=None):
        """Totales del período: invertido, recuperado, ganancia y desglose por método."""
        stmt = cls._range(
            select(
                cls.kind,
                cls.concept,
                cls.method,
                func.coalesce(func.sum(cls.amount_cents), 0),
                func.coalesce(func.sum(cls.fee_cents), 0),
                func.count(cls.id),
            ).group_by(cls.kind, cls.concept, cls.method),
            start,
            end,
        )
        s = defaultdict(int)
        methods = {m: defaultdict(int) for m in METHOD_LABELS}
        for kind, concept, method, amount, fee, count in db.session.execute(stmt):
            if concept == CONCEPT_SALE:
                s["gross_sales"] += amount
                s["fees"] += fee
                s["sales_count"] += count
                if method in methods:
                    methods[method]["sales"] += amount
                    methods[method]["fees"] += fee
            elif concept == CONCEPT_REFUND:
                s["refunds"] += amount
                if method in methods:
                    methods[method]["refunds"] += amount
            elif concept == CONCEPT_PURCHASE:
                s["invested"] += amount
                s["purchases_count"] += count
            elif concept == CONCEPT_ADJUSTMENT:
                if kind == KIND_IN:
                    s["adj_in"] += amount
                else:
                    s["adj_out"] += amount
                if method in methods:
                    methods[method]["adj"] += amount if kind == KIND_IN else -amount
        recovered = s["gross_sales"] - s["fees"] - s["refunds"]
        adjustments = s["adj_in"] - s["adj_out"]
        profit = recovered - s["invested"] + adjustments
        result = {
            "gross_sales": s["gross_sales"],
            "fees": s["fees"],
            "refunds": s["refunds"],
            "invested": s["invested"],
            "adjustments": adjustments,
            "recovered": recovered,
            "profit": profit,
            "sales_count": s["sales_count"],
            "purchases_count": s["purchases_count"],
            "recovery_pct": round(recovered * 100 / s["invested"], 1) if s["invested"] else None,
            "margin_pct": round(profit * 100 / recovered, 1) if recovered > 0 else None,
        }
        for method, m in methods.items():
            result[f"{method}_net"] = m["sales"] - m["fees"] - m["refunds"] + m["adj"]
            result[f"{method}_sales"] = m["sales"]
        return result

    @classmethod
    def cash_drawer(cls, day_start, day_end):
        """Arqueo de la caja física del día."""
        s = cls.summary(day_start, day_end)
        opening = current_app.config["CASH_FLOAT_CENTS"]
        return {"opening": opening, "collected": s["efectivo_net"], "expected": opening + s["efectivo_net"]}

    @classmethod
    def hourly_sales(cls, start=None, end=None):
        """Ventas por franja horaria y método (para el gráfico de barras)."""
        stmt = cls._range(
            select(cls.created_at, cls.amount_cents, cls.method).where(cls.concept == CONCEPT_SALE), start, end
        )
        slots = []
        for hour in range(SLOT_FIRST_HOUR, SLOT_LAST_HOUR, SLOT_HOURS):
            slots.append({"label": f"{hour:02d}-{hour + SLOT_HOURS:02d}", "efectivo": 0, "tarjeta": 0})
        for created_at, amount, method in db.session.execute(stmt):
            index = (min(max(created_at.hour, SLOT_FIRST_HOUR), SLOT_LAST_HOUR - 1) - SLOT_FIRST_HOUR) // SLOT_HOURS
            if method in ("efectivo", "tarjeta"):
                slots[index][method] += amount
        peak = max((max(s["efectivo"], s["tarjeta"]) for s in slots), default=0)
        for slot in slots:
            slot["efectivo_pct"] = round(slot["efectivo"] * 100 / peak) if peak else 0
            slot["tarjeta_pct"] = round(slot["tarjeta"] * 100 / peak) if peak else 0
        return slots

    @classmethod
    def entries_query(cls, start=None, end=None, method=None, concept=None):
        stmt = cls._range(select(cls), start, end)
        if method in METHOD_LABELS:
            stmt = stmt.where(cls.method == method)
        if concept in CONCEPT_LABELS:
            stmt = stmt.where(cls.concept == concept)
        return stmt.order_by(cls.created_at.desc(), cls.id.desc())

    @classmethod
    def transactions(cls, start=None, end=None, method=None, concept=None, page=1, per_page=10):
        return db.paginate(cls.entries_query(start, end, method, concept), page=page, per_page=per_page, error_out=False)

    def __repr__(self):
        return f"<LedgerEntry {self.tx_id} {self.concept} {self.amount_cents}>"
