"""
Lo que leen los buscadores y las vistas previas de WhatsApp/Instagram: robots.txt,
sitemap, canonical y datos estructurados.

Todo cuelga de un solo interruptor, `settings.PERMITIR_INDEXADO`:

* Apagado (por defecto): cada página sale con `noindex, nofollow`, no hay sitemap
  y robots.txt deja pasar a los buscadores a propósito — si se les bloquea la
  entrada no llegan a leer el noindex y la página puede quedar indexada igual.
* Prendido (dominio definitivo en SITIO_URL + visto bueno de CHAO): canonical al
  dominio oficial, sitemap con las páginas públicas y datos estructurados.

El carrito, el checkout, los pedidos y los paneles nunca se indexan.
"""

from django.conf import settings
from django.http import Http404, HttpResponse
from django.urls import reverse
from django.utils.html import escape

from .models import Categoria, Producto

# Solo las páginas de la tienda son públicas para un buscador.
NAMESPACE_PUBLICO = "catalogo"


def base_url(request) -> str:
    """El dominio oficial si está cargado; si no, el del pedido (vistas previas)."""
    return settings.SITIO_URL or request.build_absolute_uri("/").rstrip("/")


def absoluta(request, url: str) -> str:
    """Las fotos subidas ya vienen con dominio (Supabase); las de static/, no."""
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return f"{base_url(request)}{url if url.startswith('/') else '/' + url}"


def contexto(request):
    """Context processor: `seo` disponible en todos los templates."""
    match = getattr(request, "resolver_match", None)
    publica = bool(match) and match.namespace == NAMESPACE_PUBLICO
    indexable = settings.PERMITIR_INDEXADO and publica
    return {
        "seo": {
            "indexable": indexable,
            # Sin parámetros: /catalogo/?orden=nuevo es la misma página que /catalogo/.
            "canonical": f"{settings.SITIO_URL}{request.path}" if indexable else "",
            "url": f"{base_url(request)}{request.path}",
        }
    }


# --- Datos estructurados (schema.org) ---------------------------------------------
def tienda_jsonld(request, imagen: str = "") -> dict | None:
    """El local físico. Solo datos verificados que además se leen en la página."""
    if not settings.PERMITIR_INDEXADO:
        return None
    n = settings.NEGOCIO
    base = settings.SITIO_URL
    datos = {
        "@context": "https://schema.org",
        "@type": "ClothingStore",
        "@id": f"{base}/#tienda",
        "name": n["nombre"],
        "url": f"{base}/",
        "telephone": n["telefono_internacional"],
        "address": {
            "@type": "PostalAddress",
            "streetAddress": n["calle"],
            "addressLocality": n["localidad"],
            "addressRegion": n["provincia"],
            "addressCountry": "AR",
        },
        "openingHoursSpecification": [
            {
                "@type": "OpeningHoursSpecification",
                "dayOfWeek": n["dias_schema"],
                "opens": tramo["abre"],
                "closes": tramo["cierra"],
            }
            for tramo in n["horarios_schema"]
        ],
        "hasMap": n["mapa_url"],
        "sameAs": [n["instagram_url"]],
    }
    if imagen:
        datos["image"] = absoluta(request, imagen)
    return datos


def producto_jsonld(request, prenda, fotos) -> dict | None:
    if not settings.PERMITIR_INDEXADO:
        return None
    base = settings.SITIO_URL
    url = f"{base}{prenda.get_absolute_url()}"
    datos = {
        "@context": "https://schema.org",
        "@type": "Product",
        "@id": f"{url}#prenda",
        "name": prenda.nombre,
        "url": url,
        "category": prenda.categoria.nombre,
        "brand": {"@type": "Brand", "name": settings.NEGOCIO["nombre"]},
    }
    if prenda.descripcion:
        datos["description"] = prenda.descripcion
    imagenes = [absoluta(request, f.url) for f in fotos if f.url]
    if imagenes:
        datos["image"] = imagenes
    con_stock = prenda.hay_stock or not prenda.tiene_talles
    datos["offers"] = {
        "@type": "Offer",
        "url": url,
        "price": f"{prenda.precio:.2f}",
        "priceCurrency": "ARS",
        "availability": f"https://schema.org/{'InStock' if con_stock else 'OutOfStock'}",
        "seller": {"@id": f"{base}/#tienda"},
    }
    return datos


# --- robots.txt y sitemap -----------------------------------------------------------
def robots_txt(request):
    if settings.PERMITIR_INDEXADO:
        lineas = [
            "User-agent: *",
            "Disallow: /gestion/",
            "Disallow: /panel/",
            "Disallow: /checkout/",
            "Disallow: /carrito/",
            "",
            f"Sitemap: {settings.SITIO_URL}{reverse('catalogo:sitemap')}",
        ]
    else:
        # Sin bloqueo: los buscadores tienen que poder entrar para leer el noindex.
        lineas = ["User-agent: *", "Allow: /"]
    return HttpResponse("\n".join(lineas) + "\n", content_type="text/plain; charset=utf-8")


def sitemap_xml(request):
    if not settings.PERMITIR_INDEXADO:
        raise Http404("El sitemap se publica cuando la tienda se abre a los buscadores.")
    base = settings.SITIO_URL
    rutas = [reverse("catalogo:home"), reverse("catalogo:catalogo"), reverse("catalogo:looks")]
    rutas += [
        reverse("catalogo:catalogo_categoria", args=[c.slug])
        for c in Categoria.objects.filter(productos__activo=True).distinct()
    ]
    rutas += [p.get_absolute_url() for p in Producto.objects.filter(activo=True).only("slug")]
    urls = "".join(f"<url><loc>{escape(base + ruta)}</loc></url>" for ruta in rutas)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>'
    )
    return HttpResponse(xml, content_type="application/xml; charset=utf-8")
