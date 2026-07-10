"""Generate synthetic TTB label images for testing and demos.

Run this once (locally) to (re)create the PNGs in this folder. The committed
PNGs are what the deployed app serves, so it needs no fonts at runtime.

The five labels deliberately cover every verification path:
  1. old_tom_bourbon.png   -> clean, everything matches            -> APPROVED
  2. stones_throw_gin.png   -> "STONE'S THROW" vs app "Stone's Throw" -> APPROVED (fuzzy)
  3. title_case_warning.png -> "Government Warning:" not all-caps    -> REJECTED
  4. wrong_abv.png          -> label 40% vs application 45%          -> REJECTED
  5. missing_warning.png    -> no government warning at all          -> REJECTED

Usage:  python samples/generate_samples.py
"""
from __future__ import annotations

import os
import textwrap

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))

W, H = 600, 800
CREAM = (247, 244, 236)
INK = (33, 30, 28)
RULE = (150, 120, 70)

GOOD_WARNING = (
    "GOVERNMENT WARNING: (1) According to the Surgeon General, women should not "
    "drink alcoholic beverages during pregnancy because of the risk of birth "
    "defects. (2) Consumption of alcoholic beverages impairs your ability to "
    "drive a car or operate machinery, and may cause health problems."
)


def _font(size: int, bold: bool = False):
    """Best-effort TrueType lookup with a graceful fallback to PIL's default."""
    candidates = (
        ["arialbd.ttf", "Arial Bold.ttf", "DejaVuSans-Bold.ttf"]
        if bold
        else ["arial.ttf", "Arial.ttf", "DejaVuSans.ttf"]
    )
    search_dirs = [
        "",
        "C:\\Windows\\Fonts",
        "/usr/share/fonts/truetype/dejavu",
        "/Library/Fonts",
        "/System/Library/Fonts/Supplemental",
    ]
    for name in candidates:
        for d in search_dirs:
            try:
                return ImageFont.truetype(os.path.join(d, name) if d else name, size)
            except Exception:  # noqa: BLE001
                continue
    return ImageFont.load_default()


def _centered(draw, y, text, font, fill=INK):
    w = draw.textlength(text, font=font)
    draw.text(((W - w) / 2, y), text, font=font, fill=fill)


def _wrapped(draw, y, text, font, x=40, width=520, line_h=18, fill=INK):
    # Rough char-per-line estimate from the average glyph width.
    avg = max(1, int(draw.textlength("m", font=font)))
    chars = max(20, int(width / avg))
    for line in textwrap.wrap(text, width=chars):
        draw.text((x, y), line, font=font, fill=fill)
        y += line_h
    return y


def render(
    path: str,
    *,
    brand: str,
    class_type: str,
    abv: str,
    net: str,
    producer: str,
    warning: str | None,
    warning_heading: str = "GOVERNMENT WARNING:",
):
    img = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(img)

    # Border
    d.rectangle([15, 15, W - 15, H - 15], outline=RULE, width=3)
    d.rectangle([25, 25, W - 25, H - 25], outline=RULE, width=1)

    _centered(d, 70, "— DISTILLED SPIRITS —", _font(18), fill=RULE)
    _centered(d, 130, brand, _font(40, bold=True))
    _centered(d, 210, class_type, _font(24))

    d.line([120, 280, W - 120, 280], fill=RULE, width=2)

    _centered(d, 320, abv, _font(26, bold=True))
    _centered(d, 370, net, _font(22))
    _centered(d, 430, producer, _font(15), fill=(90, 80, 70))

    d.line([120, 500, W - 120, 500], fill=RULE, width=1)

    if warning:
        # Render the heading and body so capitalization is visually faithful.
        body = warning
        if body.upper().startswith("GOVERNMENT WARNING:"):
            body = body[len("GOVERNMENT WARNING:"):].strip()
        y = 540
        d.text((40, y), warning_heading, font=_font(14, bold=True), fill=INK)
        y += 22
        _wrapped(d, y, body, _font(13), x=40, width=520, line_h=17)

    img.save(path, "PNG")
    print(f"wrote {os.path.relpath(path)}")


def main():
    render(
        os.path.join(HERE, "old_tom_bourbon.png"),
        brand="OLD TOM DISTILLERY",
        class_type="Kentucky Straight Bourbon Whiskey",
        abv="45% Alc./Vol. (90 Proof)",
        net="750 mL",
        producer="Bottled by Old Tom Distillery, Bardstown, KY",
        warning=GOOD_WARNING,
    )
    render(
        os.path.join(HERE, "stones_throw_gin.png"),
        brand="STONE'S THROW",
        class_type="London Dry Gin",
        abv="40% Alc./Vol. (80 Proof)",
        net="750 mL",
        producer="Distilled & Bottled by Stone's Throw Spirits, Portland, OR",
        warning=GOOD_WARNING,
    )
    render(
        os.path.join(HERE, "title_case_warning.png"),
        brand="SILVER CREEK VODKA",
        class_type="Vodka",
        abv="40% Alc./Vol. (80 Proof)",
        net="750 mL",
        producer="Produced by Silver Creek Distilling Co., Austin, TX",
        warning=GOOD_WARNING.replace("GOVERNMENT WARNING:", "Government Warning:"),
        warning_heading="Government Warning:",
    )
    render(
        os.path.join(HERE, "wrong_abv.png"),
        brand="COPPER RIDGE RESERVE",
        class_type="Straight Rye Whiskey",
        abv="40% Alc./Vol. (80 Proof)",
        net="750 mL",
        producer="Bottled by Copper Ridge Distillers, Louisville, KY",
        warning=GOOD_WARNING,
    )
    render(
        os.path.join(HERE, "missing_warning.png"),
        brand="HARBOR LIGHT SPICED RUM",
        class_type="Spiced Rum",
        abv="35% Alc./Vol. (70 Proof)",
        net="750 mL",
        producer="Bottled by Harbor Light Rum Co., Key West, FL",
        warning=None,
    )


if __name__ == "__main__":
    main()
