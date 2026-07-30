"""
Carga el catálogo de la demo.

Idempotente: se puede correr muchas veces sin duplicar nada, así que sirve tanto para
levantar el proyecto de cero como para reflejar un cambio en los datos.

Sobre los precios: CHAO no publica precios en ningún posteo ("consultanos por precios
y disponibilidad" es literalmente su copy). Los de acá son estimaciones de mercado y
quedan marcados con `precio_a_confirmar=True`, que es lo que hace aparecer el aviso en
pantalla. Cuando manden la lista real, se cambian los números y se destilda el campo.

Las posiciones de los hotspots NO están escritas acá: salen de tools/hotspots.json,
que genera el mismo script que recorta las fotos. Así el marcador sobre la foto y el
recorte del producto no pueden desincronizarse.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from catalogo.models import Categoria, Look, LookItem, Producto, ProductoImagen, Talle, Variante

CATEGORIAS = [
    ("Sweaters y tejidos", 1),
    ("Remeras y tops", 2),
    ("Jeans y pantalones", 3),
    ("Bolsos", 4),
    ("Accesorios", 5),
]

TALLES_ROPA = [("S", 1), ("M", 2), ("L", 3)]
TALLES_PANTALON = [("36", 10), ("38", 11), ("40", 12), ("42", 13)]
TALLE_UNICO = [("Único", 20)]

# slug, nombre, categoría, precio, descripción, talles con stock
PRODUCTOS = [
    (
        "sweater-tejido-crudo",
        "Sweater tejido crudo",
        "Sweaters y tejidos",
        58000,
        "Tejido grueso, suave y abrigado. El que se pone con todo y nunca queda mal.",
        [("S", 2), ("M", 4), ("L", 3)],
    ),
    (
        "sweater-fino-marron",
        "Sweater fino marrón",
        "Sweaters y tejidos",
        52000,
        "Punto fino en marrón chocolate. Liviano para entrecasa y prolijo para salir.",
        [("S", 3), ("M", 5), ("L", 2)],
    ),
    (
        "sweater-fino-crudo",
        "Sweater fino crudo",
        "Sweaters y tejidos",
        52000,
        "El mismo punto fino en crudo. Es el comodín: combina con cualquier jean.",
        [("S", 2), ("M", 3), ("L", 3)],
    ),
    (
        "sweater-fino-bordo",
        "Sweater fino bordó",
        "Sweaters y tejidos",
        52000,
        "Bordó profundo, uno de los colores de la temporada. Queda bárbaro con un pañuelo.",
        [("S", 1), ("M", 2), ("L", 1)],
    ),
    (
        "sweater-rombos-marron",
        "Sweater rombos marrón",
        "Sweaters y tejidos",
        64000,
        "Rombos calados en marrón oscuro. Un tejido con detalle, para cuando querés algo más.",
        [("S", 1), ("M", 2)],
    ),
    (
        "remera-fearless",
        "Remera Fearless",
        "Remeras y tops",
        38000,
        "Algodón crudo con estampa de tigre. Con un jean oxford y listo el look.",
        [("S", 3), ("M", 4), ("L", 2)],
    ),
    (
        "remera-negra-sin-mangas",
        "Remera negra sin mangas",
        "Remeras y tops",
        32000,
        "Negra, sin mangas, corte suelto. Minimalista de las que se usan todo el año.",
        [("S", 4), ("M", 5), ("L", 3)],
    ),
    (
        "jean-oxford-azul-oscuro",
        "Jean oxford azul oscuro",
        "Jeans y pantalones",
        89000,
        "Oxford de tiro alto en azul oscuro. Estiliza y aguanta lavado tras lavado.",
        [("36", 2), ("38", 4), ("40", 3), ("42", 2)],
    ),
    (
        "jean-flare-azul",
        "Jean flare azul",
        "Jeans y pantalones",
        89000,
        "Flare azul medio, con caída. El que alarga la pierna sin tacos.",
        [("36", 1), ("38", 3), ("40", 3), ("42", 1)],
    ),
    (
        "jean-recto-celeste",
        "Jean recto celeste",
        "Jeans y pantalones",
        85000,
        "Recto en celeste clarito, tiro medio. El básico de todos los días.",
        [("36", 2), ("38", 3), ("40", 2), ("42", 2)],
    ),
    (
        "pantalon-sastrero-negro",
        "Pantalón sastrero negro",
        "Jeans y pantalones",
        72000,
        "Sastrero negro de vestir. Sube cualquier remera a otra categoría.",
        [("36", 1), ("38", 3), ("40", 2), ("42", 1)],
    ),
    (
        "bolso-tote-gamuza-marron",
        "Bolso tote de gamuza marrón",
        "Bolsos",
        95000,
        "Tote amplio en gamuza marrón, con manija larga. Entra todo y sigue quedando bien.",
        [("Único", 2)],
    ),
    (
        "bandolera-croco-negra",
        "Bandolera croco negra",
        "Bolsos",
        68000,
        "Bandolera negra con textura croco. Chica, prolija, para cuando no querés cargar nada.",
        [("Único", 3)],
    ),
    (
        "rinonera-negra",
        "Riñonera negra",
        "Bolsos",
        54000,
        "Riñonera negra de cuero ecológico. Se usa en la cintura o cruzada.",
        [("Único", 2)],
    ),
    (
        "bolso-rafia-natural",
        "Bolso de rafia natural",
        "Bolsos",
        48000,
        "Rafia natural con detalle en negro y manijas redondas. El de los días de calor.",
        [("Único", 2)],
    ),
    (
        "bolso-tejido-crudo",
        "Bolso tejido crudo",
        "Bolsos",
        46000,
        "Tejido crudo, blando, de hombro. Liviano y más grande de lo que parece.",
        [("Único", 1)],
    ),
    (
        "panuelo-rayado-beige",
        "Pañuelo rayado beige",
        "Accesorios",
        22000,
        "Pañuelo con rayas beige y crudo. Al cuello, en la cabeza o atado al bolso.",
        [("Único", 4)],
    ),
    (
        "panuelo-estampado-rosa",
        "Pañuelo estampado rosa",
        "Accesorios",
        22000,
        "Estampa rosa viejo sobre fondo crudo. Le cambia la cara a un sweater liso.",
        [("Único", 3)],
    ),
    (
        "pulseras-y-relojes",
        "Set de pulseras",
        "Accesorios",
        14000,
        "Set de pulseras en cuero y metal. Se suman de a varias, es la idea.",
        [("Único", 5)],
    ),
]

# slug del look, nombre, bajada (tomada de sus propios posteos)
LOOKS = [
    ("look-elegancia-simple", "Elegancia simple", "Lo clásico y lo moderno en el mismo look.", 1),
    ("look-del-dia", "Look del día", "Básico pero con estilo: sumale accesorios y lo transformás.", 2),
    ("look-outfit-del-dia", "Outfit del día", "Ese básico canchero que no falla.", 3),
    ("look-basicos-sweaters", "Básicos que no pueden faltar", "Los sweaters en colores tendencia.", 4),
    ("look-con-actitud", "Look con actitud", "Remera estampada y jean oxford, cómodo y con personalidad.", 5),
    ("look-remera-negra", "Elegancia y comodidad", "Minimalista, para todos los días.", 6),
]


class Command(BaseCommand):
    help = "Carga categorías, talles, productos y looks de CHAO. Se puede correr varias veces."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Borra el catálogo antes de cargar (no toca los pedidos).",
        )

    @transaction.atomic
    def handle(self, *args, **opciones):
        if opciones["reset"]:
            LookItem.objects.all().delete()
            Look.objects.all().delete()
            Variante.objects.all().delete()
            ProductoImagen.objects.all().delete()
            Producto.objects.all().delete()
            self.stdout.write("Catálogo anterior borrado.")

        categorias = {
            nombre: Categoria.objects.update_or_create(nombre=nombre, defaults={"orden": orden})[0]
            for nombre, orden in CATEGORIAS
        }
        talles = {
            nombre: Talle.objects.update_or_create(nombre=nombre, defaults={"orden": orden})[0]
            for nombre, orden in TALLES_ROPA + TALLES_PANTALON + TALLE_UNICO
        }

        hotspots = json.loads((Path(settings.BASE_DIR) / "tools" / "hotspots.json").read_text(encoding="utf-8"))

        # Invertido: para cada prenda, de qué foto de percha salió. Esa foto es la
        # segunda imagen del producto y alimenta el cambio de foto al pasar el mouse.
        look_de_producto = {
            item["producto"]: look_slug for look_slug, items in hotspots.items() for item in items
        }

        productos: dict[str, Producto] = {}
        for orden, (slug, nombre, categoria, precio, descripcion, stock) in enumerate(PRODUCTOS, start=1):
            producto, _ = Producto.objects.update_or_create(
                slug=slug,
                defaults={
                    "nombre": nombre,
                    "categoria": categorias[categoria],
                    "precio": precio,
                    "descripcion": descripcion,
                    "precio_a_confirmar": True,
                    "activo": True,
                    "orden": orden,
                },
            )
            productos[slug] = producto

            ProductoImagen.objects.update_or_create(
                producto=producto,
                orden=0,
                defaults={"ruta_estatica": f"img/productos/{slug}.jpg", "alt": f"{nombre} — CHAO Indumentaria"},
            )
            look_slug = look_de_producto.get(slug)
            if look_slug:
                ProductoImagen.objects.update_or_create(
                    producto=producto,
                    orden=1,
                    defaults={
                        "ruta_estatica": f"img/looks/{look_slug}.jpg",
                        "alt": f"{nombre} en el local de CHAO",
                    },
                )

            for talle_nombre, unidades in stock:
                Variante.objects.update_or_create(
                    producto=producto, talle=talles[talle_nombre], defaults={"stock": unidades}
                )

        for slug, nombre, bajada, orden in LOOKS:
            look, _ = Look.objects.update_or_create(
                slug=slug,
                defaults={
                    "nombre": nombre,
                    "bajada": bajada,
                    "ruta_estatica": f"img/looks/{slug}.jpg",
                    "alt": f"{nombre} — prendas en el local de CHAO en Villa Bosch",
                    "orden": orden,
                    "activo": True,
                },
            )
            for i, item in enumerate(hotspots.get(slug, [])):
                producto = productos.get(item["producto"])
                if producto is None:
                    continue
                LookItem.objects.update_or_create(
                    look=look,
                    producto=producto,
                    defaults={"x": item["x"], "y": item["y"], "orden": i},
                )

        # Las prendas de los dos looks más completos se muestran primero en el catálogo.
        Producto.objects.filter(
            en_looks__look__slug__in=["look-elegancia-simple", "look-remera-negra"]
        ).update(destacado=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"{Producto.objects.count()} prendas · {Look.objects.count()} looks · "
                f"{LookItem.objects.count()} hotspots · {Variante.objects.count()} variantes de talle"
            )
        )
