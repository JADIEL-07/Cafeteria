"""Inicio de sesión, registro y cierre de sesión."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..models import DomainError, User
from ..utils.auth import login_user, logout_user, safe_next_url
from ..utils.throttle import login_limiter

bp = Blueprint("auth", __name__)


def _home_for(user):
    return url_for("admin_orders.index") if user.is_staff else url_for("menu.index")


def _render(tab="login", status=200, **context):
    context.setdefault("next_url", request.values.get("next", ""))
    return render_template("auth/login.html", tab=tab, **context), status


@bp.get("/login")
def login():
    if g.user:
        return redirect(safe_next_url(request.args.get("next"), _home_for(g.user)))
    tab = "register" if request.args.get("tab") == "register" else "login"
    return _render(tab)


@bp.post("/login")
def login_post():
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    key = (request.remote_addr, User.normalize_email(email))
    if login_limiter.blocked(key):
        abort(429)
    user = User.authenticate(email, password)
    if user is None:
        login_limiter.register_failure(key)
        flash("Correo o contraseña incorrectos.", "error")
        return _render("login", 401, email=email)
    login_limiter.reset(key)
    login_user(user, remember=request.form.get("remember") == "on")
    flash(f"¡Bienvenido de nuevo, {user.first_name}!", "success")
    return redirect(safe_next_url(request.form.get("next"), _home_for(user)))


@bp.post("/registro")
def register_post():
    name = request.form.get("name", "")
    email = request.form.get("email", "")
    try:
        user = User.create(name, email, request.form.get("password", ""))
    except DomainError as exc:
        flash(str(exc), "error")
        return _render("register", 400, name=name, email=email)
    login_user(user, remember=True)
    flash("¡Cuenta creada! Ya puedes acumular granos Moka Club con cada pedido.", "success")
    return redirect(safe_next_url(request.form.get("next"), url_for("menu.index")))


@bp.post("/logout")
def logout():
    logout_user()
    flash("Cerraste sesión. ¡Vuelve pronto!", "info")
    return redirect(url_for("menu.index"))
