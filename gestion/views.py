"""
Panel de la dueña ("Mi tienda").

Aparte del admin de Django (/panel/, que queda como herramienta avanzada para los
looks y sus puntos): este es el que se usa todos los días, desde el celular, para
cargar prendas, cambiar precios, marcar tendencias y seguir los pedidos.

Escribe sobre los mismos modelos que lee la tienda, así que lo que se guarda acá
se ve en la web al instante. Solo entra personal (is_staff).
"""

from __future__ import annotations

import logging
import re
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from urllib.parse import urlencode

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, F, Max, Q, Sum
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from PIL import Image, ImageOps

from catalogo.models import (
    Categoria,
    ColorPrenda,
    Look,
    Portada,
    Producto,
    ProductoImagen,
    Talle,
    Variante,
)
from pedidos.models import Cobros, ConexionMP, Pedido, ZonaEnvio
from pedidos.services import mercadopago

from . import ia
from .models import CreditoIA, UsoIA
from .forms import CobrosForm, PortadaForm, ProductoForm, ZonaForm


logger = logging.getLogger(__name__)


def _es_staff(usuario):
    return usuario.is_active and usuario.is_staff


solo_duena = user_passes_test(_es_staff, login_url="gestion:ingresar")


# --- Ingreso ---------------------------------------------------------------
class Ingresar(auth_views.LoginView):
    template_name = "gestion/ingresar.html"
    next_page = "gestion:inicio"

    def get(self, request, *args, **kwargs):
        if _es_staff(request.user):
            return redirect("gestion:inicio")
        return super().get(request, *args, **kwargs)


salir = auth_views.LogoutView.as_view(next_page="gestion:ingresar")


# --- Inicio ----------------------------------------------------------------
@solo_duena
def inicio(request):
    prendas = list(Producto.objects.prefetch_related("variantes"))
    activas = [p for p in prendas if p.activo]

    hace_30 = timezone.now() - timedelta(days=30)
    pagados_mes = Pedido.objects.filter(estado=Pedido.Estado.PAGADO, creado__gte=hace_30)

    contexto = {
        "seccion": "inicio",
        "n_activas": len(activas),
        "n_ocultas": len(prendas) - len(activas),
        "sin_stock": [p for p in activas if p.variantes.all() and p.stock_total == 0],
        "pocas": [p for p in activas if 0 < p.stock_total <= 3],
        "n_destacadas": sum(1 for p in activas if p.destacado),
        "n_pendientes": Pedido.objects.filter(estado=Pedido.Estado.PENDIENTE).count(),
        "n_sin_entregar": Pedido.objects.filter(estado=Pedido.Estado.PAGADO, entregado=False).count(),
        "vendido_30": pagados_mes.aggregate(t=Sum("total"))["t"] or 0,
        "n_vendidos_30": pagados_mes.count(),
        "recientes": Pedido.objects.prefetch_related("items__producto", "items__talle")[:5],
        # Lo que falta para cobrar online: se avisa arriba de todo en el Inicio.
        "falta_mp": not ConexionMP.actual(),
        "falta_transferencia": not Cobros.actual().transferencia_lista,
        "app_mp": mercadopago.app_configurada(),
        "credito_ia": CreditoIA.actual() if ia.configurada() else None,
    }
    return render(request, "gestion/inicio.html", contexto)


# --- Prendas -----------------------------------------------------------------
@solo_duena
def prendas(request):
    qs = (
        Producto.objects.select_related("categoria")
        .prefetch_related("imagenes", "variantes__talle")
        .annotate(n_var=Count("variantes", distinct=True), stock_sum=Sum("variantes__stock"))
        .order_by("-activo", "-destacado", "orden", "nombre")
    )

    q = (request.GET.get("q") or "").strip()
    if q:
        qs = qs.filter(
            Q(nombre__icontains=q) | Q(marca__icontains=q) | Q(descripcion__icontains=q) | Q(etiqueta__icontains=q)
        )

    cat = request.GET.get("cat") or ""
    if cat:
        qs = qs.filter(categoria__slug=cat)

    ver = request.GET.get("ver") or ""
    filtros = {
        "visibles": Q(activo=True),
        "ocultas": Q(activo=False),
        "destacadas": Q(destacado=True),
        "oferta": Q(precio_anterior__isnull=False, precio_anterior__gt=F("precio")),
        "sin-stock": Q(n_var__gt=0, stock_sum=0),
    }
    if ver in filtros:
        qs = qs.filter(filtros[ver])

    return render(
        request,
        "gestion/prendas.html",
        {
            "seccion": "prendas",
            "prendas": qs,
            "categorias": Categoria.objects.all(),
            "q": q,
            "cat": cat,
            "ver": ver,
            "base_filtros": urlencode({"q": q, "cat": cat}),
        },
    )


