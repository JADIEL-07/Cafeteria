"""Carrito de compras guardado en la sesión.

En la sesión sólo se guardan ids y cantidades; los precios se recalculan siempre
desde la base de datos, así nadie puede alterar importes desde el navegador.
"""
import hashlib
from dataclasses import dataclass, field

from flask import current_app, session
from sqlalchemy import select

from ..extensions import db
from ..utils.money import basis_points
from ..utils.params import int_arg
from .base import CartError, DomainError
from .coupon import Coupon
from .order import FULFILL_BAR, FULFILLMENT_LABELS
from .product import GROUP_EXTRA, Modifier, Product

MAX_LINE_QTY = 20
MAX_LINES = 30
MAX_NOTE = 160


@dataclass
class CartLine:
    key: str
    product: Product
    qty: int
    modifiers: list
    notes: str
    unit_cents: int

    @property
    def line_cents(self):
        return self.unit_cents * self.qty

    @property
    def option_ids(self):
        return [m.id for m in self.modifiers]

    @property
    def options_text(self):
        return " • ".join(m.name for m in self.modifiers)


@dataclass
class CartSummary:
    lines: list = field(default_factory=list)
    coupon: Coupon = None
    coupon_error: str = None
    subtotal_cents: int = 0
    discount_cents: int = 0
    tax_cents: int = 0
    total_cents: int = 0
    mode: str = FULFILL_BAR
    table: str = ""

    @property
    def count(self):
        return sum(line.qty for line in self.lines)

    @property
    def is_empty(self):
        return not self.lines

    @property
    def beans_estimate(self):
        return self.total_cents // 100

    @property
    def tax_percent(self):
        return current_app.config["TAX_BP"] / 100


