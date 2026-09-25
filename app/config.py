"""Configuración de la aplicación.

Todo lo que cambia entre entornos se lee de variables de entorno; el resto son
constantes del negocio (impuestos, comisión de la pasarela, datos del local).
"""
import os
from datetime import timedelta

from dotenv import load_dotenv

from .database import engine_options, normalize_database_url

load_dotenv()  # lee el archivo .env si existe (las variables ya definidas en el entorno tienen prioridad)


class Config:
    # --- Infraestructura -------------------------------------------------
    # Sin DATABASE_URL se usa SQLite (carpeta ``instance/``). Para Supabase / PostgreSQL:
    # DATABASE_URL=postgresql://usuario:clave@host:5432/postgres  (ver .env.example)
    SQLALCHEMY_DATABASE_URI = normalize_database_url(os.environ.get("DATABASE_URL") or "sqlite:///cafeteria.db")
    SQLALCHEMY_ENGINE_OPTIONS = engine_options(SQLALCHEMY_DATABASE_URI)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Si no se define, se genera una clave aleatoria y se guarda en instance/.
    SECRET_KEY = os.environ.get("SECRET_KEY")
    TEMPLATES_AUTO_RELOAD = True  # editar una vista y refrescar, sin reiniciar el servidor
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get("CAFE_HTTPS") == "1"  # activar al servir por HTTPS
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    WTF_CSRF_TIME_LIMIT = None
    PASSWORD_HASH_METHOD = "scrypt"

    # --- Reglas del negocio ----------------------------------------------
    TAX_BP = 750            # IVA 7.5 % (en puntos básicos, sin decimales flotantes)
    CARD_FEE_BP = 240       # comisión de la pasarela de pago 2.4 %
    CASH_FLOAT_CENTS = 20000  # fondo inicial de caja: $200.00
    REWARD_BEANS = 150      # meta de granos para la barra de progreso Moka Club

    # --- Primer arranque -------------------------------------------------
    SEED_ON_FIRST_RUN = True
    DEMO_DATA = os.environ.get("CAFE_DEMO_DATA", "1") == "1"
    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@moka.com")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin1234")

    # --- Datos del local (se muestran en cabeceras y pies de página) -------
    CAFE = {
        "name": "Moka Café & Bakery",
        "short_name": "Moka",
        "tagline": "Café de especialidad & panadería artesanal",
        "location_name": "Moka Central",
        "address": "Calle Mayor 14, Centro Histórico",
        "phone": "+52 55 5512 3456",
        "closing_time": "20:00",
        "hours": [
            ("Lunes a Viernes", "07:00 - 20:00"),
            ("Sábados y Domingos", "08:00 - 21:00"),
        ],
    }


class TestConfig(Config):
    TESTING = True
    # Las pruebas NUNCA usan DATABASE_URL (podría ser tu base real): SQLite en memoria, o el
    # PostgreSQL de pruebas indicado en TEST_DATABASE_URL (se vacía en cada prueba).
    SQLALCHEMY_DATABASE_URI = normalize_database_url(os.environ.get("TEST_DATABASE_URL") or "sqlite://")
    SQLALCHEMY_ENGINE_OPTIONS = engine_options(SQLALCHEMY_DATABASE_URI)
    SECRET_KEY = "test-secret-key"
    WTF_CSRF_ENABLED = False
    PASSWORD_HASH_METHOD = "pbkdf2:sha256:1000"  # barato: acelera la suite; los hashes siguen siendo válidos
    SEED_ON_FIRST_RUN = False
    DEMO_DATA = False
