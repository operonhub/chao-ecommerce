"""
Integración con Mercado Pago.

La dueña conecta SU cuenta con un botón del panel (OAuth): la app "Operon Tiendas"
pide permiso, Mercado Pago devuelve un token para cobrar en su nombre y la plata
entra directo a su cuenta. Se llama a la API REST con `requests`, sin el SDK.

Dos formas de cobrar, las dos en la página de pago de CHAO (Payment Brick):

* Tarjeta de crédito/débito: el formulario seguro de MP tokeniza la tarjeta en el
  navegador (ni CHAO ni Operon ven los datos) y el servidor crea el pago con
  `crear_pago`. El monto SIEMPRE sale del pedido, nunca de lo que mande el navegador.
* "Pagar con mi cuenta de Mercado Pago": necesita una preferencia
  (`crear_preferencia`) y redirige a MP para pagar con saldo o tarjetas guardadas.

Reglas traídas de las integraciones anteriores (nutri-mvp, Operon Reservas):

* `external_reference` lleva el id del pedido. El webhook lo usa para saber qué
  pedido marcar, sin confiar en la URL a la que volvió el navegador.
* El webhook no se cree el estado que le mandan: consulta el pago a la API y además
  verifica que el monto y la moneda coincidan con el pedido.
* `notification_url` y `auto_return` exigen https público: en localhost se omiten.
* `binary_mode=True`: aprobado o rechazado, sin "en proceso" que explicarle a nadie.

Si la dueña todavía no conectó su cuenta, sirven MP_ACCESS_TOKEN + MP_PUBLIC_KEY
del entorno (para desarrollo con credenciales de prueba).
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

logger = logging.getLogger(__name__)

API = "https://api.mercadopago.com"
URL_AUTORIZACION = "https://auth.mercadopago.com/authorization"
TIMEOUT = 15


class MercadoPagoError(RuntimeError):
    """Falló la comunicación con Mercado Pago o la respuesta no sirve."""


@dataclass
class Credenciales:
    access_token: str
    public_key: str
    origen: str  # "conectada" (botón del panel) o "entorno" (variables de desarrollo)


# --- Conexión de la cuenta de la dueña (OAuth) --------------------------------
def app_configurada() -> bool:
    """¿Está creada la app de Mercado Pago (Client ID/Secret en el entorno)?"""
    return bool(settings.MP_CLIENT_ID and settings.MP_CLIENT_SECRET)


def url_callback(request) -> str:
    if settings.SITIO_URL:
        return f"{settings.SITIO_URL}{reverse('gestion:mp_callback')}"
    return request.build_absolute_uri(reverse("gestion:mp_callback"))


def url_para_conectar(request, estado: str) -> str:
    parametros = {
        "client_id": settings.MP_CLIENT_ID,
        "response_type": "code",
        "platform_id": "mp",
        "state": estado,
        "redirect_uri": url_callback(request),
    }
    return f"{URL_AUTORIZACION}?{urlencode(parametros)}"


def _pedir_token(datos: dict) -> dict:
    datos = {"client_id": settings.MP_CLIENT_ID, "client_secret": settings.MP_CLIENT_SECRET, **datos}
    try:
        r = requests.post(f"{API}/oauth/token", json=datos, timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise MercadoPagoError(f"No se pudo contactar a Mercado Pago: {exc}") from exc
    if r.status_code >= 400:
        logger.error("MP rechazó el pedido de token (%s): %s", r.status_code, r.text[:300])
        raise MercadoPagoError("Mercado Pago no aceptó la conexión. Probá de nuevo.")
    return r.json()


def _guardar_conexion(datos: dict, conexion=None):
    from pedidos.models import ConexionMP

    if not datos.get("access_token") or not datos.get("public_key"):
        raise MercadoPagoError("La respuesta de Mercado Pago vino incompleta.")
    conexion = conexion or ConexionMP()
    conexion.access_token = datos["access_token"]
    conexion.refresh_token = datos.get("refresh_token") or conexion.refresh_token
    conexion.public_key = datos["public_key"]
    conexion.mp_user_id = str(datos.get("user_id") or conexion.mp_user_id)
    conexion.vence = timezone.now() + timedelta(seconds=int(datos.get("expires_in") or 15552000))
    conexion.modo_prueba = not datos.get("live_mode", True)
    return conexion


def conectar_con_codigo(request, codigo: str):
    """Cambia el código que vuelve del botón por los tokens y los guarda."""
    from pedidos.models import ConexionMP

    datos = _pedir_token(
        {"grant_type": "authorization_code", "code": codigo, "redirect_uri": url_callback(request)}
    )
    conexion = _guardar_conexion(datos)
    try:
        yo = requests.get(
            f"{API}/users/me", headers={"Authorization": f"Bearer {conexion.access_token}"}, timeout=TIMEOUT
        ).json()
        conexion.apodo = (yo.get("nickname") or "")[:120]
        conexion.email = (yo.get("email") or "")[:160]
    except (requests.RequestException, ValueError):
        pass  # sin apodo se muestra el número de usuario; no es motivo para fallar
    # Una sola cuenta conectada: la nueva reemplaza a la anterior.
    ConexionMP.objects.exclude(pk=conexion.pk).delete()
    conexion.save()
    return conexion


def _renovar_si_hace_falta(conexion) -> None:
    if not conexion.por_vencer or not conexion.refresh_token or not app_configurada():
        return
    try:
        datos = _pedir_token({"grant_type": "refresh_token", "refresh_token": conexion.refresh_token})
        _guardar_conexion(datos, conexion).save()
        logger.info("Token de Mercado Pago renovado (vence %s).", conexion.vence)
    except MercadoPagoError as exc:
        # Mientras no venza sigue sirviendo: se reintenta en el próximo cobro.
        logger.error("No se pudo renovar el token de MP: %s", exc)


def credenciales() -> Credenciales | None:
    from pedidos.models import ConexionMP

    conexion = ConexionMP.actual()
    if conexion and conexion.vence > timezone.now():
        _renovar_si_hace_falta(conexion)
        return Credenciales(conexion.access_token, conexion.public_key, "conectada")
    if settings.MP_ACCESS_TOKEN and settings.MP_PUBLIC_KEY:
        return Credenciales(settings.MP_ACCESS_TOKEN, settings.MP_PUBLIC_KEY, "entorno")
    return None


def configurado() -> bool:
    return credenciales() is not None


# --- Cobros --------------------------------------------------------------------
def _headers(cred: Credenciales, **extra) -> dict:
    return {"Authorization": f"Bearer {cred.access_token}", "Content-Type": "application/json", **extra}


def _base(request) -> tuple[str, bool]:
    base = settings.SITIO_URL or request.build_absolute_uri("/").rstrip("/")
    return base, base.startswith("https://")


def _items(pedido) -> list[dict]:
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
    if pedido.descuento:
        items.append({"id": "descuento", "title": "Descuento", "quantity": 1,
                      "unit_price": -float(pedido.descuento), "currency_id": "ARS"})
    if pedido.costo_envio:
        items.append({"id": "envio", "title": f"Envío · {pedido.zona_nombre}"[:250], "quantity": 1,
                      "unit_price": float(pedido.costo_envio), "currency_id": "ARS"})
    return items


def crear_preferencia(pedido, request) -> str:
    """Preferencia para el botón "Pagar con mi cuenta de Mercado Pago". Devuelve su id."""
    cred = credenciales()
    if not cred:
        raise MercadoPagoError("Mercado Pago no está conectado.")
    base, es_https = _base(request)
    vuelta = f"{base}{reverse('pedidos:pedido', args=[pedido.codigo])}"
    payload = {
        "items": _items(pedido),
        "payer": {"name": pedido.nombre[:100], **({"email": pedido.email} if pedido.email else {})},
        "external_reference": str(pedido.pk),
        "metadata": {"pedido_id": pedido.pk},
        "back_urls": {"success": vuelta, "failure": vuelta, "pending": vuelta},
        "statement_descriptor": "CHAO",  # máx. 13 caracteres: lo que ve en el resumen
        "binary_mode": True,
    }
    if es_https:
        payload["auto_return"] = "approved"
        payload["notification_url"] = f"{base}{reverse('pedidos:mp_webhook')}"
    try:
        r = requests.post(f"{API}/checkout/preferences", json=payload, headers=_headers(cred), timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise MercadoPagoError(f"No se pudo contactar a Mercado Pago: {exc}") from exc
    if r.status_code >= 400:
        logger.error("MP rechazó la preferencia (%s): %s", r.status_code, r.text[:300])
        raise MercadoPagoError(f"Mercado Pago devolvió {r.status_code}.")
    pedido.mp_preference_id = r.json().get("id", "")
    pedido.save(update_fields=["mp_preference_id", "actualizado"])
    return pedido.mp_preference_id


def crear_pago(pedido, datos_tarjeta: dict, request) -> dict:
    """
    Cobra con la tarjeta que tokenizó el formulario. De lo que manda el navegador
    solo se usan el token y los datos de la tarjeta: el monto es el del pedido.
    """
    cred = credenciales()
    if not cred:
        raise MercadoPagoError("Mercado Pago no está conectado.")
    base, es_https = _base(request)
    pagador = datos_tarjeta.get("payer") or {}
    payload = {
        "transaction_amount": float(pedido.total),
        "token": datos_tarjeta.get("token"),
        "installments": int(datos_tarjeta.get("installments") or 1),
        "payment_method_id": datos_tarjeta.get("payment_method_id"),
        "description": f"CHAO Indumentaria · pedido #{pedido.pk}",
        "external_reference": str(pedido.pk),
        "statement_descriptor": "CHAO",
        "binary_mode": True,
        "metadata": {"pedido_id": pedido.pk},
        "payer": {
            "email": pagador.get("email") or pedido.email,
            **({"identification": pagador["identification"]} if pagador.get("identification") else {}),
        },
        "additional_info": {"items": _items(pedido)},
    }
    if datos_tarjeta.get("issuer_id"):
        payload["issuer_id"] = datos_tarjeta["issuer_id"]
    if es_https:
        payload["notification_url"] = f"{base}{reverse('pedidos:mp_webhook')}"
    if not payload["token"] or not payload["payment_method_id"]:
        raise MercadoPagoError("Faltan los datos de la tarjeta.")

    try:
        r = requests.post(
            f"{API}/v1/payments",
            json=payload,
            # Si la clienta toca dos veces "Pagar", Mercado Pago cobra una sola.
            headers=_headers(cred, **{"X-Idempotency-Key": f"chao-{pedido.pk}-{uuid.uuid4()}"}),
            timeout=TIMEOUT + 15,
        )
    except requests.RequestException as exc:
        raise MercadoPagoError(f"No se pudo contactar a Mercado Pago: {exc}") from exc
    if r.status_code >= 400:
        logger.error("MP rechazó el pago del pedido #%s (%s): %s", pedido.pk, r.status_code, r.text[:300])
        raise MercadoPagoError("Mercado Pago no pudo procesar el pago.")
    return r.json()


def consultar_pago(payment_id: str) -> dict:
    """Trae el pago desde la API. El webhook solo manda el id, nunca el estado."""
    cred = credenciales()
    if not cred:
        raise MercadoPagoError("Mercado Pago no está conectado.")
    try:
        r = requests.get(f"{API}/v1/payments/{payment_id}", headers=_headers(cred), timeout=TIMEOUT)
    except requests.RequestException as exc:
        raise MercadoPagoError(f"No se pudo consultar el pago {payment_id}: {exc}") from exc
    if r.status_code >= 400:
        raise MercadoPagoError(f"Mercado Pago devolvió {r.status_code} al consultar el pago.")
    return r.json()


def pago_coincide(pago: dict, pedido) -> bool:
    """El monto y la moneda del pago tienen que ser los del pedido (Operon Reservas)."""
    try:
        monto = Decimal(str(pago.get("transaction_amount")))
    except Exception:  # noqa: BLE001 — cualquier cosa rara = no coincide
        return False
    return pago.get("currency_id") == "ARS" and monto >= pedido.total - Decimal("0.01")


# --- Webhook -----------------------------------------------------------------------
def firma_valida(request, data_id: str) -> bool:
    """
    Verifica la cabecera x-signature con la clave secreta del webhook. Sin clave
    configurada no se puede verificar: se acepta, porque igual el estado se lee de
    la API con nuestro token (el aviso en sí no decide nada).
    """
    secreto = settings.MP_WEBHOOK_SECRET
    if not secreto:
        return True
    firma = request.headers.get("x-signature", "")
    partes = dict(p.strip().split("=", 1) for p in firma.split(",") if "=" in p)
    ts, v1 = partes.get("ts"), partes.get("v1")
    if not ts or not v1:
        return False
    manifiesto = f"id:{str(data_id).lower()};request-id:{request.headers.get('x-request-id', '')};ts:{ts};"
    esperado = hmac.new(secreto.encode(), manifiesto.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(esperado, v1)
