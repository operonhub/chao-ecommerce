"""
Editor de fotos con IA (Gemini · Nano Banana Pro).

La dueña saca la foto en el local (percha, vidriera, la calle de fondo) y la IA
la devuelve como foto de catálogo: fondo de estudio crema, luz pareja, prenda
centrada. Nunca reemplaza nada sola: la propuesta queda pendiente hasta que la
dueña la aprueba mirando las dos fotos lado a lado, y la original se guarda.

Lo más importante es que la PRENDA NO CAMBIE (corte, color, estampado, textos,
etiquetas): una foto que muestra algo distinto de lo que llega es un reclamo.
Por eso el pedido a la IA lo dice de varias maneras y se usa el modelo Pro, que
es el que mejor respeta los detalles. Si la Pro falla o no responde a tiempo,
se reintenta con el modelo rápido.

Se usa la API REST de generateContent con `requests`, sin SDK. La clave
(GEMINI_API_KEY) vive solo en las variables del hosting.
"""

from __future__ import annotations

import base64
import logging
import time
from io import BytesIO

import requests
from django.conf import settings
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

API = "https://generativelanguage.googleapis.com/v1beta"

INSTRUCCIONES = """You are retouching a real product photo for a women's clothing store's online catalog.

FIRST, look at the edges of the original photo. If the garment touches or is cut off by ANY edge (its hem, a sleeve, a leg or part of a print is missing), this is a CLOSE-UP: keep exactly that same crop, with the garment cut off at the same places. Only if the whole garment is visible with background all around it, show it whole.

Turn this phone photo, taken inside the shop, into a clean professional e-commerce product photo:
- Show ONLY the garment from the photo. Whole garment: hanging straight and centered on a simple light natural-wood hanger. Close-up: a studio detail shot of that same part, same crop, nothing added beyond the photo's edges.
- Background: a smooth, seamless warm cream studio wall (a soft beige close to #F2EADC), evenly lit.
- Soft diffused daylight from the front, gentle natural shadow, no harsh reflections.
- Remove everything else: racks, mannequins, other clothes, the shop window, the street, people.
- Vertical 3:4 framing (comfortable margins around the garment only when it is shown whole).

CRITICAL — the garment must stay EXACTLY the same as in the original photo:
- Same cut, length, sleeves, neckline, fit and proportions.
- Same exact colors and fabric texture. Do not make it brighter, whiter or more saturated than it really is.
- Same prints, graphics, embroidery and any text on it, letter by letter, in the same place and size.
- Do not add, remove, redraw, smooth away or "improve" any detail of the garment. Only fix wrinkles caused by the hanger lightly.

NO INVENTED LABELS, TAGS OR TEXT — this is strict:
- Remove ALL hang tags and price tags (cardboard or paper tags hanging on a string or plastic fastener). They are not part of the garment.
- Do NOT add any label, neck label, care label, brand tag, sticker, logo, brand name or text that is not in the original photo.
- If the original shows no sewn-in label, the result must show NO label.
- A sewn-in label that IS in the original (neck, waistband) stays in the same place and size, but always as a PLAIN patch of the same color with NO letters, numbers or logos on it. Do not try to reproduce its text.
- Buttons, rivets and zippers stay plain: no engraved or printed text on them unless it is huge and obvious in the original.
- Never write or invent brand names anywhere. Text is only allowed where it is part of the garment's own big print or graphic (like a slogan printed on a t-shirt), copied exactly.

DO NOT INVENT PARTS OF THE GARMENT:
- If the garment is cut off by an edge of the original photo, it must be cut off at the same place in the result. Keep that same partial framing (for example just the waist and a pocket, or the t-shirt without its hem).
- Never draw the missing parts (legs, hem, sleeves, bottom of a print) that are not in the photo.

Do not add any text, logo, watermark or props. Return only the edited image."""

PEDIDO_EXTRA = """

Extra request from the shop owner, written in Spanish: "{pedido}"
Apply it ONLY to the photo itself (background, light, framing, hanger, angle). It never overrides the rules
above: the garment must stay exactly the same and no labels, tags or text may be added."""

LARGO_PEDIDO = 240

TAMANO_ENTRADA = 2048  # lado mayor de la foto que se manda (más no mejora y pesa más)


class ErrorIA(RuntimeError):
    """No se pudo editar la foto (sin clave, sin crédito, la IA no devolvió imagen…)."""


def configurada() -> bool:
    return bool(settings.GEMINI_API_KEY)


def _preparar(imagen_bytes: bytes) -> tuple[str, str]:
    """Endereza (EXIF), achica y pasa a JPEG la foto que se manda."""
    img = ImageOps.exif_transpose(Image.open(BytesIO(imagen_bytes)))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((TAMANO_ENTRADA, TAMANO_ENTRADA), Image.Resampling.LANCZOS)
    salida = BytesIO()
    img.convert("RGB").save(salida, format="JPEG", quality=92)
    return base64.b64encode(salida.getvalue()).decode(), "image/jpeg"


