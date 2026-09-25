"""Carrito, cupones, modo de entrega y checkout."""
from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, url_for

from ..extensions import db
from ..models import Cart, CartError, DomainError, Order, Product
from ..utils.auth import login_required, safe_next_url, wants_json
from ..utils.params import int_arg

bp = Blueprint("cart", __name__)

OPTION_FIELDS = ("size", "temperature", "milk", "sweetness")


def _back(default):
    return redirect(safe_next_url(request.form.get("next"), default))


@bp.get("/carrito")
def view():
    summary = Cart().summary()
    in_cart = {line.product.id for line in summary.lines}
    suggestions = [
        p for p in Product.catalog(sort="popular") if not p.is_customizable and p.price_cents <= 500 and p.id not in in_cart
    ][:3]
    return render_template("customer/cart.html", summary=summary, suggestions=suggestions, wait=Order.estimated_wait())


@bp.post("/carrito/agregar")
def add():
    product_id = int_arg(request.form.get("product_id"))
    product = db.session.get(Product, product_id) if product_id else None
    cart = Cart()
    try:
        cart.add(
            product,
            selections={field: request.form.get(field) for field in OPTION_FIELDS},
            extras=request.form.getlist("extras"),
            notes=request.form.get("notes", ""),
            qty=request.form.get("qty", 1, type=int) or 1,
        )
    except CartError as exc:
        if wants_json():
            return jsonify(ok=False, message=str(exc)), 400
        flash(str(exc), "error")
        return _back(url_for("menu.index"))
    message = f"{product.name} se añadió a tu carrito."
    if wants_json():
        return jsonify(ok=True, message=message, count=cart.count())
    flash(message, "success")
    if request.form.get("go") == "cart":
        return redirect(url_for("cart.view"))
    return _back(url_for("cart.view"))


@bp.post("/carrito/<key>/cantidad")
def set_quantity(key):
    cart = Cart()
    action = request.form.get("action")
    if action == "inc":
        cart.change_qty(key, +1)
    elif action == "dec":
        cart.change_qty(key, -1)
    else:
        cart.set_qty(key, request.form.get("qty", 1, type=int) or 0)
    return redirect(url_for("cart.view"))


@bp.post("/carrito/<key>/eliminar")
def remove(key):
    Cart().remove(key)
    flash("Artículo eliminado de tu carrito.", "info")
    return redirect(url_for("cart.view"))


@bp.post("/carrito/vaciar")
def clear():
    Cart().clear()
    flash("Vaciaste tu carrito.", "info")
    return redirect(url_for("cart.view"))


@bp.post("/carrito/cupon")
def coupon():
    cart = Cart()
    if request.form.get("action") == "quitar":
        cart.remove_coupon()
        flash("Cupón removido.", "info")
    else:
        try:
            applied = cart.apply_coupon(request.form.get("code", ""))
            flash(f"Cupón {applied.code} aplicado: -{applied.label}", "success")
        except CartError as exc:
            flash(str(exc), "error")
    return redirect(url_for("cart.view"))


@bp.post("/carrito/modo")
def set_mode():
    try:
        Cart().set_mode(request.form.get("mode", ""), request.form.get("table", ""))
    except CartError as exc:
        flash(str(exc), "error")
    return _back(url_for("cart.view"))


@bp.post("/checkout")
@login_required
def checkout():
    cart = Cart()
    # El número de mesa viaja con el formulario de pago (sección "Servir en mesa")
    if request.form.get("table") is not None:
        mode, _ = cart.mode_info()
        cart.set_mode(mode, request.form.get("table", ""))
    summary = cart.summary()
    if summary.coupon_error:
        flash(summary.coupon_error, "error")
        cart.remove_coupon()
        return redirect(url_for("cart.view"))
    try:
        order = Order.create_from_cart(
            g.user,
            summary,
            request.form.get("payment", ""),
            fulfillment=summary.mode,
            table=summary.table,
            notes=request.form.get("notes"),
        )
    except DomainError as exc:
        flash(str(exc), "error")
        return redirect(url_for("cart.view"))
    cart.clear()
    if order.payment_status == "pagado":
        flash(f"¡Pago aprobado! Tu pedido {order.code} ya está en la cola de barra.", "success")
    else:
        flash(f"Pedido {order.code} recibido. Paga en barra para que podamos empezar a prepararlo.", "success")
    return redirect(url_for("orders.detail", code=order.code))
