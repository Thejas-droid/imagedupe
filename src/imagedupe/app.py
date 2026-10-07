from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import shutil
import secrets
import time
import uuid
from contextlib import asynccontextmanager
from io import BytesIO
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, File, Form, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from PIL import Image, ImageOps

from imagedupe.api.errors import ImageDupeError
from imagedupe.catalog.db import Catalog
from imagedupe.core.benchmark import run_benchmark
from imagedupe.core.collections import CollectionService
from imagedupe.core.config import Settings
from imagedupe.core.jobs import JobService
from imagedupe.core.search import SearchService
from imagedupe.hashing.base import DEFAULT_SPEC_ID, SPECS, get_spec
from imagedupe.indexes.manager import IndexManager, availability
from imagedupe.observability.diagnostics import doctor
from imagedupe.observability.logging import configure_logging


class RootIn(BaseModel):
    path: str
    recursive: bool = True
    follow_symlinks: bool = False
    include_globs: list[str] = Field(default_factory=list)
    exclude_globs: list[str] = Field(default_factory=list)


class CollectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    roots: list[RootIn] = Field(min_length=1)
    fingerprint_spec_id: str = DEFAULT_SPEC_ID
    backend_policy: str = "auto"


class CollectionPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    fingerprint_spec_id: str | None = None
    backend_policy: str | None = None
    roots: list[RootIn] | None = None


class HashIn(BaseModel):
    collection_id: str
    hash: str
    k: int = 20
    backend: str = "auto"
    max_hamming: int | None = None


class RebuildIn(BaseModel):
    backend: str = "auto"
    config: dict = Field(default_factory=dict)


class SettingsPatch(BaseModel):
    default_collection: str | None = None
    default_top_k: int | None = Field(default=None, ge=1, le=1000)
    default_fingerprint_spec_id: str | None = None
    backend_selection: str | None = None
    ann_tuning_profile: str | None = None
    worker_count: int | None = Field(default=None, ge=0, le=256)
    max_upload_bytes: int | None = Field(default=None, ge=1024)
    max_decoded_pixels: int | None = Field(default=None, ge=1_000_000)
    ingest_max_decoded_pixels: int | None = Field(default=None, ge=1_000_000)
    hash_timeout_seconds: int | None = Field(default=None, ge=1, le=3600)
    thumbnail_cache_enabled: bool | None = None
    cuda_mode: str | None = None
    logging_verbosity: str | None = None
    privacy_paths: bool | None = None


def problem(code: str, title: str, detail: str, status: int) -> JSONResponse:
    return JSONResponse(
        {
            "type": f"https://imagedupe.local/problems/{code.lower().replace('_', '-')}",
            "title": title,
            "status": status,
            "detail": detail,
            "code": code,
        },
        status_code=status,
        media_type="application/problem+json",
    )


