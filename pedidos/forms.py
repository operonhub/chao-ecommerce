"""
Formulario del checkout: datos de contacto, entrega (retiro o una zona de envío),
dirección cuando hace falta y medio de pago.

La regla que más importa: el servidor decide qué se puede elegir. Aunque alguien
manipule el HTML, una zona apagada, un medio de pago desactivado o "efectivo" con
envío no pasan la validación.
"""

import re

from django import forms

from .models import Cobros, Pedido, ZonaEnvio

PROVINCIAS = [
    "Buenos Aires", "Ciudad Autónoma de Buenos Aires", "Catamarca", "Chaco", "Chubut",
    "Córdoba", "Corrientes", "Entre Ríos", "Formosa", "Jujuy", "La Pampa", "La Rioja",
    "Mendoza", "Misiones", "Neuquén", "Río Negro", "Salta", "San Juan", "San Luis",
    "Santa Cruz", "Santa Fe", "Santiago del Estero", "Tierra del Fuego", "Tucumán",
]

CP_VALIDO = re.compile(r"^(\d{4}|[A-Za-z]\d{4}[A-Za-z]{3})$")
OBLIGATORIOS_ENVIO = ("calle", "numero", "codigo_postal", "localidad", "provincia")


class CheckoutForm(forms.Form):
    nombre = forms.CharField(max_length=120)
    telefono = forms.CharField(max_length=40)
    email = forms.EmailField()
    dni = forms.CharField(max_length=12, required=False)

    # "retiro" o "zona-<id>": un solo grupo de opciones en pantalla.
    entrega = forms.CharField(max_length=20)

    calle = forms.CharField(max_length=120, required=False)
    numero = forms.CharField(max_length=12, required=False)
    piso_depto = forms.CharField(max_length=30, required=False)
    entre_calles = forms.CharField(max_length=120, required=False)
    codigo_postal = forms.CharField(max_length=10, required=False)
    localidad = forms.CharField(max_length=80, required=False)
    provincia = forms.ChoiceField(choices=[("", "Elegí")] + [(p, p) for p in PROVINCIAS], required=False)
    indicaciones = forms.CharField(max_length=200, required=False)

    metodo_pago = forms.ChoiceField(choices=Pedido.Metodo.choices)
    notas = forms.CharField(max_length=600, required=False, widget=forms.Textarea)

    def __init__(self, *args, mp_disponible=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.cobros = Cobros.actual()
        self.zonas = list(ZonaEnvio.objects.filter(activa=True))
        self.mp_disponible = mp_disponible and self.cobros.acepta_mercadopago
        self.zona = None

    def metodos_disponibles(self) -> list[str]:
        metodos = []
        if self.mp_disponible:
            metodos.append(Pedido.Metodo.MERCADOPAGO)
        if self.cobros.transferencia_lista:
            metodos.append(Pedido.Metodo.TRANSFERENCIA)
        if self.cobros.acepta_efectivo:
            metodos.append(Pedido.Metodo.EFECTIVO)
        return metodos

    def clean_telefono(self):
        telefono = self.cleaned_data["telefono"].strip()
        if len(re.sub(r"\D", "", telefono)) < 8:
            raise forms.ValidationError("Revisá el teléfono: lo usamos para coordinar por WhatsApp.")
        return telefono

    def clean_entrega(self):
        valor = self.cleaned_data["entrega"]
        if valor == "retiro":
            return valor
        if valor.startswith("zona-"):
            self.zona = next((z for z in self.zonas if f"zona-{z.pk}" == valor), None)
            if self.zona:
                return valor
        raise forms.ValidationError("Elegí cómo querés recibir tu pedido.")

    def clean_codigo_postal(self):
        cp = self.cleaned_data["codigo_postal"].strip().upper()
        if cp and not CP_VALIDO.match(cp):
            raise forms.ValidationError("El código postal son 4 números (por ejemplo 1682).")
        return cp

    def clean(self):
        datos = super().clean()
        if self.zona:
            for campo in OBLIGATORIOS_ENVIO:
                if not (datos.get(campo) or "").strip():
                    self.add_error(campo, "Lo necesitamos para el envío.")

        metodo = datos.get("metodo_pago")
        if metodo and metodo not in self.metodos_disponibles():
            self.add_error("metodo_pago", "Ese medio de pago no está disponible.")
        elif metodo == Pedido.Metodo.EFECTIVO and self.zona:
            self.add_error("metodo_pago", "El efectivo es solo para retirar en el local.")
        return datos
