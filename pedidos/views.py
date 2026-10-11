"""
Checkout, pago y estado del pedido.

Flujo: /checkout/ (datos, entrega y medio de pago) → se crea el Pedido →
  · tarjeta / Mercado Pago: /checkout/pago/<codigo>/ (formulario seguro de MP
    dentro de la página) → /checkout/pedido/<codigo>/
  · transferencia o efectivo: directo a /checkout/pedido/<codigo>/ con los datos
    para transferir o la dirección del local.

Regla que ordena todo: **el pedido pasa a pagado solo si Mercado Pago lo confirma
del lado del servidor** (respuesta del pago o webhook, con monto y moneda
verificados) **o si la dueña lo marca a mano en el panel**. Nunca por una URL a la
que volvió el navegador.
"""

from __future__ import annotations

import json
import logging

from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from carrito.cart import Cart

from .forms import CheckoutForm
from .models import Cobros, Pedido, PedidoItem
from .services import mercadopago

logger = logging.getLogger(__name__)

# Lo que Mercado Pago contesta cuando rechaza, traducido a algo que se entienda.
# Los primeros son de la API de Orders (tarjeta en la página); los cc_rejected_*
# llegan de los pagos con la billetera de Mercado Pago (Checkout Pro).
MOTIVOS_RECHAZO = {
    "insufficient_amount": "La tarjeta no tiene saldo suficiente.",
    "card_insufficient_amount": "La tarjeta no tiene saldo suficiente.",
    "bad_filled_card_data": "Revisá los datos de la tarjeta (número, vencimiento o código).",
    "invalid_card_token": "Los datos de la tarjeta vencieron. Volvé a cargarlos.",
    "rejected_by_issuer": "El banco rechazó el pago. Probá con otra tarjeta.",
    "required_call_for_authorize": "El banco pide que autorices el pago: llamalo y volvé a intentar.",
    "card_disabled": "La tarjeta no está habilitada. Llamá al banco para activarla.",
    "high_risk": "El pago fue rechazado por seguridad. Probá con otra tarjeta.",
    "max_attempts_exceeded": "Llegaste al límite de intentos. Probá con otra tarjeta.",
    "amount_limit_exceeded": "El monto supera el límite de la tarjeta.",
    "invalid_installments": "Esas cuotas no están disponibles para esta tarjeta. Probá con otra cantidad.",
    "processing_error": "Hubo un error de Mercado Pago. Probá de nuevo en unos minutos.",
    "3ds_challenge_expired": "Se venció el tiempo para confirmar con tu banco. Probá de nuevo.",
    "cc_rejected_insufficient_amount": "La tarjeta no tiene saldo suficiente.",
    "cc_rejected_bad_filled_security_code": "El código de seguridad no es correcto.",
    "cc_rejected_bad_filled_date": "La fecha de vencimiento no es correcta.",
    "cc_rejected_bad_filled_card_number": "Revisá el número de la tarjeta.",
    "cc_rejected_bad_filled_other": "Revisá los datos de la tarjeta.",
    "cc_rejected_call_for_authorize": "El banco pide que autorices el pago: llamalo y volvé a intentar.",
    "cc_rejected_card_disabled": "La tarjeta no está habilitada. Llamá al banco para activarla.",
    "cc_rejected_duplicated_payment": "Ya hiciste un pago igual hace un momento.",
    "cc_rejected_high_risk": "El pago fue rechazado por seguridad. Probá con otra tarjeta.",
    "cc_rejected_max_attempts": "Llegaste al límite de intentos. Probá con otra tarjeta.",
}


def _mp_disponible() -> bool:
    return mercadopago.configurado()


# --- Checkout ------------------------------------------------------------------
def checkout(request):
    carrito = Cart(request)
    if carrito.vacio:
        return redirect("catalogo:home")

    lineas = list(carrito)
    # Con talles cargados y sin talle elegido no se puede cobrar: no sabríamos qué
    # prenda entregar. Se avisa acá y no en el pago, que es más tarde y peor.
    faltan_talle = [
        l["producto"].nombre for l in lineas if l["talle"] is None and l["producto"].necesita_elegir_talle
    ]

    form = CheckoutForm(request.POST or None, mp_disponible=_mp_disponible())
    if request.method == "POST" and not faltan_talle and form.is_valid():
        pedido = _crear_pedido(form, lineas)
        carrito.vaciar()
        if pedido.metodo_pago == Pedido.Metodo.MERCADOPAGO:
            return redirect("pedidos:pago", codigo=pedido.codigo)
        return redirect("pedidos:pedido", codigo=pedido.codigo)
    if request.method == "POST" and form.errors:
        messages.error(request, "Revisá los campos marcados.")

    cobros = form.cobros
    return render(
        request,
        "pedidos/checkout.html",
        {
            "carrito": carrito,
            "form": form,
            "faltan_talle": faltan_talle,
            "zonas": [
                {"zona": z, "valor": f"zona-{z.pk}", "costo": z.costo_para(carrito.total)} for z in form.zonas
            ],
            "metodos": form.metodos_disponibles(),
            "cobros": cobros,
            "entrega_elegida": form.data.get("entrega", "retiro") if form.is_bound else "retiro",
            "metodo_elegido": form.data.get("metodo_pago") if form.is_bound else (form.metodos_disponibles() or [""])[0],
        },
    )


