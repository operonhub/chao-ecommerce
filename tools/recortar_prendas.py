"""
Recorta cada prenda de las fotos de percha de CHAO para usarlas como foto de producto.

CHAO publica composiciones: varias prendas colgadas juntas en el local. No hay foto
de producto individual, así que la sacamos recortando la región de cada prenda dentro
de la foto original (1440x1920).

Las cajas están en coordenadas de la imagen original y se estimaron mirando cada foto.
El centro de cada caja se reusa como posición del hotspot en el lookbook, así el
marcador y el recorte nunca se desincronizan.

Uso:  .venv\\Scripts\\python.exe tools\\recortar_prendas.py
Salida: static/img/productos/<slug>.jpg  +  tools/hotspots.json
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

RAIZ = Path(__file__).resolve().parent.parent
LOOKS = RAIZ / "static" / "img" / "looks"
PRODUCTOS = RAIZ / "static" / "img" / "productos"

# Relación de aspecto de las cards del catálogo. Los recortes se ajustan a 3:4
# expandiendo la caja (nunca deformando la imagen).
RATIO = 3 / 4

# (slug, x1, y1, x2, y2) sobre la imagen original de 1440x1920.
#
# Las cajas ya vienen en 3:4 para que `ajustar_a_ratio` casi no tenga que corregir:
# cuando la corrección es grande, la caja se corre y termina mostrando la prenda de
# al lado en vez de la propia. Se estimaron con una grilla de coordenadas encima de
# cada foto (tools/ hizo grid-*.jpg durante el desarrollo).
#
# Tres prendas quedaron afuera a propósito — cardigan beige, conjunto de jean celeste
# y buzo estampado están pegadas al borde de la foto y no dan un recorte 3:4 sin
# meter media prenda ajena adentro. Antes que una card rota, no van.
RECORTES: dict[str, list[tuple[str, int, int, int, int]]] = {
    "look-elegancia-simple": [
        ("bolso-tote-gamuza-marron", 80, 480, 540, 1093),
        ("sweater-tejido-crudo", 480, 490, 960, 1130),
        ("pantalon-sastrero-negro", 940, 730, 1200, 1077),
        ("sweater-rombos-marron", 1180, 330, 1440, 677),
    ],
    "look-del-dia": [
        ("sweater-fino-bordo", 500, 490, 1100, 1290),
        ("bandolera-croco-negra", 280, 900, 640, 1380),
        ("panuelo-estampado-rosa", 610, 350, 970, 830),
    ],
    "look-outfit-del-dia": [
        ("sweater-fino-marron", 370, 400, 910, 1120),
        ("panuelo-rayado-beige", 30, 300, 330, 700),
        ("jean-recto-celeste", 1060, 600, 1330, 960),
    ],
    "look-basicos-sweaters": [
        ("sweater-fino-crudo", 690, 430, 1000, 843),
        ("bolso-rafia-natural", 1110, 30, 1440, 470),
    ],
    "look-con-actitud": [
        ("remera-fearless", 270, 280, 810, 1000),
        ("jean-oxford-azul-oscuro", 820, 430, 1120, 830),
    ],
    "look-remera-negra": [
        ("remera-negra-sin-mangas", 300, 280, 840, 1000),
        ("jean-flare-azul", 780, 420, 1120, 873),
        ("rinonera-negra", 10, 250, 400, 770),
        ("pulseras-y-relojes", 150, 1000, 500, 1467),
        ("bolso-tejido-crudo", 1150, 20, 1440, 407),
    ],
}


def ajustar_a_ratio(caja: tuple[int, int, int, int], ancho: int, alto: int) -> tuple[int, int, int, int]:
    """Expande la caja hasta 3:4 sin salirse de la imagen y sin deformar nada."""
    x1, y1, x2, y2 = caja
    w, h = x2 - x1, y2 - y1

    if w / h > RATIO:
        # Demasiado ancha: hay que crecer en alto.
        nuevo_h = round(w / RATIO)
        centro_y = (y1 + y2) / 2
        y1, y2 = round(centro_y - nuevo_h / 2), round(centro_y + nuevo_h / 2)
    else:
        nuevo_w = round(h * RATIO)
        centro_x = (x1 + x2) / 2
        x1, x2 = round(centro_x - nuevo_w / 2), round(centro_x + nuevo_w / 2)

    # Si la expansión se pasó del borde, se corre la caja en vez de recortarla:
    # mantener el ratio importa más que respetar el centro exacto.
    if x1 < 0:
        x2, x1 = x2 - x1, 0
    if y1 < 0:
        y2, y1 = y2 - y1, 0
    if x2 > ancho:
        x1, x2 = max(0, x1 - (x2 - ancho)), ancho
    if y2 > alto:
        y1, y2 = max(0, y1 - (y2 - alto)), alto

    return x1, y1, x2, y2


def main() -> None:
    PRODUCTOS.mkdir(parents=True, exist_ok=True)
    hotspots: dict[str, list[dict]] = {}
    total = 0

    for look_slug, prendas in RECORTES.items():
        origen = LOOKS / f"{look_slug}.jpg"
        if not origen.exists():
            print(f"FALTA  {origen.name} — se saltea")
            continue

        with Image.open(origen) as im:
            im = im.convert("RGB")
            ancho, alto = im.size
            hotspots[look_slug] = []

            for slug, *caja in prendas:
                # El hotspot va en el centro de la caja ORIGINAL (donde está la prenda),
                # no de la ajustada, que puede haberse corrido para respetar el ratio.
                x1, y1, x2, y2 = caja
                hotspots[look_slug].append(
                    {
                        "producto": slug,
                        "x": round((x1 + x2) / 2 / ancho * 100, 2),
                        "y": round((y1 + y2) / 2 / alto * 100, 2),
                    }
                )

                recorte = im.crop(ajustar_a_ratio(tuple(caja), ancho, alto))
                recorte = recorte.resize((900, 1200), Image.LANCZOS)
                destino = PRODUCTOS / f"{slug}.jpg"
                recorte.save(destino, "JPEG", quality=82, optimize=True, progressive=True)
                total += 1
                print(f"OK     {slug}.jpg  ({destino.stat().st_size // 1024} KB)")

    (RAIZ / "tools" / "hotspots.json").write_text(
        json.dumps(hotspots, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\n{total} recortes · hotspots.json actualizado")


if __name__ == "__main__":
    main()
