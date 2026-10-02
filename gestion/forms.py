"""
Formularios del panel de la dueña.

Se renderizan a mano en los templates (no con {{ form }}) para que el panel tenga
el mismo lenguaje visual que la tienda; acá solo vive la validación.
"""

from django import forms
from django.utils.text import slugify

from catalogo.models import Categoria, Look, Portada, Producto


class ProductoForm(forms.ModelForm):
    # Para no obligar a ir a otra pantalla cuando llega una categoría nueva
    # (por ejemplo "Vestidos"): se escribe acá y se crea al guardar.
    nueva_categoria = forms.CharField(max_length=60, required=False)

    class Meta:
        model = Producto
        fields = [
            "nombre",
            "categoria",
            "descripcion",
            "precio",
            "precio_anterior",
            "precio_a_confirmar",
            "etiqueta",
            "activo",
            "destacado",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categoria"].required = False
        self.fields["categoria"].queryset = Categoria.objects.all()

    def clean(self):
        datos = super().clean()
        datos["nueva_categoria"] = (datos.get("nueva_categoria") or "").strip()
        # La categoría nueva se crea recién en save(): si el formulario tiene otro
        # error, no queda una categoría huérfana en la base.
        if not datos.get("categoria") and not datos["nueva_categoria"]:
            self.add_error("categoria", "Elegí una categoría o escribí una nueva.")

        precio = datos.get("precio")
        anterior = datos.get("precio_anterior")
        if precio is not None and anterior is not None and anterior <= precio:
            self.add_error(
                "precio_anterior",
                "Para que se vea como oferta, el precio anterior tiene que ser mayor que el actual.",
            )
        return datos

    def save(self, commit=True):
        prenda = super().save(commit=False)
        nueva = self.cleaned_data["nueva_categoria"]
        if nueva:
            prenda.categoria, _ = Categoria.objects.get_or_create(
                nombre=nueva, defaults={"orden": Categoria.objects.count() + 1}
            )
        if not prenda.pk:
            # El slug es único: dos prendas con el mismo nombre no pueden pisarse.
            base = slugify(prenda.nombre)[:130] or "prenda"
            slug, n = base, 2
            while Producto.objects.filter(slug=slug).exists():
                slug = f"{base}-{n}"
                n += 1
            prenda.slug = slug
        if commit:
            prenda.save()
        return prenda


class PortadaForm(forms.ModelForm):
    class Meta:
        model = Portada
        fields = ["temporada", "frase", "bajada_coleccion", "foto_hero"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["foto_hero"].queryset = Look.objects.filter(activo=True)
        self.fields["foto_hero"].required = False
