"""
Tests del checkout y de Mercado Pago, con la API de MP simulada (no sale a internet).

Lo que cuidan: que el monto que se cobra lo ponga el servidor, que un pago solo se
dé por bueno si MP lo aprueba con el monto y la moneda correctos, que el stock se
descuente una sola vez y que el webhook rechace firmas falsas.
"""

import hashlib
import hmac
import json
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from catalogo.models import Categoria, Producto, Talle, Variante

from .models import Cobros, ConexionMP, Pedido, PedidoItem, ZonaEnvio
from .services import mercadopago


def respuesta(status=200, datos=None):
    r = mock.Mock()
    r.status_code = status
    r.json.return_value = datos or {}
    r.text = json.dumps(datos or {})
    return r


# En los tests no hay collectstatic: estáticos sin manifiesto y fotos en memoria.
SIN_MANIFIESTO = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}


@override_settings(STORAGES=SIN_MANIFIESTO)
class Base(TestCase):
    def setUp(self):
        cat = Categoria.objects.create(nombre="Sweaters")
        self.talle = Talle.objects.create(nombre="M", orden=1)
        self.prenda = Producto.objects.create(
            nombre="Sweater de prueba", slug="sweater-prueba", categoria=cat, precio=Decimal("50000")
        )
        self.variante = Variante.objects.create(producto=self.prenda, talle=self.talle, stock=3)
        self.cobros = Cobros.actual()
        self.cobros.alias = "chao.prueba"
        self.cobros.descuento_transferencia = 10
        self.cobros.save()
        ZonaEnvio.objects.all().delete()
        self.amba = ZonaEnvio.objects.create(nombre="AMBA", precio=Decimal("5000"), demora="3 a 5 días hábiles")
        self.coordinar = ZonaEnvio.objects.create(nombre="Resto del país", precio=None)

    def pedido(self, metodo=Pedido.Metodo.MERCADOPAGO, cantidad=1, envio=None):
        p = Pedido.objects.create(nombre="Ana Prueba", telefono="1155555555", email="ana@example.com",
                                  metodo_pago=metodo)
        PedidoItem.objects.create(pedido=p, producto=self.prenda, talle=self.talle, cantidad=cantidad,
                                  precio_unitario=self.prenda.precio)
        if envio is not None:
            p.entrega, p.costo_envio = Pedido.Entrega.ENVIO, envio
            p.save()
        p.recalcular_total()
        return p

    def al_carrito(self):
        self.client.post(reverse("carrito:agregar"), {"producto": self.prenda.pk, "talle": self.talle.pk})


class CheckoutTests(Base):
    datos = {"nombre": "Ana Prueba", "telefono": "11 5555-5555", "email": "ana@example.com"}

    def test_transferencia_con_envio_aplica_descuento_y_envio(self):
        self.al_carrito()
        r = self.client.post(reverse("pedidos:checkout"), {
            **self.datos, "entrega": f"zona-{self.amba.pk}", "metodo_pago": "transferencia",
            "calle": "Gaucho Cruz", "numero": "5485", "codigo_postal": "1682",
            "localidad": "Villa Bosch", "provincia": "Buenos Aires",
        })
        p = Pedido.objects.get()
        self.assertRedirects(r, reverse("pedidos:pedido", args=[p.codigo]))
        self.assertEqual(p.subtotal, Decimal("50000"))
        self.assertEqual(p.descuento, Decimal("5000"))
        self.assertEqual(p.costo_envio, Decimal("5000"))
        self.assertEqual(p.total, Decimal("50000"))

    def test_envio_sin_direccion_no_crea_pedido(self):
        self.al_carrito()
        r = self.client.post(reverse("pedidos:checkout"), {
            **self.datos, "entrega": f"zona-{self.amba.pk}", "metodo_pago": "transferencia"})
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Pedido.objects.exists())
        self.assertIn("calle", r.context["form"].errors)

    def test_efectivo_con_envio_se_rechaza(self):
        self.al_carrito()
        self.client.post(reverse("pedidos:checkout"), {
            **self.datos, "entrega": f"zona-{self.amba.pk}", "metodo_pago": "efectivo",
            "calle": "X", "numero": "1", "codigo_postal": "1682", "localidad": "Y", "provincia": "Buenos Aires"})
        self.assertFalse(Pedido.objects.exists())

    def test_zona_apagada_no_se_puede_elegir(self):
        self.amba.activa = False
        self.amba.save()
        self.al_carrito()
        r = self.client.post(reverse("pedidos:checkout"), {
            **self.datos, "entrega": f"zona-{self.amba.pk}", "metodo_pago": "transferencia"})
        self.assertIn("entrega", r.context["form"].errors)

    def test_mercadopago_no_disponible_sin_conexion(self):
        self.al_carrito()
        r = self.client.post(reverse("pedidos:checkout"), {**self.datos, "entrega": "retiro", "metodo_pago": "mercadopago"})
        self.assertIn("metodo_pago", r.context["form"].errors)

    def test_envio_a_coordinar_cobra_solo_prendas(self):
        self.al_carrito()
        self.client.post(reverse("pedidos:checkout"), {
            **self.datos, "entrega": f"zona-{self.coordinar.pk}", "metodo_pago": "transferencia",
            "calle": "X", "numero": "1", "codigo_postal": "5000", "localidad": "Córdoba", "provincia": "Córdoba"})
        p = Pedido.objects.get()
        self.assertTrue(p.envio_a_coordinar)
        self.assertEqual(p.total, Decimal("45000"))


