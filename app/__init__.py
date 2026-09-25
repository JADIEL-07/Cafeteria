"""Cafetería Moka — aplicación Flask con arquitectura MVC.

    app/models       -> M: entidades y reglas de negocio (SQLAlchemy)
    app/views        -> V: plantillas Jinja + estáticos (css, js, img)
    app/controllers  -> C: blueprints que reciben la petición y eligen la vista
"""
import secrets
from pathlib import Path

import click
from flask import Flask, g, jsonify, render_template, request
from sqlalchemy import select

from .config import Config
from .extensions import csrf, db
from .utils import timefmt
from .utils.money import format_money, format_qty


def _load_or_create_secret(instance_path):
    """Clave de sesión persistente si no se configuró SECRET_KEY."""
    key_file = Path(instance_path) / "secret.key"
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    return key


def create_app(config_object=Config):
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder="views/templates",
        static_folder="views/static",
    )
    app.config.from_object(config_object)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _load_or_create_secret(app.instance_path)

    db.init_app(app)
    csrf.init_app(app)

    from . import models  # noqa: F401  (registra las tablas)

    _register_request_hooks(app)
    _register_template_helpers(app)
    _register_error_handlers(app)

    from .controllers import register_blueprints
    from .utils.params import SafeIntegerConverter

    app.url_map.converters["int"] = SafeIntegerConverter  # ids de ruta acotados
    register_blueprints(app)
    _register_cli(app)

    with app.app_context():
        db.create_all()
        if app.config.get("SEED_ON_FIRST_RUN") and not db.session.scalar(select(models.User.id).limit(1)):
            from .seed import seed_database

            seed_database(demo=app.config.get("DEMO_DATA", True))
            app.logger.warning(
                "Base de datos creada. Administrador: %s. Si no definiste ADMIN_PASSWORD, cambia la contraseña por defecto.",
                app.config["ADMIN_EMAIL"],
            )
    return app


def _register_request_hooks(app):
    from .utils.auth import load_current_user

    app.before_request(load_current_user)

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.endpoint and request.endpoint != "static" and request.method == "GET":
            response.headers.setdefault("Cache-Control", "no-store")
        return response


def _register_template_helpers(app):
    from .models import Cart

    app.jinja_env.filters["money"] = format_money
    app.jinja_env.filters["qty"] = format_qty
    app.jinja_env.filters["friendly"] = timefmt.friendly_datetime
    app.jinja_env.filters["ago"] = timefmt.time_ago
    app.jinja_env.filters["shortdate"] = timefmt.short_date

    @app.context_processor
    def inject_globals():
        def cart_info():
            """(unidades, total) del carrito; se calcula una vez por petición y sólo si la vista lo pide."""
            if not hasattr(g, "_cart_info"):
                cart = Cart()
                count = cart.count()
                g._cart_info = (count, cart.summary().total_cents if count else 0)
            return g._cart_info

        def admin_badges():
            from .models import InventoryItem, Order

            counts = Order.filter_counts()
            return {
                "orders": counts["pendiente"] + counts["pagado"],
                "low_stock": len(InventoryItem.low_stock()),
            }

        return {
            "cafe": app.config["CAFE"],
            "current_user": getattr(g, "user", None),
            "cart_info": cart_info,
            "admin_badges": admin_badges,
            "greeting": timefmt.greeting,
        }


def _register_error_handlers(app):
    def render_error(code, title, message):
        if request.headers.get("X-Requested-With") == "fetch" or request.accept_mimetypes.best == "application/json":
            return jsonify(error=title, message=message), code
        return render_template("errors/error.html", code=code, title=title, message=message), code

    @app.errorhandler(400)
    def bad_request(_):
        return render_error(400, "Solicitud no válida", "No pudimos procesar la solicitud. Recarga la página e inténtalo de nuevo.")

    @app.errorhandler(401)
    def unauthorized(_):
        return render_error(401, "Inicia sesión", "Necesitas iniciar sesión para continuar.")

    @app.errorhandler(403)
    def forbidden(_):
        return render_error(403, "Acceso restringido", "Tu cuenta no tiene permisos para ver esta sección.")

    @app.errorhandler(404)
    def not_found(_):
        return render_error(404, "No encontramos esa página", "Puede que el enlace haya cambiado o que el producto ya no esté disponible.")

    @app.errorhandler(429)
    def too_many(_):
        return render_error(429, "Demasiados intentos", "Espera unos minutos antes de volver a intentarlo.")

    @app.errorhandler(500)
    def server_error(_):
        db.session.rollback()
        return render_error(500, "Algo salió mal", "Ocurrió un error inesperado. Ya quedó registrado; inténtalo de nuevo en un momento.")


def _register_cli(app):
    @app.cli.command("reset-db")
    @click.option("--demo/--no-demo", default=True, help="Cargar clientes y pedidos de ejemplo.")
    def reset_db(demo):
        """Borra la base de datos y la vuelve a crear con el catálogo inicial."""
        from .seed import seed_database

        db.drop_all()
        db.create_all()
        seed_database(demo=demo)
        click.echo("Base de datos reiniciada.")

    @app.cli.command("create-user")
    @click.argument("email")
    @click.argument("name")
    @click.option("--role", type=click.Choice(["cliente", "barista", "admin"]), default="barista")
    @click.password_option()
    def create_user(email, name, role, password):
        """Crea una cuenta (por ejemplo, un barista o un administrador)."""
        from .models import User

        user = User.create(name, email, password, role=role)
        click.echo(f"Cuenta creada: {user.email} ({user.role})")
