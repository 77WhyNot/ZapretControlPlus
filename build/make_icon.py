"""Генерация иконки приложения: бирюзовый щит с рельсами маршрутов.

Запуск: python build/make_icon.py
Результат: app/resources/icon.ico (+ icon.png для README и страницы GitHub).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
RUBY_LIGHT = (52, 214, 230)
RUBY_DARK = (14, 124, 140)
OUTPUT_SIZES = (16, 20, 24, 32, 48, 64, 128, 256)

ROOT = Path(__file__).resolve().parents[1]
TARGET_DIR = ROOT / "app" / "resources"


def quad(p0, p1, p2, steps: int = 60):
    """Точки квадратичной кривой Безье."""
    points = []
    for index in range(steps + 1):
        t = index / steps
        inv = 1 - t
        x = inv * inv * p0[0] + 2 * inv * t * p1[0] + t * t * p2[0]
        y = inv * inv * p0[1] + 2 * inv * t * p1[1] + t * t * p2[1]
        points.append((x, y))
    return points


def shield_polygon(scale: int) -> list[tuple[float, float]]:
    def point(x: float, y: float) -> tuple[float, float]:
        return x * scale, y * scale

    outline: list[tuple[float, float]] = []
    outline += quad(point(0.13, 0.22), point(0.50, 0.11), point(0.87, 0.22))
    outline.append(point(0.87, 0.49))
    outline += quad(point(0.87, 0.49), point(0.85, 0.79), point(0.50, 0.94))
    outline += quad(point(0.50, 0.94), point(0.15, 0.79), point(0.13, 0.49))
    return outline


def vertical_gradient(size: int, top: tuple[int, int, int],
                      bottom: tuple[int, int, int]) -> Image.Image:
    gradient = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(size - 1, 1)
        gradient.putpixel((0, y), tuple(
            round(top[i] + (bottom[i] - top[i]) * t) for i in range(3)
        ))
    return gradient.resize((size, size), Image.Resampling.BICUBIC)


def build_icon() -> Image.Image:
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))

    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).polygon(shield_polygon(SIZE), fill=255)

    body = vertical_gradient(SIZE, RUBY_LIGHT, RUBY_DARK).convert("RGBA")
    canvas.paste(body, (0, 0), mask)

    # Мягкий блик по верхней части щита — даёт объём.
    gloss = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(gloss).polygon(
        [(x, y) for x, y in shield_polygon(SIZE) if y < SIZE * 0.52]
        + [(SIZE * 0.87, SIZE * 0.49), (SIZE * 0.13, SIZE * 0.49)],
        fill=46,
    )
    gloss = gloss.filter(ImageFilter.GaussianBlur(SIZE * 0.02))
    highlight = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 255))
    combined = Image.new("L", (SIZE, SIZE), 0)
    combined.paste(gloss, (0, 0), mask)
    canvas = Image.alpha_composite(canvas, Image.composite(
        highlight, Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0)), combined
    ))

    # Три рельса — те же три пути трафика, что и на главном экране.
    draw = ImageDraw.Draw(canvas)
    thickness = int(SIZE * 0.052)
    radius = thickness // 2
    for index, (left, right, y) in enumerate((
        (0.30, 0.70, 0.395),
        (0.30, 0.62, 0.505),
        (0.30, 0.70, 0.615),
    )):
        x0, x1 = SIZE * left, SIZE * right
        cy = SIZE * y
        draw.line([(x0, cy), (x1, cy)], fill=(255, 255, 255, 255), width=thickness)
        for x in (x0, x1):
            draw.ellipse(
                (x - radius, cy - radius, x + radius, cy + radius),
                fill=(255, 255, 255, 255),
            )
        # Средний путь короче — на нём «ярлык» программы.
        if index == 1:
            dot = SIZE * 0.70
            r = thickness * 0.62
            draw.ellipse((dot - r, cy - r, dot + r, cy + r),
                         fill=(255, 255, 255, 255))
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
