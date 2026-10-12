from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from . import seo
from .models import Categoria, Look, LookItem, Portada, Producto


def _productos_visibles():
    return (
        Producto.objects.filter(activo=True)
        .select_related("categoria")
        .prefetch_related("imagenes", "variantes__talle", "colores")
    )


def _categorias_con_stock():
    return Categoria.objects.filter(productos__activo=True).distinct()


def home(request):
    """
    Home editorial de scroll vertical: hero en tríptico con los looks, lo nuevo,
    categorías con foto, un look para comprar entero, nosotras, por qué, Instagram
    y el local. El catálogo completo y el lookbook viven en sus propias páginas.
    """
    destacados = list(_productos_visibles().filter(destacado=True).order_by("orden")[:6])
    if len(destacados) < 6:
        # Si todavía no hay 6 marcadas como destacadas, se completa con las
        # primeras del orden general para que la sección no quede con huecos.
        ids = [p.pk for p in destacados]
        relleno = _productos_visibles().exclude(pk__in=ids).order_by("orden")[: 6 - len(ids)]
        destacados += list(relleno)

    portada = Portada.actual()
    looks = list(Look.objects.filter(activo=True).order_by("orden", "nombre"))
    # La foto que la dueña eligió para la portada va primera en el tríptico.
    if portada.foto_hero and portada.foto_hero in looks:
        looks.remove(portada.foto_hero)
        looks.insert(0, portada.foto_hero)

    # Cada categoría con la foto de su primera prenda: las tarjetas de "Elegí por
    # categoría" muestran ropa real, no un ícono.
    categorias = []
    con_cantidad = Categoria.objects.filter(productos__activo=True).annotate(
        n=Count("productos", filter=Q(productos__activo=True))
    )
    for cat in con_cantidad.order_by("orden", "nombre"):
        prenda = _productos_visibles().filter(categoria=cat).order_by("-destacado", "orden").first()
        foto = prenda.foto_principal if prenda else None
        categorias.append({"categoria": cat, "n": cat.n, "foto": foto.url if foto else ""})

    # El look para "comprá el look entero": el de la portada si tiene prendas
    # marcadas; si no, el primero que tenga.
    look_compra = None
    for candidato in looks:
        items = list(
            LookItem.objects.filter(look=candidato, producto__activo=True)
            .select_related("producto__categoria")
            .prefetch_related("producto__imagenes")
        )
        if items:
            look_compra = {"look": candidato, "items": items, "total": sum(i.producto.precio for i in items)}
            break

    return render(
        request,
        "catalogo/home.html",
        {
            "destacados": destacados,
            "looks_hero": looks[:6],
            # Lo mismo en datos para que el tríptico vaya rotando las fotos.
            "looks_hero_datos": [
                {
                    "src": l.url,
                    "alt": l.alt or l.nombre,
                    "nombre": l.nombre,
                    "href": f"{reverse('catalogo:looks')}#look-{l.pk}",
                }
                for l in looks[:6]
                if l.url
            ],
            "categorias_home": categorias,
            "look_compra": look_compra,
            "fotos_ig": looks[:5],
            "datos_estructurados": seo.tienda_jsonld(request, portada.hero_url),
        },
    )


def catalogo(request, categoria_slug=None):
    """
    La tienda de verdad: todas las prendas, o las de una categoría si vino
    slug en la URL — el gesto "tocá una categoría y te lleva a esa sección"
    que pidió Tomás (como Zara), en vez del filtro por JS que ocultaba cards
    en una sola página.
    """
    productos = _productos_visibles()
    categoria_actual = None
    if categoria_slug:
        categoria_actual = get_object_or_404(Categoria, slug=categoria_slug)
        productos = productos.filter(categoria=categoria_actual)

    ordenes = {
        "": ("-destacado", "orden", "nombre"),
        "menor-precio": ("precio", "nombre"),
        "mayor-precio": ("-precio", "nombre"),
        "nuevo": ("-creado",),
    }
    orden = request.GET.get("orden", "")
    if orden not in ordenes:
        orden = ""
    productos = list(productos.order_by(*ordenes[orden]))

    categorias = Categoria.objects.filter(productos__activo=True).annotate(
        n=Count("productos", filter=Q(productos__activo=True))
    ).distinct()

    return render(
        request,
        "catalogo/tienda.html",
        {
            "productos": productos,
            "categorias": categorias,
            "total_activos": _productos_visibles().count(),
            "categoria_actual": categoria_actual,
            "orden": orden,
            "portada": Portada.actual(),
            # Una foto de look para cortar la grilla (solo en "todo el catálogo"
            # y si hay suficientes prendas como para que no quede rara).
            "look_destacado": Look.objects.filter(activo=True).order_by("?").first()
            if not categoria_actual and len(productos) >= 6
            else None,
            "hay_precios_a_confirmar": any(p.precio_a_confirmar for p in productos),
        },
    )


def looks(request):
    """El lookbook con hotspots, en su propia página."""
    looks_qs = Look.objects.filter(activo=True).prefetch_related(
        "items__producto__imagenes", "items__producto__variantes__talle", "items__producto__colores"
    )
    productos = _productos_visibles()

    prendas_json = {
        p.pk: {
            "nombre": p.nombre,
            "precio": int(p.precio),
            "cuota": int(p.precio_cuota_3),
            "url": p.get_absolute_url(),
            # `necesitaElegir` y no `tieneTalles`: un bolso con una sola variante
            # "Único" tiene talle pero no hay nada que elegir.
            "necesitaElegir": p.necesita_elegir_talle,
            # Con más de un color, la ficha del look manda a la prenda a elegir.
            "colores": len(p.colores.all()),
            "talleUnico": p.variante_unica.talle.pk if p.variante_unica else None,
            "talles": [
                {"id": v.talle.pk, "nombre": v.talle.nombre, "stock": v.stock}
                for v in sorted(p.variantes.all(), key=lambda v: (v.talle.orden, v.talle.nombre))
            ],
        }
        for p in productos
    }

    return render(
        request,
        "catalogo/looks.html",
        {
            "looks": looks_qs,
            "prendas_json": prendas_json,
            "categorias": _categorias_con_stock(),
        },
    )


def producto(request, slug):
    prenda = get_object_or_404(_productos_visibles(), slug=slug)
    relacionados = _productos_visibles().filter(categoria=prenda.categoria).exclude(pk=prenda.pk)[:4]

    # "Completá el look": si la prenda está marcada en una foto de percha, se
    # muestran las otras prendas de esa misma foto. Es dato real del local, no
    # una recomendación inventada.
    item = (
        LookItem.objects.filter(producto=prenda, look__activo=True)
        .select_related("look")
        .first()
    )
    look = item.look if item else None
    del_look = []
    if look:
        del_look = [
            i.producto
            for i in look.items.select_related("producto__categoria").prefetch_related(
                "producto__imagenes", "producto__variantes__talle"
            )
            if i.producto_id != prenda.pk and i.producto.activo
        ]

    fotos = list(prenda.imagenes.all())
    return render(
        request,
        "catalogo/producto.html",
        {
            "prenda": prenda,
            "fotos": fotos,
            "og_imagen": fotos[0].url if fotos else "",
            "datos_estructurados": seo.producto_jsonld(request, prenda, fotos),
            "relacionados": relacionados,
            "look": look,
            "del_look": del_look,
        },
    )
