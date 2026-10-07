from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.fftpack import dct

from imagedupe.hashing.base import get_spec
from imagedupe.hashing.preprocessing import decode_bytes, decode_path


def compute_phash(image: Image.Image, spec) -> bytes:
    size = spec.hash_size * spec.highfreq_factor
    pixels = np.asarray(
        image.convert("L").resize((size, size), Image.Resampling.LANCZOS),
        dtype=np.float64,
    )
    coeff = dct(dct(pixels, axis=0), axis=1)
    low = coeff[: spec.hash_size, : spec.hash_size]
    bits = low > np.median(low)
    return np.packbits(bits.reshape(-1), bitorder="big").astype(
        np.uint8, copy=False
    ).tobytes()


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_bytes(
    data: bytes, spec_id: str, max_pixels: int, untrusted: bool = True
) -> tuple[bytes, dict]:
    spec = get_spec(spec_id)
    decoded = decode_bytes(data, spec, max_pixels, untrusted)
    fingerprint = compute_phash(decoded.image, spec)
    return fingerprint, {
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": decoded.width,
        "height": decoded.height,
        "format": decoded.format,
        "animation_ignored": decoded.animation_ignored,
        "bytes": len(data),
    }


def fingerprint_path(
    path: Path, spec_id: str, max_pixels: int, sha256: str | None = None
) -> tuple[bytes, dict]:
    spec = get_spec(spec_id)
    decoded = decode_path(path, spec, max_pixels)
    stat = Path(path).stat()
    fingerprint = compute_phash(decoded.image, spec)
    return fingerprint, {
        "sha256": sha256 or sha256_path(path),
        "width": decoded.width,
        "height": decoded.height,
        "format": decoded.format,
        "animation_ignored": decoded.animation_ignored,
        "bytes": stat.st_size,
    }


def encode_hash(fingerprint: bytes, spec) -> str:
    return f"phash:{spec.bits}:{fingerprint.hex()}"


def parse_hash(text: str, spec) -> bytes:
    value = text.strip().lower()
    if value.startswith("phash:"):
        parts = value.split(":", 2)
        if len(parts) != 3 or not parts[1].isdigit():
            raise ValueError("invalid hash format")
        if int(parts[1]) != spec.bits:
            raise ValueError("fingerprint spec mismatch")
        value = parts[2]
    if len(value) != spec.byte_length * 2:
        raise ValueError("invalid hash length")
    try:
        return bytes.fromhex(value)
    except ValueError as exc:
        raise ValueError("invalid hash format") from exc
