# CHAO Indumentaria — tienda online

Ecommerce en Django para **CHAO Indumentaria** (Villa Bosch, Tres de Febrero),
hecho por [Operon](https://operonhub.com/). Publicado en https://chao-ecommerce.vercel.app

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
- Panel de la dueña (el de todos los días): http://localhost:8531/gestion/
- Panel avanzado (looks y sus puntos sobre la foto): http://localhost:8531/panel/

Tests: `.venv\Scripts\python.exe manage.py test`

`seed_chao` es idempotente: se puede correr las veces que sea. Con `--reset` borra el
catálogo antes de cargar (no toca los pedidos).

---

## Cómo está armado

| App | De qué se ocupa |
|---|---|
| `catalogo` | Qué existe: categorías, prendas, talles, stock y los looks con sus hotspots |
| `carrito` | Carrito en la sesión. No escribe en la base |
| `pedidos` | Lo único que escribe registros de plata: pedidos, envíos, cobros y Mercado Pago |
| `gestion` | El panel de la dueña (`/gestion/`): prendas, fotos, stock, pedidos, portada y cobros |

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

## Datos del negocio: qué está verificado y qué no

**Verificado** con material propio de CHAO (Instagram @chao.ind y la vitrina del local):
dirección, horarios, teléfono, el aqua `#b1cfd1` del logo, las prendas del catálogo
inicial (salen de sus fotos) y las cuotas sin interés pintadas en la vitrina. Viven en
`settings.NEGOCIO`: no hay un teléfono ni una dirección escritos en un template.

**A confirmar con CHAO** (la tienda lo dice en pantalla, no lo esconde):

- **Precios del catálogo inicial.** Las prendas del seed llevan `precio_a_confirmar=True`,
  que muestra el aviso "precio de referencia". La dueña carga el precio real desde
  `/gestion/` y el aviso desaparece.
- **"3 cuotas sin interés".** El beneficio está en la vitrina; la cantidad de cuotas que
  muestra cada tarjeta es una estimación. Lo que cobra de verdad lo decide la
  configuración de cuotas de su cuenta de Mercado Pago.
- **Stock y talles** del catálogo inicial: son de relleno hasta que los cargue.
- **Permiso de uso de las fotos** tomadas de su Instagram.

---

## Mercado Pago

La dueña conecta **su** cuenta con el botón de `/gestion/cobros/` (OAuth con la app
"Operon Tiendas"): los cobros le entran directo a ella. Detalle en
`pedidos/services/mercadopago.py`.

- Tarjeta: Payment Brick dentro de la página + API de Orders. El monto lo pone siempre
  el servidor.
- Cuenta de Mercado Pago: preferencia + redirección.
- **Un pedido pasa a pagado solo si Mercado Pago lo confirma del lado del servidor**
  (respuesta del cobro o webhook, con monto y moneda verificados) o si la dueña lo marca
  a mano. Nunca por la URL a la que volvió el navegador.
- Sin cuenta conectada, el pedido igual se guarda y se termina por WhatsApp.

Variables: `MP_CLIENT_ID`, `MP_CLIENT_SECRET`, `MP_WEBHOOK_SECRET` y `SITIO_URL` (tiene
que ser exactamente la URL registrada en la app). `MP_ACCESS_TOKEN` + `MP_PUBLIC_KEY`
son solo para desarrollo con credenciales de prueba.

En local, `auto_return` y el webhook no funcionan (exigen https público): la vuelta
completa del pago se prueba deployado o con un túnel.

---

## Buscadores (Google) y vista previa al compartir

Todo cuelga de un interruptor, `PERMITIR_INDEXADO`, **apagado por defecto**
(`catalogo/seo.py`):

| | Apagado (hoy) | Prendido |
|---|---|---|
| Páginas de la tienda | `noindex, nofollow` | indexables, con `canonical` a `SITIO_URL` |
| `/robots.txt` | deja pasar (así leen el noindex) | bloquea paneles, carrito y checkout; publica el sitemap |
| `/sitemap.xml` | 404 | home, catálogo, categorías, looks y prendas activas |
| Datos estructurados | no | `ClothingStore` en la home, `Product` en cada prenda |

El carrito, el checkout, los pedidos y los paneles no se indexan nunca. Las etiquetas de
vista previa (Open Graph: título, descripción y foto al pegar el link en WhatsApp o
Instagram) salen siempre.

**Para abrir la tienda a Google**, cuando CHAO dé el visto bueno:

1. Definir el dominio definitivo y cargarlo en `SITIO_URL`. Si cambia, hay que
   actualizar también la URL de vuelta y el webhook en la app de Mercado Pago.
2. Confirmar que no queden precios de referencia ni prendas de prueba.
3. Poner `PERMITIR_INDEXADO=True` en las variables del hosting y redeployar.
4. Verificar el dominio en Google Search Console (con la cuenta de CHAO) y enviar
   `/sitemap.xml`.

Una prenda con precio de referencia nunca declara su precio a Google, aunque el
interruptor esté prendido.

---

## Hosting

- **Producción: Vercel**, con Postgres y Storage de **Supabase** (las fotos que sube la
  dueña van a Supabase Storage: el disco de Vercel es efímero). Variables que tienen que
  estar: `DJANGO_SECRET_KEY`, `DEBUG=False`, `ALLOWED_HOSTS`, `POSTGRES_URL` (o
  `DATABASE_URL`), `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SITIO_URL`, las de
  Mercado Pago y `GESTION_USUARIO` / `GESTION_CLAVE`.
- `render.yaml` quedó de la primera versión (deploy en Render). No se usa hoy.

---

## Estructura

```
chao-ecommerce/
├── chao/                  settings (todo por variables de entorno), urls, storage de Supabase
├── catalogo/              modelos, vistas de la tienda, seo.py, seed_chao
│   └── templatetags/      plata argentina ($48.900), itálicas editoriales, <head>
├── carrito/               Cart de sesión + vistas que devuelven el cajón renderizado
├── pedidos/               pedidos, checkout, envíos, cobros y services/mercadopago.py
├── gestion/               panel de la dueña
├── templates/             incluye 404.html y 500.html propias
├── static/
│   ├── css/               chao.css (tienda), home.css, gestion.css, panel.css
│   ├── js/                chao.js, home.js, intro.js, checkout.js, pago.js, gestion.js
│   └── img/               looks (fotos de percha) y productos (recortes)
└── tools/                 recortar_prendas.py + hotspots.json (lo lee el seed)
```
