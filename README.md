# CHAO Indumentaria — tienda online

Ecommerce en Django para **CHAO Indumentaria** (Villa Bosch, Tres de Febrero).
Demo de prospección hecha por [Operon](https://operonhub.com/).

El negocio hoy vende 100% en el local y por mensaje directo: el link de su bio va a
WhatsApp y cada posteo cierra con *"consultanos por precios y disponibilidad"*. Esta
tienda existe para que esa consulta no sea necesaria.

---

## Arrancar en local

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\python.exe manage.py migrate
.venv\Scripts\python.exe manage.py seed_chao
.venv\Scripts\python.exe manage.py createsuperuser
.venv\Scripts\python.exe manage.py runserver 8531
```

- Tienda: http://localhost:8531/
- Panel de la dueña: http://localhost:8531/panel/

`seed_chao` es idempotente: se puede correr las veces que sea. Con `--reset` borra el
catálogo antes de cargar (no toca los pedidos).

---

## Cómo está armado

| App | De qué se ocupa |
|---|---|
| `catalogo` | Qué existe: categorías, prendas, talles, stock y los looks con sus hotspots |
| `carrito` | Carrito en la sesión. No escribe en la base |
| `pedidos` | Lo único que escribe registros de plata: pedidos y estado de pago |

Sin React: el catálogo se renderiza en el servidor (mejor SEO local, que es justo lo que
le falta al negocio) y el carrito se maneja con sesiones y un poco de JS.

**El carrito no tiene estado en JavaScript.** Cada acción postea al servidor y el
servidor devuelve el cajón ya renderizado; el JS solo reemplaza nodos. Hay una sola
verdad y está en la sesión.

### El lookbook con hotspots

CHAO no fotografía prendas sueltas sobre fondo blanco: publica composiciones de percha
dentro del local. En vez de pelear con ese material, la tienda lo usa como está: cada
foto es un `Look` y cada `LookItem` marca dónde está una prenda dentro de ella, con `x`
e `y` en porcentaje (no en píxeles, así el marcador queda pegado a la prenda en
cualquier pantalla).

Las fotos de producto son recortes de esas mismas fotos, generados por
`tools/recortar_prendas.py`. Ese script también escribe `tools/hotspots.json`, que es
de donde el seed lee las coordenadas — por eso el marcador sobre la foto y el recorte
del producto no pueden desincronizarse.

Para mover un hotspot sin volver a recortar: se edita `x`/`y` desde el panel, en la
ficha del look.

---

## Lo que falta confirmar con CHAO

Nada de esto está inventado como si fuera dato del cliente; todo está marcado en pantalla.

- **Precios.** No publican ninguno. Los del seed son estimaciones de mercado y llevan
  `precio_a_confirmar=True`, que es lo que hace aparecer el aviso. Cuando manden la
  lista: se cambian los números y se destilda el campo (se puede hacer en lote desde el
  panel).
- **Stock y talles.** Los talles S/M/L y 36/38/40/42 son los habituales del rubro; las
  cantidades son de relleno.
- **Envíos.** No dicen en ningún lado que hagan envíos, así que la web no lo afirma: la
  sección de preguntas dice que se coordina por WhatsApp y marca la zona como a definir.
- **Cambios.** El plazo de 30 días es un supuesto, señalado como tal.

Lo que **sí** está verificado y sale de material propio de CHAO: dirección, horarios,
teléfono, el aqua `#b1cfd1` del logo (muestreado de su avatar), las prendas del catálogo
(todas salen de sus fotos) y las cuotas sin interés, que están pintadas en la vitrina.

---

## Mercado Pago

Checkout Pro con token de prueba. Se configura en `.env`:

```
MP_ACCESS_TOKEN=TEST-...
```

**El pago solo se confirma por el webhook.** La página de vuelta informa, pero no cambia
el estado: los parámetros de esa URL los puede escribir cualquiera. El webhook recibe un
id, consulta la API con nuestro token y recién entonces marca el pedido como pagado.

### Probar en local tiene un límite

`auto_return` y `notification_url` exigen una URL pública https. Con `localhost`, Mercado
Pago rechaza la preferencia con `auto_return invalid`. El código detecta que la base no
es https y omite esos dos campos, así que **la preferencia se crea y el link de pago
funciona**, pero:

- la vuelta automática al sitio no ocurre,
- el webhook no llega, así que el pedido queda en `pendiente`.

La vuelta completa del pago se prueba ya deployado. Si hace falta probarla en local,
un túnel (`ngrok http 8531`) y poner el dominio del túnel en `ALLOWED_HOSTS`.

Si Mercado Pago no responde, el pedido **igual queda guardado** y la clienta cae en una
página que le arma el mensaje de WhatsApp con su pedido. La venta no se pierde.

---

## Deploy en Render

`render.yaml` ya está listo: se importa el repo y Render lo lee. Los estáticos los sirve
WhiteNoise, así que no hace falta S3 ni nginx.

El plan es `starter` a propósito. En el free tier Render duerme el servicio y el primer
visitante espera ~50 segundos — para una demo que el cliente abre una sola vez, eso es
perder la venta en la pantalla de carga.

Después del primer deploy hay que cargar a mano en el panel de Render:
`MP_ACCESS_TOKEN` y `MP_PUBLIC_KEY`.

### Ojo con las fotos que suba la dueña

Las fotos del catálogo inicial viven en `static/img/` y viajan en el repo: esas están a
salvo. Pero si la dueña sube una foto nueva desde el panel, va a `media/`, y **en Render
sin disco persistente `media/` se borra en cada deploy.**

Si el cliente contrata, hay que descomentar el bloque `disk` de `render.yaml` y la
variable `MEDIA_ROOT`. Es un costo extra chico y conviene decirlo antes de que pase, no
después.

---

## Estructura

```
chao-ecommerce/
├── chao/                  settings (todo por variables de entorno), urls, wsgi
├── catalogo/              modelos, admin en castellano, views, seed_chao
│   └── templatetags/      formato de plata argentino ($48.900)
├── carrito/               Cart de sesión + vistas que devuelven el cajón renderizado
├── pedidos/               pedidos, checkout y services/mercadopago.py
├── templates/
├── static/
│   ├── css/chao.css       paleta y tipografía (Archivo variable, un solo archivo)
│   ├── js/chao.js         hotspots, cajón del carrito, filtros
│   └── img/
│       ├── looks/         las 6 fotos de percha + la vitrina (1440x1920, de su IG)
│       └── productos/     19 recortes generados
└── tools/
    ├── recortar_prendas.py
    └── hotspots.json      generado; lo lee el seed
```

---

## Pendiente en el código

`carrito/views.py::elegir_talle_para_look()` está sin implementar: define qué talle usar
cuando alguien agrega un look completo de un clic. Es una decisión de negocio (un clic
menos contra menos cambios en el local) y las tres opciones están documentadas ahí mismo.
Hasta que se defina, el botón "Llevar el look completo" muestra un aviso de error en vez
de agregar — el resto de la tienda funciona normal.
