"""Fechas legibles en español y rangos de período para la cartera."""
from datetime import datetime, timedelta

MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]

PERIODS = {
    "hoy": "Hoy",
    "semana": "Esta Semana",
    "mes": "Este Mes",
    "todo": "Todo",
}


def now():
    return datetime.now()


def _clock(dt):
    hour12 = dt.hour % 12 or 12
    return f"{hour12}:{dt:%M} {'AM' if dt.hour < 12 else 'PM'}"


def friendly_datetime(dt):
    """'Hoy, 10:42 AM' / 'Ayer, 4:40 PM' / '12 may, 9:15 AM'."""
    if not dt:
        return "—"
    today = now().date()
    if dt.date() == today:
        day = "Hoy"
    elif dt.date() == today - timedelta(days=1):
        day = "Ayer"
    else:
        day = f"{dt.day} {MESES[dt.month - 1]}"
    return f"{day}, {_clock(dt)}"


def short_date(dt):
    if not dt:
        return "—"
    return f"{dt.day} {MESES[dt.month - 1]} {dt.year}"


def time_ago(dt):
    """'Hace 3 min', 'Hace 2 h', 'Hace 4 días'."""
    if not dt:
        return "—"
    seconds = max(int((now() - dt).total_seconds()), 0)
    if seconds < 60:
        return "Hace un momento"
    minutes = seconds // 60
    if minutes < 60:
        return f"Hace {minutes} min"
    hours = minutes // 60
    if hours < 24:
        return f"Hace {hours} h"
    days = hours // 24
    return f"Hace {days} día{'s' if days != 1 else ''}"


def period_range(period):
    """Devuelve ``(inicio, fin)`` para 'hoy', 'semana', 'mes' o 'todo'.

    ``fin`` siempre es exclusivo. ``(None, None)`` significa sin límite.
    """
    today = now().replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow = today + timedelta(days=1)
    if period == "hoy":
        return today, tomorrow
    if period == "semana":
        return today - timedelta(days=today.weekday()), tomorrow
    if period == "mes":
        return today.replace(day=1), tomorrow
    return None, None


def greeting():
    """('¡Buenos días', 'wb_sunny') según la hora."""
    hour = now().hour
    if hour < 12:
        return "¡Buenos días", "wb_sunny"
    if hour < 19:
        return "¡Buenas tardes", "partly_cloudy_day"
    return "¡Buenas noches", "bedtime"


def start_of_day(dt=None):
    dt = dt or now()
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)
