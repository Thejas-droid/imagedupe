from __future__ import annotations

import fnmatch
import multiprocessing
import signal
import uuid
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterator

from imagedupe.hashing.phash import fingerprint_path, sha256_path

SUPPORTED = {".jpg", ".jpeg", ".png", ".webp"}


def _timeout_handler(_signum, _frame):
    raise TimeoutError("HASH_TIMEOUT")


def worker(path: str, spec: str, max_pixels: int, sha256: str, timeout: int) -> dict:
    if timeout > 0 and hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(timeout)
    try:
        file_path = Path(path)
        stat = file_path.stat()
        fingerprint, metadata = fingerprint_path(file_path, spec, max_pixels, sha256)
        return {
            "fingerprint": fingerprint,
            "path": str(file_path),
            "byte_size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
            **metadata,
        }
    finally:
        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)


class CollectionService:
    def __init__(self, catalog, settings):
        self.catalog = catalog
        self.settings = settings

    def create(self, name: str, roots: list[dict], spec: str, backend: str = "auto"):
        if not roots:
            raise ValueError("At least one collection root is required")
        for root in roots:
            path = Path(root["path"]).expanduser()
            if not path.is_dir():
                raise ValueError(f"Collection root is not a directory: {path}")
        return self.catalog.create_collection(name, roots, spec, backend)

    def files(self, root: dict) -> Iterator[tuple[Path, str, str | None]]:
        base = Path(root["path"])
        iterator = base.rglob("*") if root.get("recursive", True) else base.glob("*")
        includes = root.get("include_globs", []) or []
        excludes = root.get("exclude_globs", []) or []
        for path in iterator:
            try:
                if not path.is_file():
                    continue
                if path.is_symlink() and not root.get("follow_symlinks", False):
                    continue
            except OSError:
                continue
            relative = path.relative_to(base).as_posix()
            if includes and not any(fnmatch.fnmatch(relative, pattern) for pattern in includes):
                continue
            if any(fnmatch.fnmatch(relative, pattern) for pattern in excludes):
                continue
            if path.suffix.lower() not in SUPPORTED:
                yield path, relative, "UNSUPPORTED_EXTENSION"
                continue
            yield path.resolve(), relative, None

    def scan(
        self,
        cid: str,
        job_id: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict:
        collection = self.catalog.get_collection(cid)
        if not collection:
            raise KeyError(cid)
        scan_id = str(uuid.uuid4())
        spec = collection["fingerprint_spec_id"]
        stats = {
            "discovered": 0,
            "cached": 0,
            "content_reused": 0,
            "hashed": 0,
            "skipped": 0,
            "failed": 0,
            "missing": 0,
        }
        work: list[tuple[Path, str, object, str]] = []

        for root in collection["roots"]:
            for path, relative, skip_reason in self.files(root):
                if cancel_check and cancel_check():
                    raise RuntimeError("JOB_CANCELLED")
                stats["discovered"] += 1
                if skip_reason:
                    stats["skipped"] += 1
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    stats["failed"] += 1
                    continue
                cached = self.catalog.cached_stat(
                    cid, str(path), stat.st_size, stat.st_mtime_ns, spec
                )
                if cached:
                    self.catalog.touch(cached["id"], scan_id)
                    stats["cached"] += 1
                    continue

                sha256 = sha256_path(path)
                reused = self.catalog.content_cache(cid, sha256, spec)
                if reused:
                    row = {
                        "path": str(path),
                        "relative_path": relative,
                        "filename": path.name,
                        "byte_size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns,
                        "sha256": sha256,
                        "width": reused["width"],
                        "height": reused["height"],
                        "format": reused["format"],
                    }
                    self.catalog.upsert_image_fp(
                        cid, row, spec, bytes(reused["hash_bytes"]), scan_id
                    )
                    stats["content_reused"] += 1
                    continue
                work.append((path, relative, stat, sha256))

        if job_id:
            self.catalog.update_job(job_id, "HASHING", stats)

        if work:
            context = multiprocessing.get_context("spawn")
            with ProcessPoolExecutor(
                max_workers=self.settings.effective_workers, mp_context=context
            ) as pool:
                futures = {
                    pool.submit(
                        worker,
                        str(path),
                        spec,
                        self.settings.ingest_max_decoded_pixels,
                        sha256,
                        self.settings.hash_timeout_seconds,
                    ): (path, relative, stat)
                    for path, relative, stat, sha256 in work
                }
                for future in as_completed(futures):
                    path, relative, stat = futures[future]
                    if cancel_check and cancel_check():
                        for pending in futures:
                            pending.cancel()
                        raise RuntimeError("JOB_CANCELLED")
                    try:
                        row = future.result()
                        fingerprint = row.pop("fingerprint")
                        row["relative_path"] = relative
                        row["filename"] = path.name
                        self.catalog.upsert_image_fp(
                            cid, row, spec, fingerprint, scan_id
                        )
                        stats["hashed"] += 1
                    except Exception as exc:
                        code = getattr(exc, "code", None) or (
                            "HASH_TIMEOUT" if "HASH_TIMEOUT" in str(exc) else "IMAGE_DECODE_FAILED"
                        )
                        self.catalog.mark_failed(
                            cid,
                            str(path),
                            relative,
                            path.name,
                            stat.st_size,
                            stat.st_mtime_ns,
                            scan_id,
                            code,
                        )
                        stats["failed"] += 1
                    if job_id:
                        self.catalog.update_job(job_id, progress=stats)

        stats["missing"] = self.catalog.finish_scan(cid, scan_id, spec)
        index_affecting_changes = (
            stats["hashed"]
            + stats["content_reused"]
            + stats["failed"]
            + stats["missing"]
        )
        if index_affecting_changes:
            self.catalog.bump_catalog_revision(cid)
        self.catalog.record_scan(cid, stats)
        return stats
