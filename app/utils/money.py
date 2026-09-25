"""Manejo de dinero en centavos (enteros) para evitar errores de coma flotante."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MAX_MONEY = Decimal("1000000")      # tope por importe: $1,000,000.00
MAX_QUANTITY = Decimal("1000000")   # tope por cantidad de stock


def format_money(cents, signed=False):
    """1234567 -> '$12,345.67'. Con ``signed`` agrega '+' / '-' explícitos."""
    cents = int(cents or 0)
    sign = "-" if cents < 0 else ("+" if signed and cents > 0 else "")
    whole, frac = divmod(abs(cents), 100)
    return f"{sign}${whole:,}.{frac:02d}"


def parse_money(value, allow_zero=True):
    """Convierte texto del usuario ('12.50', '12,50', '$1,250.00') a centavos.

    Lanza ``ValueError`` si no es un importe válido y positivo.
    """
    text = str(value or "").strip().replace("$", "").replace(" ", "")
    if not text:
        raise ValueError("Importe vacío")
    if "," in text and "." in text:
        text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("Importe inválido") from exc
    if not amount.is_finite() or amount < 0 or amount > MAX_MONEY or (amount == 0 and not allow_zero):
        raise ValueError("Importe inválido")
    return int((amount * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def parse_quantity(value, allow_zero=False):
    """Convierte texto a cantidad decimal (stock). Lanza ``ValueError``."""
    text = str(value or "").strip().replace(",", ".")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError("Cantidad inválida") from exc
    if not amount.is_finite() or amount < 0 or amount > MAX_QUANTITY or (amount == 0 and not allow_zero):
        raise ValueError("Cantidad inválida")
    return float(amount)


def basis_points(cents, bp):
    """Aplica una tasa en puntos básicos (750 = 7.5 %) redondeando hacia arriba."""
    return (int(cents) * int(bp) + 5000) // 10000


def line_cost(quantity, unit_cost_cents):
    """Costo total (centavos) de ``quantity`` unidades a ``unit_cost_cents``."""
    total = Decimal(str(quantity)) * int(unit_cost_cents)
    return int(total.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def format_qty(value):
    """5.0 -> '5'; 4.5 -> '4.5'; 0.2500001 -> '0.25'."""
    value = round(float(value or 0), 3)
    text = f"{value:,.3f}".rstrip("0").rstrip(".")
    return text or "0"
