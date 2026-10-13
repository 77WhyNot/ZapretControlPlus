"""Генерация иконки ZapretCtrl: росток тушью на бумажной плитке с глиняной точкой.

Запуск: python build/make_icon.py
Результат: app/resources/icon.ico (+ icon.png для README и страницы GitHub).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
OUTPUT_SIZES = (16, 20, 24, 32, 48, 64, 128, 256)

PAPER = (250, 249, 245)
RING = (227, 218, 204)
INK = (20, 20, 19)
OLIVE = (120, 140, 93)
CLAY = (217, 119, 87)

ROOT = Path(__file__).resolve().parents[1]
TARGET_DIR = ROOT / "app" / "resources"


def cubic(p0, p1, p2, p3, steps: int = 48):
    """Точки кубической кривой Безье."""
    points = []
    for index in range(steps + 1):
        t = index / steps
        inv = 1 - t
        x = (inv ** 3 * p0[0] + 3 * inv * inv * t * p1[0]
             + 3 * inv * t * t * p2[0] + t ** 3 * p3[0])
        y = (inv ** 3 * p0[1] + 3 * inv * inv * t * p1[1]
             + 3 * inv * t * t * p2[1] + t ** 3 * p3[1])
        points.append((x, y))
    return points


def build_icon() -> Image.Image:
    """Тот же знак, что в заголовке окна: росток из сетки 20×20 и точка."""
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    # Плитка: бумага с тонким кольцом и мягкой тенью.
    shadow = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(shadow).rounded_rectangle(
        (SIZE * 0.06, SIZE * 0.08, SIZE * 0.94, SIZE * 0.96), radius=SIZE * 0.22, fill=90)
    shadow = shadow.filter(ImageFilter.GaussianBlur(SIZE * 0.025))
    canvas.paste((20, 20, 19, 255), (0, 0), shadow.point(lambda v: v // 3))
    tile = ImageDraw.Draw(canvas)
    tile.rounded_rectangle((SIZE * 0.06, SIZE * 0.05, SIZE * 0.94, SIZE * 0.93),
                           radius=SIZE * 0.22, fill=PAPER + (255,),
                           outline=RING + (255,), width=int(SIZE * 0.012))

    # Росток: 20×20 → плитка с полями.
    scale = SIZE * 0.86 / 20
    ox, oy = SIZE * 0.07, SIZE * 0.04

    def p(x: float, y: float) -> tuple[float, float]:
        return ox + x * scale, oy + y * scale

    left_leaf = cubic(p(10, 11), p(6, 11), p(4, 8), p(4, 5)) + \
        cubic(p(4, 5), p(8, 5), p(10, 7), p(10, 11))
    right_leaf = cubic(p(10, 9), p(10, 6), p(12, 4), p(16, 4)) + \
        cubic(p(16, 4), p(16, 7), p(14, 9), p(10, 9))
    draw = ImageDraw.Draw(canvas)
    draw.polygon(left_leaf, fill=OLIVE + (255,))
    draw.polygon(right_leaf, fill=OLIVE + (255,))

    width = int(SIZE * 0.05)

    def stroke(points) -> None:
        # Круг в каждой точке — круглые стыки без «заусенцев» на изгибах.
        radius = width / 2
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            draw.line([(x0, y0), (x1, y1)], fill=INK + (255,), width=width)
        for x, y in points:
            draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=INK + (255,))

    stroke([p(10, 18), p(10, 9)])
    stroke(left_leaf)
    stroke(right_leaf)

    cx, cy = p(16, 4)
    r = 2.3 * scale
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=CLAY + (255,))
    return canvas


def main() -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    icon = build_icon()

    png_path = TARGET_DIR / "icon.png"
    icon.resize((512, 512), Image.Resampling.LANCZOS).save(png_path)

    ico_path = TARGET_DIR / "icon.ico"
    frames = [
        icon.resize((size, size), Image.Resampling.LANCZOS) for size in OUTPUT_SIZES
    ]
    frames[-1].save(
        ico_path, format="ICO",
        sizes=[(size, size) for size in OUTPUT_SIZES],
        append_images=frames[:-1],
    )
    print(f"Готово: {ico_path} и {png_path}")


if __name__ == "__main__":
    main()
