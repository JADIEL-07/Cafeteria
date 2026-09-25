"""Utilidades de fecha: formato legible en español y rangos de período (con reloj congelado)."""
from datetime import datetime

import pytest

from app.utils import timefmt

# Miércoles 13 de mayo de 2026, 10:42
NOW = datetime(2026, 5, 13, 10, 42)


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    monkeypatch.setattr(timefmt, "now", lambda: NOW)


class TestFriendlyDatetime:
    @pytest.mark.parametrize(
        "dt, expected",
        [
            (datetime(2026, 5, 13, 10, 42), "Hoy, 10:42 AM"),
            (datetime(2026, 5, 13, 0, 5), "Hoy, 12:05 AM"),
            (datetime(2026, 5, 13, 12, 0), "Hoy, 12:00 PM"),
            (datetime(2026, 5, 12, 16, 40), "Ayer, 4:40 PM"),
            (datetime(2026, 5, 1, 9, 15), "1 may, 9:15 AM"),
            (datetime(2025, 12, 31, 23, 59), "31 dic, 11:59 PM"),
        ],
    )
    def test_formats(self, dt, expected):
        assert timefmt.friendly_datetime(dt) == expected

    def test_missing_value(self):
        assert timefmt.friendly_datetime(None) == "—"


class TestShortDate:
    def test_formats(self):
        assert timefmt.short_date(datetime(2026, 1, 5)) == "5 ene 2026"

    def test_missing_value(self):
        assert timefmt.short_date(None) == "—"


class TestTimeAgo:
    @pytest.mark.parametrize(
        "dt, expected",
        [
            (datetime(2026, 5, 13, 10, 42), "Hace un momento"),
            (datetime(2026, 5, 13, 10, 41, 30), "Hace un momento"),
            (datetime(2026, 5, 13, 10, 39), "Hace 3 min"),
            (datetime(2026, 5, 13, 8, 42), "Hace 2 h"),
            (datetime(2026, 5, 12, 10, 42), "Hace 1 día"),
            (datetime(2026, 5, 9, 10, 42), "Hace 4 días"),
            (datetime(2026, 5, 13, 11, 0), "Hace un momento"),      # el futuro no da tiempos negativos
        ],
    )
    def test_formats(self, dt, expected):
        assert timefmt.time_ago(dt) == expected

    def test_missing_value(self):
        assert timefmt.time_ago(None) == "—"


class TestPeriodRange:
    def test_today(self):
        assert timefmt.period_range("hoy") == (datetime(2026, 5, 13), datetime(2026, 5, 14))

    def test_week_starts_on_monday(self):
        assert timefmt.period_range("semana") == (datetime(2026, 5, 11), datetime(2026, 5, 14))

    def test_month_starts_on_the_first(self):
        assert timefmt.period_range("mes") == (datetime(2026, 5, 1), datetime(2026, 5, 14))

    @pytest.mark.parametrize("period", ["todo", "", None, "anio"])
    def test_unbounded(self, period):
        assert timefmt.period_range(period) == (None, None)

    def test_every_period_has_a_label(self):
        assert set(timefmt.PERIODS) == {"hoy", "semana", "mes", "todo"}


class TestGreeting:
    @pytest.mark.parametrize(
        "hour, expected",
        [
            (0, "¡Buenos días"), (11, "¡Buenos días"), (12, "¡Buenas tardes"),
            (18, "¡Buenas tardes"), (19, "¡Buenas noches"), (23, "¡Buenas noches"),
        ],
    )
    def test_by_hour(self, monkeypatch, hour, expected):
        monkeypatch.setattr(timefmt, "now", lambda: NOW.replace(hour=hour))
        text, icon = timefmt.greeting()
        assert text == expected and icon


class TestStartOfDay:
    def test_defaults_to_today(self):
        assert timefmt.start_of_day() == datetime(2026, 5, 13)

    def test_explicit_value(self):
        assert timefmt.start_of_day(datetime(2026, 1, 2, 23, 59, 59, 999)) == datetime(2026, 1, 2)
