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

    talle = None
    talle_id = request.POST.get("talle")
    if talle_id:
        talle = get_object_or_404(Talle, pk=talle_id)
    elif producto.variantes.exists():
        # El producto tiene talles cargados y no eligieron ninguno: no se adivina.
        return HttpResponseBadRequest("Falta elegir el talle.")

    try:
        cantidad = max(1, int(request.POST.get("cantidad", 1)))
    except (TypeError, ValueError):
        cantidad = 1

    Cart(request).agregar(producto, talle, cantidad)
    return _respuesta_carrito(request)


@require_POST
def agregar_look(request):
    """
    "Llevar el look completo": suma de una vez todas las prendas marcadas en la foto.

    Es el remate del factor sorpresa, y tiene una decisión de negocio adentro: qué
    talle usar cuando la clienta agrega un look entero con un solo clic.
    """
    look = get_object_or_404(Look, pk=request.POST.get("look"), activo=True)
    carrito = Cart(request)

    items = look.items.select_related("producto").prefetch_related("producto__variantes__talle")
    for item in items:
        if not item.producto.activo:
            continue
        carrito.agregar(item.producto, elegir_talle_para_look(item.producto), 1)

    return _respuesta_carrito(request)


def elegir_talle_para_look(producto: Producto) -> Talle | None:
    """
    Decide con qué talle entra una prenda al carrito cuando se agrega el look completo.

    TODO(santi): implementar. Es una decisión de negocio, no técnica — mirá el
    comentario de abajo antes de elegir.

    Opciones y qué implica cada una:

    a) Devolver el primer talle con stock (`producto.talles_disponibles.first().talle`).
       Un solo clic y el carrito queda completo. Riesgo: si la clienta usa L y le
       entra una M, o lo corrige en el carrito o te llega un cambio al local.

    b) Devolver el talle de "en medio" de los disponibles (la M de S/M/L, el 40 de
       36/38/40/42). Es el talle que más se vende, así que acierta más veces que (a)
       sin agregar ningún paso.

    c) Devolver None y que el carrito muestre la línea con un "elegí tu talle" en
       rojo, bloqueando el checkout hasta que estén todos. Es el más honesto y el
       que menos cambios genera, pero le saca la magia al "un solo clic".

    Para las prendas sin talles cargados (bolsos, pañuelos) hay que devolver None
    igual, porque no tienen variantes: eso ya lo maneja `Cart.agregar`.
    """
    raise NotImplementedError("Definir la estrategia de talle para 'llevar el look completo'.")


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
