from django.shortcuts import get_object_or_404, render

from .models import Categoria, Look, Producto


def _productos_visibles():
    return (
        Producto.objects.filter(activo=True)
        .select_related("categoria")
        .prefetch_related("imagenes", "variantes__talle")
    )


def home(request):
    """
    Una sola página con todo: hero, lookbook, catálogo y el local.

    Los looks traen sus prendas con prefetch porque cada hotspot necesita el producto,
    sus talles y su foto — sin esto son decenas de consultas para 6 looks.
    """
    looks = Look.objects.filter(activo=True).prefetch_related(
        "items__producto__imagenes", "items__producto__variantes__talle"
    )
    productos = _productos_visibles().order_by("-destacado", "orden")

    # Datos que la ficha del hotspot necesita para llenarse sin ir al servidor.
    # Se serializan acá y no en el template para que el JS no tenga que leer precios
    # de dentro del HTML ni volver a formatearlos.
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
        "catalogo/home.html",
        {
            "looks": looks,
            "productos": productos,
            "prendas_json": prendas_json,
            "categorias": Categoria.objects.filter(productos__activo=True).distinct(),
            # Basta con que una prenda tenga precio estimado para que el aviso deba
            # aparecer: es más honesto avisar de más que de menos.
            "hay_precios_a_confirmar": any(p.precio_a_confirmar for p in productos),
        },
    )


def producto(request, slug):
    prenda = get_object_or_404(_productos_visibles(), slug=slug)
    relacionados = _productos_visibles().filter(categoria=prenda.categoria).exclude(pk=prenda.pk)[:4]
    return render(request, "catalogo/producto.html", {"prenda": prenda, "relacionados": relacionados})
