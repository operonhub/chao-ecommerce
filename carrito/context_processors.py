"""El carrito tiene que estar disponible en el header de todas las páginas."""

from django.urls import reverse

from .cart import Cart


def carrito(request):
    return {
        "carrito": Cart(request),
        # Las rutas se resuelven en Django y viajan al JS por json_script, así no
        # hay URLs escritas a mano en el JavaScript.
        "urls_carrito": {
            "agregar": reverse("carrito:agregar"),
            "actualizar": reverse("carrito:actualizar"),
            "quitar": reverse("carrito:quitar"),
        },
    }
