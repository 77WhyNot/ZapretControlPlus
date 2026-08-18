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

TOP = (28, 12, 24)
BOTTOM = (150, 18, 55)


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

    # Мягкое световое пятно за щитом.
    glow = Image.new("L", BANNER_SIZE, 0)
    ImageDraw.Draw(glow).ellipse(
        (width * 0.05, height * 0.16, width * 0.95, height * 0.52), fill=90
    )
    glow = glow.filter(ImageFilter.GaussianBlur(width * 0.12))
    canvas = Image.alpha_composite(
        canvas,
        Image.composite(
            Image.new("RGBA", BANNER_SIZE, (255, 120, 150, 255)),
            Image.new("RGBA", BANNER_SIZE, (0, 0, 0, 0)),
            glow,
        ),
    )

    shield = build_icon().resize(
        (int(width * 0.62), int(width * 0.62)), Image.Resampling.LANCZOS
    )
    canvas.alpha_composite(
        shield,
        (int((width - shield.width) / 2), int(height * 0.20)),
    )

    # Тонкая диагональная штриховка снизу — немного «продукта».
    stripes = Image.new("L", BANNER_SIZE, 0)
    draw = ImageDraw.Draw(stripes)
    for offset in range(-height, width, 26):
        draw.line(
            [(offset, height), (offset + height, 0)], fill=16, width=7
        )
    canvas = Image.alpha_composite(
        canvas,
        Image.composite(
            Image.new("RGBA", BANNER_SIZE, (255, 255, 255, 255)),
            Image.new("RGBA", BANNER_SIZE, (0, 0, 0, 0)),
            stripes,
        ),
    )
    return canvas.convert("RGB")


def make_small() -> Image.Image:
    canvas = Image.new("RGB", SMALL_SIZE, (255, 255, 255))
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
