"""
Admin del catálogo — este es el "panel" que usa la dueña de CHAO.

Se apoya en el admin de Django en lugar de construir un panel a mano: sale gratis,
tiene permisos y auditoría, y es lo que le permite cargar prendas sin llamar a nadie.
Todo lo visible está en castellano y con los campos ordenados por lo que se toca
seguido (precio y stock) contra lo que se toca una vez (slug, orden).
"""

from django.contrib import admin
from django.utils.html import format_html

from .models import Categoria, Look, LookItem, Producto, ProductoImagen, Talle, Variante

admin.site.site_header = "CHAO Indumentaria"
admin.site.site_title = "CHAO"
admin.site.index_title = "Panel de la tienda"


def _miniatura(url, alto=60):
    if not url:
        return format_html('<span style="color:#999">sin foto</span>')
    return format_html(
        '<img src="{}" style="height:{}px;width:auto;border-radius:4px;object-fit:cover" />', url, alto
    )


class ProductoImagenInline(admin.TabularInline):
    model = ProductoImagen
    extra = 1
    fields = ("vista", "imagen", "ruta_estatica", "alt", "orden")
    readonly_fields = ("vista",)

    @admin.display(description="Vista")
    def vista(self, obj):
        return _miniatura(obj.url if obj.pk else "")


class VarianteInline(admin.TabularInline):
    model = Variante
    extra = 1
    fields = ("talle", "stock")


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = (
        "vista",
        "nombre",
        "categoria",
        "precio",
        "precio_a_confirmar",
        "stock_total",
        "activo",
        "destacado",
    )
    list_display_links = ("vista", "nombre")
    # El día a día es cambiar precios y prender/apagar prendas: se edita en la lista,
    # sin entrar a cada ficha.
    list_editable = ("precio", "activo", "destacado")
    list_filter = ("categoria", "activo", "destacado", "precio_a_confirmar")
    search_fields = ("nombre", "descripcion")
    prepopulated_fields = {"slug": ("nombre",)}
    inlines = [ProductoImagenInline, VarianteInline]
    fieldsets = (
        (None, {"fields": ("nombre", "categoria", "descripcion")}),
        ("Precio", {"fields": ("precio", "precio_a_confirmar")}),
        ("Visibilidad", {"fields": ("activo", "destacado", "orden", "slug")}),
    )

    @admin.display(description="")
    def vista(self, obj):
        foto = obj.foto_principal
        return _miniatura(foto.url if foto else "")

    @admin.display(description="Stock")
    def stock_total(self, obj):
        total = sum(v.stock for v in obj.variantes.all())
        color = "#b00" if total == 0 else ("#b57500" if total <= 3 else "#2F6B70")
        return format_html('<b style="color:{}">{}</b>', color, total)

    def get_queryset(self, request):
        # Sin esto, la columna de stock dispara una consulta por fila.
        return super().get_queryset(request).select_related("categoria").prefetch_related("variantes", "imagenes")


class LookItemInline(admin.TabularInline):
    model = LookItem
    extra = 1
    fields = ("producto", "x", "y", "orden")
    autocomplete_fields = ("producto",)
    verbose_name = "prenda marcada"
    verbose_name_plural = "prendas marcadas en la foto (x e y en % de la imagen)"


@admin.register(Look)
class LookAdmin(admin.ModelAdmin):
    list_display = ("vista", "nombre", "cantidad_prendas", "activo", "orden")
    list_display_links = ("vista", "nombre")
    list_editable = ("activo", "orden")
    prepopulated_fields = {"slug": ("nombre",)}
    inlines = [LookItemInline]

    @admin.display(description="")
    def vista(self, obj):
        return _miniatura(obj.url, alto=80)

    @admin.display(description="Prendas")
    def cantidad_prendas(self, obj):
        return obj.items.count()


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "orden", "cantidad")
    list_editable = ("orden",)
    prepopulated_fields = {"slug": ("nombre",)}

    @admin.display(description="Prendas")
    def cantidad(self, obj):
        return obj.productos.count()


@admin.register(Talle)
class TalleAdmin(admin.ModelAdmin):
    list_display = ("nombre", "orden")
    list_editable = ("orden",)
