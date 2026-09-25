"""Panel: pizarra de pedidos (validar cobro, aceptar, marcar listo, entregar)."""
from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from ..extensions import db
from ..models import DomainError, LedgerEntry, Order
from ..models.order import BOARD_FILTERS
from ..utils.auth import safe_next_url, staff_required
from ..utils.params import page_arg
from ..utils.timefmt import period_range

bp = Blueprint("admin_orders", __name__, url_prefix="/admin")


@bp.get("/")
@staff_required
def dashboard():
    return redirect(url_for("admin_orders.index"))


@bp.get("/pedidos")
@staff_required
def index():
    key = request.args.get("estado", "activas")
    if key not in BOARD_FILTERS and key != "todas":
        key = "activas"
    query = request.args.get("q", "").strip()[:60]
    page = page_arg(request.args.get("page"))
    board = Order.board(key, query or None, page)

    selected = None
    code = request.args.get("ver")
    if code:
        selected = Order.get_by_code(code)
    if selected is None and board.items:
        selected = board.items[0]

    today_start, tomorrow = period_range("hoy")
    today = LedgerEntry.summary(today_start, tomorrow)
    pending_count, pending_amount = Order.pending_payments()
    counts = Order.filter_counts()
    avg_prep = Order.avg_prep_minutes(today_start)
    return render_template(
        "admin/orders.html",
        board=board,
        selected=selected,
        counts=counts,
        filters=BOARD_FILTERS,
        active_filter=key,
        query=query,
        kpis={
            "pending_count": pending_count,
            "pending_amount": pending_amount,
            "ready_to_accept": counts["pagado"],
            "in_bar": counts["en_barra"],
            "avg_prep": avg_prep,
            "sales_today": today["gross_sales"] - today["refunds"],
            "tickets_today": today["sales_count"],
        },
        signature=Order.signature(),
    )


@bp.get("/pedidos/senal")
@staff_required
def signal():
    """El panel consulta esta huella cada pocos segundos y se recarga si cambió."""
    return jsonify(signature=Order.signature())


def _act(order_id, action, success):
    order = db.session.get(Order, order_id)
    if order is None:
        flash("Ese pedido no existe.", "error")
    else:
        try:
            action(order)
            flash(success.format(code=order.code), "success")
        except DomainError as exc:
            flash(str(exc), "error")
    default = url_for("admin_orders.index", **({"ver": order.code} if order else {}))
    return redirect(safe_next_url(request.form.get("next"), default))


@bp.post("/pedidos/<int:order_id>/validar-pago")
@staff_required
def confirm_payment(order_id):
    return _act(order_id, lambda o: o.confirm_payment(by=g.user), "Pago de {code} registrado. Ya se puede aceptar el pedido.")


@bp.post("/pedidos/<int:order_id>/aceptar")
@staff_required
def accept(order_id):
    return _act(order_id, lambda o: o.accept(g.user), "{code} aceptado: elaboración iniciada e inventario descontado.")


@bp.post("/pedidos/<int:order_id>/listo")
@staff_required
def ready(order_id):
    return _act(order_id, lambda o: o.mark_ready(), "{code} listo para retiro.")


@bp.post("/pedidos/<int:order_id>/entregar")
@staff_required
def deliver(order_id):
    return _act(order_id, lambda o: o.mark_delivered(), "{code} entregado al cliente.")


@bp.post("/pedidos/<int:order_id>/cancelar")
@staff_required
def cancel(order_id):
    reason = request.form.get("reason", "").strip() or "Cancelado desde barra"
    return _act(order_id, lambda o: o.cancel(by=g.user, reason=reason), "{code} cancelado" + " (reembolso emitido si estaba cobrado).")
