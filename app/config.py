"""Configuración de la aplicación.

Todo lo que cambia entre entornos se lee de variables de entorno; el resto son
constantes del negocio (impuestos, comisión de la pasarela, datos del local).
"""
import os
from datetime import timedelta


class Config:
    # --- Infraestructura -------------------------------------------------
    # Ruta relativa => se guarda en la carpeta ``instance/``.
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///cafeteria.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Si no se define, se genera una clave aleatoria y se guarda en instance/.
    SECRET_KEY = os.environ.get("SECRET_KEY")
    TEMPLATES_AUTO_RELOAD = True  # editar una vista y refrescar, sin reiniciar el servidor
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SECURE = os.environ.get("CAFE_HTTPS") == "1"  # activar al servir por HTTPS
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    WTF_CSRF_TIME_LIMIT = None

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
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SECRET_KEY = "test-secret-key"
    WTF_CSRF_ENABLED = False
    SEED_ON_FIRST_RUN = False
    DEMO_DATA = False
