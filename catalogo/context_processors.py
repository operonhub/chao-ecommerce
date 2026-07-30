"""
Datos del negocio disponibles en cualquier template.

Están en settings.NEGOCIO y no repartidos por los templates para que cambiar un
horario o un teléfono sea tocar un solo lugar.
"""

from django.conf import settings


def datos_negocio(request):
    return {"negocio": settings.NEGOCIO}
