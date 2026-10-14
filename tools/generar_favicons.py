"""
Genera los favicons en los formatos que lee Google Search.

Por qué existe este script: el favicon era solo un SVG, y Google Search **no
acepta SVG**. Su lista es BMP, GIF, ICO, PNG, JPEG, PPM y TIFF
(developers.google.com/search/docs/appearance/favicon-in-search), así que en los
resultados salía el globo genérico. Los navegadores sí prefieren el SVG, que se
mantiene: se declaran los dos y cada uno toma el que entiende.

El diseño es el mismo del SVG y del avatar de Instagram: "CH" en blanco sobre el
aqua #b1cfd1 del logo. Dice "CH" y no "CHAO" porque a 16px las cuatro letras son
un borrón.

Uso:  .venv\\Scripts\\python.exe tools\\generar_favicons.py
Salida: static/favicon.ico · static/apple-touch-icon.png
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

RAIZ = Path(__file__).resolve().parent.parent
STATIC = RAIZ / "static"

AQUA = (177, 207, 209)  # #b1cfd1, muestreado del avatar de Instagram de CHAO
BLANCO = (255, 255, 255)
TEXTO = "CH"

# Arial Bold: es a lo que caía el SVG por su propio font-family
# ("Archivo, Helvetica, Arial, sans-serif"), así que el dibujo no cambia.
FUENTE = Path("C:/Windows/Fonts/arialbd.ttf")


def dibujar(lado: int) -> Image.Image:
    """Un cuadrado aqua con 'CH' blanco centrado, dibujado a 4x y reducido.

    El supersampling importa: a 32px, dibujar el texto directo deja los bordes
    dentados. Renderizar grande y achicar con LANCZOS los deja suaves.
    """
    escala = 4
    grande = lado * escala
    im = Image.new("RGB", (grande, grande), AQUA)
    d = ImageDraw.Draw(im)

    # El tamaño de fuente se busca para que la "CH" ocupe ~72% del ancho: menos
    # se pierde al achicar, más se come los márgenes.
    objetivo = grande * 0.72
    tam = grande
    while tam > 4:
        fuente = ImageFont.truetype(str(FUENTE), tam)
        if d.textlength(TEXTO, font=fuente) <= objetivo:
            break
        tam -= 1

    # Centrado por la caja real del texto (no por la métrica de la fuente, que
    # incluye el espacio de acentos y descendentes y lo deja alto).
    caja = d.textbbox((0, 0), TEXTO, font=fuente)
    x = (grande - (caja[2] - caja[0])) / 2 - caja[0]
    y = (grande - (caja[3] - caja[1])) / 2 - caja[1]
    d.text((x, y), TEXTO, font=fuente, fill=BLANCO)

    return im.resize((lado, lado), Image.LANCZOS)


def main() -> None:
    (STATIC / "img").mkdir(parents=True, exist_ok=True)

    # El .ico lleva varias resoluciones adentro; cada superficie toma la que le
    # sirve y ninguna tiene que escalar.
    ico = STATIC / "favicon.ico"
    dibujar(256).save(ico, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print(f"OK  favicon.ico            {ico.stat().st_size // 1024} KB  (16 a 256 px)")


    apple = STATIC / "apple-touch-icon.png"
    dibujar(180).save(apple, "PNG", optimize=True)
    print(f"OK  apple-touch-icon.png   {apple.stat().st_size} bytes")


if __name__ == "__main__":
    main()
