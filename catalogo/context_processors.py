"""
Datos disponibles en cualquier template, sin que cada vista tenga que acordarse
de pasarlos.
"""

from django.conf import settings

from .models import Categoria, Portada


def datos_negocio(request):
    return {"negocio": settings.NEGOCIO}


def descuento_transferencia(request):
    """El % off por transferencia, solo si la transferencia se ofrece de verdad
    (prendida y con alias o CBU): si no, la tienda no lo anuncia."""
    from pedidos.models import Cobros

    cobros = Cobros.actual()
    return {"off_transferencia": cobros.descuento_transferencia if cobros.transferencia_lista else 0}


def menu_categorias(request):
    """El menú y el footer viven en base.html y aparecen en toda la tienda, así
    que las categorías y la portada (temporada, frase) se resuelven acá una sola
    vez en vez de que cada vista se acuerde de pasarlas."""
    return {
        "menu_categorias": Categoria.objects.filter(productos__activo=True).distinct(),
        "portada": Portada.actual(),
    }
