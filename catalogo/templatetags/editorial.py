"""
Detalles tipográficos del lenguaje editorial de la tienda.
"""

from django import template
from django.utils.html import format_html

register = template.Library()


@register.filter
def acento(texto):
    """
    Pone la última palabra en itálica, el gesto de los títulos del sitio
    ("Sweaters y *tejidos*"). Con una sola palabra, la deja recta.
    """
    palabras = str(texto or "").split()
    if len(palabras) < 2:
        return texto
    return format_html("{} <em>{}</em>", " ".join(palabras[:-1]), palabras[-1])
