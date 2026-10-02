"""
Panel de la dueña ("Mi tienda").

Aparte del admin de Django (/panel/, que queda como herramienta avanzada para los
looks y sus puntos): este es el que se usa todos los días, desde el celular, para
cargar prendas, cambiar precios, marcar tendencias y seguir los pedidos.

Escribe sobre los mismos modelos que lee la tienda, así que lo que se guarda acá
se ve en la web al instante. Solo entra personal (is_staff).
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, F, Max, Q, Sum
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from PIL import Image, ImageOps

from catalogo.models import Categoria, Look, Portada, Producto, ProductoImagen, Talle, Variante
from pedidos.models import Pedido

from .forms import PortadaForm, ProductoForm


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
        "n_a_confirmar": sum(1 for p in activas if p.precio_a_confirmar),
        "n_destacadas": sum(1 for p in activas if p.destacado),
        "n_pendientes": Pedido.objects.filter(estado=Pedido.Estado.PENDIENTE).count(),
        "n_sin_entregar": Pedido.objects.filter(estado=Pedido.Estado.PAGADO, entregado=False).count(),
        "vendido_30": pagados_mes.aggregate(t=Sum("total"))["t"] or 0,
        "n_vendidos_30": pagados_mes.count(),
        "recientes": Pedido.objects.prefetch_related("items__producto", "items__talle")[:5],
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
        qs = qs.filter(Q(nombre__icontains=q) | Q(descripcion__icontains=q) | Q(etiqueta__icontains=q))

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
        "a-confirmar": Q(precio_a_confirmar=True),
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


def _guardar_talles(post, prenda, talles):
    """
    Una fila por talle existente. Vacío = la prenda no viene en ese talle;
    0 = viene, pero no hay stock ahora. La diferencia importa en la tienda: el
    talle agotado aparece tachado, el que no existe no aparece.
    """
    for talle in talles:
        crudo = (post.get(f"stock_{talle.pk}") or "").strip()
        if crudo == "":
            Variante.objects.filter(producto=prenda, talle=talle).delete()
            continue
        try:
            stock = max(0, int(crudo))
        except ValueError:
            continue
        Variante.objects.update_or_create(producto=prenda, talle=talle, defaults={"stock": stock})

    nuevo = (post.get("talle_nuevo") or "").strip()[:10]
    if nuevo:
        talle, _ = Talle.objects.get_or_create(nombre=nuevo, defaults={"orden": 50})
        try:
            stock = max(0, int(post.get("talle_nuevo_stock") or 0))
        except ValueError:
            stock = 0
        Variante.objects.update_or_create(producto=prenda, talle=talle, defaults={"stock": stock})


@solo_duena
def prenda_editar(request, pk=None):
    prenda = get_object_or_404(Producto, pk=pk) if pk else None
    talles = list(Talle.objects.all())

    if request.method == "POST":
        form = ProductoForm(request.POST, instance=prenda)
        if form.is_valid():
            with transaction.atomic():
                prenda = form.save()
                _guardar_talles(request.POST, prenda, talles)
                errores = _guardar_fotos(request.FILES.getlist("fotos"), prenda)
            for error in errores:
                messages.warning(request, error)
            messages.success(request, f"Guardamos «{prenda.nombre}».")
            if request.POST.get("despues") == "otra":
                return redirect("gestion:prenda_nueva")
            return redirect("gestion:prenda_editar", pk=prenda.pk)
        messages.error(request, "Revisá los campos marcados.")
    else:
        form = ProductoForm(instance=prenda)

    stock_por_talle = {v.talle_id: v.stock for v in prenda.variantes.all()} if prenda else {}
    filas_talle = [{"talle": t, "stock": stock_por_talle.get(t.pk, "")} for t in talles]

    return render(
        request,
        "gestion/prenda_form.html",
        {
            "seccion": "prendas",
            "form": form,
            "prenda": prenda,
            "fotos": prenda.imagenes.all() if prenda else [],
            "filas_talle": filas_talle,
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
CAMPOS_TOGGLE = {"activo", "destacado", "precio_a_confirmar"}


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
    # Si la dueña escribe el precio a mano, ya no es una estimación.
    prenda.precio_a_confirmar = False
    prenda.save(update_fields=["precio", "precio_a_confirmar"])
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


# --- Pedidos -----------------------------------------------------------------
@solo_duena
def pedidos(request):
    qs = Pedido.objects.prefetch_related("items__producto__imagenes", "items__talle")
    ver = request.GET.get("ver") or ""
    if ver == "sin-entregar":
        qs = qs.filter(estado=Pedido.Estado.PAGADO, entregado=False)
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
    campos = ["actualizado"]
    estado = request.POST.get("estado")
    if estado in Pedido.Estado.values:
        pedido.estado = estado
        campos.append("estado")
    if "entregado" in request.POST:
        pedido.entregado = request.POST["entregado"] == "1"
        campos.append("entregado")
    pedido.save(update_fields=campos)
    return JsonResponse({"ok": True, "estado": pedido.estado, "entregado": pedido.entregado})


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
