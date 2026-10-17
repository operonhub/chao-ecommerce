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

CRITICAL — this is a real product that a customer will receive. The garment must be IDENTICAL to the one in the original photo:
- LENGTH AND WIDTHS: keep the exact proportions of the garment. Same ratio between its length and its width; same width at the shoulders, chest, waist and hem; same length and width of the sleeves (or legs); same neckline shape and depth. Do not make it longer, shorter, slimmer, wider, more fitted, more cropped or more flowy. Do not change the cut or the fit. When it is shown whole on the hanger, it hangs with the same shape it has in the original.
- COLOR: exactly the same color, shade and tone as the garment in the original, as it would look in neutral daylight. Do not change the hue and do not make it brighter, darker, whiter, more saturated or more faded. Black stays black, a beige stays that same beige, a washed denim keeps its exact wash and fading. The new studio light changes the background, not the garment's color.
- PRINT: copy the print, graphic, embroidery or pattern exactly: every element, with the same colors, the same size relative to the garment and the same position (same distance to the neckline, the hem and the sides). Do not redraw, simplify, complete, sharpen, mirror, recolor or add any element. Any text that is part of the print is copied letter by letter. If part of the print is hidden, folded or cut off in the original, it stays that way.
- TEXTURE AND DETAILS: same fabric texture (knit, slub cotton, ribbing, denim), seams, stitching, buttons, pockets, rips and trims, in the same places.
- Do not add, remove, redraw, smooth away or "improve" anything on the garment. Only lightly reduce wrinkles caused by the hanger.

NO INVENTED LABELS, TAGS OR TEXT — this is strict:
- Remove ALL hang tags and price tags (cardboard or paper tags hanging on a string or plastic fastener). They are not part of the garment.
- Do NOT add any label, neck label, care label, brand tag, sticker, logo, brand name or text that is not in the original photo.
- If the original shows no sewn-in label, the result must show NO label.
{regla_etiqueta}
- Buttons, rivets and zippers stay plain: no engraved or printed text on them unless it is huge and obvious in the original.
{regla_marcas}

DO NOT INVENT PARTS OF THE GARMENT:
- If the garment is cut off by an edge of the original photo, it must be cut off at the same place in the result. Keep that same partial framing (for example just the waist and a pocket, or the t-shirt without its hem).
- Never draw the missing parts (legs, hem, sleeves, bottom of a print) that are not in the photo.

Before returning the image, compare the garment with the original one more time: length, widths, color, print, label and details. If anything is different, fix it so it matches the original.

Do not add any text, logo, watermark or props. Return only the edited image."""

PEDIDO_EXTRA = """

