"""
Modelos del catálogo.

Nota sobre las fotos: CHAO no fotografía prendas sueltas sobre fondo blanco, publica
composiciones de percha dentro del local. Por eso el modelo central no es solo
`Producto` sino la dupla `Look` + `LookItem`: un Look es una de esas fotos, y cada
LookItem marca dónde está una prenda dentro de ella. De ahí sale el "comprá el look
completo" de la home.
"""

from decimal import Decimal

from django.db import models
from django.urls import reverse
from django.utils.text import slugify


class Categoria(models.Model):
    nombre = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=60, unique=True, blank=True)
    orden = models.PositiveSmallIntegerField(default=0, help_text="Menor número = aparece primero.")

    class Meta:
        ordering = ["orden", "nombre"]
        verbose_name = "categoría"
        verbose_name_plural = "categorías"

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nombre)
        super().save(*args, **kwargs)


class Talle(models.Model):
    nombre = models.CharField(max_length=10, unique=True, help_text="Por ejemplo: S, M, L, 38, 40.")
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    nombre = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, related_name="productos")
    descripcion = models.TextField(blank=True)
    precio = models.DecimalField(max_digits=10, decimal_places=2)

    # Mientras CHAO no pase su lista, los precios son de referencia y la web lo dice
    # en pantalla. Cuando manden la lista real, se destilda y desaparece el cartel.
    precio_a_confirmar = models.BooleanField(
        default=True,
        verbose_name="precio de referencia",
        help_text="Tildado = se muestra el aviso de que el precio es estimado y falta confirmarlo.",
    )

    activo = models.BooleanField(default=True)
    destacado = models.BooleanField(default=False, help_text="Aparece primero en el catálogo.")
    orden = models.PositiveSmallIntegerField(default=0)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nombre)[:140]
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("catalogo:producto", args=[self.slug])

    # -- Fotos ---------------------------------------------------------------
    # El grid del catálogo hace un cross-fade entre dos imágenes al pasar el mouse:
    # la prenda recortada y la foto de la percha completa. Si solo hay una, no hay
    # swap y la card se comporta como una card normal.
    @property
    def foto_principal(self):
        return self.imagenes.first()

    @property
    def foto_hover(self):
        imagenes = list(self.imagenes.all()[:2])
        return imagenes[1] if len(imagenes) > 1 else None

    # -- Stock ---------------------------------------------------------------
    @property
    def talles_disponibles(self):
        return self.variantes.filter(stock__gt=0).select_related("talle")

    @property
    def hay_stock(self):
        return any(v.stock > 0 for v in self.variantes.all())

    @property
    def tiene_talles(self):
        """Usa las variantes ya prefetcheadas en lugar de un .exists() que
        dispararía otra consulta por card."""
        return bool(self.variantes.all())

    @property
    def variante_unica(self):
        """La única variante, cuando el producto tiene una sola.

        Los bolsos y pañuelos llevan una variante 'Único' para poder contarles el
        stock igual que a la ropa. Pero de cara a la clienta eso no es una decisión:
        no hay nada que elegir."""
        variantes = list(self.variantes.all())
        return variantes[0] if len(variantes) == 1 else None

    @property
    def necesita_elegir_talle(self):
        """True solo cuando hay más de una opción. Con una sola variante se agrega
        directo y el talle se adjunta solo, así el stock se sigue descontando bien."""
        return len(list(self.variantes.all())) > 1

    @property
    def ultimas_unidades(self):
        """True cuando queda poco y conviene decirlo. Umbral bajo a propósito: un
        'últimas unidades' que aparece siempre deja de significar algo."""
        total = sum(v.stock for v in self.variantes.all())
        return 0 < total <= 3

    @property
    def precio_cuota_3(self):
        """3 cuotas sin interés. La vitrina del local dice 'cuotas sin intereses,
        ¡todos los días!', así que el beneficio es dato de ellos; la cantidad de
        cuotas es el mínimo habitual y va declarada como estimación en el template."""
        return (self.precio / Decimal(3)).quantize(Decimal("1"))


class ProductoImagen(models.Model):
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="imagenes")

    # Las fotos del seed viven en static/ y se referencian por ruta relativa.
    # `imagen` es para lo que la dueña suba después desde el admin.
    ruta_estatica = models.CharField(
        max_length=200,
        blank=True,
        help_text="Ruta dentro de static/, por ejemplo img/productos/sweater.jpg",
    )
    imagen = models.ImageField(upload_to="productos/", blank=True)
    alt = models.CharField(max_length=180, blank=True)
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["orden", "id"]
        verbose_name = "imagen"
        verbose_name_plural = "imágenes"

    def __str__(self):
        return f"{self.producto.nombre} ({self.orden})"

    @property
    def url(self):
        """Una sola propiedad para los templates, sin importar de dónde salga la foto."""
        if self.imagen:
            return self.imagen.url
        if self.ruta_estatica:
            from django.templatetags.static import static

            return static(self.ruta_estatica)
        return ""


class Variante(models.Model):
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="variantes")
    talle = models.ForeignKey(Talle, on_delete=models.PROTECT, related_name="variantes")
    stock = models.PositiveSmallIntegerField(default=0)

    class Meta:
        # Un producto no puede tener dos filas del mismo talle: si no, el stock
        # queda partido en dos lugares y ninguno es la verdad.
        constraints = [
            models.UniqueConstraint(fields=["producto", "talle"], name="variante_unica_por_talle"),
        ]
        ordering = ["talle__orden", "talle__nombre"]

    def __str__(self):
        return f"{self.producto.nombre} · {self.talle}"


class Look(models.Model):
    """Una de las fotos de percha que CHAO publica en Instagram."""

    nombre = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    bajada = models.CharField(max_length=220, blank=True, help_text="Una línea, tono CHAO.")
    ruta_estatica = models.CharField(max_length=200, blank=True)
    imagen = models.ImageField(upload_to="looks/", blank=True)
    alt = models.CharField(max_length=180, blank=True)
    orden = models.PositiveSmallIntegerField(default=0)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["orden", "nombre"]

    def __str__(self):
        return self.nombre

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.nombre)[:140]
        super().save(*args, **kwargs)

    @property
    def url(self):
        if self.imagen:
            return self.imagen.url
        if self.ruta_estatica:
            from django.templatetags.static import static

            return static(self.ruta_estatica)
        return ""

    @property
    def total(self):
        return sum(item.producto.precio for item in self.items.select_related("producto"))


class LookItem(models.Model):
    """Una prenda marcada dentro de un look, con su posición para el hotspot."""

    look = models.ForeignKey(Look, on_delete=models.CASCADE, related_name="items")
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name="en_looks")

    # Porcentajes sobre la foto, no píxeles: así el marcador queda pegado a la prenda
    # en cualquier tamaño de pantalla sin recalcular nada en JS.
    x = models.DecimalField(max_digits=5, decimal_places=2, help_text="Posición horizontal en % (0-100).")
    y = models.DecimalField(max_digits=5, decimal_places=2, help_text="Posición vertical en % (0-100).")
    orden = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["orden", "id"]
        constraints = [
            models.UniqueConstraint(fields=["look", "producto"], name="producto_una_vez_por_look"),
        ]
        verbose_name = "prenda del look"
        verbose_name_plural = "prendas del look"

    def __str__(self):
        return f"{self.look.nombre} → {self.producto.nombre}"
