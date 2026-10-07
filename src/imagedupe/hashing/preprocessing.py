from __future__ import annotations

import io
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageOps, UnidentifiedImageError

from imagedupe.api.errors import ImageDupeError

ALLOWED = {"JPEG", "PNG", "WEBP"}
FORMATS = ["JPEG", "PNG", "WEBP"]


@dataclass(slots=True)
class Decoded:
    image: Image.Image
    width: int
    height: int
    format: str
    animation_ignored: bool


def _decode(source: BinaryIO | Path, spec, max_pixels: int, untrusted: bool) -> Decoded:
    try:
        with warnings.catch_warnings():
            if untrusted:
                warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source, formats=FORMATS) as src:
                fmt = (src.format or "").upper()
                if fmt not in ALLOWED:
                    raise ImageDupeError(
                        "UNSUPPORTED_IMAGE_FORMAT",
                        f"Decoded format {fmt or 'unknown'} is not allowed",
                        415,
                        "Unsupported image",
                    )
                width, height = src.size
                if width <= 0 or height <= 0 or width * height > max_pixels:
                    raise ImageDupeError(
                        "IMAGE_TOO_LARGE",
                        f"Decoded image has {width * height:,} pixels; limit {max_pixels:,}",
                        422,
                        "Image too large",
                    )
                animation_ignored = bool(getattr(src, "is_animated", False))
                if animation_ignored:
                    src.seek(0)
                image = ImageOps.exif_transpose(src.copy())
                if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                    rgba = image.convert("RGBA")
                    background = Image.new(
                        "RGBA", rgba.size, (*spec.alpha_background, 255)
                    )
                    image = Image.alpha_composite(background, rgba).convert("RGB")
                image = image.convert("L")
                image.load()
                width, height = image.size
                return Decoded(
                    image=image,
                    width=width,
                    height=height,
                    format=fmt.lower(),
                    animation_ignored=animation_ignored,
                )
    except ImageDupeError:
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ImageDupeError(
            "IMAGE_TOO_LARGE",
            "Image exceeds safe decoded-pixel limits",
            422,
            "Image too large",
        ) from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageDupeError(
            "IMAGE_DECODE_FAILED",
            "Malformed, truncated, or unsupported image",
            422,
            "Image decode failed",
        ) from exc


def decode_bytes(data: bytes, spec, max_pixels: int, untrusted: bool = True) -> Decoded:
    return _decode(io.BytesIO(data), spec, max_pixels, untrusted)


def decode_path(path: Path, spec, max_pixels: int) -> Decoded:
    return _decode(Path(path), spec, max_pixels, False)
