"""Pedidos: creación desde el carrito y ciclo de vida.

Regla de oro del negocio: un pedido sólo puede **aceptarse** (entrar a barra u
horno) cuando su pago está confirmado. Todas las transiciones son atómicas
(``UPDATE ... WHERE estado = esperado``), así un doble clic no duplica cobros
ni descuentos de inventario.
"""
import json
import secrets
from collections import defaultdict
from datetime import datetime

from flask import current_app
from sqlalchemy import func, or_, select

from ..extensions import db
from ..utils.money import basis_points
from .base import DomainError, OrderStateError, unit_of_work
from .inventory import InventoryItem
from .ledger import METHOD_CARD, METHOD_CASH, METHOD_LABELS, LedgerEntry
from .product import Modifier
from .user import User

ST_NEW = "nuevo"
ST_PREP = "en_barra"
ST_READY = "listo"
ST_DONE = "entregado"
ST_CANCELLED = "cancelado"
OPEN_STATUSES = (ST_NEW, ST_PREP, ST_READY)

PAY_PENDING = "pendiente"
PAY_PAID = "pagado"
PAY_REFUNDED = "reembolsado"

FULFILL_BAR = "barra"
FULFILL_TABLE = "mesa"
FULFILLMENT_LABELS = {FULFILL_BAR: "Retiro en barra", FULFILL_TABLE: "Servir en mesa"}

PAYMENT_METHODS = (METHOD_CARD, METHOD_CASH)

# Etapa visible (combina estado + pago) -> textos e iconos del diseño
STAGES = {
    "pending_payment": {
        "label": "PENDIENTE DE PAGO",
        "short": "Pendiente de pago",
        "icon": "hourglass_top",
        "badge": "bg-error-container text-on-error-container",
        "tile": "bg-error-container text-on-error-container",
    },
    "paid": {
        "label": "PAGO CONFIRMADO",
        "short": "Listo para aceptar",
        "icon": "task_alt",
        "badge": "bg-tertiary-fixed text-on-tertiary-fixed",
        "tile": "bg-tertiary-fixed text-on-tertiary-fixed",
    },
    "in_bar": {
        "label": "EN BARRA",
        "short": "En preparación",
        "icon": "coffee_maker",
        "badge": "bg-secondary-fixed text-on-secondary-fixed",
        "tile": "bg-secondary-fixed text-on-secondary-fixed",
    },
    "ready": {
        "label": "LISTO PARA RETIRO",
        "short": "Listo para retiro",
        "icon": "notifications_active",
        "badge": "bg-secondary text-on-secondary",
        "tile": "bg-secondary text-on-secondary",
    },
    "delivered": {
        "label": "ENTREGADO",
        "short": "Entregado",
        "icon": "check_circle",
        "badge": "bg-surface-container-highest text-on-surface-variant",
        "tile": "bg-surface-container text-on-surface-variant",
    },
    "cancelled": {
        "label": "CANCELADO",
        "short": "Cancelado",
        "icon": "cancel",
        "badge": "bg-surface-container-highest text-on-surface-variant",
        "tile": "bg-surface-container text-on-surface-variant",
    },
}

# Filtros de la pizarra de pedidos: clave -> (etiqueta, condición)
BOARD_FILTERS = {
    "activas": "Activas",
    "pendiente": "Pendiente de Pago",
    "pagado": "Pagado · Listo para Aceptar",
    "en_barra": "En Barra",
    "listo": "Listos",
    "cerrados": "Cerrados",
}


def _needs_condition(key):
    """Condición SQL de cada filtro de la pizarra."""
    if key == "pendiente":
        return (Order.status == ST_NEW) & (Order.payment_status == PAY_PENDING)
    if key == "pagado":
        return (Order.status == ST_NEW) & (Order.payment_status == PAY_PAID)
    if key == "en_barra":
        return Order.status == ST_PREP
    if key == "listo":
        return Order.status == ST_READY
    if key == "cerrados":
        return Order.status.in_((ST_DONE, ST_CANCELLED))
    return Order.status.in_(OPEN_STATUSES)  # activas