def _normalizar_imagen(archivo) -> ContentFile:
    """
    Las fotos del celular llegan de 4000px y 6 MB, giradas según el EXIF. Se
    enderezan y se achican a 1600px de lado mayor en JPEG: se ven igual de bien
    en la tienda y la página carga diez veces más rápido.
    """
    img = Image.open(archivo)
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        fondo = Image.new("RGB", img.size, (250, 246, 238))
        if img.mode in ("RGBA", "LA"):
            fondo.paste(img, mask=img.getchannel("A"))
        else:
            fondo.paste(img.convert("RGB"))
        img = fondo
    img.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    salida = BytesIO()
    img.convert("RGB").save(salida, format="JPEG", quality=85, optimize=True, progressive=True)
    return ContentFile(salida.getvalue())


def _guardar_fotos(archivos, prenda) -> list[str]:
    """Valida cada archivo como imagen real (no alcanza con la extensión)."""
    errores = []
    orden = prenda.imagenes.aggregate(m=Max("orden"))["m"] or 0
    validador = forms.ImageField()
    for archivo in archivos:
        if archivo.size > 15 * 1024 * 1024:
            errores.append(f"{archivo.name}: pesa más de 15 MB.")
            continue
        try:
            validador.clean(archivo)
            archivo.seek(0)
            contenido = _normalizar_imagen(archivo)
        except (ValidationError, OSError):
            errores.append(f"{archivo.name}: no es una imagen que se pueda abrir.")
            continue
        orden += 1
        foto = ProductoImagen(producto=prenda, alt=prenda.nombre, orden=orden)
        foto.imagen.save(f"{prenda.slug}-{orden}.jpg", contenido, save=False)
        foto.save()
    return errores


def _guardar_stock(post, clave, prenda, talle, color):
    """
    Una casilla de stock. Que no venga la casilla = no se toca (por ejemplo, un
    color recién agregado todavía no tiene casillas). Vacía = la prenda no viene
    en ese talle (y color); 0 = viene, pero no hay stock ahora. La diferencia
    importa en la tienda: el talle agotado aparece tachado, el que no existe no.
    """
    if clave not in post:
        return
    crudo = (post.get(clave) or "").strip()
    if crudo == "":
        Variante.objects.filter(producto=prenda, talle=talle, color=color).delete()
        return
    try:
        stock = max(0, int(crudo))
    except ValueError:
        return
    Variante.objects.update_or_create(producto=prenda, talle=talle, color=color, defaults={"stock": stock})


def _guardar_talles(post, prenda, talles):
    # Sin colores: una casilla por talle (stock_<talle>). Con colores: una por
    # color y talle (stock_<color>_<talle>).
    colores = list(prenda.colores.all())
    for talle in talles:
        _guardar_stock(post, f"stock_{talle.pk}", prenda, talle, None)
        for color in colores:
            _guardar_stock(post, f"stock_{color.pk}_{talle.pk}", prenda, talle, color)

    nuevo = (post.get("talle_nuevo") or "").strip()[:10]
    if nuevo:
        talle, _ = Talle.objects.get_or_create(nombre=nuevo, defaults={"orden": 50})
        try:
            stock = max(0, int(post.get("talle_nuevo_stock") or 0))
        except ValueError:
            stock = 0
        if prenda.colores.exists():
            # Con colores, el talle nuevo aparece en cada color para cargarle stock.
            return
        Variante.objects.update_or_create(producto=prenda, talle=talle, color=None, defaults={"stock": stock})


HEX_VALIDO = re.compile(r"^#[0-9a-fA-F]{6}$")


