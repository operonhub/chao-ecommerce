"""
Crea (o actualiza) la usuaria del panel a partir de variables de entorno.

    GESTION_USUARIO=...  GESTION_CLAVE=...  [GESTION_NOMBRE=...]

Así la contraseña nunca queda escrita en el repo ni en la base que viaja con el
deploy: vive en el .env local o en las variables del hosting. Es idempotente;
correrlo de nuevo con otra clave la cambia.
"""

import hashlib
import hmac
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import make_password
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Crea o actualiza la usuaria de /gestion/ desde GESTION_USUARIO y GESTION_CLAVE."

    def handle(self, *args, **options):
        usuario = (os.getenv("GESTION_USUARIO") or "").strip()
        clave = os.getenv("GESTION_CLAVE") or ""
        if not usuario or not clave:
            self.stdout.write("Faltan GESTION_USUARIO o GESTION_CLAVE: no se tocó ninguna usuaria.")
            return

        User = get_user_model()
        persona, creada = User.objects.get_or_create(username=usuario)
        persona.is_active = True
        persona.is_staff = True
        # Superusuaria para que también pueda entrar al panel avanzado (/panel/).
        persona.is_superuser = True
        nombre = (os.getenv("GESTION_NOMBRE") or "").strip()
        if nombre:
            persona.first_name = nombre
        # Salt derivado (no al azar): en Vercel cada instancia recrea la usuaria
        # en su propia SQLite, y con salt al azar cada una tendría un hash
        # distinto. Django firma la sesión con ese hash, así que la sesión de una
        # instancia no valía en la otra y el panel pedía login a cada rato.
        salt = hmac.new(
            settings.SECRET_KEY.encode(), f"gestion:{usuario}".encode(), hashlib.sha256
        ).hexdigest()[:24]
        persona.password = make_password(clave, salt=salt)
        persona.save()
        self.stdout.write(f"Usuaria «{usuario}» {'creada' if creada else 'actualizada'}.")
