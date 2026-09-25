"""Panel: usuarios (clientes Moka Club y equipo)."""
import csv
import io

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select

from ..extensions import db
from ..models import DomainError, Order, User
from ..models.order import PAY_PAID
from ..models.user import ROLE_ADMIN, ROLE_BARISTA, ROLE_CLIENT, ROLE_LABELS, ROLES, VIP_BEANS
from ..utils.auth import admin_required, safe_next_url
from ..utils.params import int_arg, page_arg
from .admin_finance_controller import csv_safe

bp = Blueprint("admin_users", __name__, url_prefix="/admin/usuarios")

FILTERS = {
    "todos": "Todos",
    "vip": "VIP / Granos Dorados",
    "clientes": "Clientes",
    "baristas": "Baristas",
    "admins": "Administradores",
}


def _condition(key):
    if key == "vip":
        return (User.role == ROLE_CLIENT) & (User.beans >= VIP_BEANS)
    if key == "clientes":
        return User.role == ROLE_CLIENT
    if key == "baristas":
        return User.role == ROLE_BARISTA
    if key == "admins":
        return User.role == ROLE_ADMIN
    return None


def _query(key, text):
    stmt = select(User)
    condition = _condition(key)
    if condition is not None:
        stmt = stmt.where(condition)
    if text:
        like = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        stmt = stmt.where(or_(User.name.ilike(like, escape="\\"), User.email.ilike(like, escape="\\")))
    return stmt.order_by(User.created_at.desc(), User.id.desc())


def _kpis():
    clients = db.session.scalar(select(func.count(User.id)).where(User.role == ROLE_CLIENT)) or 0
    buyers = db.session.scalar(select(func.count(func.distinct(Order.user_id))).where(Order.payment_status == PAY_PAID)) or 0
    repeat = db.session.scalar(
        select(func.count()).select_from(
            select(Order.user_id).where(Order.payment_status == PAY_PAID).group_by(Order.user_id).having(func.count(Order.id) > 1).subquery()
        )
    ) or 0
    beans = db.session.scalar(select(func.coalesce(func.sum(User.beans), 0)).where(User.role == ROLE_CLIENT)) or 0
    vip = db.session.scalar(select(func.count(User.id)).where(_condition("vip"))) or 0
    return {
        "clients": clients,
        "buyers": buyers,
        "buyers_pct": round(buyers * 100 / clients) if clients else 0,
        "beans": beans,
        "vip": vip,
        "repeat_pct": round(repeat * 100 / buyers) if buyers else 0,
    }


@bp.get("/")
@admin_required
def index():
    key = request.args.get("rol", "todos")
    if key not in FILTERS:
        key = "todos"
    text = request.args.get("q", "").strip()[:60]
    page = page_arg(request.args.get("page"))
    people = db.paginate(_query(key, text), page=page, per_page=10, error_out=False)
    ver = int_arg(request.args.get("ver"))
    selected = (db.session.get(User, ver) if ver else None) or (people.items[0] if people.items else None)
    counts = {k: db.session.scalar(select(func.count(User.id)).where(_condition(k))) if _condition(k) is not None else db.session.scalar(select(func.count(User.id))) for k in FILTERS}
    return render_template(
        "admin/users.html",
        people=people,
        selected=selected,
        stats=selected.order_stats() if selected else None,
        favorites=selected.favorite_products() if selected else [],
        filters=FILTERS,
        counts=counts,
        active_filter=key,
        query=text,
        kpis=_kpis(),
        roles=ROLE_LABELS,
    )


def _back(user=None):
    default = url_for("admin_users.index", **({"ver": user.id} if user else {}))
    return redirect(safe_next_url(request.form.get("next"), default))


def _user_or_404(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    return user


@bp.post("/nuevo")
@admin_required
def create():
    role = request.form.get("role")
    try:
        if role not in ROLES:
            raise DomainError("Elige un rol para la nueva cuenta.")
        user = User.create(request.form.get("name"), request.form.get("email"), request.form.get("password", ""), role=role)
        flash(f"Cuenta creada para {user.name} ({user.role_label}).", "success")
        return _back(user)
    except DomainError as exc:
        flash(str(exc), "error")
        return _back()


@bp.post("/<int:user_id>/granos")
@admin_required
def bonus(user_id):
    user = _user_or_404(user_id)
    amount = int_arg(request.form.get("amount"), minimum=-500, maximum=500)
    if user.role != ROLE_CLIENT:
        flash("Sólo los clientes acumulan granos.", "error")
    elif not amount or not (-500 <= amount <= 500):
        flash("Indica una cantidad de granos entre -500 y 500.", "error")
    else:
        user.add_beans(amount)
        db.session.commit()
        flash(f"{'Se bonificaron' if amount > 0 else 'Se descontaron'} {abs(amount)} granos a {user.name}.", "success")
    return _back(user)


@bp.post("/<int:user_id>/editar")
@admin_required
def edit(user_id):
    user = _user_or_404(user_id)
    name = request.form.get("name", "").strip()
    role = request.form.get("role")
    try:
        if len(name) < 2:
            raise DomainError("Escribe el nombre completo.")
        if role not in ROLES:
            raise DomainError("Rol no válido.")
        if user.id == g.user.id and role != ROLE_ADMIN:
            raise DomainError("No puedes quitarte a ti mismo el rol de administrador.")
        user.name = name
        user.role = role
        db.session.commit()
        flash("Perfil actualizado.", "success")
    except DomainError as exc:
        db.session.rollback()
        flash(str(exc), "error")
    return _back(user)


@bp.post("/<int:user_id>/estado")
@admin_required
def toggle_active(user_id):
    user = _user_or_404(user_id)
    if user.id == g.user.id:
        flash("No puedes suspender tu propia cuenta.", "error")
    else:
        user.is_active_account = not user.is_active_account
        db.session.commit()
        flash(f"Cuenta de {user.name} {'reactivada' if user.is_active_account else 'suspendida'}.", "success")
    return _back(user)


@bp.get("/exportar.csv")
@admin_required
def export():
    key = request.args.get("rol", "todos")
    text = request.args.get("q", "").strip()[:60]
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["ID", "Nombre", "Correo", "Rol", "Nivel", "Granos", "Activo", "Alta"])
    for user in db.session.scalars(_query(key if key in FILTERS else "todos", text)):
        writer.writerow(
            [user.id, csv_safe(user.name), csv_safe(user.email), user.role_label, user.tier, user.beans,
             "sí" if user.is_active_account else "no", user.created_at.strftime("%Y-%m-%d")]
        )
    return Response(
        "﻿" + out.getvalue(), mimetype="text/csv", headers={"Content-Disposition": 'attachment; filename="usuarios.csv"'}
    )
