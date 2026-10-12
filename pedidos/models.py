"""
Pedidos, entrega y cobro.

Los precios se copian dentro de PedidoItem en el momento de la compra. Si la dueña
después cambia el precio de un sweater desde el admin, los pedidos viejos siguen
mostrando lo que la clienta realmente pagó. Lo mismo con el envío: el nombre de la
zona y su costo se copian al pedido.

También viven acá la configuración de cobros (qué medios acepta la tienda, datos
de transferencia), las zonas de envío y la conexión con la cuenta de Mercado Pago
de la dueña — las tres se editan desde /gestion/cobros/.
"""

import re
import secrets
from datetime import timedelta
from decimal import Decimal
from urllib.parse import quote

from django.db import models, transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone

from catalogo.models import Producto, Talle


class Pedido(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "pendiente", "Pendiente de pago"
        PAGADO = "pagado", "Pagado"
        RECHAZADO = "rechazado", "Pago rechazado"
        CANCELADO = "cancelado", "Cancelado"

    class Entrega(models.TextChoices):
        RETIRO = "retiro", "Retiro en el local"
        ENVIO = "envio", "Envío"

    class Metodo(models.TextChoices):
        MERCADOPAGO = "mercadopago", "Tarjeta / Mercado Pago"
        TRANSFERENCIA = "transferencia", "Transferencia"
        EFECTIVO = "efectivo", "Efectivo al retirar"

    # Lo que va en las URLs públicas del pedido (/checkout/pedido/<codigo>/): al
    # azar, para que nadie pueda ver pedidos ajenos cambiando un número.
    codigo = models.CharField(max_length=16, unique=True, null=True, blank=True, editable=False)

    nombre = models.CharField(max_length=120)
    telefono = models.CharField(max_length=40)
    email = models.EmailField(blank=True)
    dni = models.CharField(max_length=12, blank=True)
    notas = models.TextField(blank=True, help_text="Comentario que dejó la clienta.")

    # --- Entrega ---------------------------------------------------------------
    entrega = models.CharField(max_length=10, choices=Entrega.choices, default=Entrega.RETIRO)
    zona = models.ForeignKey("ZonaEnvio", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    zona_nombre = models.CharField(max_length=80, blank=True)
    zona_demora = models.CharField(max_length=80, blank=True)
    # None = "a coordinar": la zona no tiene precio fijo y se arregla por WhatsApp.
    costo_envio = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    calle = models.CharField(max_length=120, blank=True)
    numero = models.CharField(max_length=12, blank=True)
    piso_depto = models.CharField(max_length=30, blank=True)
    entre_calles = models.CharField(max_length=120, blank=True)
    codigo_postal = models.CharField(max_length=10, blank=True)
    localidad = models.CharField(max_length=80, blank=True)
    provincia = models.CharField(max_length=40, blank=True)
    indicaciones = models.CharField(max_length=200, blank=True)
    seguimiento = models.CharField(
        max_length=60, blank=True, help_text="Número de seguimiento del correo, si se despachó."
    )

    # --- Cobro -----------------------------------------------------------------
    metodo_pago = models.CharField(max_length=15, choices=Metodo.choices, default=Metodo.MERCADOPAGO)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    descuento = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Lo que se cobra: subtotal − descuento + envío (si tiene precio fijo).
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    estado = models.CharField(max_length=20, choices=Estado.choices, default=Estado.PENDIENTE)
    stock_descontado = models.BooleanField(default=False, editable=False)

    # Independiente del pago: un pedido pagado puede no haberse retirado todavía,
    # y uno coordinado por WhatsApp se cobra en el local al entregarlo.
    entregado = models.BooleanField(default=False)

    # Rastro de Mercado Pago. `mp_payment_id` lo completa el webhook, no el navegador.
    mp_preference_id = models.CharField(max_length=80, blank=True)
    mp_payment_id = models.CharField(max_length=80, blank=True)
    mp_status_detail = models.CharField(max_length=80, blank=True)

    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-creado"]

    def __str__(self):
        return f"Pedido #{self.pk} · {self.nombre} · {self.get_estado_display()}"

    def save(self, *args, **kwargs):
        if not self.codigo:
            self.codigo = secrets.token_urlsafe(9)[:12]
        super().save(*args, **kwargs)

    def recalcular_total(self, guardar=True, descuento_pct=0):
        self.subtotal = sum((i.subtotal for i in self.items.all()), start=Decimal(0))
        self.descuento = (self.subtotal * Decimal(descuento_pct) / 100).quantize(Decimal("1"))
        self.total = self.subtotal - self.descuento + (self.costo_envio or 0)
        if guardar:
            self.save(update_fields=["subtotal", "descuento", "total", "actualizado"])
        return self.total

    # --- Entrega y estado, para mostrar --------------------------------------------
    @property
    def envio_a_coordinar(self) -> bool:
        return self.entrega == self.Entrega.ENVIO and self.costo_envio is None

    @property
    def direccion_completa(self) -> str:
        if self.entrega != self.Entrega.ENVIO:
            return ""
        linea = f"{self.calle} {self.numero}".strip()
        if self.piso_depto:
            linea += f", {self.piso_depto}"
        lugar = self.localidad + (f" ({self.codigo_postal})" if self.codigo_postal else "")
        return " · ".join(p for p in (linea, lugar, self.provincia) if p)

    @property
    def descripcion_estado(self) -> str:
        """Lo que ve la dueña en el panel, según el medio de pago."""
        if self.estado == self.Estado.PENDIENTE:
            if self.metodo_pago == self.Metodo.TRANSFERENCIA:
                return "Esperando transferencia"
            if self.metodo_pago == self.Metodo.EFECTIVO:
                return "Paga al retirar"
        return self.get_estado_display()

    # --- Cambios de estado (con stock) -------------------------------------------
    def marcar_pagado(self, payment_id: str = "", status_detail: str = "") -> None:
        """Pasa el pedido a pagado y descuenta el stock — una sola vez, aunque el
        webhook de Mercado Pago llegue repetido."""
        with transaction.atomic():
            pedido = Pedido.objects.select_for_update().get(pk=self.pk)
            pedido.estado = self.Estado.PAGADO
            if payment_id:
                pedido.mp_payment_id = payment_id
            if status_detail:
                pedido.mp_status_detail = status_detail
            if not pedido.stock_descontado:
                pedido._mover_stock(-1)
                pedido.stock_descontado = True
            pedido.save()
        self.refresh_from_db()

    def cambiar_estado(self, nuevo: str) -> None:
        """Desde el panel. Si un pedido pagado se cancela, el stock vuelve."""
        if nuevo == self.Estado.PAGADO:
            self.marcar_pagado()
            return
        with transaction.atomic():
            pedido = Pedido.objects.select_for_update().get(pk=self.pk)
            if nuevo == self.Estado.CANCELADO and pedido.stock_descontado:
                pedido._mover_stock(+1)
                pedido.stock_descontado = False
            pedido.estado = nuevo
            pedido.save()
        self.refresh_from_db()

    def _mover_stock(self, signo: int) -> None:
        from catalogo.models import Variante

        for item in self.items.all():
            if not item.talle_id:
                continue
            variante = Variante.objects.filter(
                producto_id=item.producto_id, talle_id=item.talle_id, color_id=item.color_id
            )
            if signo < 0:
                # Nunca por debajo de cero, aunque se haya vendido algo en el local.
                variante.update(stock=Greatest(F("stock") - item.cantidad, 0))
            else:
                variante.update(stock=F("stock") + item.cantidad)

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
            color = f" · {item.color_nombre}" if item.color_nombre else ""
            talle = f" (T: {item.talle})" if item.talle else ""
            lineas.append(f"{item.cantidad}x {item.producto.nombre}{color}{talle}")
        lineas.append(f"Total: ${self.total:,.0f}".replace(",", "."))
        if self.entrega == self.Entrega.ENVIO:
            lineas.append(f"Envío: {self.zona_nombre} — {self.direccion_completa}")
        else:
            lineas.append("Retiro en el local")
        lineas.append(f"Pago: {self.get_metodo_pago_display()}")
        return "\n".join(lineas)

    @property
    def texto_comprobante(self) -> str:
        monto = f"${self.total:,.0f}".replace(",", ".")
        return f"¡Hola CHAO! Te mando el comprobante de la transferencia del pedido #{self.pk} ({monto})."

    @property
    def texto_problema_pago(self) -> str:
        return f"¡Hola CHAO! Tengo un problema para pagar el pedido #{self.pk}."

    @property
    def texto_seguimiento(self) -> str:
        """El mensaje que manda la dueña cuando despacha por correo."""
        return (
            f"¡Hola {self.nombre.split()[0] if self.nombre else ''}! Tu pedido #{self.pk} de CHAO ya salió por "
            f"Correo Argentino. Número de seguimiento: {self.seguimiento}. Lo podés seguir en "
            "la web de Correo Argentino (correoargentino.com.ar)."
        )

    @property
    def link_whatsapp_seguimiento(self) -> str:
        return f"https://wa.me/{self.whatsapp_cliente}?text={quote(self.texto_seguimiento)}"


class PedidoItem(models.Model):
    pedido = models.ForeignKey(Pedido, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name="items_pedido")
    talle = models.ForeignKey(Talle, on_delete=models.PROTECT, null=True, blank=True)
    color = models.ForeignKey(
        "catalogo.ColorPrenda", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # El nombre se copia: si la dueña después borra o renombra el color, el
    # pedido sigue diciendo lo que la clienta compró.
    color_nombre = models.CharField(max_length=40, blank=True)
    cantidad = models.PositiveSmallIntegerField(default=1)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        verbose_name = "prenda del pedido"
        verbose_name_plural = "prendas del pedido"

    def __str__(self):
        color = f" · {self.color_nombre}" if self.color_nombre else ""
        return f"{self.cantidad}x {self.producto.nombre}{color}"

    @property
    def subtotal(self):
        return self.precio_unitario * self.cantidad


class ZonaEnvio(models.Model):
    """
    Una opción de envío del checkout. La dueña las arma desde el panel: por
    ejemplo "Villa Bosch y alrededores" (la lleva ella) o "Resto del país"
    (Correo Argentino). Sin precio = "a coordinar" por WhatsApp.
    """

    class Tipo(models.TextChoices):
        PROPIA = "propia", "La entrega CHAO"
        CORREO = "correo", "Correo Argentino"

    nombre = models.CharField(max_length=80)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.CORREO)
    descripcion = models.CharField(
        max_length=140, blank=True, help_text="Qué localidades cubre, en una línea."
    )
    precio = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Vacío = el costo se coordina por WhatsApp.",
    )
    gratis_desde = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        help_text="Compras desde este monto no pagan envío. Vacío = nunca gratis.",
    )
    demora = models.CharField(max_length=80, default="3 a 5 días hábiles")
    activa = models.BooleanField(default=True)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["orden", "id"]
        verbose_name = "zona de envío"
        verbose_name_plural = "zonas de envío"

    def __str__(self):
        return self.nombre

    def costo_para(self, subtotal):
        """Lo que paga la clienta por esta zona (None = a coordinar)."""
        if self.gratis_desde is not None and subtotal >= self.gratis_desde:
            return Decimal(0)
        return self.precio