class Order(db.Model):
    __tablename__ = "orders"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), index=True)
    status = db.Column(db.String(12), nullable=False, default=ST_NEW, index=True)
    payment_status = db.Column(db.String(12), nullable=False, default=PAY_PENDING, index=True)
    payment_method = db.Column(db.String(12), nullable=False, default=METHOD_CARD)
    fulfillment = db.Column(db.String(8), nullable=False, default=FULFILL_BAR)
    table_number = db.Column(db.String(10))
    notes = db.Column(db.String(200))
    subtotal_cents = db.Column(db.Integer, nullable=False, default=0)
    discount_cents = db.Column(db.Integer, nullable=False, default=0)
    tax_cents = db.Column(db.Integer, nullable=False, default=0)
    total_cents = db.Column(db.Integer, nullable=False, default=0)
    fee_cents = db.Column(db.Integer, nullable=False, default=0)
    coupon_code = db.Column(db.String(30))
    pickup_pin = db.Column(db.String(4))
    beans_earned = db.Column(db.Integer, nullable=False, default=0)
    transaction_ref = db.Column(db.String(30))
    accepted_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    cancel_reason = db.Column(db.String(200))

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.now, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)
    paid_at = db.Column(db.DateTime)
    accepted_at = db.Column(db.DateTime)
    ready_at = db.Column(db.DateTime)
    delivered_at = db.Column(db.DateTime)
    cancelled_at = db.Column(db.DateTime)
    arrived_at = db.Column(db.DateTime)

    user = db.relationship("User", foreign_keys=[user_id])
    accepted_by = db.relationship("User", foreign_keys=[accepted_by_id])
    items = db.relationship("OrderItem", back_populates="order", cascade="all, delete-orphan", order_by="OrderItem.id")

    # ---- propiedades de presentación -----------------------------------------------
    @property
    def customer_name(self):
        return self.user.name if self.user else "Cliente"

    @property
    def item_count(self):
        return sum(i.qty for i in self.items)

    @property
    def stage(self):
        if self.status == ST_CANCELLED:
            return "cancelled"
        if self.status == ST_DONE:
            return "delivered"
        if self.status == ST_READY:
            return "ready"
        if self.status == ST_PREP:
            return "in_bar"
        return "paid" if self.payment_status == PAY_PAID else "pending_payment"

    @property
    def stage_info(self):
        return STAGES[self.stage]

    @property
    def payment_method_label(self):
        return METHOD_LABELS.get(self.payment_method, self.payment_method)

    @property
    def fulfillment_label(self):
        label = FULFILLMENT_LABELS.get(self.fulfillment, self.fulfillment)
        if self.fulfillment == FULFILL_TABLE and self.table_number:
            label += f" · Mesa {self.table_number}"
        return label

    @property
    def is_open(self):
        return self.status in OPEN_STATUSES

    @property
    def can_accept(self):
        return self.status == ST_NEW and self.payment_status == PAY_PAID

    @property
    def can_cancel(self):
        return self.status == ST_NEW

    @property
    def can_confirm_payment(self):
        return self.status == ST_NEW and self.payment_status == PAY_PENDING

    @property
    def events(self):
        """Bitácora del pedido (sirve de línea de tiempo y de auditoría)."""
        log = [("Pedido recibido", self.created_at, "receipt_long")]
        if self.paid_at:
            how = "en barra" if self.payment_method == METHOD_CASH else "con tarjeta"
            ref = f" · {self.transaction_ref}" if self.transaction_ref else ""
            log.append((f"Pago confirmado {how}{ref}", self.paid_at, "payments"))
        if self.accepted_at:
            who = f" por {self.accepted_by.name}" if self.accepted_by else ""
            log.append((f"Aceptado e iniciada la elaboración{who}", self.accepted_at, "coffee_maker"))
        if self.ready_at:
            log.append(("Listo para retiro", self.ready_at, "notifications_active"))
        if self.delivered_at:
            log.append(("Entregado al cliente", self.delivered_at, "check_circle"))
        if self.cancelled_at:
            extra = " · reembolso emitido" if self.payment_status == PAY_REFUNDED else ""
            log.append((f"Cancelado{extra}", self.cancelled_at, "cancel"))
        return sorted(log, key=lambda e: e[1])

    # ---- creación ------------------------------------------------------------------------
    @classmethod
    def create_from_cart(cls, user, summary, payment_method, fulfillment=FULFILL_BAR, table=None, notes=None, at=None):
        """Convierte el carrito valorizado en pedido. Con tarjeta el pago se confirma al instante."""
        if user is None:
            raise DomainError("Inicia sesión para completar tu pedido.")
        if not summary.lines:
            raise DomainError("Tu carrito está vacío.")
        if payment_method not in PAYMENT_METHODS:
            raise DomainError("Elige un método de pago.")
        if fulfillment not in FULFILLMENT_LABELS:
            fulfillment = FULFILL_BAR
        table = (table or "").strip()[:10]
        if fulfillment == FULFILL_TABLE and not table:
            raise DomainError("Indica tu número de mesa para servir en mesa.")
        at = at or datetime.now()

        with unit_of_work():
            order = cls(
                user_id=user.id,
                status=ST_NEW,
                payment_status=PAY_PENDING,
                payment_method=payment_method,
                fulfillment=fulfillment,
                table_number=table or None,
                notes=(notes or "").strip()[:200] or None,
                subtotal_cents=summary.subtotal_cents,
                discount_cents=summary.discount_cents,
                tax_cents=summary.tax_cents,
                total_cents=summary.total_cents,
                coupon_code=summary.coupon.code if summary.coupon else None,
                pickup_pin=f"{secrets.randbelow(9000) + 1000}",
                created_at=at,
                updated_at=at,
            )
            db.session.add(order)
            db.session.flush()
            order.code = f"MK-{8000 + order.id}"
            for line in summary.lines:
                db.session.add(
                    OrderItem(
                        order_id=order.id,
                        product_id=line.product.id,
                        name=line.product.name,
                        options_text=line.options_text,
                        options_json=json.dumps(line.option_ids),
                        notes=line.notes or None,
                        unit_price_cents=line.unit_cents,
                        qty=line.qty,
                        line_total_cents=line.line_cents,
                    )
                )
            if summary.coupon:
                summary.coupon.uses_count += 1
            db.session.flush()
            db.session.refresh(order)
            if payment_method == METHOD_CARD:
                # Pasarela simulada: aprobación inmediata.
                order._confirm_payment(reference=f"CH-{order.id:05d}", at=at)
        return order

    # ---- transiciones --------------------------------------------------------------------
    def _claim(self, expect_status, expect_payment=None, **changes):
        """UPDATE atómico: sólo cambia si el pedido sigue en el estado esperado."""
        conditions = [Order.id == self.id, Order.status == expect_status]
        if expect_payment is not None:
            conditions.append(Order.payment_status == expect_payment)
        result = db.session.execute(db.update(Order).where(*conditions).values(**changes).execution_options(synchronize_session=False))
        if result.rowcount != 1:
            return False
        db.session.refresh(self)
        return True

    def _confirm_payment(self, reference=None, at=None, by=None):
        at = at or datetime.now()
        fee = basis_points(self.total_cents, current_app.config["CARD_FEE_BP"]) if self.payment_method == METHOD_CARD else 0
        beans = self.total_cents // 100
        ok = self._claim(
            ST_NEW,
            PAY_PENDING,
            payment_status=PAY_PAID,
            paid_at=at,
            fee_cents=fee,
            beans_earned=beans,
            transaction_ref=reference or f"EF-{self.id:05d}",
        )
        if not ok:
            raise OrderStateError("Este pedido ya no está pendiente de pago.")
        LedgerEntry.record_sale(self, at=at, user=by)
        if self.user:
            self.user.add_beans(beans)

    def confirm_payment(self, by=None, at=None):
        """Barra confirma que recibió el pago en efectivo."""
        with unit_of_work():
            self._confirm_payment(reference=None, at=at, by=by)

    def ingredient_needs(self):
        """Insumos que consume el pedido: receta de cada producto + opciones elegidas."""
        needs = defaultdict(float)
        for item in self.items:
            if item.product:
                for ing in item.product.ingredients:
                    needs[ing.item_id] += ing.qty * item.qty
            for modifier_id in item.modifier_ids:
                modifier = db.session.get(Modifier, modifier_id)
                if modifier and modifier.inventory_item_id and modifier.inventory_qty:
                    needs[modifier.inventory_item_id] += modifier.inventory_qty * item.qty
        return {item_id: round(qty, 3) for item_id, qty in needs.items()}

    def accept(self, by, at=None):
        """Acepta el pedido: exige pago confirmado y descuenta el inventario."""
        if self.status != ST_NEW:
            raise OrderStateError("Este pedido ya fue procesado.")
        if self.payment_status != PAY_PAID:
            raise OrderStateError("Bloqueado: el pedido no tiene el pago confirmado. Valida el cobro antes de aceptarlo.")
        at = at or datetime.now()
        with unit_of_work():
            needs = self.ingredient_needs()
            InventoryItem.check_available(needs)
            ok = self._claim(ST_NEW, PAY_PAID, status=ST_PREP, accepted_at=at, accepted_by_id=by.id if by else None)
            if not ok:
                raise OrderStateError("Este pedido ya fue procesado.")
            InventoryItem.consume(needs, reference=self.code, user=by, at=at)

    def mark_ready(self, at=None):
        with unit_of_work():
            if not self._claim(ST_PREP, ready_at=at or datetime.now(), status=ST_READY):
                raise OrderStateError("Sólo se puede marcar como listo un pedido en barra.")

    def mark_delivered(self, at=None):
        with unit_of_work():
            if not self._claim(ST_READY, delivered_at=at or datetime.now(), status=ST_DONE):
                raise OrderStateError("Sólo se puede entregar un pedido que está listo.")

    def cancel(self, by=None, reason=None, at=None):
        """Cancela un pedido aún no aceptado. Si ya estaba pagado, emite el reembolso."""
        at = at or datetime.now()
        reason = (reason or "").strip()[:200] or None
        with unit_of_work():
            if self._claim(ST_NEW, PAY_PAID, status=ST_CANCELLED, payment_status=PAY_REFUNDED, cancelled_at=at, cancel_reason=reason):
                LedgerEntry.record_refund(self, at=at, user=by)
                if self.user:
                    self.user.add_beans(-self.beans_earned)
            elif not self._claim(ST_NEW, PAY_PENDING, status=ST_CANCELLED, cancelled_at=at, cancel_reason=reason):
                raise OrderStateError("Este pedido ya está en preparación y no se puede cancelar.")

    def mark_arrived(self):
        if not self.is_open:
            raise OrderStateError("Este pedido ya no está activo.")
        with unit_of_work():
            self.arrived_at = datetime.now()

    def update_notes(self, notes):
        if self.status != ST_NEW:
            raise OrderStateError("Sólo puedes editar las notas antes de que el barista acepte el pedido.")
        with unit_of_work():
            self.notes = (notes or "").strip()[:200] or None

    # ---- consultas -----------------------------------------------------------------------
    @classmethod
    def get_by_code(cls, code):
        return db.session.scalar(select(cls).where(cls.code == (code or "").strip().upper()))

    @classmethod
    def for_user(cls, user, limit=None):
        stmt = select(cls).where(cls.user_id == user.id).order_by(cls.created_at.desc(), cls.id.desc())
        if limit:
            stmt = stmt.limit(limit)
        return db.session.scalars(stmt).all()

    @classmethod
    def board(cls, key="activas", query=None, page=1, per_page=8):
        """Pizarra del panel: pedidos filtrados y paginados."""
        stmt = select(cls)
        if key != "todas":
            stmt = stmt.where(_needs_condition(key if key in BOARD_FILTERS else "activas"))
        if query:
            like = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            stmt = stmt.outerjoin(User, User.id == cls.user_id).where(
                or_(cls.code.ilike(like, escape="\\"), User.name.ilike(like, escape="\\"))
            )
        if key in ("cerrados", "todas"):
            stmt = stmt.order_by(cls.created_at.desc(), cls.id.desc())
        else:  # cola de trabajo: primero el más antiguo
            stmt = stmt.order_by(cls.created_at.asc(), cls.id.asc())
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    @classmethod
    def filter_counts(cls):
        counts = {}
        for key in BOARD_FILTERS:
            counts[key] = db.session.scalar(select(func.count(cls.id)).where(_needs_condition(key))) or 0
        return counts

    @classmethod
    def pending_payments(cls):
        """(cantidad, importe) de pedidos aún no cobrados y no cancelados."""
        row = db.session.execute(
            select(func.count(cls.id), func.coalesce(func.sum(cls.total_cents), 0)).where(_needs_condition("pendiente"))
        ).one()
        return row[0], row[1]

    @classmethod
    def avg_prep_minutes(cls, since):
        rows = db.session.execute(
            select(cls.accepted_at, cls.ready_at).where(cls.accepted_at.is_not(None), cls.ready_at.is_not(None), cls.ready_at >= since)
        ).all()
        if not rows:
            return None
        return round(sum((ready - accepted).total_seconds() for accepted, ready in rows) / len(rows) / 60, 1)

    @classmethod
    def signature(cls):
        """Huella del estado global de pedidos (para refrescar el panel al vuelo)."""
        count, last = db.session.execute(select(func.count(cls.id), func.max(cls.updated_at))).one()
        return f"{count}:{last.isoformat() if last else ''}"

    @classmethod
    def estimated_wait(cls):
        """Rango de espera estimado según la cola de barra."""
        queue = db.session.scalar(
            select(func.count(cls.id)).where(
                or_(cls.status == ST_PREP, (cls.status == ST_NEW) & (cls.payment_status == PAY_PAID))
            )
        ) or 0
        low = min(5 + 2 * queue, 30)
        return low, low + 4

    def __repr__(self):
        return f"<Order {self.code}>"


class OrderItem(db.Model):
    __tablename__ = "order_items"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("orders.id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("products.id"), nullable=False)
    name = db.Column(db.String(120), nullable=False)          # foto del nombre al comprar
    options_text = db.Column(db.String(300))                   # "Mediano 16 oz • Leche de Avena"
    options_json = db.Column(db.String(200), nullable=False, default="[]")
    notes = db.Column(db.String(200))
    unit_price_cents = db.Column(db.Integer, nullable=False)
    qty = db.Column(db.Integer, nullable=False, default=1)
    line_total_cents = db.Column(db.Integer, nullable=False)

    order = db.relationship("Order", back_populates="items")
    product = db.relationship("Product")

    @property
    def modifier_ids(self):
        try:
            return [int(i) for i in json.loads(self.options_json or "[]")]
        except (ValueError, TypeError):
            return []
