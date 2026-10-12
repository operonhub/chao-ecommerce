"""
Vistas del carrito.

Patrón: cada acción devuelve el HTML del cajón lateral ya renderizado y el JS lo
reemplaza. El estado del carrito vive en un solo lugar (la sesión, en el servidor) y
no hay una copia en JavaScript que se pueda desincronizar. Es el mismo enfoque que
usa htmx, sin sumar la librería.
"""

from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST

from catalogo.models import Look, Producto, Talle

from .cart import Cart


def _respuesta_carrito(request):
    """El cajón renderizado. Todas las acciones terminan acá."""
    return render(request, "carrito/_drawer.html", {"carrito": Cart(request), "abrir": True})


def ver(request):
    return render(request, "carrito/_drawer.html", {"carrito": Cart(request), "abrir": False})


@require_POST
def agregar(request):
    producto = get_object_or_404(Producto, pk=request.POST.get("producto"), activo=True)

    # Color: si la prenda tiene colores, es obligatorio y tiene que ser de ella.
    color = None
    colores = list(producto.colores.all())
    if colores:
        color = next((c for c in colores if str(c.pk) == request.POST.get("color")), None)
        if color is None and len(colores) == 1:
            color = colores[0]
        if color is None:
            return HttpResponseBadRequest("Falta elegir el color.")

    talle = None
    talle_id = request.POST.get("talle")
    if talle_id:
        talle = get_object_or_404(Talle, pk=talle_id)
    elif producto.variantes.exists():
        # El producto tiene talles cargados y no eligieron ninguno: no se adivina.
        return HttpResponseBadRequest("Falta elegir el talle.")

    if talle and not producto.variantes.filter(talle=talle, color=color).exists():
        return HttpResponseBadRequest("Ese talle no viene en ese color.")

    try:
        cantidad = max(1, int(request.POST.get("cantidad", 1)))
    except (TypeError, ValueError):
        cantidad = 1

    Cart(request).agregar(producto, talle, cantidad, color)
    return _respuesta_carrito(request)


@require_POST
def agregar_look(request):
    """
    "Llevar el look completo": suma de una vez todas las prendas de la foto.

    El talle (y el color) de cada prenda lo elige la clienta en la misma lista
    del look: talle_<prenda> y color_<prenda>. No se adivina ninguno — un talle
    adivinado es un cambio en el local. Las prendas sin stock se saltean; si a
    alguna con stock le falta elegir, no se agrega nada y se avisa cuál.
    """
    look = get_object_or_404(Look, pk=request.POST.get("look"), activo=True)
    items = look.items.select_related("producto").prefetch_related(
        "producto__variantes__talle", "producto__colores"
    )

    a_sumar, faltan = [], []
    for item in items:
        prenda = item.producto
        if not prenda.activo:
            continue
        variantes = [v for v in prenda.variantes.all() if v.stock > 0]
        if prenda.variantes.all() and not variantes:
            continue  # sin stock: queda afuera del look

        colores = list(prenda.colores.all())
        color = None
        if colores:
            color = next((x for x in colores if str(x.pk) == request.POST.get(f"color_{prenda.pk}")), None)
            if color is None and len(colores) == 1:
                color = colores[0]
            if color is None:
                faltan.append(prenda.nombre)
                continue
            variantes = [v for v in variantes if v.color_id == color.pk]

        talle = None
        if prenda.variantes.all():
            elegido = request.POST.get(f"talle_{prenda.pk}")
            variante = next((v for v in variantes if str(v.talle_id) == elegido), None)
            if variante is None and len(variantes) == 1:
                variante = variantes[0]
            if variante is None:
                faltan.append(prenda.nombre)
                continue
            talle = variante.talle
        a_sumar.append((prenda, talle, color))

    if faltan:
        return HttpResponseBadRequest(f"Elegí el talle de: {', '.join(faltan)}.")
    if not a_sumar:
        return HttpResponseBadRequest("Las prendas de este look están sin stock por ahora.")

    carrito = Cart(request)
    for prenda, talle, color in a_sumar:
        carrito.agregar(prenda, talle, 1, color)
    return _respuesta_carrito(request)


@require_POST
def actualizar(request):
    clave = request.POST.get("clave", "")
    try:
        cantidad = int(request.POST.get("cantidad", 1))
    except (TypeError, ValueError):
        return HttpResponseBadRequest("Cantidad inválida.")
    Cart(request).actualizar(clave, cantidad)
    return _respuesta_carrito(request)


@require_POST
def quitar(request):
    Cart(request).quitar(request.POST.get("clave", ""))
    return _respuesta_carrito(request)