Extra request from the shop owner, written in Spanish: "{pedido}"
Apply it ONLY to the photo itself (background, light, framing, hanger, angle). It never overrides the rules
above: the garment must stay exactly the same and no labels, tags or text may be added."""

LARGO_PEDIDO = 240

# La etiqueta cosida. La IA no sabe leer la letra chica de una etiqueta e inventa
# marcas ("ST. BARTH" por St. Marie): sin marca cargada sale lisa; con marca, se le
# dicta el texto exacto, que es lo único que puede escribir ahí.
ETIQUETA_LISA = (
    "- A sewn-in label that IS in the original (neck, waistband) stays in the same place and size, but always as a "
    "PLAIN patch of the same color with NO letters, numbers or logos on it. Do not try to reproduce its text."
)
MARCAS_NINGUNA = (
    "- Never write or invent brand names anywhere. Text is only allowed where it is part of the garment's own big "
    "print or graphic (like a slogan printed on a t-shirt), copied exactly."
)
ETIQUETA_CON_MARCA = (
    '- A sewn-in label that IS in the original (neck, waistband) stays in the same place, size and colors. The brand '
    'on it is "{marca}": write exactly "{rotulo}" on it, spelled exactly like that, and nothing else (no sizes, '
    "numbers, logos or other words). Copy the LOOK of the lettering on the original label as closely as you can: "
    "same kind of typeface (serif or sans-serif, condensed or wide, thin or bold), same letter color, same size "
    "relative to the label and same layout (one line, centered, spacing). Only the words come from this text: do "
    "not try to read them from the photo."
)
MARCAS_SOLO_ESA = (
    '- The only brand name allowed anywhere in the photo is "{rotulo}", and only on that sewn-in label. Never write '
    "any other brand name. Other text is only allowed where it is part of the garment's own big print or graphic "
    "(like a slogan printed on a t-shirt), copied exactly."
)
LARGO_MARCA = 40

TAMANO_ENTRADA = 2048  # lado mayor de la foto que se manda (más no mejora y pesa más)


class ErrorIA(RuntimeError):
    """No se pudo editar la foto (sin clave, sin crédito, la IA no devolvió imagen…)."""


def configurada() -> bool:
    return bool(settings.GEMINI_API_KEY)


def _preparar(imagen_bytes: bytes, lado: int = TAMANO_ENTRADA) -> tuple[str, str]:
    """Endereza (EXIF), achica y pasa a JPEG la foto que se manda."""
    img = ImageOps.exif_transpose(Image.open(BytesIO(imagen_bytes)))
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((lado, lado), Image.Resampling.LANCZOS)
    salida = BytesIO()
    img.convert("RGB").save(salida, format="JPEG", quality=92)
    return base64.b64encode(salida.getvalue()).decode(), "image/jpeg"


def instrucciones(pedido: str = "", marca: str = "") -> str:
    pedido = " ".join((pedido or "").split())[:LARGO_PEDIDO].replace('"', "'")
    marca = " ".join((marca or "").split())[:LARGO_MARCA].replace('"', "'")
    if marca:
        rotulo = marca.upper()
        reglas = {
            "regla_etiqueta": ETIQUETA_CON_MARCA.format(marca=marca, rotulo=rotulo),
            "regla_marcas": MARCAS_SOLO_ESA.format(rotulo=rotulo),
        }
    else:
        reglas = {"regla_etiqueta": ETIQUETA_LISA, "regla_marcas": MARCAS_NINGUNA}
    texto = INSTRUCCIONES.replace("{regla_etiqueta}", reglas["regla_etiqueta"]).replace(
        "{regla_marcas}", reglas["regla_marcas"]
    )
    return texto + (PEDIDO_EXTRA.format(pedido=pedido) if pedido else "")


def _pedir(modelo: str, datos: str, mime: str, timeout: float, pedido: str = "", marca: str = "") -> bytes:
    cuerpo = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": instrucciones(pedido, marca)},
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
    if status in (402, 429) or "quota" in texto or "billing" in texto or "credit" in texto:
        return "Se terminó el crédito de la IA (o llegó al límite). Hay que cargar más en Google AI Studio → Billing."
    if status == 404:
        return "El modelo de IA no está disponible para esta clave."
    return "La IA no pudo editar la foto ahora. Probá de nuevo en un rato."


def mejorar(imagen_bytes: bytes, plazo: float | None = None, pedido: str = "", marca: str = "") -> tuple[bytes, str]:
    """
    Devuelve (foto editada, modelo que la hizo). Prueba la Pro y, si falla o se
    queda sin tiempo, el modelo de respaldo con lo que queda del plazo.
    `pedido` es el cambio opcional que escribe la dueña ("más luz", "sin percha").
    `marca` es la de la prenda: si la tiene, es el texto que va en la etiqueta.
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
            return _pedir(modelo, datos, mime, timeout=restante - 5, pedido=pedido, marca=marca), modelo
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


