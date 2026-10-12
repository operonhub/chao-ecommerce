"""
Configuración de Django para el ecommerce de CHAO Indumentaria.

Todo lo que cambia entre la máquina de desarrollo y el servidor sale de variables
de entorno (archivo .env en local, panel de Render en producción). Nunca hay una
credencial escrita acá.
"""

from pathlib import Path
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_bool(nombre: str, default: bool = False) -> bool:
    return os.getenv(nombre, str(default)).strip().lower() in {"1", "true", "yes", "si", "sí"}


# En desarrollo hay una clave de descarte para que el proyecto arranque sin configurar
# nada. En producción DEBUG=False y ahí sí se exige la variable de entorno.
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "dev-insegura-solo-para-desarrollo")
DEBUG = env_bool("DEBUG", True)

if not DEBUG and SECRET_KEY == "dev-insegura-solo-para-desarrollo":
    raise RuntimeError("Falta DJANGO_SECRET_KEY: no se puede correr con DEBUG=False sin clave real.")

ALLOWED_HOSTS = [h.strip() for h in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if h.strip()]

# Render expone el dominio asignado en esta variable. Se agrega solo para no tener
# que acordarse de actualizar ALLOWED_HOSTS a mano en cada deploy.
RENDER_HOST = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if RENDER_HOST:
    ALLOWED_HOSTS.append(RENDER_HOST)

# Django 4+ exige el origen completo (con esquema) para validar el POST de formularios.
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in {"localhost", "127.0.0.1"}]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "catalogo",
    "carrito",
    "pedidos",
    "gestion",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # WhiteNoise va inmediatamente después de SecurityMiddleware: así sirve los
    # estáticos en producción sin necesitar nginx ni un bucket aparte.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "chao.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "carrito.context_processors.carrito",
                "catalogo.context_processors.datos_negocio",
                "catalogo.context_processors.menu_categorias",
            ],
        },
    },
]

WSGI_APPLICATION = "chao.wsgi.application"

# En local, SQLite sin configurar nada. En producción, Postgres: DATABASE_URL si
# está, o si no POSTGRES_URL, que es la que carga la integración de Supabase en
# Vercel (apunta al pooler en modo transacción, puerto 6543).
def _url_base():
    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
    if not url:
        return f"sqlite:///{BASE_DIR / 'db.sqlite3'}"
    # Supabase agrega ?supa=base-pooler.x, que psycopg no entiende.
    partes = urlsplit(url)
    query = urlencode([(k, v) for k, v in parse_qsl(partes.query) if k != "supa"])
    return urlunsplit(partes._replace(query=query))


_url_db = _url_base()
_por_pooler = ":6543/" in _url_db

DATABASES = {
    "default": dj_database_url.parse(
        _url_db,
        # La conexión se reusa entre pedidos mientras la instancia siga viva:
        # abrir una conexión segura nueva en cada página costaba varios viajes
        # de ida y vuelta a la base. El pooler (modo transacción) multiplexa
        # igual, y el chequeo de salud descarta una conexión que se cortó
        # mientras la instancia dormía.
        conn_max_age=60 if _por_pooler else 600,
        conn_health_checks=True,
    )
}

if _por_pooler:
    # En modo transacción la conexión física cambia entre consultas: ni cursores
    # del lado del servidor ni sentencias preparadas sobreviven a eso.
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
    DATABASES["default"].setdefault("OPTIONS", {})["prepare_threshold"] = None

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es-ar"
TIME_ZONE = "America/Argentina/Buenos_Aires"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Las fotos del catálogo viajan en el repo dentro de static/. MEDIA_ROOT es solo para
# lo que la dueña suba desde el admin. Atención: en Render sin disco persistente esa
# carpeta se borra en cada deploy (ver README).
MEDIA_URL = "media/"
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "media"))
SERVIR_MEDIA = env_bool("SERVIR_MEDIA", False)

