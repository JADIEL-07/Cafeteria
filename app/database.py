"""Conexión y arranque de la base de datos (SQLite en local, PostgreSQL / Supabase en producción).

Supabase es PostgreSQL administrado: la app usa la cadena de conexión de Supabase
(``DATABASE_URL``) a través de SQLAlchemy, igual que con SQLite. Este módulo se encarga de
lo que cambia entre motores: el formato de la URL, las opciones del pool y la seguridad de
las tablas.
"""
from sqlalchemy import select, text
from sqlalchemy.engine import make_url

from .extensions import db

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", ""}
BOOTSTRAP_LOCK_ID = 7_281_001  # candado de asesoría: un solo proceso crea las tablas a la vez


def normalize_database_url(url):
    """Deja la cadena lista para SQLAlchemy + psycopg 3.

    Supabase entrega ``postgresql://…`` (y algunas plataformas ``postgres://…``), que SQLAlchemy
    interpretaría con el driver antiguo psycopg2; aquí se fuerza ``postgresql+psycopg://``.
    """
    url = (url or "").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def is_postgres(url):
    return str(url).startswith("postgresql")


def engine_options(url):
    """Opciones del motor: vacías para SQLite; para PostgreSQL, pensadas para el pooler de Supabase."""
    if not is_postgres(url):
        return {}
    parsed = make_url(url)
    connect_args = {
        # El pooler de Supabase en modo transacción (puerto 6543) no admite sentencias preparadas.
        "prepare_threshold": None,
    }
    if (parsed.host or "") not in LOCAL_HOSTS and "sslmode" not in parsed.query:
        connect_args["sslmode"] = "require"  # Supabase sólo acepta conexiones cifradas
    return {
        "pool_pre_ping": True,     # descarta conexiones que el pooler ya cerró
        "pool_recycle": 280,
        "pool_size": 5,
        "max_overflow": 5,
        "connect_args": connect_args,
    }


def database_name(url):
    return make_url(url).database or ""


def init_database():
    """Crea las tablas que falten y, en PostgreSQL, las protege con Row Level Security.

    Con varios procesos (gunicorn) arrancando a la vez, el candado de asesoría evita que dos
    intenten crear las mismas tablas. Las sentencias DDL de PostgreSQL son transaccionales,
    así que un fallo no deja la base a medias.
    """
    engine = db.engine
    with engine.begin() as conn:
        postgres = conn.dialect.name == "postgresql"
        if postgres:
            conn.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": BOOTSTRAP_LOCK_ID})
        db.metadata.create_all(bind=conn)
        if postgres:
            _enable_row_level_security(conn)


def _enable_row_level_security(conn):
    """Activa RLS en las tablas de la app.

    Supabase expone el esquema ``public`` por su API REST (PostgREST): sin RLS, cualquiera con la
    clave pública podría leer tablas como ``users`` (correos y hashes de contraseña). Con RLS y
    sin políticas esa API no ve nada. La app no usa esa API: se conecta como dueña de las tablas,
    y el dueño no queda sujeto a RLS, así que sus consultas siguen funcionando igual.
    """
    ours = {table.name for table in db.metadata.sorted_tables}
    rows = conn.execute(
        text(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = current_schema() AND c.relkind = 'r' AND NOT c.relrowsecurity"
        )
    ).all()
    for (name,) in rows:
        if name in ours:
            conn.execute(text(f'ALTER TABLE "{name}" ENABLE ROW LEVEL SECURITY'))


def seed_once(seed):
    """Ejecuta ``seed`` si la base está vacía; tolera que otro proceso la haya sembrado antes."""
    from sqlalchemy.exc import IntegrityError

    from .models import User

    if db.session.scalar(select(User.id).limit(1)):
        return False
    try:
        seed()
    except IntegrityError:  # otro worker sembró al mismo tiempo
        db.session.rollback()
        return False
    return True
