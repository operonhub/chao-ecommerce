"""
Pedidos y su estado de pago.

Los precios se copian dentro de PedidoItem en el momento de la compra. Si la dueña
después cambia el precio de un sweater desde el admin, los pedidos viejos siguen
mostrando lo que la clienta realmente pagó.
"""

import re
from urllib.parse import quote

from django.db import models

from catalogo.models import Producto, Talle


class Pedido(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente de pago"
        PAGADO = "pagado", "Pagado"
        RECHAZADO = "rechazado", "Pago rechazado"
        CANCELADO = "cancelado", "Cancelado"

    nombre = models.CharField(max_length=120)
    telefono = models.CharField(max_length=40)
    email = models.EmailField(blank=True)
    notas = models.TextField(blank=True, help_text="Comentario que dejó la clienta.")

    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE)

    # Independiente del pago: un pedido pagado puede no haberse retirado todavía,
    # y uno coordinado por WhatsApp se cobra en el local al entregarlo.
    entregado = models.BooleanField(default=False)

    # Rastro de Mercado Pago. `mp_payment_id` lo completa el webhook, no el navegador.
    mp_preference_id = models.CharField(max_length=80, blank=True)
    mp_payment_id = models.CharField(max_length=80, blank=True)

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado"]

    def __str__(self):
        return f"Pedido #{self.pk} · {self.nombre} · {self.get_estado_display()}"

    def recalcular_total(self, guardar=True):
        self.total = sum((i.subtotal for i in self.items.all()), start=0)
        if guardar:
            self.save(update_fields=["total", "actualizado"])
        return self.total

    @property
    def whatsapp_cliente(self) -> str:
        """El teléfono de la clienta en formato wa.me (549 + área + número)."""
        digitos = re.sub(r"\D", "", self.telefono or "")
        if digitos.startswith("54"):
            return digitos
        if digitos.startswith("0"):
            digitos = digitos[1:]
        # "11 15 5555-5555": el 15 de celular sobra en el formato internacional.
        if len(digitos) == 12 and digitos.startswith("1115"):
            digitos = "11" + digitos[4:]
        return "549" + digitos if len(digitos) == 10 else digitos

    @property
    def link_whatsapp_cliente(self) -> str:
        texto = f"¡Hola {self.nombre}! Te escribimos de CHAO Indumentaria por tu pedido #{self.pk}."
        return f"https://wa.me/{self.whatsapp_cliente}?text={quote(texto)}"

    @property
    def resumen_whatsapp(self) -> str:
        """Texto plano del pedido, para que la dueña lo lea de un vistazo en el chat."""
        lineas = [f"Pedido #{self.pk} — {self.nombre}"]
        for item in self.items.select_related("producto", "talle"):
            talle = f" (T: {item.talle})" if item.talle else ""
            lineas.append(f"{item.cantidad}x {item.producto.nombre}{talle}")
        lineas.append(f"Total: ${self.total:,.0f}".replace(",", "."))
        return "\n".join(lineas)


class PedidoItem(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="items_pedido")
    talle = models.ForeignKey(Talle, on_delete=models.PROTECT, null=True, blank=True)
    cantidad = models.PositiveSmallIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "prenda del pedido"
        verbose_name_plural = "prendas del pedido"

    def __str__(self):
        return f"{self.cantidad}x {self.producto.nombre}"

    @property
    def subtotal(self):
        return self.precio_unitario * self.cantidad
