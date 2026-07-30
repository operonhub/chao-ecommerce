"""
Formato de plata argentino.

Django trae `intcomma`, pero con la locale es-AR queda inconsistente según la
configuración del server. Acá se fuerza el formato que se lee en cualquier vidriera
de Buenos Aires: punto para los miles y sin decimales ($48.900, no $48,900.00).
"""

from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


def _a_decimal(valor):
    try:
        return Decimal(str(valor or 0))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


@register.filter
def pesos(valor):
    """48900 → 48.900"""
    entero = _a_decimal(valor).quantize(Decimal("1"))
    return f"{entero:,}".replace(",", ".")


@register.filter
def cuota(valor, cantidad=3):
    """Valor de cada cuota, redondeado. 48900 en 3 → 16.300"""
    try:
        cantidad = int(cantidad)
    except (TypeError, ValueError):
        cantidad = 3
    if cantidad < 1:
        cantidad = 1
    return pesos(_a_decimal(valor) / cantidad)
