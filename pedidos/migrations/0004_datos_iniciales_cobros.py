"""
Datos de arranque del checkout nuevo.

- Los pedidos que ya existían reciben su código público y su subtotal (= total,
  porque antes no había envío ni descuento).
- Zonas de envío iniciales SIN precio: no sabemos lo que cobra CHAO, así que
  arrancan "a coordinar" y la dueña carga los montos reales desde el panel.
"""

import secrets

from django.db import migrations

ZONAS = [
    {
        "nombre": "Villa Bosch y alrededores",
        "tipo": "propia",
        "descripcion": "Lo lleva CHAO. Coordinamos el día por WhatsApp.",
        "demora": "Coordinamos el día por WhatsApp",
        "orden": 1,
    },
    {
        "nombre": "AMBA",
        "tipo": "correo",
        "descripcion": "CABA y Gran Buenos Aires, por Correo Argentino.",
        "demora": "3 a 5 días hábiles",
        "orden": 2,
    },
    {
        "nombre": "Resto del país",
        "tipo": "correo",
        "descripcion": "A todo el país por Correo Argentino.",
        "demora": "3 a 5 días hábiles",
        "orden": 3,
    },
]


def adelante(apps, schema_editor):
    Pedido = apps.get_model("pedidos", "Pedido")
    ZonaEnvio = apps.get_model("pedidos", "ZonaEnvio")
    Cobros = apps.get_model("pedidos", "Cobros")

    for pedido in Pedido.objects.filter(codigo__isnull=True):
        pedido.codigo = secrets.token_urlsafe(9)[:12]
        pedido.subtotal = pedido.total
        pedido.save(update_fields=["codigo", "subtotal"])

    if not ZonaEnvio.objects.exists():
        for zona in ZONAS:
            ZonaEnvio.objects.create(**zona)

    Cobros.objects.get_or_create(pk=1)


class Migration(migrations.Migration):
    dependencies = [
        ("pedidos", "0003_entrega_cobros_mercadopago"),
    ]

    operations = [migrations.RunPython(adelante, migrations.RunPython.noop)]