class Cobros(models.Model):
    """Qué medios de pago acepta la tienda y los datos para transferir. Una sola fila."""

    acepta_mercadopago = models.BooleanField("Tarjeta / Mercado Pago", default=True)
    acepta_transferencia = models.BooleanField("Transferencia", default=True)
    acepta_efectivo = models.BooleanField("Efectivo al retirar", default=True)
    descuento_transferencia = models.PositiveSmallIntegerField(
        "Descuento por transferencia (%)", default=0,
        help_text="0 = sin descuento. Se aplica a las prendas, no al envío.",
    )
    alias = models.CharField(max_length=60, blank=True)
    cbu = models.CharField("CBU / CVU", max_length=30, blank=True)
    titular = models.CharField(max_length=100, blank=True)
    banco = models.CharField(max_length=60, blank=True)

    class Meta:
        verbose_name = verbose_name_plural = "cobros"

    def __str__(self):
        return "Cobros"

    @classmethod
    def actual(cls):
        cobros, _ = cls.objects.get_or_create(pk=1)
        return cobros

    @property
    def transferencia_lista(self) -> bool:
        """Solo se ofrece si además de estar prendida tiene a dónde transferir."""
        return self.acepta_transferencia and bool(self.alias or self.cbu)


class ConexionMP(models.Model):
    """
    La cuenta de Mercado Pago de la dueña, conectada con el botón del panel (OAuth).

    Los tokens permiten cobrar en su nombre: viven solo en la base (Postgres, con
    acceso restringido) y nunca se muestran en pantalla. Una sola fila.
    """

    mp_user_id = models.CharField(max_length=30)
    apodo = models.CharField(max_length=120, blank=True)
    email = models.CharField(max_length=160, blank=True)
    access_token = models.CharField(max_length=300)
    refresh_token = models.CharField(max_length=300, blank=True)
    public_key = models.CharField(max_length=120)
    vence = models.DateTimeField()
    modo_prueba = models.BooleanField(default=False)
    conectada = models.DateTimeField(auto_now_add=True)
    renovada = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = verbose_name_plural = "conexión con Mercado Pago"

    def __str__(self):
        return f"Mercado Pago · {self.apodo or self.mp_user_id}"

    @classmethod
    def actual(cls):
        return cls.objects.order_by("-renovada").first()

    @property
    def por_vencer(self) -> bool:
        return self.vence - timezone.now() < timedelta(days=15)
