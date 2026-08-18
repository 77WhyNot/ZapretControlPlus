"""Баннер для шапки README и страницы GitHub.

Запуск: python build/make_banner.py
Результат: docs/banner.png
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "build"))

from make_icon import build_icon  # noqa: E402

SIZE = (1280, 420)
TOP = (16, 8, 14)
BOTTOM = (96, 12, 40)
RUBY = (212, 34, 80)

TARGET = ROOT / "docs" / "banner.png"


def _font(names: list[str], size: int) -> ImageFont.FreeTypeFont:
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def gradient(size: tuple[int, int]) -> Image.Image:
    width, height = size
    base = Image.new("RGB", (1, height))
    for y in range(height):
        t = (y / max(height - 1, 1)) ** 0.85
        base.putpixel((0, y), tuple(
            round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)
        ))
    return base.resize(size, Image.Resampling.BICUBIC)


def build() -> Image.Image:
    width, height = SIZE
    canvas = gradient(SIZE).convert("RGBA")

    # Световое пятно за щитом.
    glow = Image.new("L", SIZE, 0)
    ImageDraw.Draw(glow).ellipse(
        (width * 0.02, height * 0.05, width * 0.42, height * 1.05), fill=120
    )
    glow = glow.filter(ImageFilter.GaussianBlur(90))
    canvas = Image.alpha_composite(canvas, Image.composite(
        Image.new("RGBA", SIZE, (*RUBY, 255)),
        Image.new("RGBA", SIZE, (0, 0, 0, 0)),
        glow,
    ))

    # Тонкие диагональные линии — намёк на трафик.
    stripes = Image.new("L", SIZE, 0)
    draw = ImageDraw.Draw(stripes)
    for offset in range(-height, width + height, 46):
        draw.line([(offset, height), (offset + height, 0)], fill=14, width=9)
    canvas = Image.alpha_composite(canvas, Image.composite(
        Image.new("RGBA", SIZE, (255, 255, 255, 255)),
        Image.new("RGBA", SIZE, (0, 0, 0, 0)),
        stripes,
    ))

    shield = build_icon().resize((248, 248), Image.Resampling.LANCZOS)
    canvas.alpha_composite(shield, (92, (height - 248) // 2))

    draw = ImageDraw.Draw(canvas)
    title_font = _font(["bahnschrift.ttf", "segoeuib.ttf", "arialbd.ttf"], 92)
    sub_font = _font(["segoeui.ttf", "arial.ttf"], 32)
    small_font = _font(["consola.ttf", "cour.ttf"], 25)

    left = 392
    draw.text((left, 122), "Zapret Control+", font=title_font, fill=(255, 255, 255))
    draw.text(
        (left, 232),
        "Обход блокировок, VPN и Smart DNS в одном окне",
        font=sub_font, fill=(240, 212, 220),
    )
    draw.text(
        (left, 286),
        "zapret · VPN по приложениям · Telegram · xbox-dns",
        font=small_font, fill=(206, 158, 174),
    )
    return canvas.convert("RGB")


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    build().save(TARGET, quality=95)
    print(f"Готово: {TARGET}")


if __name__ == "__main__":
    main()