def _guardar_colores(post, prenda) -> list[str]:
    """
    Colores de la prenda: renombrar, cambiar el circulito, quitar y agregar.
    Devuelve avisos para la dueña. Si la prenda recibe su PRIMER color y ya
    tenía stock por talle, ese stock pasa a ese color: no se pierde nada.
    """
    avisos = []
    tenia_colores = prenda.colores.exists()

    for color in list(prenda.colores.all()):
        if post.get(f"color_borrar_{color.pk}"):
            color.delete()  # sus talles y stock se van con él
            continue
        nombre = (post.get(f"color_nombre_{color.pk}") or "").strip()[:40]
        hex_ = (post.get(f"color_hex_{color.pk}") or "").strip()
        cambios = []
        if nombre and nombre != color.nombre:
            if prenda.colores.filter(nombre__iexact=nombre).exclude(pk=color.pk).exists():
                avisos.append(f"Ya hay un color «{nombre}» en esta prenda.")
            else:
                color.nombre = nombre
                cambios.append("nombre")
        if HEX_VALIDO.match(hex_) and hex_.lower() != color.hex.lower():
            color.hex = hex_.lower()
            cambios.append("hex")
        if cambios:
            color.save(update_fields=cambios)

    nuevos = []
    orden = prenda.colores.count()
    for nombre, hex_ in zip(post.getlist("color_nuevo_nombre"), post.getlist("color_nuevo_hex")):
        nombre = (nombre or "").strip()[:40]
        if not nombre:
            continue
        if prenda.colores.filter(nombre__iexact=nombre).exists():
            avisos.append(f"Ya hay un color «{nombre}» en esta prenda.")
            continue
        orden += 1
        nuevos.append(
            ColorPrenda.objects.create(
                producto=prenda, nombre=nombre, hex=hex_.lower() if HEX_VALIDO.match(hex_ or "") else "#b1cfd1",
                orden=orden,
            )
        )

    if nuevos and not tenia_colores:
        sin_color = Variante.objects.filter(producto=prenda, color__isnull=True)
        if sin_color.exists():
            sin_color.update(color=nuevos[0])
            avisos.append(f"El stock que ya tenía la prenda quedó en el color «{nuevos[0].nombre}».")
    if nuevos:
        avisos.append("Cargá el stock de los colores nuevos en «Talles y stock».")
    return avisos


def _guardar_colores_de_fotos(post, prenda):
    """Cada foto puede ser de un color (o de todos, si queda vacío)."""
    colores = {str(c.pk): c for c in prenda.colores.all()}
    for foto in prenda.imagenes.all():
        clave = f"foto_color_{foto.pk}"
        if clave not in post:
            continue
        color = colores.get(post.get(clave) or "")
        if foto.color_id != (color.pk if color else None):
            foto.color = color
            foto.save(update_fields=["color"])


@solo_duena
def prenda_editar(request, pk=None):
    prenda = get_object_or_404(Producto, pk=pk) if pk else None
    talles = list(Talle.objects.all())

    if request.method == "POST":
        form = ProductoForm(request.POST, instance=prenda)
        if form.is_valid():
            with transaction.atomic():
                prenda = form.save()
                # Primero el stock tal como se veía en pantalla y después los
                # cambios de colores (un color nuevo todavía no tenía casillas).
                _guardar_talles(request.POST, prenda, talles)
                avisos = _guardar_colores(request.POST, prenda)
                _guardar_colores_de_fotos(request.POST, prenda)
                errores = _guardar_fotos(request.FILES.getlist("fotos"), prenda)
            for aviso in avisos:
                messages.info(request, aviso)
            for error in errores:
                messages.warning(request, error)
            messages.success(request, f"Guardamos «{prenda.nombre}».")
            if request.POST.get("despues") == "otra":
                return redirect("gestion:prenda_nueva")
            return redirect("gestion:prenda_editar", pk=prenda.pk)
        messages.error(request, "Revisá los campos marcados.")
    else:
        form = ProductoForm(instance=prenda)

    variantes = list(prenda.variantes.all()) if prenda else []
    stock_por_talle = {v.talle_id: v.stock for v in variantes if v.color_id is None}
    filas_talle = [{"talle": t, "stock": stock_por_talle.get(t.pk, "")} for t in talles]

    # Con colores: un bloque por color con una casilla por talle.
    colores = list(prenda.colores.all()) if prenda else []
    stock_color = {(v.color_id, v.talle_id): v.stock for v in variantes if v.color_id}
    bloques_color = [
        {
            "color": col,
            "filas": [{"talle": t, "stock": stock_color.get((col.pk, t.pk), "")} for t in talles],
        }
        for col in colores
    ]

    return render(
        request,
        "gestion/prenda_form.html",
        {
            "seccion": "prendas",
            "form": form,
            "prenda": prenda,
            "fotos": prenda.imagenes.all() if prenda else [],
            "filas_talle": filas_talle,
            "colores": colores,
            "bloques_color": bloques_color,
            # Las marcas ya usadas, para sugerirlas al escribir (St. Marie…).
            "marcas": Producto.objects.exclude(marca="").values_list("marca", flat=True).distinct().order_by("marca"),
            "ia_activa": ia.configurada(),
            "credito_ia": CreditoIA.actual() if ia.configurada() else None,
            "categorias": Categoria.objects.all(),
            "vendida": prenda.items_pedido.exists() if prenda else False,
        },
    )


