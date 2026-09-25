"""Área del cliente: perfil, historial y seguimiento de cada pedido."""
from flask import Blueprint, abort, flash, g, jsonify, redirect, render_template, request, url_for

from ..models import DomainError, Order
from ..models.order import PAY_PAID
from ..utils.auth import login_required, safe_next_url

bp = Blueprint("orders", __name__)


def _order_or_404(code):
    order = Order.get_by_code(code)
    if order is None or (order.user_id != g.user.id and not g.user.is_staff):
        abort(404)  # no revelamos si el pedido existe
    return order


@bp.get("/perfil")
@login_required
def profile():
    return render_template("customer/profile.html", orders=Order.for_user(g.user, limit=20), stats=g.user.order_stats())


@bp.get("/pedidos/<code>")
@login_required
def detail(code):
    order = _order_or_404(code)
    return render_template("customer/order_status.html", order=order, wait=Order.estimated_wait())


@bp.get("/pedidos/<code>/estado")
@login_required
def state(code):
    order = _order_or_404(code)
    return jsonify(stage=order.stage, label=order.stage_info["label"], updated=order.updated_at.isoformat())


@bp.post("/pedidos/<code>/cancelar")
@login_required
def cancel(code):
    order = _order_or_404(code)
    try:
        was_paid = order.payment_status == PAY_PAID
        order.cancel(by=g.user, reason="Cancelado por el cliente" if order.user_id == g.user.id else f"Cancelado por {g.user.name}")
        flash("Pedido cancelado. " + ("Emitimos tu reembolso completo." if was_paid else "No se realizó ningún cobro."), "success")
    except DomainError as exc:
        flash(str(exc), "error")
    return redirect(url_for("orders.detail", code=order.code))


@bp.post("/pedidos/<code>/llegue")
@login_required
def arrived(code):
    order = _order_or_404(code)
    try:
        order.mark_arrived()
        flash("¡Avisamos a la barra que ya estás aquí!", "success")
    except DomainError as exc:
        flash(str(exc), "error")
    return redirect(url_for("orders.detail", code=order.code))


@bp.post("/pedidos/<code>/notas")
@login_required
def update_notes(code):
    order = _order_or_404(code)
    try:
        order.update_notes(request.form.get("notes", ""))
        flash("Notas actualizadas.", "success")
    except DomainError as exc:
        flash(str(exc), "error")
    return redirect(safe_next_url(request.form.get("next"), url_for("orders.detail", code=order.code)))
