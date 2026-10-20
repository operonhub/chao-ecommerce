from django.apps import AppConfig
from django.db.models.signals import post_migrate


# La base vive en Supabase, que además de la conexión directa (la que usa Django)
# publica cada tabla del esquema `public` en una API REST para los roles `anon` y
# `authenticated`. La tienda no usa esa API, así que se cierra del todo: RLS
# prendido sin políticas (nadie de la API ve filas) y sin permisos para esos
# roles. Django se conecta como `postgres`, dueño de las tablas, que no pasa por
# RLS. Corre en cada `migrate`, así las tablas nuevas también quedan cerradas.
ROLES_API = ("anon", "authenticated")


def cerrar_api_publica(using="default", **kwargs):
    from django.db import connections

    conexion = connections[using]
    if conexion.vendor != "postgresql":
        return
    with conexion.cursor() as c:
        c.execute("select 1 from pg_roles where rolname = any(%s)", [list(ROLES_API)])
        if not c.fetchall():
            return  # Postgres común (sin Supabase): no hay API que cerrar.
        c.execute("select tablename from pg_tables where schemaname = 'public' and not rowsecurity")
        for (tabla,) in c.fetchall():
            c.execute(f'alter table public."{tabla}" enable row level security')
        roles = ", ".join(ROLES_API)
        c.execute(f"revoke all on all tables in schema public from {roles}")
        c.execute(f"revoke all on all sequences in schema public from {roles}")
        c.execute(f"alter default privileges in schema public revoke all on tables from {roles}")
        c.execute(f"alter default privileges in schema public revoke all on sequences from {roles}")


class GestionConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "gestion"
    verbose_name = "Mi tienda (panel de la dueña)"

    def ready(self):
        post_migrate.connect(cerrar_api_publica, sender=self, dispatch_uid="gestion.cerrar_api_publica")