@solo_duena
@require_POST
def prenda_borrar(request, pk):
    prenda = get_object_or_404(Producto, pk=pk)
    if prenda.items_pedido.exists():
        # Tiene pedidos: borrarla rompería el historial. Se oculta.
        prenda.activo = False
        prenda.save(update_fields=["activo"])
        messages.info(request, f"«{prenda.nombre}» tiene pedidos, así que la ocultamos en vez de borrarla.")
    else:
        nombre = prenda.nombre
        for foto in prenda.imagenes.all():
            if foto.imagen:
                foto.imagen.delete(save=False)
        prenda.delete()
        messages.success(request, f"Borramos «{nombre}».")
    return redirect("gestion:prendas")


# --- Acciones rápidas (fetch, JSON) ---------------------------------------------
CAMPOS_TOGGLE = {"activo", "destacado"}


@solo_duena
@require_POST
def prenda_toggle(request, pk):
    campo = request.POST.get("campo")
    if campo not in CAMPOS_TOGGLE:
        return HttpResponseBadRequest("Campo inválido.")
    prenda = get_object_or_404(Producto, pk=pk)
    setattr(prenda, campo, not getattr(prenda, campo))
    prenda.save(update_fields=[campo])
    return JsonResponse({"ok": True, "valor": getattr(prenda, campo)})


@solo_duena
@require_POST
def prenda_precio(request, pk):
    prenda = get_object_or_404(Producto, pk=pk)
    crudo = (request.POST.get("precio") or "").replace("$", "").replace(".", "").replace(",", ".").strip()
    try:
        precio = Decimal(crudo)
    except InvalidOperation:
        return JsonResponse({"ok": False, "error": "Precio inválido."}, status=400)
    if precio <= 0:
        return JsonResponse({"ok": False, "error": "El precio tiene que ser mayor a cero."}, status=400)
    prenda.precio = precio
    prenda.save(update_fields=["precio"])
    return JsonResponse({"ok": True, "precio": int(precio)})


def _normalizar_orden(prenda):
    fotos = list(prenda.imagenes.all())
    for i, foto in enumerate(fotos):
        if foto.orden != i:
            foto.orden = i
            foto.save(update_fields=["orden"])
    return fotos


@solo_duena
@require_POST
def foto_mover(request, pk):
    foto = get_object_or_404(ProductoImagen, pk=pk)
    fotos = _normalizar_orden(foto.producto)
    i = next(n for n, f in enumerate(fotos) if f.pk == foto.pk)
    destino = {"izq": i - 1, "der": i + 1, "principal": 0}.get(request.POST.get("dir"))
    if destino is None or not 0 <= destino < len(fotos):
        return JsonResponse({"ok": True, "orden": [f.pk for f in fotos]})
    fotos.insert(destino, fotos.pop(i))
    for n, f in enumerate(fotos):
        if f.orden != n:
            f.orden = n
            f.save(update_fields=["orden"])
    return JsonResponse({"ok": True, "orden": [f.pk for f in fotos]})


