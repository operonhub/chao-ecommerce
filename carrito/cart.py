"""
Carrito guardado en la sesión.

Vive en la sesión y no en la base a propósito: una visitante que mira prendas no
debería generar filas en una tabla. Solo cuando confirma el pedido se escribe algo
(ver app `pedidos`).

La clave de cada línea es "<producto_id>:<talle_id>". Ese detalle importa: el mismo
sweater en M y en L son dos líneas distintas, con su propio stock y su propia cantidad.
"""

from __future__ import annotations

from decimal import Decimal

from catalogo.models import Producto, Talle

SESION_KEY = "carrito"


def _clave(producto_id: int, talle_id: int | None) -> str:
    return f"{producto_id}:{talle_id or 0}"


class Cart:
    def __init__(self, request):
        self.session = request.session
        self.items: dict[str, dict] = self.session.setdefault(SESION_KEY, {})

    # -- Escritura -----------------------------------------------------------
    def guardar(self):
        self.session[SESION_KEY] = self.items
        self.session.modified = True

    def agregar(self, producto: Producto, talle: Talle | None = None, cantidad: int = 1) -> None:
        clave = _clave(producto.pk, talle.pk if talle else None)
        linea = self.items.get(clave)
        if linea:
            linea["cantidad"] += cantidad
        else:
            self.items[clave] = {
                "producto_id": producto.pk,
                "talle_id": talle.pk if talle else None,
                "cantidad": cantidad,
                # Se guarda el precio del momento para que el total del carrito no
                # cambie solo si la dueña reprecia mientras la clienta está comprando.
                "precio": str(producto.precio),
            }
        self._limitar(clave)
        self.guardar()

    def actualizar(self, clave: str, cantidad: int) -> None:
        if clave not in self.items:
            return
        if cantidad <= 0:
            del self.items[clave]
        else:
            self.items[clave]["cantidad"] = cantidad
            self._limitar(clave)
        self.guardar()

    def quitar(self, clave: str) -> None:
        self.items.pop(clave, None)
        self.guardar()

    def vaciar(self) -> None:
        self.items = {}
        self.guardar()

    def _limitar(self, clave: str) -> None:
        """Nunca dejar en el carrito más unidades de las que hay en stock."""
        linea = self.items.get(clave)
        if not linea:
            return
        disponible = self._stock(linea)
        if disponible is not None:
            linea["cantidad"] = max(1, min(linea["cantidad"], disponible))

    @staticmethod
    def _stock(linea: dict) -> int | None:
        if not linea.get("talle_id"):
            return None
        from catalogo.models import Variante

        variante = Variante.objects.filter(
            producto_id=linea["producto_id"], talle_id=linea["talle_id"]
        ).first()
        return variante.stock if variante else 0

    # -- Lectura -------------------------------------------------------------
    def __iter__(self):
        """Devuelve las líneas ya hidratadas, en dos consultas y no en 2N."""
        productos = {
            p.pk: p
            for p in Producto.objects.filter(pk__in=[l["producto_id"] for l in self.items.values()])
            .select_related("categoria")
            .prefetch_related("imagenes")
        }
        talles = {t.pk: t for t in Talle.objects.filter(pk__in=[l["talle_id"] for l in self.items.values() if l["talle_id"]])}

        for clave, linea in list(self.items.items()):
            producto = productos.get(linea["producto_id"])
            if producto is None:
                # La prenda se borró del catálogo mientras el carrito estaba abierto.
                del self.items[clave]
                self.guardar()
                continue
            precio = Decimal(linea["precio"])
            yield {
                "clave": clave,
                "producto": producto,
                "talle": talles.get(linea["talle_id"]) if linea["talle_id"] else None,
                "cantidad": linea["cantidad"],
                "precio": precio,
                "subtotal": precio * linea["cantidad"],
            }

    def __len__(self):
        return sum(l["cantidad"] for l in self.items.values())

    @property
    def total(self) -> Decimal:
        return sum((Decimal(l["precio"]) * l["cantidad"] for l in self.items.values()), start=Decimal(0))

    @property
    def vacio(self) -> bool:
        return not self.items
