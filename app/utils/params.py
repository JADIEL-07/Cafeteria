"""Lectura segura de parámetros enteros que llegan del navegador.

SQLite no admite enteros de más de 64 bits: un ``id=999999999999999999999`` haría
fallar la consulta. Estos ayudantes descartan valores fuera de rango.
"""
from werkzeug.routing import IntegerConverter

MAX_ID = 2_147_483_647
MAX_PAGE = 100_000


def int_arg(value, default=None, minimum=1, maximum=MAX_ID):
    """Convierte ``value`` a int dentro de [minimum, maximum]; si no se puede, ``default``."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    if number < minimum or number > maximum:
        return default
    return number


def page_arg(value):
    """Número de página válido (1 si viene vacío, negativo o absurdo)."""
    return int_arg(value, default=1, minimum=1, maximum=MAX_PAGE)


class SafeIntegerConverter(IntegerConverter):
    """``<int:id>`` de las rutas, acotado para que nunca desborde la base de datos."""

    def __init__(self, map, fixed_digits=0, min=None, max=MAX_ID, signed=False):
        super().__init__(map, fixed_digits, min, max, signed)