# --- Descripción de la prenda -------------------------------------------------
# A la dueña le cuesta escribirlas: la IA mira las fotos (y lo que ella anote,
# "algodón, oversize") y propone dos o tres oraciones en el tono de la tienda.
# Nada se guarda solo: el texto cae en el campo y ella lo corrige o lo borra.
DESCRIBIR = """Sos quien escribe las fichas de CHAO Indumentaria, una tienda de ropa de mujer de Villa Bosch (Buenos Aires).
Escribí la descripción de esta prenda para la tienda online, mirando la(s) foto(s).

Prenda: {nombre}
Marca: {marca}
Categoría: {categoria}
Lo que anotó la dueña (es verdad, usalo): {notas}

Cómo escribir:
- Español rioplatense, de vos, cercano y simple, como habla la dueña en el local. Nada de lenguaje de catálogo ni palabras rebuscadas.
- Entre 2 y 3 oraciones cortas, máximo 300 caracteres en total.
- Contá lo que se ve: color, corte, cuello, mangas, largo, estampa o detalle, textura (tejido, punto fino, denim).
- Podés cerrar con una idea de con qué combinarla o cuándo usarla.

Nunca inventes datos que no se ven en la foto ni anotó la dueña:
- Ni composición de la tela (algodón, lana, lino, poliéster…), ni medidas, talles, calce exacto, cuidados, origen ni marca (la única marca que podés nombrar es la de arriba, si hay).
- Ni precios, ofertas, stock, envíos ni promesas ("no se deforma", "dura años").
- Si la foto es de cerca y no se ve la prenda entera, no describas el largo ni lo que no se ve.

Sin emojis, sin hashtags, sin comillas, sin signos de exclamación y sin título. Devolvé solo el texto de la descripción."""

LARGO_NOTAS = 400
LARGO_DESCRIPCION = 600  # tope duro por si el modelo se va de largo


def describir(fotos: list[bytes], nombre: str = "", categoria: str = "", notas: str = "", marca: str = "") -> str:
    """Propone una descripción a partir de hasta 3 fotos y lo que anotó la dueña."""
    if not configurada():
        raise ErrorIA("Falta configurar la IA (GEMINI_API_KEY en Vercel).")
    if not fotos and not (nombre or notas):
        raise ErrorIA("Subí una foto o escribí el nombre de la prenda primero.")

    limpio = lambda t, n: " ".join((t or "").split())[:n] or "(nada)"  # noqa: E731
    partes = [
        {
            "text": DESCRIBIR.format(
                nombre=limpio(nombre, 120),
                marca=limpio(marca, LARGO_MARCA),
                categoria=limpio(categoria, 60),
                notas=limpio(notas, LARGO_NOTAS),
            )
        }
    ]
    for foto in fotos[:3]:
        datos, mime = _preparar(foto, lado=1024)
        partes.append({"inline_data": {"mime_type": mime, "data": datos}})
    cuerpo = {"contents": [{"role": "user", "parts": partes}], "generationConfig": {"temperature": 0.7}}

    ultimo_error = None
    for modelo in [m for m in (settings.GEMINI_MODELO_TEXTO, settings.GEMINI_MODELO_TEXTO_RESPALDO) if m]:
        try:
            r = requests.post(
                f"{API}/models/{modelo}:generateContent",
                json=cuerpo,
                headers={"x-goog-api-key": settings.GEMINI_API_KEY, "Content-Type": "application/json"},
                timeout=60,
            )
        except requests.RequestException as exc:
            ultimo_error = ErrorIA(f"No se pudo contactar a la IA: {exc.__class__.__name__}.")
            continue
        if r.status_code >= 400:
            try:
                error = r.json().get("error", {})
            except ValueError:
                error = {}
            logger.error("Gemini %s respondió %s: %s", modelo, r.status_code, (error.get("message") or r.text)[:300])
            ultimo_error = ErrorIA(_mensaje_error(r.status_code, error))
            if r.status_code in (401, 402, 403, 429):
                break
            continue
        texto = "".join(
            p.get("text", "")
            for c in r.json().get("candidates") or []
            for p in (c.get("content") or {}).get("parts") or []
            if not p.get("thought")
        )
        texto = " ".join(texto.split()).strip().strip('"«»“”').strip()
        if texto:
            return texto[:LARGO_DESCRIPCION]
        ultimo_error = ErrorIA("La IA no devolvió un texto esta vez. Probá de nuevo.")
    raise ultimo_error or ErrorIA("La IA no pudo escribir la descripción.")


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
