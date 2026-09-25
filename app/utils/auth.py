"""Sesión, usuario actual y decoradores de acceso."""
from functools import wraps
from urllib.parse import urlparse

from flask import abort, flash, g, redirect, request, session, url_for

from ..extensions import db
from ..models.user import ROLE_ADMIN, STAFF_ROLES, User


def load_current_user():
    """``before_request``: carga ``g.user`` desde la sesión (o None)."""
    g.user = None
    user_id = session.get("user_id")
    if user_id:
        user = db.session.get(User, user_id)
        if user and user.is_active_account:
            g.user = user
        else:  # cuenta borrada o suspendida: se invalida la sesión
            session.pop("user_id", None)


def login_user(user, remember=False):
    session["user_id"] = user.id
    session.permanent = bool(remember)
    g.user = user


def logout_user():
    session.clear()
    g.user = None


def safe_next_url(target, default=None):
    """Sólo permite redirigir a rutas internas (evita open redirect)."""
    default = default or url_for("menu.index")
    if not target:
        return default
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return default
    return target


def wants_json():
    return (
        request.headers.get("X-Requested-With") == "fetch"
        or request.accept_mimetypes.best == "application/json"
    )


def _unauthenticated():
    if wants_json():
        abort(401)
    flash("Inicia sesión para continuar.", "info")
    target = request.full_path.rstrip("?") if request.method == "GET" else None
    return redirect(url_for("auth.login", next=target))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return _unauthenticated()
        return view(*args, **kwargs)

    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if g.user is None:
                return _unauthenticated()
            if g.user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


staff_required = roles_required(*STAFF_ROLES)
admin_required = roles_required(ROLE_ADMIN)