@solo_duena
@require_POST
def foto_borrar(request, pk):
    foto = get_object_or_404(ProductoImagen, pk=pk)
    if foto.imagen:
        foto.imagen.delete(save=False)
    foto.delete()
    return JsonResponse({"ok": True})


# --- Fotos con IA (Gemini) ----------------------------------------------------------
def _leer_foto(foto) -> bytes:
    """
    Los bytes de la foto ORIGINAL (la que sacó la dueña), venga del storage o de
    static/. Si la foto publicada ya es una versión con IA, se parte de la
    original guardada: editar lo ya editado va acumulando inventos.
    """
    from django.core.files.storage import default_storage

    if foto.original:
        tipo, _, ruta = foto.original.partition(":")
        if tipo == "img":
            with default_storage.open(ruta, "rb") as f:
                return f.read()
        return _leer_estatica(ruta)
    if foto.imagen:
        with foto.imagen.open("rb") as f:
            return f.read()
    return _leer_estatica(foto.ruta_estatica)


def _leer_estatica(ruta_estatica: str) -> bytes:
    if ruta_estatica:
        from django.contrib.staticfiles import finders
        from django.contrib.staticfiles.storage import staticfiles_storage

        try:
            with staticfiles_storage.open(ruta_estatica) as f:
                return f.read()
        except (FileNotFoundError, OSError):
            ruta = finders.find(ruta_estatica)  # en desarrollo, sin collectstatic
            if ruta:
                with open(ruta, "rb") as f:
                    return f.read()
    raise ia.ErrorIA("No encontramos el archivo de esta foto.")


def _borrar_archivo(nombre: str) -> None:
    from django.core.files.storage import default_storage

    if nombre:
        try:
            default_storage.delete(nombre)
        except Exception:  # noqa: BLE001 — un archivo huérfano no es motivo para fallar
            pass


@solo_duena
@require_POST
def foto_ia(request, pk):
    """Pide a la IA la versión de catálogo de la foto. Queda pendiente de aprobar."""
    from django.core.files.storage import default_storage

    foto = get_object_or_404(ProductoImagen.objects.select_related("producto"), pk=pk)
    try:
        # La marca: la que está escrita en la ficha (aunque no se haya guardado) o la guardada.
        marca = request.POST["marca"] if "marca" in request.POST else foto.producto.marca
        editada, modelo = ia.mejorar(_leer_foto(foto), pedido=request.POST.get("pedido", ""), marca=marca)
        archivo = _normalizar_imagen(BytesIO(editada))
    except ia.ErrorIA as exc:
        _si_es_sin_credito(exc)
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
    except Exception:  # noqa: BLE001
        logger.exception("Falló la edición con IA de la foto %s", pk)
        return JsonResponse({"ok": False, "error": "No pudimos editar la foto. Probá de nuevo."}, status=500)

    _borrar_archivo(foto.ia_pendiente)  # si había una propuesta anterior sin usar
    nombre = default_storage.save(f"productos/ia/{foto.producto.slug[:60]}.jpg", archivo)
    foto.ia_pendiente = nombre
    foto.save(update_fields=["ia_pendiente"])
    UsoIA.anotar(UsoIA.Tipo.FOTO, modelo)
    logger.info("Foto %s editada con %s", pk, modelo)
    return JsonResponse({"ok": True, "url": foto.url_ia_pendiente, "original": foto.url, "modelo": modelo})


@solo_duena
@require_POST
def foto_ia_usar(request, pk):
    """Reemplaza la foto por la versión de la IA y guarda la original."""
    foto = get_object_or_404(ProductoImagen, pk=pk)
    if not foto.ia_pendiente:
        return JsonResponse({"ok": False, "error": "No hay una versión con IA para usar."}, status=400)
    # Si la foto ya era una versión con IA, la original verdadera sigue siendo la primera.
    if not foto.original:
        foto.original = f"img:{foto.imagen.name}" if foto.imagen else f"static:{foto.ruta_estatica}"
    elif foto.imagen:
        _borrar_archivo(foto.imagen.name)
    foto.imagen.name = foto.ia_pendiente
    foto.ruta_estatica = ""
    foto.ia_pendiente = ""
    foto.save(update_fields=["imagen", "ruta_estatica", "ia_pendiente", "original"])
    return JsonResponse({"ok": True, "url": foto.url})


