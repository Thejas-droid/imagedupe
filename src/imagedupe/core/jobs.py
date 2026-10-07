from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from imagedupe.api.errors import ImageDupeError


class JobService:
    def __init__(self, catalog, collections, indexes):
        self.catalog = catalog
        self.collections = collections
        self.indexes = indexes
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="imagedupe-jobs")

    def _ensure_available(self, cid: str) -> None:
        active = self.catalog.active_job_for_collection(cid)
        if active:
            raise ImageDupeError(
                "JOB_CONFLICT",
                f"Collection already has an active {active['type']} job ({active['id']})",
                409,
                "Job conflict",
            )

    def scan(self, cid: str) -> str:
        self._ensure_available(cid)
        job_id = self.catalog.create_job(cid, "scan")
        self.pool.submit(self._scan, job_id, cid)
        return job_id

    def _scan(self, job_id: str, cid: str) -> None:
        try:
            self.catalog.update_job(job_id, "SCANNING", {})
            stats = self.collections.scan(
                cid,
                job_id,
                cancel_check=lambda: self.catalog.is_cancel_requested(job_id),
            )
            self.catalog.update_job(job_id, "SUCCEEDED", stats, stats, end=True)
        except Exception as exc:
            state = "CANCELLED" if str(exc) == "JOB_CANCELLED" else "FAILED"
            self.catalog.update_job(job_id, state, error=str(exc), end=True)

    def rebuild(self, cid: str, backend: str = "auto", config: dict | None = None) -> str:
        self._ensure_available(cid)
        job_id = self.catalog.create_job(cid, "rebuild")
        self.pool.submit(self._rebuild, job_id, cid, backend, config or {})
        return job_id

    def _rebuild(self, job_id: str, cid: str, backend: str, config: dict) -> None:
        try:
            if self.catalog.is_cancel_requested(job_id):
                raise RuntimeError("JOB_CANCELLED")

            def stage(state: str) -> None:
                self.catalog.update_job(job_id, state)

            manifest = self.indexes.build(
                cid,
                backend,
                config=config,
                activate=True,
                stage_callback=stage,
                cancel_check=lambda: self.catalog.is_cancel_requested(job_id),
            )
            progress = {"generation": manifest["generation"], "backend": manifest["backend"]}
            self.catalog.update_job(job_id, "SUCCEEDED", progress, manifest, end=True)
        except Exception as exc:
            state = "CANCELLED" if str(exc) == "JOB_CANCELLED" else "FAILED"
            self.catalog.update_job(job_id, state, error=str(exc), end=True)

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)
