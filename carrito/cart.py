"""
Carrito guardado en la sesión.

Vive en la sesión y no en la base a propósito: una visitante que mira prendas no
debería generar filas en una tabla. Solo cuando confirma el pedido se escribe algo
(ver app `pedidos`).

La clave de cada línea es "<producto_id>:<talle_id>" (más ":<color_id>" si la prenda
tiene colores). Ese detalle importa: el mismo sweater en M y en L, o en bordó y en
crudo, son líneas distintas, con su propio stock y su propia cantidad.
"""

from __future__ import annotations

from decimal import Decimal

from catalogo.models import ColorPrenda, Producto, Talle

SESION_KEY = "carrito"


def _clave(producto_id: int, talle_id: int | None, color_id: int | None = None) -> str:
    base = f"{producto_id}:{talle_id or 0}"
    # Sin color, la clave queda como antes: los carritos ya abiertos siguen andando.
    return f"{base}:{color_id}" if color_id else base


class Cart:
    def __init__(self, request):
        self.session = request.session
        # .get y no .setdefault: setdefault marca la sesión como modificada y Django
        # guardaba una sesión nueva (una fila en la base) por cada visitante o bot
        # que abría cualquier página, aunque nunca tocara el carrito.
        self.items: dict[str, dict] = self.session.get(SESION_KEY, {})

    # -- Escritura -----------------------------------------------------------
    def guardar(self):
        self.session[SESION_KEY] = self.items
        self.session.modified = True

    def agregar(
        self, producto: Producto, talle: Talle | None = None, cantidad: int = 1, color: ColorPrenda | None = None
    ) -> None:
        clave = _clave(producto.pk, talle.pk if talle else None, color.pk if color else None)
        linea = self.items.get(clave)
        if linea:
            linea["cantidad"] += cantidad
        else:
            self.items[clave] = {
                "producto_id": producto.pk,
                "talle_id": talle.pk if talle else None,
                "color_id": color.pk if color else None,
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
            producto_id=linea["producto_id"], talle_id=linea["talle_id"], color_id=linea.get("color_id")
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
        ids_color = [l.get("color_id") for l in self.items.values() if l.get("color_id")]
        colores = {c.pk: c for c in ColorPrenda.objects.filter(pk__in=ids_color)}

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
                "color": colores.get(linea.get("color_id")),
                # La foto del color elegido, si tiene; si no, la principal.
                "foto": next(
                    (f for f in producto.imagenes.all() if linea.get("color_id") and f.color_id == linea.get("color_id")),
                    producto.foto_principal,
                ),
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
