"""
Tests de lo que ven los buscadores y de las páginas públicas de la tienda.

Lo que cuidan: que mientras la tienda no esté abierta a Google ninguna página se
pueda indexar, que al abrirla el canonical apunte al dominio oficial y que el
carrito, el checkout y los pedidos no se indexen nunca.
"""

import json
import re
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Categoria, Producto, Talle, Variante

SIN_MANIFIESTO = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
ABIERTA = {"PERMITIR_INDEXADO": True, "SITIO_URL": "https://chao.example"}


def datos_estructurados(html: str) -> dict:
    bloque = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    return json.loads(bloque.group(1)) if bloque else {}


@override_settings(STORAGES=SIN_MANIFIESTO)
class Base(TestCase):
    def setUp(self):
        self.cat = Categoria.objects.create(nombre="Sweaters")
        self.talle = Talle.objects.create(nombre="M", orden=1)
        self.prenda = Producto.objects.create(
            nombre="Sweater de prueba", slug="sweater-prueba", categoria=self.cat,
            precio=Decimal("50000"), descripcion="Tejido </script> grueso.",
        )
        self.variante = Variante.objects.create(producto=self.prenda, talle=self.talle, stock=2)
        self.url_prenda = reverse("catalogo:producto", args=[self.prenda.slug])


@override_settings(PERMITIR_INDEXADO=False, SITIO_URL="")
class TiendaCerradaTests(Base):
    def test_ninguna_pagina_se_puede_indexar(self):
        for url in (reverse("catalogo:home"), reverse("catalogo:catalogo"), reverse("catalogo:looks"), self.url_prenda):
            html = self.client.get(url).content.decode()
            self.assertIn('<meta name="robots" content="noindex, nofollow">', html, url)
            self.assertNotIn('rel="canonical"', html, url)
            self.assertNotIn("application/ld+json", html, url)

    def test_robots_deja_entrar_para_que_lean_el_noindex(self):
        r = self.client.get("/robots.txt")
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r["Content-Type"].startswith("text/plain"))
        self.assertNotIn("Disallow", r.content.decode())
        self.assertNotIn("Sitemap", r.content.decode())

    def test_no_hay_sitemap(self):
        self.assertEqual(self.client.get("/sitemap.xml").status_code, 404)

    def test_vista_previa_para_compartir_esta_siempre(self):
        html = self.client.get(self.url_prenda).content.decode()
        self.assertIn('<meta property="og:title" content="Sweater de prueba — CHAO Indumentaria">', html)
        self.assertIn('<meta property="og:type" content="product">', html)
        self.assertIn(f'<meta property="og:url" content="http://testserver{self.url_prenda}">', html)


@override_settings(**ABIERTA)
class TiendaAbiertaTests(Base):
    def test_canonical_al_dominio_oficial_sin_parametros(self):
        html = self.client.get(reverse("catalogo:catalogo") + "?orden=nuevo").content.decode()
        self.assertIn('<link rel="canonical" href="https://chao.example/catalogo/">', html)
        self.assertNotIn('name="robots"', html)

    def test_checkout_y_carrito_nunca_se_indexan(self):
        self.client.post(reverse("carrito:agregar"), {"producto": self.prenda.pk, "talle": self.talle.pk})
        html = self.client.get(reverse("pedidos:checkout")).content.decode()
        self.assertIn('<meta name="robots" content="noindex, nofollow">', html)
        self.assertNotIn('rel="canonical"', html)

    def test_robots_y_sitemap(self):
        robots = self.client.get("/robots.txt").content.decode()
        self.assertIn("Disallow: /checkout/", robots)
        self.assertIn("Sitemap: https://chao.example/sitemap.xml", robots)

        Producto.objects.create(nombre="Oculta", slug="oculta", categoria=self.cat, precio=1, activo=False)
        xml = self.client.get("/sitemap.xml").content.decode()
        self.assertIn("<loc>https://chao.example/</loc>", xml)
        self.assertIn(f"<loc>https://chao.example{self.url_prenda}</loc>", xml)
        self.assertIn("<loc>https://chao.example/catalogo/sweaters/</loc>", xml)
        self.assertNotIn("oculta", xml)
        self.assertNotIn("checkout", xml)

    def test_home_describe_el_local(self):
        datos = datos_estructurados(self.client.get(reverse("catalogo:home")).content.decode())
        self.assertEqual(datos["@type"], "ClothingStore")
        self.assertEqual(datos["@id"], "https://chao.example/#tienda")
        self.assertEqual(datos["address"]["streetAddress"], "Gaucho Cruz 5485")
        self.assertEqual(len(datos["openingHoursSpecification"]), 2)
        # Nada de puntajes ni reseñas propias.
        self.assertNotIn("aggregateRating", datos)

    def test_prenda_con_precio_confirmado_declara_la_oferta(self):
        html = self.client.get(self.url_prenda).content.decode()
        datos = datos_estructurados(html)
        self.assertEqual(datos["offers"]["price"], "50000.00")
        self.assertEqual(datos["offers"]["priceCurrency"], "ARS")
        self.assertTrue(datos["offers"]["availability"].endswith("InStock"))
        # La descripción no puede cerrar la etiqueta <script>.
        self.assertEqual(html.count("</script>"), html.count("<script"))

    def test_sin_stock_se_declara_agotada(self):
        self.variante.stock = 0
        self.variante.save()
        datos = datos_estructurados(self.client.get(self.url_prenda).content.decode())
        self.assertTrue(datos["offers"]["availability"].endswith("OutOfStock"))


@override_settings(STORAGES=SIN_MANIFIESTO, DEBUG=False)
class PaginasTests(Base):
    def test_404_con_la_cara_de_la_tienda(self):
        r = self.client.get("/prenda/no-existe/")
        self.assertEqual(r.status_code, 404)
        self.assertIn("Ver la colección", r.content.decode())

    def test_visitar_no_crea_sesion(self):
        """Una visita sin tocar el carrito no escribe una sesión en la base."""
        r = self.client.get(reverse("catalogo:catalogo"))
        self.assertNotIn("sessionid", r.cookies)


class CarritoTests(Base):
    def agregar(self, **datos):
        return self.client.post(reverse("carrito:agregar"), datos)

    def test_talle_sin_stock_no_se_agrega(self):
        self.variante.stock = 0
        self.variante.save()
        r = self.agregar(producto=self.prenda.pk, talle=self.talle.pk)
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.client.session.get("carrito", {}), {})

    def test_datos_ilegibles_no_rompen(self):
        self.assertEqual(self.agregar(producto="abc").status_code, 400)
        self.assertEqual(self.agregar(producto=self.prenda.pk, talle="x").status_code, 400)

    def test_agregar_guarda_el_carrito(self):
        self.agregar(producto=self.prenda.pk, talle=self.talle.pk)
        self.assertEqual(len(self.client.session["carrito"]), 1)
        self.assertIn("sessionid", self.client.cookies)