def instrucciones(pedido: str = "") -> str:
    pedido = " ".join((pedido or "").split())[:LARGO_PEDIDO].replace('"', "'")
    return INSTRUCCIONES + (PEDIDO_EXTRA.format(pedido=pedido) if pedido else "")


def _pedir(modelo: str, datos: str, mime: str, timeout: float, pedido: str = "") -> bytes:
    cuerpo = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": instrucciones(pedido)},
                    {"inline_data": {"mime_type": mime, "data": datos}},
                ],
            }
        ],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": "3:4", "imageSize": "2K"},
        },
    }
    r = requests.post(
        f"{API}/models/{modelo}:generateContent",
        json=cuerpo,
        headers={"x-goog-api-key": settings.GEMINI_API_KEY, "Content-Type": "application/json"},
        timeout=timeout,
    )
    if r.status_code >= 400:
        try:
            error = r.json().get("error", {})
        except ValueError:
            error = {}
        logger.error("Gemini %s respondió %s: %s", modelo, r.status_code, (error.get("message") or r.text)[:300])
        raise ErrorIA(_mensaje_error(r.status_code, error))

    datos_resp = r.json()
    for candidato in datos_resp.get("candidates") or []:
        for parte in (candidato.get("content") or {}).get("parts") or []:
            imagen = parte.get("inlineData") or parte.get("inline_data")
            if imagen and imagen.get("data") and not parte.get("thought"):
                return base64.b64decode(imagen["data"])
    motivo = (datos_resp.get("promptFeedback") or {}).get("blockReason") or ""
    razon = ((datos_resp.get("candidates") or [{}])[0]).get("finishReason", "")
    logger.error("Gemini %s no devolvió imagen (bloqueo=%s, fin=%s)", modelo, motivo, razon)
    raise ErrorIA("La IA no devolvió una foto esta vez. Probá de nuevo.")


def _mensaje_error(status: int, error: dict) -> str:
    texto = (error.get("message") or "").lower()
    if status in (401, 403) or "api key" in texto:
        return "La clave de Gemini no es válida o no tiene permiso. Revisala en Vercel."
    if status == 429 or "quota" in texto or "billing" in texto:
        return "Gemini no tiene crédito o llegó al límite. Revisá la facturación en Google AI Studio."
    if status == 404:
        return "El modelo de IA no está disponible para esta clave."
    return "La IA no pudo editar la foto ahora. Probá de nuevo en un rato."


def mejorar(imagen_bytes: bytes, plazo: float | None = None, pedido: str = "") -> tuple[bytes, str]:
    """
    Devuelve (foto editada, modelo que la hizo). Prueba la Pro y, si falla o se
    queda sin tiempo, el modelo de respaldo con lo que queda del plazo.
    `pedido` es el cambio opcional que escribe la dueña ("más luz", "sin percha").
    """
    if not configurada():
        raise ErrorIA("Falta configurar la IA (GEMINI_API_KEY en Vercel).")
    plazo = plazo or settings.GEMINI_PLAZO
    datos, mime = _preparar(imagen_bytes)
    inicio = time.monotonic()
    ultimo_error = None
    modelos = [m for m in (settings.GEMINI_MODELO, settings.GEMINI_MODELO_RESPALDO) if m]
    for i, modelo in enumerate(modelos):
        restante = plazo - (time.monotonic() - inicio)
        # Al respaldo le hace falta un margen mínimo para tener sentido.
        if restante < 20:
            break
        try:
            return _pedir(modelo, datos, mime, timeout=restante - 5, pedido=pedido), modelo
        except requests.Timeout:
            logger.warning("Gemini %s tardó demasiado; pruebo el respaldo.", modelo)
            ultimo_error = ErrorIA("La IA tardó demasiado. Probá de nuevo.")
        except requests.RequestException as exc:
            ultimo_error = ErrorIA(f"No se pudo contactar a la IA: {exc.__class__.__name__}.")
        except ErrorIA as exc:
            ultimo_error = exc
            # Sin crédito o clave inválida: el respaldo va a fallar igual.
            if "clave" in str(exc) or "crédito" in str(exc):
                break
    raise ultimo_error or ErrorIA("La IA no pudo editar la foto.")


def modelos_disponibles() -> list[dict]:
    """Para el diagnóstico del panel: qué modelos de imagen ve esta clave."""
    r = requests.get(
        f"{API}/models", params={"pageSize": 1000}, headers={"x-goog-api-key": settings.GEMINI_API_KEY}, timeout=20
    )
    r.raise_for_status()
    return [
        {"modelo": m["name"].split("/", 1)[-1], "metodos": m.get("supportedGenerationMethods", [])}
        for m in r.json().get("models", [])
        if "image" in m["name"].lower() or "banana" in m["name"].lower()
    ]
