"""Panel: inventario de insumos, compras (egreso en cartera) y ajustes de stock."""
from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from ..extensions import db
from ..models import DomainError, InventoryItem, InventoryMovement
from ..models.inventory import CATEGORIES, MOV_ADJUSTMENT, MOV_WASTE, UNITS
from ..utils.auth import safe_next_url, staff_required
from ..utils.money import format_money, parse_money, parse_quantity
from ..utils.params import int_arg

bp = Blueprint("admin_inventory", __name__, url_prefix="/admin/inventario")


def _back():
    return redirect(safe_next_url(request.form.get("next"), url_for("admin_inventory.index")))


def _item_or_flash():
    item_id = int_arg(request.form.get("item_id"))
    item = db.session.get(InventoryItem, item_id) if item_id else None
    if item is None or not item.is_active:
        flash("Ese insumo no existe.", "error")
    return item


def _run(action, success):
    """Ejecuta una acción del modelo y traduce errores de negocio a mensajes."""
    try:
        action()
        flash(success, "success")
    except (DomainError, ValueError) as exc:
        flash(str(exc) if isinstance(exc, DomainError) else "Revisa los importes y cantidades: deben ser números válidos.", "error")
    return _back()


@bp.get("/")
@staff_required
def index():
    category = request.args.get("cat") if request.args.get("cat") in CATEGORIES else None
    query = request.args.get("q", "").strip()[:60]
    items = InventoryItem.listing(category, query or None)
    all_low = InventoryItem.low_stock()
    return render_template(
        "admin/inventory.html",
        items=items,
        all_items=InventoryItem.listing(),
        kpis=InventoryItem.kpis(),
        counts=InventoryItem.category_counts(),
        categories=CATEGORIES,
        units=UNITS,
        active_category=category,
        query=query,
        alerts=all_low[:2],
        suggestions=InventoryItem.restock_suggestions(),
        movements=InventoryMovement.recent(10),
    )


@bp.post("/nuevo")
@staff_required
def create():
    def action():
        InventoryItem.create(
            name=request.form.get("name"),
            category=request.form.get("category"),
            unit=request.form.get("unit"),
            min_stock=parse_quantity(request.form.get("min_stock") or "0", allow_zero=True),
            unit_cost_cents=parse_money(request.form.get("unit_cost") or "0"),
            supplier=request.form.get("supplier"),
            sku=request.form.get("sku"),
            initial_stock=parse_quantity(request.form.get("initial_stock") or "0", allow_zero=True),
            user=g.user,
        )

    return _run(action, "Insumo creado.")


@bp.post("/editar")
@staff_required
def edit():
    item = _item_or_flash()
    if item is None:
        return _back()
    return _run(
        lambda: item.update_details(
            name=request.form.get("name"),
            category=request.form.get("category"),
            min_stock=parse_quantity(request.form.get("min_stock") or "0", allow_zero=True),
            unit_cost_cents=parse_money(request.form.get("unit_cost") or "0"),
            supplier=request.form.get("supplier"),
        ),
        "Insumo actualizado.",
    )


@bp.post("/compra")
@staff_required
def purchase():
    item = _item_or_flash()
    if item is None:
        return _back()
    return _run(
        lambda: item.purchase(
            parse_quantity(request.form.get("qty")),
            parse_money(request.form.get("unit_cost")),
            supplier=request.form.get("supplier"),
            user=g.user,
        ),
        f"Compra registrada: {item.name}. Se descontó de la cartera como inversión en inventario.",
    )


@bp.post("/ajuste")
@staff_required
def adjust():
    item = _item_or_flash()
    if item is None:
        return _back()
    kind = MOV_WASTE if request.form.get("kind") == MOV_WASTE else MOV_ADJUSTMENT
    return _run(
        lambda: item.adjust(
            parse_quantity(request.form.get("new_stock"), allow_zero=True),
            kind=kind,
            note=request.form.get("note"),
            user=g.user,
        ),
        f"Stock de {item.name} actualizado.",
    )


@bp.post("/reabastecer")
@staff_required
def restock():
    """Compra sugerida: repone uno o todos los insumos bajos al último costo conocido."""
    ids = {n for n in (int_arg(i) for i in request.form.getlist("item_id")) if n}
    suggestions = [s for s in InventoryItem.restock_suggestions() if s["item"].id in ids]
    if not suggestions:
        flash("No hay insumos por reponer en esa selección.", "info")
        return _back()

    def action():
        for suggestion in suggestions:
            item = suggestion["item"]
            item.purchase(suggestion["qty"], item.unit_cost_cents, supplier=item.supplier, user=g.user)

    total = sum(s["cost_cents"] for s in suggestions)
    return _run(action, f"{len(suggestions)} compra(s) registradas por {format_money(total)}.")