def _crear_pedido(form, lineas) -> Pedido:
    d = form.cleaned_data
    zona = form.zona
    cobros = Cobros.actual()
    # El pedido y sus líneas se crean juntos o no se crean: un pedido sin items es
    # basura en la base y confunde a la dueña en el panel.
    with transaction.atomic():
        pedido = Pedido(
            nombre=d["nombre"].strip(),
            telefono=d["telefono"],
            email=d["email"],
            dni=d.get("dni", "").strip(),
            notas=(d.get("notas") or "").strip(),
            metodo_pago=d["metodo_pago"],
            entrega=Pedido.Entrega.ENVIO if zona else Pedido.Entrega.RETIRO,
        )
        if zona:
            subtotal = sum(l["subtotal"] for l in lineas)
            pedido.zona = zona
            pedido.zona_nombre = zona.nombre
            pedido.zona_demora = zona.demora
            pedido.costo_envio = zona.costo_para(subtotal)
            for campo in ("calle", "numero", "piso_depto", "entre_calles", "codigo_postal",
                          "localidad", "provincia", "indicaciones"):
                setattr(pedido, campo, (d.get(campo) or "").strip())
        pedido.save()
        PedidoItem.objects.bulk_create(
            [
                PedidoItem(
                    pedido=pedido,
                    producto=l["producto"],
                    talle=l["talle"],
                    cantidad=l["cantidad"],
                    precio_unitario=l["precio"],
                )
                for l in lineas
            ]
        )
        descuento = cobros.descuento_transferencia if pedido.metodo_pago == Pedido.Metodo.TRANSFERENCIA else 0
        pedido.recalcular_total(descuento_pct=descuento)
    return pedido


# --- Pago con tarjeta / Mercado Pago -------------------------------------------
def pago(request, codigo):
    pedido = get_object_or_404(Pedido, codigo=codigo)
    if pedido.estado == Pedido.Estado.PAGADO or pedido.metodo_pago != Pedido.Metodo.MERCADOPAGO:
        return redirect("pedidos:pedido", codigo=codigo)

    cred = mercadopago.credenciales()
    if not cred:
        # Sin Mercado Pago conectado el pedido no se pierde: se termina por WhatsApp.
        return render(request, "pedidos/pedido.html", {"pedido": pedido, "sin_mp": True})

    try:
        # Para el botón "Pagar con mi cuenta de Mercado Pago". Si falla, el
        # formulario de tarjeta sigue andando igual.
        preferencia = mercadopago.crear_preferencia(pedido, request)
    except mercadopago.MercadoPagoError as exc:
        logger.warning("Pedido #%s sin preferencia para la billetera: %s", pedido.pk, exc)
        preferencia = ""

    return render(
        request,
        "pedidos/pago.html",
        {
            "pedido": pedido,
            "mp_config": {
                "publicKey": cred.public_key,
                "monto": float(pedido.total),
                "preferenceId": preferencia,
                "email": pedido.email,
                "urlProcesar": reverse("pedidos:procesar", args=[pedido.codigo]),
                "urlPedido": reverse("pedidos:pedido", args=[pedido.codigo]),
            },
        },
    )


@require_POST
def procesar(request, codigo):
    """Recibe la tarjeta tokenizada por el formulario seguro y crea la order."""
    pedido = get_object_or_404(Pedido, codigo=codigo)
    if pedido.estado == Pedido.Estado.PAGADO:
        return JsonResponse({"estado": "pagado", "url": reverse("pedidos:pedido", args=[codigo])})
    try:
        datos = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return HttpResponseBadRequest("Datos ilegibles")

    try:
        orden = mercadopago.crear_orden(pedido, datos)
    except mercadopago.MercadoPagoError as exc:
        return JsonResponse({"estado": "error", "mensaje": str(exc)}, status=502)

    url_pedido = reverse("pedidos:pedido", args=[codigo])
    if orden.aprobada and mercadopago.orden_coincide(orden, pedido):
        pedido.marcar_pagado(orden.id, orden.detalle)
        return JsonResponse({"estado": "pagado", "url": url_pedido})

    pedido.mp_payment_id = orden.id
    pedido.mp_status_detail = orden.detalle
    if orden.fallida:
        pedido.estado = Pedido.Estado.RECHAZADO
    pedido.save(update_fields=["mp_payment_id", "mp_status_detail", "estado", "actualizado"])
    if orden.fallida:
        return JsonResponse(
            {"estado": "rechazado",
             "mensaje": MOTIVOS_RECHAZO.get(orden.detalle, "La tarjeta rechazó el pago. Probá con otra.")}
        )
    # processing / action_required (en revisión, 3DS…): lo resuelve el webhook.
    return JsonResponse({"estado": "pendiente", "url": url_pedido})