def create_app(settings: Settings | None = None, desktop=None) -> FastAPI:
    settings = settings or Settings()
    catalog = Catalog(settings.db_path)
    settings.apply_saved(catalog.all_settings())
    configure_logging(settings.logging_verbosity)
    logger = logging.getLogger("imagedupe.api")
    indexes = IndexManager(catalog, settings.index_dir, settings)
    collections = CollectionService(catalog, settings)
    search = SearchService(catalog, indexes, settings)
    jobs = JobService(catalog, collections, indexes)
    @asynccontextmanager
    async def lifespan(_app):
        yield
        jobs.close()
        indexes.close()

    app = FastAPI(
        title="ImageDupe",
        version="1.1.1",
        openapi_version="3.1.0",
        description="Local binary perceptual-hash near-duplicate image search.",
        lifespan=lifespan,
    )
    app.state.catalog = catalog
    app.state.indexes = indexes
    app.state.collections = collections
    app.state.search = search
    app.state.jobs = jobs
    app.state.settings = settings
    hits: dict[str, deque[float]] = defaultdict(deque)
    decode_semaphore = asyncio.Semaphore(settings.query_decode_concurrency)

    @app.middleware("http")
    async def request_middleware(request: Request, call_next):
        if desktop is not None:
            if request.headers.get("host") != desktop.url.removeprefix("http://"):
                return problem("DESKTOP_HOST", "Local access only", "Open ImageDupe from its desktop shortcut", 403)
            if request.url.path.startswith("/api/"):
                supplied = request.headers.get("X-ImageDupe-Desktop") or request.cookies.get("imagedupe_desktop", "")
                if not secrets.compare_digest(supplied, desktop.token):
                    return problem("DESKTOP_SESSION", "Session required", "Open ImageDupe from its desktop shortcut", 401)
                origin = request.headers.get("origin")
                if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin != desktop.url:
                    return problem("DESKTOP_ORIGIN", "Local access only", "Request origin is not the desktop app", 403)
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        if request.url.path.startswith("/api/"):
            key = request.client.host if request.client else "local"
            current = time.monotonic()
            queue = hits[key]
            while queue and queue[0] < current - 60:
                queue.popleft()
            if len(queue) >= settings.request_rate_per_minute:
                return problem("RATE_LIMITED", "Rate limit exceeded", "Too many requests", 429)
            queue.append(current)
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "request_complete",
            extra={
                "request_id": request_id,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
            },
        )
        return response

    @app.exception_handler(ImageDupeError)
    async def known_error(_request: Request, exc: ImageDupeError):
        return JSONResponse(
            exc.problem(), status_code=exc.status, media_type="application/problem+json"
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request: Request, exc: RequestValidationError):
        return problem("VALIDATION_ERROR", "Request validation failed", str(exc), 422)

    @app.exception_handler(KeyError)
    async def missing_error(_request: Request, exc: KeyError):
        return problem("NOT_FOUND", "Not found", str(exc), 404)

    @app.exception_handler(ValueError)
    async def value_error(_request: Request, exc: ValueError):
        return problem("INVALID_REQUEST", "Invalid request", str(exc), 422)

    @app.exception_handler(Exception)
    async def internal_error(_request: Request, exc: Exception):
        logger.exception("internal_error", extra={"error_code": "INTERNAL_ERROR"})
        return problem(
            "INTERNAL_ERROR",
            "Internal server error",
            "An unexpected error occurred. Check the structured logs for the request ID.",
            500,
        )

    @app.get("/api/v1/desktop")
    def desktop_capabilities():
        return {"enabled": desktop is not None, "folder_picker": bool(desktop and desktop.picker)}

    @app.post("/api/v1/desktop/session")
    def desktop_session():
        if desktop is None:
            raise KeyError("Desktop mode is not running")
        response = JSONResponse({"enabled": True})
        response.set_cookie("imagedupe_desktop", desktop.token, httponly=True, samesite="strict")
        return response

    @app.post("/api/v1/desktop/activate")
    def desktop_activate():
        if desktop is None:
            raise KeyError("Desktop mode is not running")
        desktop.activation_requested.set()
        return {"activated": True}

    @app.post("/api/v1/desktop/folder")
    def desktop_folder():
        if desktop is None or desktop.picker is None:
            raise KeyError("Folder selection is available in the desktop application")
        try:
            path = desktop.picker.choose()
            return {"path": path}
        except RuntimeError as exc:
            raise ImageDupeError("FOLDER_PICKER_BUSY", str(exc), 409, "Folder selection unavailable") from exc

    @app.get("/api/v1/health/live")
    def live():
        return {"status": "ok"}

    @app.get("/api/v1/health/ready")
    def ready():
        if not catalog.ping():
            return JSONResponse({"status": "unhealthy", "catalog": False}, status_code=503)
        return {"status": "ok", "catalog": True}

    @app.get("/api/v1/system/status")
    def status(collection_id: str | None = None):
        stats = catalog.system_stats(collection_id)
        system_status = "healthy"
        active = None
        if collection_id:
            collection = catalog.get_collection(collection_id)
            if not collection:
                raise KeyError(collection_id)
            active = collection.get("active_index")
            system_status = collection["health"]
            stats.update(indexes.delta_status(collection_id))
            stats["collection"] = {
                "name": collection["name"],
                "catalog_revision": collection["catalog_revision"],
                "last_scan_at": collection["last_scan_at"],
                "cache_hit_rate": collection["cache_hit_rate"],
            }
            stats["active_generation"] = active
            if active:
                try:
                    stats["index_size_bytes"] = sum(
                        path.stat().st_size
                        for path in Path(active["disk_path"]).rglob("*")
                        if path.is_file()
                    )
                except OSError:
                    stats["index_size_bytes"] = 0
            else:
                stats["index_size_bytes"] = 0
        if settings.cuda_mode == "On" and not doctor(settings).get("faiss_binary_gpu_compatible"):
            system_status = "degraded"
        stats.update(
            {
                "backends": availability(),
                "fingerprint_specs": list(SPECS),
                "system_status": system_status,
            }
        )
        return stats

    @app.get("/api/v1/system/metrics")
    def metrics(collection_id: str | None = None):
        payload = catalog.metrics(collection_id)
        if collection_id:
            collection = catalog.get_collection(collection_id)
            if not collection:
                raise KeyError(collection_id)
            active = collection.get("active_index")
            payload.update(indexes.delta_status(collection_id))
            payload["active_generation"] = active.get("generation") if active else None
            payload["index_disk_bytes"] = 0
            payload["index_build_duration_seconds"] = 0.0
            payload["ann_recall_at_k"] = None
            if active:
                try:
                    payload["index_disk_bytes"] = sum(
                        path.stat().st_size for path in Path(active["disk_path"]).rglob("*") if path.is_file()
                    )
                except OSError:
                    pass
                try:
                    from datetime import datetime
                    if active.get("build_started_at") and active.get("build_ended_at"):
                        payload["index_build_duration_seconds"] = (
                            datetime.fromisoformat(active["build_ended_at"])
                            - datetime.fromisoformat(active["build_started_at"])
                        ).total_seconds()
                except (TypeError, ValueError):
                    pass
                benchmark = active.get("benchmark") or {}
                payload["ann_recall_at_k"] = benchmark.get("recall_at_k")
                payload["index_load_duration_ms"] = indexes.load_duration_ms(
                    collection_id, active["generation"], active["backend"]
                )
            else:
                payload["index_load_duration_ms"] = 0.0
            logical = max(1, settings.effective_workers)
            cpu = max(1, settings.effective_workers if settings.effective_workers else 1)
            payload["hash_worker_utilization"] = None
            payload["hash_worker_capacity"] = logical
        return payload

    @app.get("/api/v1/system/doctor")
    def doctor_endpoint(show_paths: bool = False):
        return doctor(settings, catalog, show_paths=show_paths)

    @app.get("/api/v1/settings")
    def get_settings():
        return {"runtime": settings.public_runtime(), "saved": catalog.all_settings()}

    @app.patch("/api/v1/settings")
    def patch_settings(body: SettingsPatch):
        values = body.model_dump(exclude_none=True)
        if "default_collection" in body.model_fields_set:
            values["default_collection"] = body.default_collection
        if "default_fingerprint_spec_id" in values:
            get_spec(values["default_fingerprint_spec_id"])
        if "backend_selection" in values and values["backend_selection"] not in {
            "auto",
            "exact",
            "hnsw",
            "ngt",
        }:
            raise ValueError("Unsupported backend selection")
        if "ann_tuning_profile" in values and values["ann_tuning_profile"] not in {
            "fast",
            "balanced",
            "high-recall",
        }:
            raise ValueError("Unsupported ANN tuning profile")
        if "cuda_mode" in values and values["cuda_mode"] not in {"Auto", "Off", "On"}:
            raise ValueError("CUDA mode must be Auto, Off, or On")
        catalog.set_settings(values)
        settings.apply_saved(values)
        configure_logging(settings.logging_verbosity)
        return {"runtime": settings.public_runtime(), "saved": catalog.all_settings()}

    @app.get("/api/v1/collections")
    def collection_list():
        return catalog.list_collections()

    @app.post("/api/v1/collections", status_code=201)
    def collection_create(body: CollectionIn):
        get_spec(body.fingerprint_spec_id)
        return collections.create(
            body.name,
            [root.model_dump() for root in body.roots],
            body.fingerprint_spec_id,
            body.backend_policy,
        )

    @app.get("/api/v1/collections/{cid}")
    def collection_get(cid: str):
        collection = catalog.get_collection(cid)
        if not collection:
            raise KeyError(cid)
        return collection

    @app.patch("/api/v1/collections/{cid}")
    def collection_patch(cid: str, body: CollectionPatch):
        if not catalog.get_collection(cid):
            raise KeyError(cid)
        values = body.model_dump(exclude_none=True)
        roots = values.pop("roots", None)
        if values.get("fingerprint_spec_id"):
            get_spec(values["fingerprint_spec_id"])
        collection = catalog.update_collection(cid, values)
        if roots is not None:
            for root in roots:
                path = Path(root["path"]).expanduser()
                if not path.is_dir():
                    raise ValueError(f"Collection root is not a directory: {path}")
            collection = catalog.replace_roots(cid, roots)
        return collection

    @app.delete("/api/v1/collections/{cid}", status_code=204)
    def collection_delete(cid: str):
        collection = catalog.get_collection(cid)
        if not collection:
            raise KeyError(cid)
        if catalog.active_job_for_collection(cid):
            raise ImageDupeError(
                "JOB_CONFLICT", "Collection has an active job", 409, "Job conflict"
            )
        for generation in catalog.generations(cid):
            shutil.rmtree(generation["disk_path"], ignore_errors=True)
        if not catalog.delete_collection(cid):
            raise KeyError(cid)
        return Response(status_code=204)

    @app.get("/api/v1/collections/{cid}/failures")
    def collection_failures(cid: str, limit: int = Query(500, ge=1, le=5000)):
        if not catalog.get_collection(cid):
            raise KeyError(cid)
        return catalog.list_images(cid, "failed", limit)

    @app.post("/api/v1/collections/{cid}/scan", status_code=202)
    def scan(cid: str):
        if not catalog.get_collection(cid):
            raise KeyError(cid)
        return {"job_id": jobs.scan(cid)}

    @app.post("/api/v1/collections/{cid}/rebuild", status_code=202)
    def rebuild(cid: str, body: RebuildIn = RebuildIn()):
        if not catalog.get_collection(cid):
            raise KeyError(cid)
        return {"job_id": jobs.rebuild(cid, body.backend, body.config)}

    @app.get("/api/v1/jobs/{job_id}")
    def job(job_id: str, request: Request):
        result = catalog.get_job(job_id)
        if not result:
            raise KeyError(job_id)
        serialized = json.dumps(result, sort_keys=True, default=str).encode()
        etag = '"' + hashlib.sha256(serialized).hexdigest()[:24] + '"'
        if request.headers.get("if-none-match") == etag:
            return Response(status_code=304, headers={"ETag": etag})
        return JSONResponse(result, headers={"ETag": etag})

    @app.post("/api/v1/jobs/{job_id}/cancel", status_code=202)
    def cancel(job_id: str):
        if not catalog.get_job(job_id):
            raise KeyError(job_id)
        if not catalog.request_cancel(job_id):
            raise KeyError(job_id)
        return {"job_id": job_id, "cancel_requested": True}

    @app.get("/api/v1/collections/{cid}/indexes")
    def generations(cid: str):
        if not catalog.get_collection(cid):
            raise KeyError(cid)
        return catalog.generations(cid)

    @app.post("/api/v1/collections/{cid}/indexes/{generation}/activate")
    def activate(cid: str, generation: int, backend: str | None = None):
        try:
            selected = indexes.activate(cid, generation, backend)
        except RuntimeError as exc:
            if str(exc) == "FINGERPRINT_SPEC_MISMATCH":
                raise ImageDupeError(
                    "FINGERPRINT_SPEC_MISMATCH",
                    "Generation fingerprint spec is incompatible with the collection",
                    409,
                    "Fingerprint spec mismatch",
                ) from exc
            raise
        return selected

    @app.delete("/api/v1/collections/{cid}/indexes/{generation}", status_code=204)
    def delete_generation(cid: str, generation: int, backend: str | None = None):
        row = indexes.delete(cid, generation, backend)
        if not row:
            raise KeyError(generation)
        return Response(status_code=204)

    @app.post("/api/v1/collections/{cid}/indexes/benchmark")
    def benchmark(cid: str, k: int = 20, queries: int = 50, backend: str = "auto"):
        return run_benchmark(catalog, indexes, cid, k, queries, backend)

    @app.post("/api/v1/search/image")
    async def search_image(
        image: UploadFile = File(...),
        collection_id: str = Form(...),
        k: int = Form(20),
        backend: str = Form("auto"),
        max_hamming: str | None = Form(None),
    ):
        data = await image.read(settings.max_upload_bytes + 1)
        maximum = None if max_hamming in (None, "", "null") else int(max_hamming)
        async with decode_semaphore:
            return await run_in_threadpool(
                search.image,
                collection_id,
                data,
                image.filename or "query",
                k,
                backend,
                maximum,
                image.content_type,
            )

    @app.post("/api/v1/search/hash")
    def search_hash(body: HashIn):
        return search.hash(
            body.collection_id, body.hash, body.k, body.backend, body.max_hamming
        )

    @app.get("/api/v1/images/{image_id}/thumbnail")
    def thumbnail(image_id: int):
        row = catalog.image(image_id)
        if not row:
            raise KeyError(image_id)
        cache = settings.thumb_dir / f"{image_id}-{row['mtime_ns']}.jpg"
        try:
            if settings.thumbnail_cache_enabled and cache.exists():
                path = cache
            else:
                with Image.open(row["path"], formats=["JPEG", "PNG", "WEBP"]) as source:
                    image = ImageOps.exif_transpose(source.copy())
                    image.thumbnail((settings.thumbnail_size, settings.thumbnail_size))
                    image = image.convert("RGB")
                    if settings.thumbnail_cache_enabled:
                        image.save(cache, "JPEG", quality=85, optimize=True)
                        path = cache
                    else:
                        buffer = BytesIO()
                        image.save(buffer, "JPEG", quality=85, optimize=True)
                        buffer.seek(0)
                        path = None
        except Exception as exc:
            raise ImageDupeError(
                "IMAGE_DECODE_FAILED", "Unable to derive thumbnail", 422, "Thumbnail failed"
            ) from exc
        headers = {
            "Cache-Control": "private, max-age=3600" if settings.thumbnail_cache_enabled else "no-store",
            "X-Content-Type-Options": "nosniff",
        }
        if path is not None:
            return FileResponse(path, media_type="image/jpeg", headers=headers)
        return StreamingResponse(buffer, media_type="image/jpeg", headers=headers)

    web = Path(__file__).parent / "web"
    app.mount("/assets", StaticFiles(directory=web), name="assets")

    @app.get("/")
    def root():
        return FileResponse(web / "index.html")

    return app

