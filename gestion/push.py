"""
Avisos al celular de la dueña (Web Push).

El panel instalado en la pantalla de inicio se suscribe a los avisos (el botón
"Activar avisos" del Inicio). Cuando entra una venta por la página, el servidor
le manda una notificación a cada celular suscripto, firmada con las claves VAPID
de la tienda (se generan solas la primera vez y viven en la base).

Mandar un aviso nunca puede romper una compra ni un webhook de Mercado Pago:
cualquier error se registra y se sigue.
"""

from __future__ import annotations

import base64
import json
import logging

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from .models import ClavesPush, SuscripcionPush

logger = logging.getLogger(__name__)

DURACION = 24 * 60 * 60  # si el celular está apagado, el aviso espera hasta un día


def claves() -> ClavesPush:
    from py_vapid import Vapid

    actuales = ClavesPush.objects.order_by("pk").first()
    if actuales:
        return actuales
    with transaction.atomic():
        vapid = Vapid()
        vapid.generate_keys()
        publica = vapid.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        return ClavesPush.objects.create(
            publica=base64.urlsafe_b64encode(publica).rstrip(b"=").decode(),
            privada=vapid.private_pem().decode(),
        )


def _contacto() -> str:
    # El servicio de push (Apple/Google) pide un contacto del que manda: mailto o https.
    sitio = settings.SITIO_URL or ""
    return sitio if sitio.startswith("https://") else "https://www.chaoindumentaria.com"


def avisar(titulo: str, cuerpo: str, url: str = "", etiqueta: str = "") -> int:
    """Manda el aviso a todos los celulares suscriptos. Devuelve a cuántos llegó."""
    try:
        from py_vapid import Vapid
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.error("Falta pywebpush: no se pueden mandar avisos.")
        return 0

    suscripciones = list(SuscripcionPush.objects.all())
    if not suscripciones:
        return 0
    try:
        firma = Vapid.from_pem(claves().privada.encode())
    except Exception:  # noqa: BLE001
        logger.exception("No se pudieron leer las claves de los avisos")
        return 0

    datos = json.dumps({"titulo": titulo, "cuerpo": cuerpo, "url": url or reverse("gestion:pedidos"), "etiqueta": etiqueta})
    enviados = 0
    for sus in suscripciones:
        try:
            webpush(
                subscription_info={"endpoint": sus.endpoint, "keys": {"p256dh": sus.p256dh, "auth": sus.auth}},
                data=datos,
                vapid_private_key=firma,
                vapid_claims={"sub": _contacto()},
                ttl=DURACION,
                headers={"Urgency": "high"},
                timeout=8,
            )
        except WebPushException as exc:
            estado = getattr(exc.response, "status_code", None)
            if estado in (404, 410):
                # El celular desinstaló el panel o le sacó el permiso: se borra.
                sus.delete()
            else:
                logger.warning("Aviso no entregado a %s: %s", sus.pk, exc)
            continue
        except Exception:  # noqa: BLE001
            logger.exception("Falló el aviso a %s", sus.pk)
            continue
        enviados += 1
        SuscripcionPush.objects.filter(pk=sus.pk).update(ultimo_envio=timezone.now())
    return enviados


def avisar_pedido(pedido, motivo: str) -> None:
    """
    `motivo`: "pagado" (entró la plata por Mercado Pago), "transferencia" (pedido
    nuevo que espera la transferencia) o "efectivo" (paga al retirar).
    """
    from catalogo.templatetags.humanize_ar import pesos

    try:
        items = list(pedido.items.select_related("producto", "talle"))
        if items:
            primero = items[0]
            prenda = primero.producto.nombre + (f" ({primero.talle})" if primero.talle_id else "")
            if primero.cantidad > 1:
                prenda = f"{primero.cantidad}× {prenda}"
            resto = sum(i.cantidad for i in items[1:])
            if resto:
                prenda += f" y {resto} más"
        else:
            prenda = f"Pedido #{pedido.pk}"
        entrega = f"envío a {pedido.zona_nombre}" if pedido.entrega == pedido.Entrega.ENVIO else "retira en el local"
        titulo = {
            "pagado": f"¡Venta en la web! ${pesos(pedido.total)}",
            "transferencia": f"Pedido nuevo · espera transferencia · ${pesos(pedido.total)}",
            "efectivo": f"Pedido nuevo · paga al retirar · ${pesos(pedido.total)}",
        }.get(motivo, f"Pedido #{pedido.pk}")
        avisar(
            titulo,
            f"{prenda} · {pedido.nombre} · {entrega}",
            url=reverse("gestion:pedidos") + f"#pedido-{pedido.pk}",
            etiqueta=f"pedido-{pedido.pk}",
        )
    except Exception:  # noqa: BLE001 — un aviso que falla no puede frenar una venta
        logger.exception("No se pudo avisar el pedido %s", getattr(pedido, "pk", "?"))
