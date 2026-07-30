"""
Integración con Mercado Pago (Checkout Pro).

Se llama a la API REST directo con `requests`, sin el SDK: es una sola llamada y el
SDK agrega una dependencia que hay que mantener al día para nada. Es el mismo enfoque
que ya está probado en nutri-mvp.

Decisiones traídas de esa integración, que ahí costaron debug:

* `external_reference` lleva el id del pedido. El webhook lo usa para saber qué pedido
  marcar como pagado, sin confiar en la URL a la que volvió el navegador (que la
  clienta podría escribir a mano).
* La URL base se deriva del request y no de una variable de entorno, así siempre es
  el dominio real desde el que se está comprando.
* `binary_mode=True`: aprobado o rechazado, sin estados "en proceso" que después hay
  que explicarle a la dueña.

Y una que es propia de trabajar en local:

* `auto_return` y `notification_url` exigen una URL pública https. Con localhost,
  Mercado Pago rechaza la preferencia con `auto_return invalid`. Por eso ambos campos
  se mandan SOLO si la base es https — en desarrollo se verifica que la preferencia se
  cree, y la vuelta completa del pago se prueba ya deployado.
"""

from __future__ import annotations

import logging

import requests
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)

API_PREFERENCIAS = "https://api.mercadopago.com/checkout/preferences"
API_PAGOS = "https://api.mercadopago.com/v1/payments/{id}"
TIMEOUT = 15


class MercadoPagoError(RuntimeError):
    """Falló la comunicación con Mercado Pago o la respuesta no sirve."""


def configurado() -> bool:
    return bool(settings.MP_ACCESS_TOKEN)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.MP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }


def crear_preferencia(pedido, request) -> str:
    """Crea la preferencia de pago y devuelve el link al que hay que mandar a la clienta."""
    if not configurado():
        raise MercadoPagoError("Falta MP_ACCESS_TOKEN en el entorno.")

    base = request.build_absolute_uri("/").rstrip("/")
    es_https = base.startswith("https://")

    items = [
        {
            "id": str(item.producto.pk),
            "title": f"{item.producto.nombre}{f' (T {item.talle})' if item.talle else ''}"[:250],
            "category_id": "fashion",
            "quantity": item.cantidad,
            "unit_price": float(item.precio_unitario),
            "currency_id": "ARS",
        }
        for item in pedido.items.select_related("producto", "talle")
    ]

    payload = {
        "items": items,
        "payer": {"name": pedido.nombre[:100], **({"email": pedido.email} if pedido.email else {})},
        "external_reference": str(pedido.pk),
        "metadata": {"pedido_id": pedido.pk},
        "back_urls": {
            "success": f"{base}{reverse('pedidos:resultado')}?pedido={pedido.pk}",
            "failure": f"{base}{reverse('pedidos:resultado')}?pedido={pedido.pk}",
            "pending": f"{base}{reverse('pedidos:resultado')}?pedido={pedido.pk}",
        },
        # Máximo 13 caracteres: es lo que la clienta ve en el resumen de la tarjeta.
        "statement_descriptor": "CHAO",
        "binary_mode": True,
    }

    if es_https:
        payload["auto_return"] = "approved"
        payload["notification_url"] = f"{base}{reverse('pedidos:mp_webhook')}"
    else:
        logger.warning(
            "Base %s no es https: se omiten auto_return y notification_url. "
            "El pago no va a volver solo ni a avisar por webhook (esperado en desarrollo).",
            base,
        )

    try:
        respuesta = requests.post(API_PREFERENCIAS, json=payload, headers=_headers(), timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise MercadoPagoError(f"No se pudo contactar a Mercado Pago: {exc}") from exc

    if respuesta.status_code >= 400:
        logger.error("Mercado Pago rechazó la preferencia (%s): %s", respuesta.status_code, respuesta.text)
        raise MercadoPagoError(f"Mercado Pago devolvió {respuesta.status_code}.")

    datos = respuesta.json()
    pedido.mp_preference_id = datos.get("id", "")
    pedido.save(update_fields=["mp_preference_id", "actualizado"])

    # `sandbox_init_point` es el link de prueba; `init_point` el real. Con un token
    # TEST- los dos funcionan, pero el de sandbox es el que corresponde.
    link = datos.get("sandbox_init_point") or datos.get("init_point")
    if not link:
        raise MercadoPagoError("La respuesta de Mercado Pago no trajo el link de pago.")
    return link


def consultar_pago(payment_id: str) -> dict:
    """Trae el pago desde la API. El webhook solo manda el id, nunca el estado."""
    if not configurado():
        raise MercadoPagoError("Falta MP_ACCESS_TOKEN en el entorno.")
    try:
        respuesta = requests.get(API_PAGOS.format(id=payment_id), headers=_headers(), timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise MercadoPagoError(f"No se pudo consultar el pago {payment_id}: {exc}") from exc

    if respuesta.status_code >= 400:
        raise MercadoPagoError(f"Mercado Pago devolvió {respuesta.status_code} al consultar el pago.")
    return respuesta.json()
