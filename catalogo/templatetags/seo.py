"""
Etiquetas para el <head>: URLs absolutas y datos estructurados.
"""

import json

from django import template
from django.utils.safestring import mark_safe

from catalogo import seo

register = template.Library()

# Los mismos reemplazos que hace `json_script` de Django: un "</script>" dentro de
# una descripción no puede cerrar la etiqueta.
_ESCAPES = {ord(">"): "\\u003E", ord("<"): "\\u003C", ord("&"): "\\u0026"}


@register.simple_tag(takes_context=True)
def absoluta(context, url):
    """`/static/img/x.jpg` → `https://dominio/static/img/x.jpg` (og:image lo exige)."""
    return seo.absoluta(context["request"], str(url or ""))


@register.simple_tag
def jsonld(datos):
    if not datos:
        return ""
    cuerpo = json.dumps(datos, ensure_ascii=False).translate(_ESCAPES)
    return mark_safe(f'<script type="application/ld+json">{cuerpo}</script>')


@register.filter
def meta_texto(valor, largo=110):
    """Deja un texto listo para meterlo en un atributo `content`: sin saltos de
    línea ni espacios repetidos, y cortado en la última palabra entera.

    `truncatechars` sola no alcanza. La dueña escribe las descripciones en un
    textarea del panel, así que llegan con Enters que terminaban crudos adentro
    del `<meta name="description">` y le partían el snippet a Google.
    """
    texto = " ".join(str(valor or "").split())
    if len(texto) <= largo:
        return texto
    return texto[:largo].rsplit(" ", 1)[0] + "…"
