from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, render

from .models import Categoria, Look, LookItem, Portada, Producto


def _productos_visibles():
    return (
        Producto.objects.filter(activo=True)
        .select_related("categoria")
        .prefetch_related("imagenes", "variantes__talle")
    )


def _categorias_con_stock():
    return Categoria.objects.filter(productos__activo=True).distinct()


def home(request):
    """
    La home es la presentación de 6 diapositivas (hero, nosotras, colección
    destacada, por qué, instagram, contacto). El catálogo completo, el
    lookbook y el resto de la tienda viven en sus propias páginas — ver
    `catalogo` y `looks` más abajo.
    """
    destacados = _productos_visibles().filter(destacado=True).order_by("orden")[:6]
    if destacados.count() < 6:
        # Si todavía no hay 6 marcadas como destacadas, se completa con las
        # primeras del orden general para que la diapositiva no quede vacía.
        ids = [p.pk for p in destacados]
        faltan = 6 - len(ids)
        relleno = _productos_visibles().exclude(pk__in=ids).order_by("orden")[:faltan]
        destacados = list(destacados) + list(relleno)

    return render(request, "catalogo/home.html", {"destacados": destacados})


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
        "items__producto__imagenes", "items__producto__variantes__talle"
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

    return render(
        request,
        "catalogo/producto.html",
        {
            "prenda": prenda,
            "fotos": list(prenda.imagenes.all()),
            "relacionados": relacionados,
            "look": look,
            "del_look": del_look,
        },
    )
