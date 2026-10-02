"""
Crea (o actualiza) la usuaria del panel a partir de variables de entorno.

    GESTION_USUARIO=...  GESTION_CLAVE=...  [GESTION_NOMBRE=...]

Así la contraseña nunca queda escrita en el repo ni en la base que viaja con el
deploy: vive en el .env local o en las variables del hosting. Es idempotente;
correrlo de nuevo con otra clave la cambia.
"""

import os

from django.contrib.auth import get_user_model
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
        persona.set_password(clave)
        persona.save()
        self.stdout.write(f"Usuaria «{usuario}» {'creada' if creada else 'actualizada'}.")
