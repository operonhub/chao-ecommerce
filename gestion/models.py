"""
Cuenta propia del crédito de la IA.

Google no deja consultar por API el saldo prepago de Gemini (solo se ve en AI
Studio → Billing). Así que la tienda lleva su propia cuenta: alguien anota el
saldo que figura en AI Studio y cada foto o descripción que sale bien resta su
costo estimado. Es una estimación: el número exacto siempre es el de AI Studio.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum


class UsoIA(models.Model):
    class Tipo(models.TextChoices):
        FOTO = "foto", "Foto"
        DESCRIPCION = "descripcion", "Descripción"

    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    modelo = models.CharField(max_length=60, blank=True)
    costo_usd = models.DecimalField(max_digits=8, decimal_places=4)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado"]
        verbose_name = "uso de la IA"
        verbose_name_plural = "usos de la IA"

    @classmethod
    def anotar(cls, tipo: str, modelo: str = "") -> "UsoIA":
        costo = settings.GEMINI_COSTO_FOTO if tipo == cls.Tipo.FOTO else settings.GEMINI_COSTO_DESCRIPCION
        return cls.objects.create(tipo=tipo, modelo=modelo[:60], costo_usd=Decimal(str(costo)))


class CreditoIA(models.Model):
    """El último saldo anotado. Una sola fila."""

    saldo_usd = models.DecimalField("Saldo en AI Studio (USD)", max_digits=8, decimal_places=2, null=True, blank=True)
    anotado = models.DateTimeField(null=True, blank=True)
    # Lo marca la IA cuando Google responde "sin saldo" (402); se borra al anotar uno nuevo.
    sin_credito = models.BooleanField(default=False)

    class Meta:
        verbose_name = verbose_name_plural = "crédito de la IA"

    def __str__(self):
        return "Crédito de la IA"

    @classmethod
    def actual(cls) -> "CreditoIA":
        credito, _ = cls.objects.get_or_create(pk=1)
        return credito

    @property
    def con_dato(self) -> bool:
        return self.saldo_usd is not None

    @property
    def gastado_usd(self) -> Decimal:
        if not self.anotado:
            return Decimal(0)
        return UsoIA.objects.filter(creado__gte=self.anotado).aggregate(t=Sum("costo_usd"))["t"] or Decimal(0)

    @property
    def restante_usd(self) -> Decimal:
        if self.sin_credito or self.saldo_usd is None:
            return Decimal(0)
        return max(self.saldo_usd - self.gastado_usd, Decimal(0))

    @property
    def fotos_restantes(self) -> int:
        return int(self.restante_usd / Decimal(str(settings.GEMINI_COSTO_FOTO)))

    @property
    def porcentaje(self) -> int:
        if not self.saldo_usd:
            return 0
        return max(0, min(100, round(self.restante_usd / self.saldo_usd * 100)))

    @property
    def estado(self) -> str:
        """agotado · bajo · ok · sin-dato (para el color en el panel)."""
        if self.sin_credito:
            return "agotado"
        if not self.con_dato:
            return "sin-dato"
        if self.fotos_restantes <= 10:
            return "bajo"
        return "ok"
