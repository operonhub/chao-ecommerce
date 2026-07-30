"""Admin de pedidos: pensado para leer, no para editar a mano."""

from django.contrib import admin
from django.utils.html import format_html

from .models import Pedido, PedidoItem


class PedidoItemInline(admin.TabularInline):
    model = PedidoItem
    extra = 0
    fields = ("producto", "talle", "cantidad", "precio_unitario")
    # Un pedido ya cerrado no se toca: si hay que corregir algo, se crea otro.
    readonly_fields = ("producto", "talle", "cantidad", "precio_unitario")
    can_delete = False


@admin.register(Pedido)
class PedidoAdmin(admin.ModelAdmin):
    list_display = ("id", "creado", "nombre", "telefono", "total_formateado", "estado_color")
    list_filter = ("estado", "creado")
    search_fields = ("nombre", "telefono", "email", "mp_payment_id")
    date_hierarchy = "creado"
    inlines = [PedidoItemInline]
    readonly_fields = ("creado", "actualizado", "mp_preference_id", "mp_payment_id", "total", "resumen")

    fieldsets = (
        ("Clienta", {"fields": ("nombre", "telefono", "email", "notas")}),
        ("Pedido", {"fields": ("total", "estado", "resumen")}),
        ("Mercado Pago", {"fields": ("mp_preference_id", "mp_payment_id"), "classes": ("collapse",)}),
        ("Fechas", {"fields": ("creado", "actualizado"), "classes": ("collapse",)}),
    )

    @admin.display(description="Total", ordering="total")
    def total_formateado(self, obj):
        return f"${obj.total:,.0f}".replace(",", ".")

    @admin.display(description="Estado", ordering="estado")
    def estado_color(self, obj):
        colores = {
            Pedido.Estado.PAGADO: "#2F6B70",
            Pedido.Estado.PENDIENTE: "#b57500",
            Pedido.Estado.RECHAZADO: "#b00",
            Pedido.Estado.CANCELADO: "#777",
        }
        return format_html(
            '<b style="color:{}">{}</b>', colores.get(obj.estado, "#333"), obj.get_estado_display()
        )

    @admin.display(description="Para copiar y pegar")
    def resumen(self, obj):
        return format_html("<pre style='margin:0'>{}</pre>", obj.resumen_whatsapp)