@solo_duena
@require_POST
def foto_ia_descartar(request, pk):
    foto = get_object_or_404(ProductoImagen, pk=pk)
    _borrar_archivo(foto.ia_pendiente)
    foto.ia_pendiente = ""
    foto.save(update_fields=["ia_pendiente"])
    return JsonResponse({"ok": True})


@solo_duena
@require_POST
def foto_ia_original(request, pk):
    """Vuelve a la foto original (la versión con IA se borra)."""
    foto = get_object_or_404(ProductoImagen, pk=pk)
    if not foto.original:
        return JsonResponse({"ok": False, "error": "Esta foto ya es la original."}, status=400)
    tipo, _, ruta = foto.original.partition(":")
    if foto.imagen:
        _borrar_archivo(foto.imagen.name)
    if tipo == "static":
        foto.imagen.name = ""
        foto.ruta_estatica = ruta
    else:
        foto.imagen.name = ruta
        foto.ruta_estatica = ""
    foto.original = ""
    foto.save(update_fields=["imagen", "ruta_estatica", "original"])
    return JsonResponse({"ok": True, "url": foto.url})


@solo_duena
@require_POST
def descripcion_ia(request):
    """
    Propone la descripción de una prenda. Mira las fotos que se están por subir y
    las ya guardadas (hasta 3) y lo que la dueña escribió en el campo, que la IA
    toma como datos ciertos. Devuelve el texto; no guarda nada.
    """
    fotos = []
    for archivo in request.FILES.getlist("fotos")[:3]:
        if archivo.size <= 15 * 1024 * 1024:
            fotos.append(archivo.read())
    pk = request.POST.get("prenda") or ""
    if pk.isdigit() and len(fotos) < 3:
        for foto in ProductoImagen.objects.filter(producto_id=int(pk))[: 3 - len(fotos)]:
            try:
                fotos.append(_leer_foto(foto))
            except Exception:  # noqa: BLE001 — una foto que no se lee no frena la descripción
                logger.warning("No se pudo leer la foto %s para describir", foto.pk)

    categoria = (request.POST.get("nueva_categoria") or "").strip()
    if not categoria and (request.POST.get("categoria") or "").isdigit():
        categoria = Categoria.objects.filter(pk=request.POST["categoria"]).values_list("nombre", flat=True).first() or ""
    try:
        texto = ia.describir(
            fotos,
            nombre=request.POST.get("nombre", ""),
            marca=request.POST.get("marca", ""),
            categoria=categoria,
            notas=request.POST.get("notas", ""),
        )
    except ia.ErrorIA as exc:
        _si_es_sin_credito(exc)
        return JsonResponse({"ok": False, "error": str(exc)}, status=502)
    except Exception:  # noqa: BLE001
        logger.exception("Falló la descripción con IA")
        return JsonResponse({"ok": False, "error": "No pudimos escribir la descripción. Probá de nuevo."}, status=500)
    UsoIA.anotar(UsoIA.Tipo.DESCRIPCION, settings.GEMINI_MODELO_TEXTO)
    return JsonResponse({"ok": True, "texto": texto})


def _si_es_sin_credito(exc) -> None:
    """Google avisó que no hay saldo: el contador pasa a "sin crédito" hasta que se anote uno nuevo."""
    if "crédito" in str(exc):
        CreditoIA.objects.update_or_create(pk=1, defaults={"sin_credito": True})


@solo_duena
@require_POST
def credito_ia(request):
    """Anota el saldo que figura hoy en AI Studio → Billing; desde ahí se descuenta."""
    crudo = (request.POST.get("saldo") or "").replace("US$", "").replace("$", "").replace(",", ".").strip()
    try:
        saldo = Decimal(crudo)
    except InvalidOperation:
        saldo = None
    if saldo is None or saldo < 0 or saldo > 10000:
        messages.error(request, "Escribí el saldo en dólares, por ejemplo 10 o 7.50.")
        return redirect(reverse("gestion:inicio") + "#credito-ia")
    credito = CreditoIA.actual()
    credito.saldo_usd = saldo.quantize(Decimal("0.01"))
    credito.anotado = timezone.now()
    credito.sin_credito = False
    credito.save()
    messages.success(request, f"Listo: anotamos USD {credito.saldo_usd} de crédito para la IA.")
    return redirect(reverse("gestion:inicio") + "#credito-ia")