class StockTests(Base):
    def test_pagado_descuenta_una_vez_y_cancelar_devuelve(self):
        p = self.pedido(cantidad=2)
        p.marcar_pagado("1")
        p.marcar_pagado("1")  # webhook repetido
        self.variante.refresh_from_db()
        self.assertEqual(self.variante.stock, 1)
        p.cambiar_estado(Pedido.Estado.CANCELADO)
        self.variante.refresh_from_db()
        self.assertEqual(self.variante.stock, 3)

    def test_stock_nunca_negativo(self):
        p = self.pedido(cantidad=5)
        p.marcar_pagado()
        self.variante.refresh_from_db()
        self.assertEqual(self.variante.stock, 0)


@override_settings(MP_ACCESS_TOKEN="TEST-token", MP_PUBLIC_KEY="TEST-public", MP_WEBHOOK_SECRET="")
class PagoTests(Base):
    @staticmethod
    def orden(estado="processed", detalle="accredited", monto="50000.00", ref="1"):
        return {"id": "ORD01TEST", "status": estado, "status_detail": detalle, "total_amount": monto,
                "external_reference": ref,
                "transactions": {"payments": [{"id": "PAY01", "amount": monto, "status": estado,
                                               "status_detail": detalle}]}}

    def test_monto_lo_pone_el_servidor(self):
        p = self.pedido()
        with mock.patch("pedidos.services.mercadopago.requests.post",
                        return_value=respuesta(201, self.orden(ref=str(p.pk)))) as post:
            r = self.client.post(reverse("pedidos:procesar", args=[p.codigo]),
                                 json.dumps({"token": "tok", "payment_method_id": "visa", "installments": 3,
                                             "payment_type_id": "credit_card", "transaction_amount": 1,
                                             "payer": {"email": "ana@example.com"}}),
                                 content_type="application/json")
        self.assertTrue(post.call_args.args[0].endswith("/v1/orders"))
        enviado = post.call_args.kwargs["json"]
        self.assertEqual(enviado["total_amount"], "50000.00")  # no el 1 que mandó el navegador
        pago = enviado["transactions"]["payments"][0]
        self.assertEqual(pago["amount"], "50000.00")
        self.assertEqual(pago["payment_method"], {"id": "visa", "type": "credit_card", "token": "tok", "installments": 3})
        self.assertIn("X-Idempotency-Key", post.call_args.kwargs["headers"])
        self.assertEqual(r.json()["estado"], "pagado")
        p.refresh_from_db()
        self.assertEqual(p.estado, Pedido.Estado.PAGADO)
        self.assertEqual(p.mp_payment_id, "ORD01TEST")

    def test_rechazo_402_explica_el_motivo(self):
        p = self.pedido()
        with mock.patch("pedidos.services.mercadopago.requests.post",
                        return_value=respuesta(402, self.orden("failed", "insufficient_amount", ref=str(p.pk)))):
            r = self.client.post(reverse("pedidos:procesar", args=[p.codigo]),
                                 json.dumps({"token": "t", "payment_method_id": "visa"}), content_type="application/json")
        self.assertEqual(r.json()["estado"], "rechazado")
        self.assertIn("saldo", r.json()["mensaje"])
        p.refresh_from_db()
        self.assertEqual(p.estado, Pedido.Estado.RECHAZADO)

    def test_rechazo_402_solo_con_errores(self):
        p = self.pedido()
        cuerpo = {"errors": [{"code": "failed", "message": "x", "details": ["rejected_by_issuer"]}]}
        with mock.patch("pedidos.services.mercadopago.requests.post", return_value=respuesta(402, cuerpo)):
            r = self.client.post(reverse("pedidos:procesar", args=[p.codigo]),
                                 json.dumps({"token": "t", "payment_method_id": "visa"}), content_type="application/json")
        self.assertEqual(r.json()["estado"], "rechazado")
        self.assertIn("banco", r.json()["mensaje"])

    def test_en_revision_queda_pendiente(self):
        p = self.pedido()
        with mock.patch("pedidos.services.mercadopago.requests.post",
                        return_value=respuesta(201, self.orden("processing", "in_review", ref=str(p.pk)))):
            r = self.client.post(reverse("pedidos:procesar", args=[p.codigo]),
                                 json.dumps({"token": "t", "payment_method_id": "visa"}), content_type="application/json")
        self.assertEqual(r.json()["estado"], "pendiente")
        p.refresh_from_db()
        self.assertEqual(p.estado, Pedido.Estado.PENDIENTE)

    def test_webhook_order_aprobada(self):
        p = self.pedido()
        with mock.patch("pedidos.services.mercadopago.requests.get",
                        return_value=respuesta(200, self.orden(ref=str(p.pk)))) as get:
            r = self.client.post(reverse("pedidos:mp_webhook") + "?data.id=ORD01TEST&type=order",
                                 json.dumps({"type": "order", "action": "order.processed", "data": {"id": "ORD01TEST"}}),
                                 content_type="application/json")
        self.assertTrue(get.call_args.args[0].endswith("/v1/orders/ORD01TEST"))
        self.assertEqual(r.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.estado, Pedido.Estado.PAGADO)

    def test_webhook_order_con_monto_menor_no_paga(self):
        p = self.pedido()
        with mock.patch("pedidos.services.mercadopago.requests.get",
                        return_value=respuesta(200, self.orden(monto="10.00", ref=str(p.pk)))):
            self.client.post(reverse("pedidos:mp_webhook") + "?data.id=ORD01TEST&type=order",
                             json.dumps({"type": "order"}), content_type="application/json")
        p.refresh_from_db()
        self.assertEqual(p.estado, Pedido.Estado.PENDIENTE)

    def test_webhook_pago_billetera_aprobado(self):
        p = self.pedido()
        pago = {"status": "approved", "external_reference": str(p.pk), "transaction_amount": 50000, "currency_id": "ARS"}
        with mock.patch("pedidos.services.mercadopago.requests.get", return_value=respuesta(200, pago)):
            r = self.client.post(reverse("pedidos:mp_webhook") + "?data.id=123&type=payment",
                                 json.dumps({"type": "payment", "data": {"id": "123"}}), content_type="application/json")
        self.assertEqual(r.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.estado, Pedido.Estado.PAGADO)

    def test_webhook_pago_billetera_monto_menor(self):
        p = self.pedido()
        pago = {"status": "approved", "external_reference": str(p.pk), "transaction_amount": 10, "currency_id": "ARS"}
        with mock.patch("pedidos.services.mercadopago.requests.get", return_value=respuesta(200, pago)):
            self.client.post(reverse("pedidos:mp_webhook") + "?data.id=123&type=payment",
                             json.dumps({"type": "payment"}), content_type="application/json")
        p.refresh_from_db()
        self.assertEqual(p.estado, Pedido.Estado.PENDIENTE)

    @override_settings(MP_WEBHOOK_SECRET="secreto")
    def test_webhook_firma(self):
        p = self.pedido()
        pago = {"status": "approved", "external_reference": str(p.pk), "transaction_amount": 50000, "currency_id": "ARS"}
        url = reverse("pedidos:mp_webhook") + "?data.id=ABC123&type=payment"
        with mock.patch("pedidos.services.mercadopago.requests.get", return_value=respuesta(200, pago)):
            falsa = self.client.post(url, "{}", content_type="application/json",
                                     HTTP_X_SIGNATURE="ts=1,v1=deadbeef", HTTP_X_REQUEST_ID="req-1")
            self.assertEqual(falsa.status_code, 401)
            manifiesto = "id:abc123;request-id:req-1;ts:1700000000;"
            v1 = hmac.new(b"secreto", manifiesto.encode(), hashlib.sha256).hexdigest()
            buena = self.client.post(url, "{}", content_type="application/json",
                                     HTTP_X_SIGNATURE=f"ts=1700000000,v1={v1}", HTTP_X_REQUEST_ID="req-1")
        self.assertEqual(buena.status_code, 200)
        p.refresh_from_db()
        self.assertEqual(p.estado, Pedido.Estado.PAGADO)