class Cart:
    KEY = "cart"

    def __init__(self, store=None):
        self._store = session if store is None else store

    # ---- estado crudo -----------------------------------------------------------
    def _data(self):
        data = self._store.get(self.KEY)
        if not isinstance(data, dict):
            data = {}
        return {
            "lines": [l for l in data.get("lines", []) if isinstance(l, dict)],
            "coupon": data.get("coupon"),
            "mode": data.get("mode") if data.get("mode") in FULFILLMENT_LABELS else FULFILL_BAR,
            "table": str(data.get("table") or "")[:10],
        }

    def _save(self, data):
        self._store[self.KEY] = data  # reasignar marca la sesión como modificada

    def clear(self):
        self._store.pop(self.KEY, None)

    def count(self):
        """Unidades en el carrito (para el globo del encabezado)."""
        return sum(int(l.get("qty", 0)) for l in self._data()["lines"])

    def mode_info(self):
        """(modo de entrega, número de mesa) sin valorizar el carrito."""
        data = self._data()
        return data["mode"], data["table"]

    # ---- edición --------------------------------------------------------------------
    @staticmethod
    def line_key(product_id, modifier_ids, notes):
        raw = f"{product_id}|{','.join(str(i) for i in sorted(modifier_ids))}|{notes}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]

    @staticmethod
    def resolve_modifiers(product, selections, extras):
        """Valida las opciones elegidas y completa con los valores por defecto."""
        chosen = []
        for group in product.option_group_list:
            if group == GROUP_EXTRA:
                ids = set()
                for raw in extras or []:
                    modifier_id = int_arg(raw)
                    if modifier_id is None:
                        raise CartError("Opción no válida.")
                    ids.add(modifier_id)
                if len(ids) > 10:
                    raise CartError("Demasiados extras.")
                if ids:
                    found = db.session.scalars(
                        select(Modifier).where(Modifier.id.in_(ids), Modifier.group == GROUP_EXTRA, Modifier.is_active.is_(True))
                    ).all()
                    if len(found) != len(ids):
                        raise CartError("Uno de los extras ya no está disponible.")
                    chosen.extend(sorted(found, key=lambda m: (m.sort_order, m.id)))
                continue
            raw = (selections or {}).get(group)
            if raw in (None, ""):
                modifier = Modifier.default_for(group)
            else:
                modifier_id = int_arg(raw)
                modifier = db.session.get(Modifier, modifier_id) if modifier_id else None
                if modifier is None or modifier.group != group or not modifier.is_active:
                    raise CartError("La opción elegida ya no está disponible.")
            if modifier is not None:
                chosen.append(modifier)
        return chosen

    def add(self, product, selections=None, extras=None, notes="", qty=1):
        if product is None or not product.is_active:
            raise CartError("Este producto ya no está disponible.")
        qty = max(1, min(int(qty), MAX_LINE_QTY))
        notes = (notes or "").strip()[:MAX_NOTE]
        modifiers = self.resolve_modifiers(product, selections, extras)
        key = self.line_key(product.id, [m.id for m in modifiers], notes)
        data = self._data()
        for line in data["lines"]:
            if line.get("key") == key:
                line["qty"] = min(int(line["qty"]) + qty, MAX_LINE_QTY)
                break
        else:
            if len(data["lines"]) >= MAX_LINES:
                raise CartError("Tu carrito tiene demasiados productos distintos.")
            data["lines"].append({"key": key, "pid": product.id, "mods": [m.id for m in modifiers], "notes": notes, "qty": qty})
        self._save(data)
        return key

    def set_qty(self, key, qty):
        data = self._data()
        qty = max(0, min(int(qty), MAX_LINE_QTY))
        data["lines"] = [
            {**l, "qty": qty} if l.get("key") == key else l for l in data["lines"] if not (l.get("key") == key and qty == 0)
        ]
        self._save(data)

    def change_qty(self, key, delta):
        for line in self._data()["lines"]:
            if line.get("key") == key:
                self.set_qty(key, max(1, int(line["qty"]) + delta))
                return

    def remove(self, key):
        data = self._data()
        data["lines"] = [l for l in data["lines"] if l.get("key") != key]
        self._save(data)

    def set_mode(self, mode, table=""):
        if mode not in FULFILLMENT_LABELS:
            raise CartError("Modo de entrega no válido.")
        data = self._data()
        data["mode"] = mode
        data["table"] = (table or "").strip()[:10] if mode != FULFILL_BAR else ""
        self._save(data)

    def apply_coupon(self, code):
        coupon = Coupon.find(code)
        if coupon is None:
            raise CartError("El cupón no existe.")
        summary = self.summary()
        try:
            coupon.check(summary.subtotal_cents)
        except DomainError as exc:
            raise CartError(str(exc))
        data = self._data()
        data["coupon"] = coupon.code
        self._save(data)
        return coupon

    def remove_coupon(self):
        data = self._data()
        data["coupon"] = None
        self._save(data)

    # ---- valorización -------------------------------------------------------------------
    def summary(self):
        data = self._data()
        lines = []
        for raw in data["lines"]:
            product = db.session.get(Product, raw.get("pid"))
            if product is None or not product.is_active:
                continue
            mod_ids = [int(i) for i in raw.get("mods", [])]
            by_id = {m.id: m for m in db.session.scalars(select(Modifier).where(Modifier.id.in_(mod_ids)))} if mod_ids else {}
            modifiers = [by_id[i] for i in mod_ids if i in by_id]
            unit = product.price_cents + sum(m.price_delta_cents for m in modifiers)
            lines.append(
                CartLine(
                    key=raw.get("key", ""),
                    product=product,
                    qty=max(1, int(raw.get("qty", 1))),
                    modifiers=modifiers,
                    notes=raw.get("notes", ""),
                    unit_cents=unit,
                )
            )
        subtotal = sum(l.line_cents for l in lines)
        coupon, coupon_error, discount = None, None, 0
        if data["coupon"]:
            candidate = Coupon.find(data["coupon"])
            try:
                if candidate is None:
                    raise DomainError("El cupón ya no existe.")
                candidate.check(subtotal)
                coupon = candidate
                discount = candidate.discount_for(subtotal)
            except DomainError as exc:
                coupon_error = str(exc)
        tax = basis_points(subtotal - discount, current_app.config["TAX_BP"])
        return CartSummary(
            lines=lines,
            coupon=coupon,
            coupon_error=coupon_error,
            subtotal_cents=subtotal,
            discount_cents=discount,
            tax_cents=tax,
            total_cents=subtotal - discount + tax,
            mode=data["mode"],
            table=data["table"],
        )