@solo_duena
def ia_diagnostico(request):
    """Para Operon: si la IA está configurada y qué modelos de imagen ve la clave."""
    if not ia.configurada():
        return JsonResponse({"configurada": False})
    try:
        modelos = ia.modelos_disponibles()
    except Exception as exc:  # noqa: BLE001
        return JsonResponse({"configurada": True, "error": exc.__class__.__name__}, status=502)
    return JsonResponse(
        {
            "configurada": True,
            "modelo": settings.GEMINI_MODELO,
            "respaldo": settings.GEMINI_MODELO_RESPALDO,
            "modelos_de_imagen": modelos,
        }
    )


# --- Pedidos -----------------------------------------------------------------
@solo_duena
def pedidos(request):
    qs = Pedido.objects.prefetch_related("items__producto__imagenes", "items__talle")
    ver = request.GET.get("ver") or ""
    if ver == "sin-entregar":
        qs = qs.filter(estado=Pedido.Estado.PAGADO, entregado=False)
    elif ver == "transferencia":
        qs = qs.filter(estado=Pedido.Estado.PENDIENTE, metodo_pago=Pedido.Metodo.TRANSFERENCIA)
    elif ver == "envios":
        qs = qs.filter(estado=Pedido.Estado.PAGADO, entrega=Pedido.Entrega.ENVIO, entregado=False)
    elif ver in Pedido.Estado.values:
        qs = qs.filter(estado=ver)

    return render(
        request,
        "gestion/pedidos.html",
        {
            "seccion": "pedidos",
            "pedidos": qs[:100],
            "ver": ver,
            "estados": Pedido.Estado.choices,
        },
    )


@solo_duena
@require_POST
def pedido_actualizar(request, pk):
    """
    La dueña es usuaria autenticada: puede marcar a mano un pago que entró por
    WhatsApp o en el local. Lo que nunca cambia el estado es la URL de vuelta de
    Mercado Pago (ver pedidos/views.py).
    """
    pedido = get_object_or_404(Pedido, pk=pk)
    estado = request.POST.get("estado")
    if estado in Pedido.Estado.values and estado != pedido.estado:
        # Por el modelo, no a mano: pagado descuenta stock, cancelado lo devuelve.
        pedido.cambiar_estado(estado)
    campos = ["actualizado"]
    if "entregado" in request.POST:
        pedido.entregado = request.POST["entregado"] == "1"
        campos.append("entregado")
    if "seguimiento" in request.POST:
        pedido.seguimiento = request.POST["seguimiento"].strip()[:60]
        campos.append("seguimiento")
    if len(campos) > 1:
        pedido.save(update_fields=campos)
    return JsonResponse(
        {
            "ok": True,
            "estado": pedido.estado,
            "estado_texto": pedido.descripcion_estado,
            "entregado": pedido.entregado,
            "seguimiento": pedido.seguimiento,
            "link_seguimiento": pedido.link_whatsapp_seguimiento if pedido.seguimiento else "",
        }
    )


@solo_duena
@require_POST
def pedido_borrar(request, pk):
    pedido = get_object_or_404(Pedido, pk=pk)
    numero = pedido.pk
    if pedido.eliminar():
        messages.success(request, f"Eliminamos el pedido #{numero} y el stock volvió a la tienda.")
    else:
        messages.success(request, f"Eliminamos el pedido #{numero}.")
    return redirect(reverse("gestion:pedidos") + (f"?ver={request.POST['ver']}" if request.POST.get("ver") else ""))


# --- Portada -------------------------------------------------------------------
@solo_duena
def portada(request):
    actual = Portada.actual()
    if request.method == "POST":
        form = PortadaForm(request.POST, instance=actual)
        if form.is_valid():
            form.save()
            messages.success(request, "Listo: la portada ya muestra los cambios.")
            return redirect("gestion:portada")
        messages.error(request, "Revisá los campos marcados.")
    else:
        form = PortadaForm(instance=actual)

    return render(
        request,
        "gestion/portada.html",
        {
            "seccion": "portada",
            "form": form,
            "portada": actual,
            "looks": Look.objects.filter(activo=True),
            "destacadas": Producto.objects.filter(activo=True, destacado=True).prefetch_related("imagenes"),
        },
    )