@override_settings(MP_CLIENT_ID="123", MP_CLIENT_SECRET="secreto", SITIO_URL="https://chao.test")
class ConexionTests(Base):
    def setUp(self):
        super().setUp()
        from django.contrib.auth import get_user_model

        self.duena = get_user_model().objects.create_user("duena-test", is_staff=True)
        self.client.force_login(self.duena)

    def test_inicio_avisa_que_falta_conectar(self):
        r = self.client.get(reverse("gestion:inicio"))
        self.assertContains(r, "Conectá Mercado Pago")
        ConexionMP.objects.create(mp_user_id="1", access_token="a", public_key="p",
                                  vence=timezone.now() + timedelta(days=100))
        r = self.client.get(reverse("gestion:inicio"))
        self.assertNotContains(r, "Conectá Mercado Pago")

    def test_cobros_muestra_cuenta_conectada(self):
        ConexionMP.objects.create(mp_user_id="1", apodo="CHAOIND", access_token="a", public_key="p",
                                  vence=timezone.now() + timedelta(days=100))
        r = self.client.get(reverse("gestion:cobros"))
        self.assertContains(r, "CHAOIND")
        self.assertNotContains(r, "access_token")

    def test_boton_conectar_lleva_a_mercadopago_con_state(self):
        r = self.client.get(reverse("gestion:mp_conectar"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("auth.mercadopago.com/authorization", r["Location"])
        self.assertIn("redirect_uri=https%3A%2F%2Fchao.test%2Fgestion%2Fmercadopago%2Fcallback%2F", r["Location"])
        self.assertTrue(self.client.session["mp_estado"])

    def test_callback_con_state_incorrecto_no_conecta(self):
        self.client.get(reverse("gestion:mp_conectar"))
        self.client.get(reverse("gestion:mp_callback") + "?code=X&state=otro")
        self.assertFalse(ConexionMP.objects.exists())

    def test_callback_guarda_tokens(self):
        self.client.get(reverse("gestion:mp_conectar"))
        estado = self.client.session["mp_estado"]
        token = {"access_token": "APP_USR-acc", "public_key": "APP_USR-pub", "refresh_token": "TG-ref",
                 "user_id": 555, "expires_in": 15552000, "live_mode": True}
        with mock.patch("pedidos.services.mercadopago.requests.post", return_value=respuesta(200, token)), \
             mock.patch("pedidos.services.mercadopago.requests.get",
                        return_value=respuesta(200, {"nickname": "CHAOINDUMENTARIA", "email": "chao@example.com"})):
            self.client.get(reverse("gestion:mp_callback") + f"?code=TG-code&state={estado}")
        con = ConexionMP.actual()
        self.assertEqual(con.public_key, "APP_USR-pub")
        self.assertEqual(con.apodo, "CHAOINDUMENTARIA")
        cred = mercadopago.credenciales()
        self.assertEqual(cred.origen, "conectada")

    def test_token_por_vencer_se_renueva(self):
        ConexionMP.objects.create(mp_user_id="1", access_token="viejo", refresh_token="TG-ref", public_key="pub",
                                  vence=timezone.now() + timedelta(days=3))
        nuevo = {"access_token": "nuevo", "public_key": "pub", "refresh_token": "TG-2", "expires_in": 15552000}
        with mock.patch("pedidos.services.mercadopago.requests.post", return_value=respuesta(200, nuevo)):
            cred = mercadopago.credenciales()
        self.assertEqual(ConexionMP.actual().access_token, "nuevo")
        self.assertEqual(cred.access_token, "nuevo")


@override_settings(MP_ACCESS_TOKEN="TEST-token", MP_PUBLIC_KEY="TEST-public-123")
class PaginasTests(Base):
    def test_pagina_de_pago_carga_el_brick(self):
        p = self.pedido()
        with mock.patch("pedidos.services.mercadopago.requests.post", return_value=respuesta(201, {"id": "pref-1"})):
            r = self.client.get(reverse("pedidos:pago", args=[p.codigo]))
        self.assertContains(r, "sdk.mercadopago.com/js/v2")
        self.assertContains(r, "TEST-public-123")
        self.assertContains(r, "pref-1")

    def test_pagina_del_pedido_en_cada_estado(self):
        casos = [
            (Pedido.Metodo.TRANSFERENCIA, Pedido.Estado.PENDIENTE, "Te falta"),
            (Pedido.Metodo.EFECTIVO, Pedido.Estado.PENDIENTE, "separamos"),
            (Pedido.Metodo.MERCADOPAGO, Pedido.Estado.PENDIENTE, "Falta"),
            (Pedido.Metodo.MERCADOPAGO, Pedido.Estado.RECHAZADO, "no pasó"),
            (Pedido.Metodo.MERCADOPAGO, Pedido.Estado.PAGADO, "Gracias"),
        ]
        for metodo, estado, texto in casos:
            p = self.pedido(metodo=metodo)
            p.estado = estado
            p.save()
            r = self.client.get(reverse("pedidos:pedido", args=[p.codigo]))
            self.assertContains(r, texto, msg_prefix=f"{metodo}/{estado}")

    def test_codigo_ajeno_da_404(self):
        self.assertEqual(self.client.get(reverse("pedidos:pedido", args=["noexiste"])).status_code, 404)