# El panel de la dueña (/gestion/) tiene su propio login.
LOGIN_URL = "gestion:ingresar"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Con Supabase configurado (lo carga la integración de Vercel), las fotos que sube
# la dueña van a Supabase Storage en vez del disco, que en Vercel se borra.
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "media")
if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
    STORAGES["default"] = {"BACKEND": "chao.almacenamiento.SupabaseStorage"}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Seguridad en producción -------------------------------------------------
# Solo con DEBUG=False: en desarrollo se sirve por http y estas opciones romperían
# el login del panel (la cookie de sesión no viajaría).
if not DEBUG:
    # Render corta el TLS en su proxy y reenvía por http; sin esta cabecera Django
    # cree que la conexión es insegura y entra en un loop de redirecciones.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True

    # La tienda recibe nombre y teléfono de clientas: las cookies no viajan en claro.
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

    # Un año, con subdominios. Es la recomendación estándar; conviene dejarlo así
    # desde el principio y no cuando ya hay tráfico.
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# --- Datos del negocio -------------------------------------------------------
# Verificados del Instagram y de la vitrina de CHAO (@chao.ind). Viven acá para que
# no haya un teléfono o una dirección hardcodeada en medio de un template.
NEGOCIO = {
    "nombre": "CHAO Indumentaria",
    "instagram": "chao.ind",
    "instagram_url": "https://www.instagram.com/chao.ind/",
    "whatsapp": "5491162285175",
    "whatsapp_visible": "11 6228-5175",
    "direccion": "Gaucho Cruz 5485, Villa Bosch",
    "partido": "Tres de Febrero, Buenos Aires",
    "horario_manana": "9.30 a 13.00",
    "horario_tarde": "16.30 a 20.00",
    "dias": "Lunes a sábado",
}

# --- Mercado Pago ------------------------------------------------------------
# Token de PRUEBA (empieza con TEST-). Se obtiene en mercadopago.com/developers.
MP_ACCESS_TOKEN = os.getenv("MP_ACCESS_TOKEN", "")
MP_PUBLIC_KEY = os.getenv("MP_PUBLIC_KEY", "")
# App de Mercado Pago de Operon ("Operon Tiendas") para el botón "Conectar Mercado
# Pago" del panel (OAuth). Con esto la dueña conecta su cuenta y los cobros le
# entran directo a ella; MP_ACCESS_TOKEN/MP_PUBLIC_KEY quedan solo para desarrollo.
MP_CLIENT_ID = os.getenv("MP_CLIENT_ID", "")
MP_CLIENT_SECRET = os.getenv("MP_CLIENT_SECRET", "")
MP_WEBHOOK_SECRET = os.getenv("MP_WEBHOOK_SECRET", "")

# --- Editor de fotos con IA (Gemini) -------------------------------------------
# Nano Banana Pro para fidelidad de la prenda; si falla o tarda, el respaldo.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODELO = os.getenv("GEMINI_MODELO", "gemini-3-pro-image")
GEMINI_MODELO_RESPALDO = os.getenv("GEMINI_MODELO_RESPALDO", "gemini-nano-banana-2.1")
GEMINI_MODELO_TEXTO = os.getenv("GEMINI_MODELO_TEXTO", "gemini-flash-latest")  # descripciones
GEMINI_MODELO_TEXTO_RESPALDO = os.getenv("GEMINI_MODELO_TEXTO_RESPALDO", "gemini-2.5-flash")
GEMINI_PLAZO = float(os.getenv("GEMINI_PLAZO", "280"))  # segundos; debajo del límite de la función
# Dirección pública canónica (https://chao-ecommerce.vercel.app). La URL de vuelta
# del botón de MP tiene que ser EXACTAMENTE la registrada en la app, aunque se
# entre por otro dominio de Vercel. Vacío = se arma con el dominio del request.
SITIO_URL = os.getenv("SITIO_URL", "").rstrip("/")