# --- Cobros y envíos -------------------------------------------------------------
@solo_duena
def cobros(request):
    """Medios de pago, datos de transferencia, zonas de envío y la conexión con MP."""
    actual = Cobros.actual()
    form = CobrosForm(instance=actual)
    zona_con_error = None

    if request.method == "POST":
        accion = request.POST.get("accion")
        if accion == "cobros":
            form = CobrosForm(request.POST, instance=actual)
            if form.is_valid():
                form.save()
                messages.success(request, "Listo: los medios de pago ya se ven así en la tienda.")
                return redirect("gestion:cobros")
            messages.error(request, "Revisá los campos marcados.")
        elif accion == "zona":
            zona = ZonaEnvio.objects.filter(pk=request.POST.get("zona")).first() or ZonaEnvio(
                orden=ZonaEnvio.objects.count() + 1
            )
            zona_form = ZonaForm(request.POST, instance=zona, prefix=f"z{zona.pk or 'nueva'}")
            if zona_form.is_valid():
                zona_form.save()
                messages.success(request, f"Zona «{zona.nombre}» guardada.")
                return redirect(f"{reverse('gestion:cobros')}#envios")
            zona_con_error = zona_form
            messages.error(request, "Revisá los datos de la zona.")
        elif accion == "zona-borrar":
            ZonaEnvio.objects.filter(pk=request.POST.get("zona")).delete()
            messages.success(request, "Zona borrada.")
            return redirect(f"{reverse('gestion:cobros')}#envios")

    zonas = []
    for z in ZonaEnvio.objects.all():
        if zona_con_error is not None and zona_con_error.instance.pk == z.pk:
            zonas.append(zona_con_error)
        else:
            zonas.append(ZonaForm(instance=z, prefix=f"z{z.pk}"))
    nueva = zona_con_error if zona_con_error is not None and not zona_con_error.instance.pk else ZonaForm(prefix="znueva")

    return render(
        request,
        "gestion/cobros.html",
        {
            "seccion": "cobros",
            "form": form,
            "zonas": zonas,
            "zona_nueva": nueva,
            "conexion": ConexionMP.actual(),
            "app_mp": mercadopago.app_configurada(),
            "mp_entorno": not ConexionMP.actual() and mercadopago.configurado(),
        },
    )


@solo_duena
def mp_conectar(request):
    """El botón "Conectar Mercado Pago": manda a la dueña a autorizar en MP."""
    if not mercadopago.app_configurada():
        messages.error(request, "Falta configurar la app de Mercado Pago (Client ID y Secret en Vercel).")
        return redirect("gestion:cobros")
    estado = secrets.token_urlsafe(24)
    request.session["mp_estado"] = estado
    return redirect(mercadopago.url_para_conectar(request, estado))


@solo_duena
def mp_callback(request):
    """Vuelta desde Mercado Pago con el código para pedir los tokens."""
    esperado = request.session.pop("mp_estado", None)
    if request.GET.get("error"):
        messages.error(request, "No se conectó Mercado Pago: la autorización se canceló.")
        return redirect("gestion:cobros")
    # `state` evita que alguien conecte SU cuenta a la tienda con un link armado.
    if not esperado or request.GET.get("state") != esperado or not request.GET.get("code"):
        messages.error(request, "El link de conexión venció. Tocá «Conectar Mercado Pago» de nuevo.")
        return redirect("gestion:cobros")
    try:
        conexion = mercadopago.conectar_con_codigo(request, request.GET["code"])
    except mercadopago.MercadoPagoError as exc:
        messages.error(request, str(exc))
        return redirect("gestion:cobros")
    quien = conexion.apodo or conexion.email or f"usuario {conexion.mp_user_id}"
    messages.success(request, f"¡Listo! Mercado Pago quedó conectado con la cuenta {quien}.")
    return redirect("gestion:cobros")


@solo_duena
@require_POST
def mp_desconectar(request):
    ConexionMP.objects.all().delete()
    messages.success(request, "Mercado Pago desconectado. La tienda deja de cobrar con tarjeta hasta que lo vuelvas a conectar.")
    return redirect("gestion:cobros")
