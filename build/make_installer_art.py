"""Картинки для мастера установки Inno Setup (BMP, с запасом по разрешению)."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

from make_icon import build_icon  # noqa: E402

TARGET_DIR = ROOT / "build" / "art"

# Inno растягивает картинку под текущий DPI, поэтому берём 3× от базовых
# 164×314 и 55×55.
BANNER_SIZE = (492, 942)
SMALL_SIZE = (165, 165)

# «Пергамент»: бумага сверху, тёплая тарелка снизу.
TOP = (250, 249, 245)
BOTTOM = (227, 218, 204)
INK = (20, 20, 19)
CLAY = (217, 119, 87)
OLIVE = (120, 140, 93)


def gradient(size: tuple[int, int]) -> Image.Image:
    width, height = size
    base = Image.new("RGB", (1, height))
    for y in range(height):
        t = y / max(height - 1, 1)
        base.putpixel((0, y), tuple(
            round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)
        ))
    return base.resize(size, Image.Resampling.BICUBIC)


def make_banner() -> Image.Image:
    canvas = gradient(BANNER_SIZE).convert("RGBA")
    width, height = BANNER_SIZE

    # Солнце-глина за знаком.
    sun = Image.new("L", BANNER_SIZE, 0)
    ImageDraw.Draw(sun).ellipse(
        (width * 0.52, height * 0.12, width * 0.88, height * 0.12 + width * 0.36), fill=255
    )
    sun = sun.filter(ImageFilter.GaussianBlur(2))
    canvas = Image.alpha_composite(canvas, Image.composite(
        Image.new("RGBA", BANNER_SIZE, CLAY + (255,)),
        Image.new("RGBA", BANNER_SIZE, (0, 0, 0, 0)), sun))

    sprout = build_icon().resize(
        (int(width * 0.66), int(width * 0.66)), Image.Resampling.LANCZOS
    )
    canvas.alpha_composite(sprout, (int((width - sprout.width) / 2), int(height * 0.24)))

    # Холм и линия земли тушью — как в саду на главной.
    draw = ImageDraw.Draw(canvas)
    ground = int(height * 0.80)
    draw.rectangle((0, ground, width, height), fill=(195, 204, 176, 255))
    points = [(x, ground + 6 * __import__("math").sin(x / width * 6.0)) for x in range(0, width + 8, 8)]
    draw.line(points, fill=INK + (255,), width=6, joint="curve")
    for x in (width * 0.18, width * 0.74):
        draw.line([(x, ground), (x - 8, ground - 34)], fill=INK + (255,), width=5)
        draw.line([(x + 14, ground), (x + 18, ground - 42)], fill=INK + (255,), width=5)
    return canvas.convert("RGB")


def make_small() -> Image.Image:
    canvas = Image.new("RGB", SMALL_SIZE, TOP)
    shield = build_icon().resize(
        (int(SMALL_SIZE[0] * 0.86), int(SMALL_SIZE[0] * 0.86)),
        Image.Resampling.LANCZOS,
    )
    canvas.paste(
        shield,
        (
            (SMALL_SIZE[0] - shield.width) // 2,
            (SMALL_SIZE[1] - shield.height) // 2,
        ),
        shield,
    )
    return canvas


def main() -> None:
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    banner_path = TARGET_DIR / "wizard-banner.bmp"
    small_path = TARGET_DIR / "wizard-small.bmp"
    make_banner().save(banner_path, format="BMP")
    make_small().save(small_path, format="BMP")
    print(f"Готово: {banner_path.name}, {small_path.name}")


if __name__ == "__main__":
    main()
