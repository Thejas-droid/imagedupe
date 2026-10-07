from __future__ import annotations

import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any


def _home() -> Path:
    return Path(
        os.getenv("IMAGEDUPE_HOME", Path.home() / ".local/share/imagedupe")
    ).expanduser().resolve()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


@dataclass(slots=True)
class Settings:
    home: Path = _home()
    host: str = os.getenv("IMAGEDUPE_HOST", "127.0.0.1")
    port: int = int(os.getenv("IMAGEDUPE_PORT", "8765"))
    max_upload_bytes: int = int(
        os.getenv("IMAGEDUPE_MAX_UPLOAD_BYTES", str(20 * 1024 * 1024))
    )
    max_decoded_pixels: int = int(os.getenv("IMAGEDUPE_MAX_DECODED_PIXELS", "50000000"))
    ingest_max_decoded_pixels: int = int(
        os.getenv("IMAGEDUPE_INGEST_MAX_DECODED_PIXELS", "150000000")
    )
    worker_count: int = int(os.getenv("IMAGEDUPE_WORKERS", "0"))
    worker_cap: int = int(os.getenv("IMAGEDUPE_WORKER_CAP", "32"))
    hash_timeout_seconds: int = int(os.getenv("IMAGEDUPE_HASH_TIMEOUT_SECONDS", "120"))
    candidate_multiplier: int = int(os.getenv("IMAGEDUPE_CANDIDATE_MULTIPLIER", "5"))
    max_top_k: int = int(os.getenv("IMAGEDUPE_MAX_TOP_K", "1000"))
    default_top_k: int = int(os.getenv("IMAGEDUPE_DEFAULT_TOP_K", "20"))
    default_fingerprint_spec_id: str = os.getenv(
        "IMAGEDUPE_DEFAULT_FINGERPRINT_SPEC", "phash-v1-256-exif-luma"
    )
    backend_selection: str = os.getenv("IMAGEDUPE_BACKEND", "auto")
    ann_tuning_profile: str = os.getenv("IMAGEDUPE_ANN_PROFILE", "balanced")
    auto_exact_max_buckets: int = int(os.getenv("IMAGEDUPE_AUTO_EXACT_MAX", "10000"))
    thumbnail_size: int = int(os.getenv("IMAGEDUPE_THUMBNAIL_SIZE", "480"))
    thumbnail_cache_enabled: bool = _env_bool("IMAGEDUPE_THUMBNAIL_CACHE", True)
    request_rate_per_minute: int = int(os.getenv("IMAGEDUPE_RATE_LIMIT", "120"))
    query_decode_concurrency: int = int(os.getenv("IMAGEDUPE_QUERY_DECODE_CONCURRENCY", "4"))
    privacy_paths: bool = _env_bool("IMAGEDUPE_PRIVACY_PATHS", True)
    cuda_mode: str = os.getenv("IMAGEDUPE_CUDA_MODE", "Auto")
    logging_verbosity: str = os.getenv("IMAGEDUPE_LOG_LEVEL", "INFO")
    default_collection: str | None = os.getenv("IMAGEDUPE_DEFAULT_COLLECTION")

    def __post_init__(self) -> None:
        self.home = Path(self.home).expanduser().resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.thumb_dir.mkdir(parents=True, exist_ok=True)
        self._validate()

    def _validate(self) -> None:
        if self.max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")
        if self.max_decoded_pixels <= 0 or self.ingest_max_decoded_pixels <= 0:
            raise ValueError("decoded pixel limits must be positive")
        if self.candidate_multiplier < 1:
            raise ValueError("candidate_multiplier must be >= 1")
        if self.max_top_k < 1:
            raise ValueError("max_top_k must be >= 1")
        if self.query_decode_concurrency < 1:
            raise ValueError("query_decode_concurrency must be >= 1")
        if self.cuda_mode not in {"Auto", "Off", "On"}:
            raise ValueError("cuda_mode must be Auto, Off, or On")
        if self.ann_tuning_profile not in {"fast", "balanced", "high-recall"}:
            raise ValueError("ann_tuning_profile must be fast, balanced, or high-recall")

    @property
    def db_path(self) -> Path:
        return self.home / "catalog.sqlite3"

    @property
    def index_dir(self) -> Path:
        return self.home / "indexes"

    @property
    def thumb_dir(self) -> Path:
        return self.home / "thumbnails"

    @property
    def effective_workers(self) -> int:
        if self.worker_count > 0:
            return max(1, min(self.worker_count, self.worker_cap))
        return max(1, min(self.worker_cap, (os.cpu_count() or 1) - 2))

    def public_runtime(self) -> dict[str, Any]:
        return {
            "worker_count": self.effective_workers,
            "worker_count_configured": self.worker_count,
            "max_upload_bytes": self.max_upload_bytes,
            "max_decoded_pixels": self.max_decoded_pixels,
            "ingest_max_decoded_pixels": self.ingest_max_decoded_pixels,
            "hash_timeout_seconds": self.hash_timeout_seconds,
            "candidate_multiplier": self.candidate_multiplier,
            "max_top_k": self.max_top_k,
            "query_decode_concurrency": self.query_decode_concurrency,
            "default_top_k": self.default_top_k,
            "default_fingerprint_spec_id": self.default_fingerprint_spec_id,
            "backend_selection": self.backend_selection,
            "ann_tuning_profile": self.ann_tuning_profile,
            "thumbnail_cache_enabled": self.thumbnail_cache_enabled,
            "privacy_paths": self.privacy_paths,
            "cuda_mode": self.cuda_mode,
            "logging_verbosity": self.logging_verbosity,
            "default_collection": self.default_collection,
            "cache_location": str(self.home),
        }

    def apply_saved(self, saved: dict[str, Any]) -> None:
        mutable = {
            "worker_count",
            "max_upload_bytes",
            "max_decoded_pixels",
            "ingest_max_decoded_pixels",
            "hash_timeout_seconds",
            "candidate_multiplier",
            "max_top_k",
            "query_decode_concurrency",
            "default_top_k",
            "default_fingerprint_spec_id",
            "backend_selection",
            "ann_tuning_profile",
            "thumbnail_cache_enabled",
            "privacy_paths",
            "cuda_mode",
            "logging_verbosity",
            "default_collection",
        }
        available = {f.name for f in fields(self)}
        for key, value in saved.items():
            if key in mutable and key in available:
                setattr(self, key, value)
        self._validate()
