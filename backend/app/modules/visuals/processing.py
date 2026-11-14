"""Image validation and web derivatives (Pillow).

* decoded and verified — non-images, truncated files and decompression bombs are rejected;
* the downloaded file is preserved as the source copy;
* derivatives are proportional resizes only (no crops, no colour edits), WebP, with all
  metadata stripped — documentary photos are never altered in meaning.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from typing import Any

from PIL import Image, UnidentifiedImageError

MAX_PIXELS = 40_000_000
WIDTHS = (1600, 800, 400)
ALLOWED_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class ImageRejected(Exception):
    pass


@dataclass(frozen=True)
class Processed:
    mime: str
    width: int
    height: int
    sha256: str
    derivatives: list[tuple[str, bytes, dict[str, Any]]]  # (name, bytes, info)


def inspect(data: bytes) -> tuple[str, int, int]:
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format or ""
            width, height = img.size
            if width * height > MAX_PIXELS:
                raise ImageRejected("image too large")
            img.verify()
    except Image.DecompressionBombError as exc:
        raise ImageRejected("image too large") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ImageRejected("not a valid image") from exc
    if fmt not in ALLOWED_FORMATS:
        raise ImageRejected(f"unsupported image format {fmt or 'unknown'}")
    return ALLOWED_FORMATS[fmt], width, height


def process(data: bytes) -> Processed:
    mime, width, height = inspect(data)
    derivatives: list[tuple[str, bytes, dict[str, Any]]] = []
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        base = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    for target in WIDTHS:
        if target > width and derivatives:
            continue
        w = min(target, width)
        h = max(1, round(height * w / width))
        resized = base.resize((w, h), Image.Resampling.LANCZOS) if w != width else base.copy()
        out = io.BytesIO()
        resized.save(out, "WEBP", quality=82, method=4)  # no exif/icc passed: metadata stripped
        derivatives.append(
            (f"w{w}.webp", out.getvalue(), {"width": w, "height": h, "mime": "image/webp"})
        )
    return Processed(mime, width, height, hashlib.sha256(data).hexdigest(), derivatives)
