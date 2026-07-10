"""Image preprocessing before vision calls.

Two reasons this exists, both from the brief:
  - Speed (Sarah's 5-second target): Claude downscales anything past ~1568px
    on the long edge anyway, so sending more pixels only adds upload time and
    image tokens. Resizing client-side keeps latency and cost down.
  - Reliability (Jenny's phone photos): the API rejects images over ~5 MB.
    A raw phone photo fails outright without this step.

If Pillow can't parse the bytes we return them untouched and let the API
report the real error.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image

# Claude's effective max resolution — larger images are server-downscaled.
MAX_EDGE = 1568
# Stay comfortably under the API's 5 MB image limit.
MAX_BYTES = 4_500_000

JPEG_QUALITY = 90


def prepare_image(image_bytes: bytes, media_type: str) -> tuple[bytes, str]:
    """Downscale/re-encode an image if it's oversized. Returns (bytes, media_type).

    No-op for images that are already within both limits.
    """
    try:
        img = Image.open(BytesIO(image_bytes))
        img.load()
    except Exception:  # noqa: BLE001 — not an image we can parse; send as-is
        return image_bytes, media_type

    needs_resize = max(img.size) > MAX_EDGE
    if not needs_resize and len(image_bytes) <= MAX_BYTES:
        return image_bytes, media_type

    if needs_resize:
        img.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)

    # JPEG needs no alpha channel; labels are photos/artwork, so JPEG is fine.
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    buf = BytesIO()
    img.save(buf, "JPEG", quality=JPEG_QUALITY)
    out = buf.getvalue()

    # Pathological case: re-encode grew a small file — keep the original.
    if not needs_resize and len(out) >= len(image_bytes):
        return image_bytes, media_type
    return out, "image/jpeg"
