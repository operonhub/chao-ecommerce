"""
Datos disponibles en cualquier template, sin que cada vista tenga que acordarse
de pasarlos.
"""

from django.conf import settings

from .models import Categoria, Portada


def datos_negocio(request):
    return {"negocio": settings.NEGOCIO}


def menu_categorias(request):
    """El menú y el footer viven en base.html y aparecen en toda la tienda, así
    que las categorías y la portada (temporada, frase) se resuelven acá una sola
    vez en vez de que cada vista se acuerde de pasarlas."""
    return {
        "menu_categorias": Categoria.objects.filter(productos__activo=True).distinct(),
        "portada": Portada.actual(),
    }
