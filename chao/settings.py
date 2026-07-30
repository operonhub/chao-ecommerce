"""
Configuración de Django para el ecommerce de CHAO Indumentaria.

Todo lo que cambia entre la máquina de desarrollo y el servidor sale de variables
de entorno (archivo .env en local, panel de Render en producción). Nunca hay una
credencial escrita acá.
"""

from pathlib import Path
import os

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
            ],
        },
    },
]

WSGI_APPLICATION = "chao.wsgi.application"

# En local, SQLite sin configurar nada. En Render, DATABASE_URL apunta a Postgres.
DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

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

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

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
