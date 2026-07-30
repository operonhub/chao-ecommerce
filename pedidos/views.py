"""
Checkout y vuelta de Mercado Pago.

Regla que ordena todo este módulo: **el estado de pago solo lo cambia el webhook**,
nunca la URL a la que volvió el navegador. La página de resultado le muestra a la
clienta lo que pasó, pero si dice "aprobado" es porque el webhook ya lo confirmó
consultando la API. Si no, muestra "estamos confirmando el pago".
"""

from __future__ import annotations

import json
import logging

from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from carrito.cart import Cart

from .models import Pedido, PedidoItem
from .services import mercadopago

logger = logging.getLogger(__name__)


def checkout(request):
    carrito = Cart(request)
    if carrito.vacio:
        return redirect("catalogo:home")

    # Con talles cargados y sin talle elegido no se puede cobrar: no sabríamos qué
    # prenda entregar. Se avisa acá y no en el pago, que es más tarde y peor.
    faltan_talle = [
        linea["producto"].nombre
        for linea in carrito
        if linea["talle"] is None and linea["producto"].necesita_elegir_talle
    ]

    return render(
        request,
        "pedidos/checkout.html",
        {
            "carrito": carrito,
            "faltan_talle": faltan_talle,
            "mp_activo": mercadopago.configurado(),
        },
    )


@require_POST
def pagar(request):
    """Convierte el carrito en un Pedido y manda a la clienta a Mercado Pago."""
    carrito = Cart(request)
    if carrito.vacio:
        return redirect("catalogo:home")

    nombre = (request.POST.get("nombre") or "").strip()
    telefono = (request.POST.get("telefono") or "").strip()
    email = (request.POST.get("email") or "").strip()

    if not nombre or not telefono:
        messages.error(request, "Necesitamos tu nombre y un teléfono para coordinar la entrega.")
        return redirect("pedidos:checkout")

    lineas = list(carrito)
    if any(l["talle"] is None and l["producto"].necesita_elegir_talle for l in lineas):
        messages.error(request, "Hay prendas sin talle elegido. Revisá el carrito antes de pagar.")
        return redirect("pedidos:checkout")

    # El pedido y sus líneas se crean juntos o no se crean: un pedido sin items es
    # basura en la base y confunde a la dueña en el panel.
    with transaction.atomic():
        pedido = Pedido.objects.create(
            nombre=nombre,
            telefono=telefono,
            email=email,
            notas=(request.POST.get("notas") or "").strip(),
        )
        PedidoItem.objects.bulk_create(
            [
                PedidoItem(
                    pedido=pedido,
                    producto=linea["producto"],
                    talle=linea["talle"],
                    cantidad=linea["cantidad"],
                    precio_unitario=linea["precio"],
                )
                for linea in lineas
            ]
        )
        pedido.recalcular_total()

    try:
        link = mercadopago.crear_preferencia(pedido, request)
    except mercadopago.MercadoPagoError as exc:
        logger.error("Pedido #%s sin link de pago: %s", pedido.pk, exc)
        # El pedido queda igual, en estado pendiente: la venta no se pierde, se
        # termina por WhatsApp. Es lo que haría la dueña de todas formas.
        return render(
            request,
            "pedidos/sin_pago.html",
            {"pedido": pedido, "motivo": str(exc), "debug": settings.DEBUG},
        )

    # El carrito se vacía recién cuando hay link: si falló, la clienta lo sigue teniendo.
    carrito.vaciar()
    return redirect(link)


def resultado(request):
    """
    Vuelta desde Mercado Pago. Solo informa — no cambia el estado del pedido.

    Los parámetros de esta URL los puede escribir cualquiera, así que lo único que se
    usa es el id del pedido para leerlo de la base.
    """
    pedido = Pedido.objects.filter(pk=request.GET.get("pedido")).prefetch_related(
        "items__producto", "items__talle"
    ).first()
    return render(request, "pedidos/resultado.html", {"pedido": pedido})


@csrf_exempt
@require_POST
def mp_webhook(request):
    """
    Aviso de Mercado Pago. Es el único lugar que marca un pedido como pagado.

    Va sin CSRF porque el que postea es Mercado Pago, no un formulario nuestro. La
    seguridad no está en el token: está en que el estado no se lee del cuerpo del
    aviso sino consultando la API con nuestro token privado.

    Devuelve 200 casi siempre a propósito: si contestamos error, Mercado Pago
    reintenta el mismo aviso durante horas. Solo interesa retener el 500 cuando el
    problema es nuestro y un reintento puede andar.
    """
    try:
        cuerpo = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        logger.warning("Webhook de MP con cuerpo ilegible.")
        return HttpResponse(status=200)

    payment_id = (cuerpo.get("data") or {}).get("id") or request.GET.get("data.id")
    tipo = cuerpo.get("type") or request.GET.get("type")

    if tipo != "payment" or not payment_id:
        # Mercado Pago manda otros tipos de aviso que no nos interesan.
        return HttpResponse(status=200)

    try:
        pago = mercadopago.consultar_pago(str(payment_id))
    except mercadopago.MercadoPagoError as exc:
        logger.error("No se pudo consultar el pago %s: %s", payment_id, exc)
        return HttpResponse(status=500)  # Que reintente: puede ser un corte pasajero.

    referencia = pago.get("external_reference")
    pedido = Pedido.objects.filter(pk=referencia).first() if referencia else None
    if pedido is None:
        logger.warning("Pago %s con external_reference desconocido: %r", payment_id, referencia)
        return HttpResponse(status=200)

    estados = {
        "approved": Pedido.Estado.PAGADO,
        "rejected": Pedido.Estado.RECHAZADO,
        "cancelled": Pedido.Estado.CANCELADO,
    }
    nuevo = estados.get(pago.get("status"))
    if nuevo:
        pedido.estado = nuevo
        pedido.mp_payment_id = str(payment_id)
        pedido.save(update_fields=["estado", "mp_payment_id", "actualizado"])
        logger.info("Pedido #%s → %s (pago %s)", pedido.pk, nuevo, payment_id)

    return HttpResponse(status=200)
