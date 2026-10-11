"""
Fotos que sube la dueña → Supabase Storage.

En Vercel el disco es efímero: lo que se guarda en /tmp desaparece en el próximo
arranque en frío. Este backend guarda los archivos en un bucket público de
Supabase (el mismo proyecto que tiene la base) usando su API REST, así que no
hace falta ninguna dependencia nueva más allá de `requests`.

Se activa solo si están SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY (las carga la
integración de Supabase en Vercel). En local, sin esas variables, todo sigue en
la carpeta media/ como siempre.
"""

import mimetypes
import posixpath
import uuid
from urllib.parse import quote

import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.utils.deconstruct import deconstructible

TIMEOUT = 20


@deconstructible
class SupabaseStorage(Storage):
    def __init__(self, bucket=None):
        self.bucket = bucket or settings.SUPABASE_BUCKET
        self.base = settings.SUPABASE_URL.rstrip("/")
        self.clave = settings.SUPABASE_SERVICE_ROLE_KEY

    # --- helpers ------------------------------------------------------------
    def _headers(self, **extra):
        return {"Authorization": f"Bearer {self.clave}", "apikey": self.clave, **extra}

    def _ruta(self, name):
        return quote(name.replace("\\", "/").lstrip("/"))

    def _objeto(self, name):
        return f"{self.base}/storage/v1/object/{self.bucket}/{self._ruta(name)}"

    def asegurar_bucket(self):
        """Crea el bucket público si no existe (idempotente)."""
        r = requests.post(
            f"{self.base}/storage/v1/bucket",
            json={"id": self.bucket, "name": self.bucket, "public": True},
            headers=self._headers(),
            timeout=TIMEOUT,
        )
        if r.status_code not in (200, 201) and "already exists" not in r.text.lower():
            raise RuntimeError(f"No se pudo crear el bucket {self.bucket}: {r.status_code} {r.text}")

    # --- API de Storage -----------------------------------------------------
    def _save(self, name, content):
        content.seek(0)
        tipo = mimetypes.guess_type(name)[0] or "application/octet-stream"
        r = requests.post(
            self._objeto(name),
            data=content.read(),
            headers=self._headers(**{"Content-Type": tipo, "x-upsert": "false",
                                     "Cache-Control": "max-age=31536000"}),
            timeout=TIMEOUT,
        )
        if r.status_code not in (200, 201):
            raise IOError(f"Supabase rechazó {name}: {r.status_code} {r.text}")
        return name

    def _open(self, name, mode="rb"):
        r = requests.get(self.url(name), timeout=TIMEOUT)
        r.raise_for_status()
        return ContentFile(r.content, name=name)

    def delete(self, name):
        if not name:
            return
        requests.delete(
            f"{self.base}/storage/v1/object/{self.bucket}",
            json={"prefixes": [name]},
            headers=self._headers(),
            timeout=TIMEOUT,
        )

    def exists(self, name):
        r = requests.head(self.url(name), timeout=TIMEOUT)
        return r.status_code == 200

    def get_available_name(self, name, max_length=None):
        # Un sufijo al azar en vez de preguntarle a Supabase si el nombre existe:
        # una consulta menos por foto y nunca se pisa una foto vieja.
        carpeta, archivo = posixpath.split(name.replace("\\", "/"))
        raiz, ext = posixpath.splitext(archivo)
        nuevo = posixpath.join(carpeta, f"{raiz[:60]}-{uuid.uuid4().hex[:8]}{ext}")
        return nuevo[:max_length] if max_length else nuevo

    def url(self, name):
        return f"{self.base}/storage/v1/object/public/{self.bucket}/{self._ruta(name)}"

    def size(self, name):
        r = requests.head(self.url(name), timeout=TIMEOUT)
        return int(r.headers.get("Content-Length", 0))