# --- Estado del pedido ---------------------------------------------------------------
def pedido(request, codigo):
    pedido = get_object_or_404(
        Pedido.objects.prefetch_related("items__producto__imagenes", "items__talle"), codigo=codigo
    )
    return render(
        request,
        "pedidos/pedido.html",
        {
            "pedido": pedido,
            "cobros": Cobros.actual(),
            "motivo_rechazo": MOTIVOS_RECHAZO.get(pedido.mp_status_detail, ""),
        },
    )


@require_GET
def estado(request, codigo):
    """Para que la página del pedido se entere sola cuando el webhook confirma."""
    p = get_object_or_404(Pedido, codigo=codigo)
    return JsonResponse({"estado": p.estado})


# --- Webhook ---------------------------------------------------------------------------
@csrf_exempt
@require_POST
def mp_webhook(request):
    """
    Aviso de Mercado Pago. Junto con `procesar`, el único lugar que marca un pedido
    como pagado.

    Va sin CSRF porque el que postea es Mercado Pago. La seguridad está en tres
    capas: la firma (x-signature), que el estado se consulta a la API con nuestro
    token y que el monto y la moneda tienen que coincidir con el pedido.

    Devuelve 200 casi siempre a propósito: si contestamos error, Mercado Pago
    reintenta el mismo aviso durante horas. Solo se usa 500 cuando el problema es
    nuestro y un reintento puede andar.
    """
    try:
        cuerpo = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        logger.warning("Webhook de MP con cuerpo ilegible.")
        return HttpResponse(status=200)

    data_id = request.GET.get("data.id") or (cuerpo.get("data") or {}).get("id")
    tipo = cuerpo.get("type") or request.GET.get("type")
    if tipo not in ("order", "payment") or not data_id:
        return HttpResponse(status=200)  # otros avisos que no nos interesan

    if not mercadopago.firma_valida(request, str(data_id)):
        logger.warning("Webhook de MP con firma inválida (%s %s).", tipo, data_id)
        return HttpResponse(status=401)

    if tipo == "order":
        return _webhook_orden(str(data_id))
    payment_id = data_id
    try:
        pago_mp = mercadopago.consultar_pago(str(payment_id))
    except mercadopago.MercadoPagoError as exc:
        logger.error("No se pudo consultar el pago %s: %s", payment_id, exc)
        return HttpResponse(status=500)  # que reintente: puede ser un corte pasajero

    referencia = pago_mp.get("external_reference")
    pedido = Pedido.objects.filter(pk=referencia).first() if str(referencia or "").isdigit() else None
    if pedido is None:
        logger.warning("Pago %s con external_reference desconocido: %r", payment_id, referencia)
        return HttpResponse(status=200)

    estado_mp = pago_mp.get("status")
    if estado_mp == "approved":
        if mercadopago.pago_coincide(pago_mp, pedido):
            pedido.marcar_pagado(str(payment_id), pago_mp.get("status_detail", ""))
            logger.info("Pedido #%s pagado (pago %s)", pedido.pk, payment_id)
        else:
            logger.error("Pago %s aprobado pero el monto no coincide con el pedido #%s", payment_id, pedido.pk)
    elif estado_mp in ("rejected", "cancelled") and pedido.estado != Pedido.Estado.PAGADO:
        pedido.estado = Pedido.Estado.RECHAZADO if estado_mp == "rejected" else Pedido.Estado.CANCELADO
        pedido.mp_payment_id = str(payment_id)
        pedido.mp_status_detail = pago_mp.get("status_detail", "")
        pedido.save(update_fields=["estado", "mp_payment_id", "mp_status_detail", "actualizado"])
    return HttpResponse(status=200)


def _webhook_orden(order_id: str) -> HttpResponse:
    """Aviso de una order (pago con tarjeta en la página)."""
    try:
        orden = mercadopago.consultar_orden(order_id)
    except mercadopago.MercadoPagoError as exc:
        logger.error("No se pudo consultar la order %s: %s", order_id, exc)
        return HttpResponse(status=500)

    pedido = Pedido.objects.filter(pk=orden.referencia).first() if orden.referencia.isdigit() else None
    if pedido is None:
        logger.warning("Order %s con external_reference desconocido: %r", order_id, orden.referencia)
        return HttpResponse(status=200)

    if orden.aprobada:
        if mercadopago.orden_coincide(orden, pedido):
            pedido.marcar_pagado(orden.id, orden.detalle)
            logger.info("Pedido #%s pagado (order %s)", pedido.pk, order_id)
        else:
            logger.error("Order %s aprobada pero el monto no coincide con el pedido #%s", order_id, pedido.pk)
    elif orden.estado in ("failed", "canceled", "expired") and pedido.estado != Pedido.Estado.PAGADO:
        pedido.estado = Pedido.Estado.RECHAZADO if orden.estado == "failed" else Pedido.Estado.CANCELADO
        pedido.mp_payment_id = orden.id
        pedido.mp_status_detail = orden.detalle
        pedido.save(update_fields=["estado", "mp_payment_id", "mp_status_detail", "actualizado"])
    return HttpResponse(status=200)
