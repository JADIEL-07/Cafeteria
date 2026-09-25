# syntax=docker/dockerfile:1
#
# Cafetería Moka — imagen de producción (gunicorn).
#
#   docker build -t moka-cafe .
#   docker run -p 8000:8000 --env-file .env moka-cafe
#
# La configuración (DATABASE_URL de Supabase, SECRET_KEY, ADMIN_PASSWORD…) entra por variables de entorno:
# el archivo .env NUNCA se copia a la imagen (ver .dockerignore).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

# Las dependencias van primero: esta capa se reutiliza mientras requirements.txt no cambie.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY run.py ./
COPY app ./app

# Usuario sin privilegios. instance/ es lo único escribible (SQLite y la clave de sesión si no defines SECRET_KEY).
RUN useradd --system --create-home --uid 10001 moka \
    && mkdir -p /app/instance \
    && chown -R moka:moka /app/instance
USER moka

EXPOSE 8000

# /healthz responde 200 sólo si la app y su base de datos están vivas.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'), timeout=4)"

# Un worker con varios hilos: el límite de intentos de login vive en memoria y así se aplica completo, y el pool
# de conexiones (5 + 5) no agota el plan gratuito de Supabase. Sube WEB_CONCURRENCY / GUNICORN_THREADS si lo necesitas.
# Sin --preload: cada worker abre sus propias conexiones a la base de datos.
CMD ["sh", "-c", "exec gunicorn run:app --bind 0.0.0.0:${PORT} --workers ${WEB_CONCURRENCY:-1} --threads ${GUNICORN_THREADS:-4} --timeout 60 --access-logfile - --error-logfile -"]
