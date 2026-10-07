from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np

from imagedupe.hashing.base import get_spec
from imagedupe.indexes.backends import FaissFlat, FaissHNSW, NGT, NumpyExact


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


ALIASES = {
    "hnsw": "faiss-binary-hnsw",
    "ngt": "ngt-hamming",
    "faiss": "faiss-binary-flat",
}


def availability() -> dict:
    return {
        "exact": {
            "available": True,
            "preferred": "faiss-binary-flat" if FaissFlat.available() else "numpy-exact",
        },
        "numpy-exact": {"available": True},
        "faiss-binary-flat": {"available": FaissFlat.available()},
        "faiss-binary-hnsw": {"available": FaissHNSW.available()},
        "ngt-hamming": {"available": NGT.available()},
    }


class IndexManager:
    def __init__(self, catalog, root: Path, settings=None):
        self.catalog = catalog
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.settings = settings
        self.cache: dict[tuple[str, int, str], dict] = {}
        self.load_times_ms: dict[tuple[str, int, str], float] = {}
        self._cleanup_incomplete()

    def _cleanup_incomplete(self) -> None:
        for path in self.root.glob("*/.*.tmp"):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)

    def _auto_backend(self, vector_count: int) -> str:
        cutoff = getattr(self.settings, "auto_exact_max_buckets", 10000)
        if vector_count <= cutoff:
            return "faiss-binary-flat" if FaissFlat.available() else "numpy-exact"
        if FaissHNSW.available():
            return "faiss-binary-hnsw"
        if NGT.available():
            return "ngt-hamming"
        return "faiss-binary-flat" if FaissFlat.available() else "numpy-exact"

    def backend(self, name: str, bits: int, vector_count: int = 0):
        name = ALIASES.get(name, name)
        if name == "auto":
            name = self._auto_backend(vector_count)
        if name == "exact":
            name = "faiss-binary-flat" if FaissFlat.available() else "numpy-exact"
        cls = {
            "numpy-exact": NumpyExact,
            "faiss-binary-flat": FaissFlat,
            "faiss-binary-hnsw": FaissHNSW,
            "ngt-hamming": NGT,
        }.get(name)
        if not cls:
            raise ValueError(f"unknown backend {name}")
        backend = cls(bits)
        if hasattr(backend, "available") and not backend.available():
            raise RuntimeError("BACKEND_UNAVAILABLE")
        return backend

    def default_config(self, backend_id: str) -> dict:
        profile = getattr(self.settings, "ann_tuning_profile", "balanced")
        if backend_id == "faiss-binary-hnsw":
            profiles = {
                "fast": {"M": 16, "efConstruction": 120, "efSearch": 32},
                "balanced": {"M": 16, "efConstruction": 200, "efSearch": 96},
                "high-recall": {"M": 24, "efConstruction": 300, "efSearch": 192},
            }
            return profiles.get(profile, profiles["balanced"])
        if backend_id == "ngt-hamming":
            profiles = {
                "fast": {"edge_size_for_creation": 10, "edge_size_for_search": 30, "epsilon": 0.05},
                "balanced": {"edge_size_for_creation": 20, "edge_size_for_search": 60, "epsilon": 0.1},
                "high-recall": {"edge_size_for_creation": 30, "edge_size_for_search": 120, "epsilon": 0.2},
            }
            return profiles.get(profile, profiles["balanced"])
        return {}

    def build(
        self,
        cid: str,
        name: str = "auto",
        config: dict | None = None,
        activate: bool = True,
        stage_callback: Callable[[str], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict:
        collection = self.catalog.get_collection(cid)
        if not collection:
            raise KeyError(cid)
        spec = get_spec(collection["fingerprint_spec_id"])
        ids, hashes = self.catalog.bucket_vectors(cid, spec.spec_id)
        vectors = (
            np.vstack([np.frombuffer(value, np.uint8) for value in hashes])
            if hashes
            else np.empty((0, spec.byte_length), np.uint8)
        )
        requested_name = name
        if name == "auto" and collection.get("backend_policy", "auto") != "auto":
            requested_name = collection["backend_policy"]
        backend = self.backend(requested_name, spec.bits, len(ids))
        merged_config = self.default_config(backend.backend_id)
        merged_config.update(config or {})
        generation = self.catalog.next_generation(cid)
        started = now()
        base = self.root / cid
        base.mkdir(parents=True, exist_ok=True)
        temp_path = base / f".{generation}-{backend.backend_id}.tmp"
        final_path = base / f"{generation}-{backend.backend_id}"
        shutil.rmtree(temp_path, ignore_errors=True)

        try:
            if cancel_check and cancel_check():
                raise RuntimeError("JOB_CANCELLED")
            if stage_callback:
                stage_callback("BUILDING")
            backend.build(vectors, np.asarray(ids, np.int64), merged_config)
            backend.save(temp_path)
            manifest = {
                "schema_version": 1,
                "generation": generation,
                "collection_id": cid,
                "backend": backend.backend_id,
                "backend_version": self.version(backend.backend_id),
                "fingerprint_spec_id": spec.spec_id,
                "vector_count": len(ids),
                "image_count": collection["counts"]["valid"],
                "catalog_revision": collection["catalog_revision"],
                "config": merged_config,
                "build_started_at": started,
                "created_at": now(),
            }
            (temp_path / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
            )
            checksum = self.checksum(temp_path)
            manifest["sha256"] = checksum
            (temp_path / "manifest.json").write_text(
                json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
            )

            if stage_callback:
                stage_callback("VALIDATING")
            self._validate_path(
                temp_path,
                manifest,
                expected_spec=spec.spec_id,
                load_and_smoke=True,
                vectors=vectors,
                ids=ids,
            )
            if cancel_check and cancel_check():
                raise RuntimeError("JOB_CANCELLED")
            if stage_callback:
                stage_callback("PROMOTING")
            shutil.rmtree(final_path, ignore_errors=True)
            os.replace(temp_path, final_path)
            self.catalog.add_generation(manifest, str(final_path), checksum, activate)
            return manifest
        except Exception:
            shutil.rmtree(temp_path, ignore_errors=True)
            raise
        finally:
            backend.close()

    def version(self, name: str) -> str:
        try:
            if name.startswith("faiss"):
                import faiss

                return getattr(faiss, "__version__", "installed")
            if name.startswith("ngt"):
                import ngtpy

                return getattr(ngtpy, "__version__", "installed")
            return np.__version__
        except Exception:
            return "unavailable"

    def checksum(self, path: Path) -> str:
        digest = hashlib.sha256()
        for file in sorted(
            item for item in Path(path).rglob("*") if item.is_file() and item.name != "manifest.json"
        ):
            digest.update(file.relative_to(path).as_posix().encode())
            with file.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        return digest.hexdigest()

    def _validate_path(
        self,
        path: Path,
        row: dict,
        expected_spec: str,
        load_and_smoke: bool = False,
        vectors=None,
        ids=None,
    ) -> dict:
        manifest_path = Path(path) / "manifest.json"
        if not manifest_path.is_file():
            raise RuntimeError("INDEX_MANIFEST_MISSING")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for key in ("collection_id", "generation", "backend", "fingerprint_spec_id", "vector_count"):
            if str(manifest.get(key)) != str(row.get(key)):
                raise RuntimeError("INDEX_MANIFEST_MISMATCH")
        if manifest["fingerprint_spec_id"] != expected_spec:
            raise RuntimeError("FINGERPRINT_SPEC_MISMATCH")
        actual_checksum = self.checksum(path)
        expected_checksum = row.get("checksum") or row.get("sha256") or manifest.get("sha256")
        if expected_checksum and actual_checksum != expected_checksum:
            raise RuntimeError("INDEX_CHECKSUM_MISMATCH")
        if load_and_smoke:
            spec = get_spec(expected_spec)
            tester = self.backend(manifest["backend"], spec.bits, manifest["vector_count"])
            try:
                tester.load(Path(path))
                if int(tester.stats().get("vector_count", -1)) != int(manifest["vector_count"]):
                    raise RuntimeError("INDEX_VECTOR_COUNT_MISMATCH")
                if ids:
                    got, _ = tester.search(vectors[0], min(3, len(ids)))
                    if int(ids[0]) not in set(map(int, got)):
                        raise RuntimeError("INDEX_SELF_TEST_FAILED")
            finally:
                tester.close()
        return manifest

    def validate_generation(self, row: dict, expected_spec: str) -> dict:
        return self._validate_path(Path(row["disk_path"]), row, expected_spec, load_and_smoke=False)

    def _load_row(self, row: dict, spec) -> dict:
        key = (row["collection_id"], int(row["generation"]), row["backend"])
        cached = self.cache.get(key)
        if cached:
            return cached
        started = time.perf_counter()
        self.validate_generation(row, spec.spec_id)
        backend = self.backend(row["backend"], spec.bits, int(row["vector_count"]))
        backend.load(Path(row["disk_path"]))
        self.load_times_ms[key] = (time.perf_counter() - started) * 1000
        if int(backend.stats().get("vector_count", -1)) != int(row["vector_count"]):
            backend.close()
            raise RuntimeError("INDEX_VECTOR_COUNT_MISMATCH")
        item = {"key": key, "row": row, "spec": spec, "backend": backend}
        self.cache[key] = item
        return item

    def load_active(self, cid: str) -> dict:
        collection = self.catalog.get_collection(cid)
        if not collection:
            raise KeyError(cid)
        spec = get_spec(collection["fingerprint_spec_id"])
        active = self.catalog.active_generation(cid)
        if active and active["fingerprint_spec_id"] != spec.spec_id:
            raise RuntimeError("FINGERPRINT_SPEC_MISMATCH")
        candidates = self.catalog.compatible_generations(cid, spec.spec_id)
        if not candidates:
            raise RuntimeError("INDEX_NOT_READY")
        errors: list[str] = []
        for row in candidates:
            try:
                return self._load_row(row, spec)
            except RuntimeError as exc:
                errors.append(str(exc))
                self.catalog.update_generation_status(
                    cid, row["generation"], row["backend"], "DEGRADED"
                )
        raise RuntimeError(errors[0] if errors else "INDEX_NOT_READY")

    def _exact_current(self, cid: str, spec, query: np.ndarray, k: int):
        ids, hashes = self.catalog.bucket_vectors(cid, spec.spec_id)
        vectors = (
            np.vstack([np.frombuffer(value, np.uint8) for value in hashes])
            if hashes
            else np.empty((0, spec.byte_length), np.uint8)
        )
        backend = self.backend("exact", spec.bits, len(ids))
        backend.build(vectors, np.asarray(ids, np.int64), {})
        try:
            started = time.perf_counter()
            result_ids, distances = backend.search(query, k)
            elapsed = (time.perf_counter() - started) * 1000
            row = {
                "collection_id": cid,
                "backend": backend.backend_id,
                "generation": None,
                "fingerprint_spec_id": spec.spec_id,
                "catalog_revision": self.catalog.get_collection(cid)["catalog_revision"],
            }
            return result_ids, distances, row, elapsed
        finally:
            backend.close()

    def _load_requested_backend(self, cid: str, requested: str, spec) -> dict:
        requested = ALIASES.get(requested, requested)
        if requested == "exact":
            raise RuntimeError("TRANSIENT_EXACT")
        if requested == "auto":
            return self.load_active(cid)
        if requested not in availability():
            raise RuntimeError("BACKEND_UNAVAILABLE")
        if not availability()[requested]["available"]:
            raise RuntimeError("BACKEND_UNAVAILABLE")
        row = self.catalog.latest_generation_for_backend(cid, requested, spec.spec_id)
        if not row:
            raise RuntimeError("INDEX_NOT_READY")
        return self._load_row(row, spec)

    def _merge_delta(self, cid: str, item: dict, query: np.ndarray, k: int, ids, distances):
        collection = self.catalog.get_collection(cid)
        generation_revision = int(item["row"].get("catalog_revision", 0))
        if generation_revision >= int(collection["catalog_revision"]):
            return ids, distances
        current_ids, current_hashes = self.catalog.bucket_vectors(cid, item["spec"].spec_id)
        base_ids = set(map(int, getattr(item["backend"], "ids", [])))
        delta_positions = [pos for pos, bucket_id in enumerate(current_ids) if int(bucket_id) not in base_ids]
        if not delta_positions:
            return ids, distances
        delta_vectors = np.vstack(
            [np.frombuffer(current_hashes[pos], np.uint8) for pos in delta_positions]
        )
        delta_ids = np.asarray([current_ids[pos] for pos in delta_positions], np.int64)
        exact = NumpyExact(item["spec"].bits)
        exact.build(delta_vectors, delta_ids, {})
        delta_result_ids, delta_distances = exact.search(query, k)
        merged: dict[int, int] = {
            int(bucket_id): int(distance) for bucket_id, distance in zip(ids, distances)
        }
        for bucket_id, distance in zip(delta_result_ids, delta_distances):
            merged[int(bucket_id)] = min(merged.get(int(bucket_id), 10**9), int(distance))
        ordered = sorted(merged.items(), key=lambda item_: (item_[1], item_[0]))[:k]
        return (
            np.asarray([item_[0] for item_ in ordered], np.int64),
            np.asarray([item_[1] for item_ in ordered], np.int32),
        )

    def search(self, cid: str, query: bytes, k: int, override: str = "auto"):
        collection = self.catalog.get_collection(cid)
        if not collection:
            raise KeyError(cid)
        spec = get_spec(collection["fingerprint_spec_id"])
        query_vector = np.frombuffer(query, np.uint8)
        if override == "exact":
            return self._exact_current(cid, spec, query_vector, k)
        item = self._load_requested_backend(cid, override or "auto", spec)
        stale = int(item["row"].get("catalog_revision", 0)) < int(collection["catalog_revision"])
        backend_k = min(max(k * 2 if stale else k, k), max(k, int(item["row"]["vector_count"])))
        started = time.perf_counter()
        ids, distances = item["backend"].search(query_vector, backend_k)
        ids, distances = self._merge_delta(cid, item, query_vector, k, ids, distances)
        elapsed = (time.perf_counter() - started) * 1000
        return ids[:k], distances[:k], item["row"], elapsed

    def delta_status(self, cid: str) -> dict:
        collection = self.catalog.get_collection(cid)
        active = self.catalog.active_generation(cid)
        if not collection or not active or active["fingerprint_spec_id"] != collection["fingerprint_spec_id"]:
            return {"delta_bucket_count": 0, "tombstone_count": 0, "needs_compaction": False}
        try:
            item = self._load_row(active, get_spec(collection["fingerprint_spec_id"]))
        except RuntimeError:
            return {"delta_bucket_count": 0, "tombstone_count": 0, "needs_compaction": True}
        current_ids, _ = self.catalog.bucket_vectors(cid, collection["fingerprint_spec_id"])
        current = set(map(int, current_ids))
        base = set(map(int, getattr(item["backend"], "ids", [])))
        delta = len(current - base)
        tombstones = len(base - current)
        base_count = max(1, len(base))
        return {
            "delta_bucket_count": delta,
            "tombstone_count": tombstones,
            "delta_ratio": delta / base_count,
            "tombstone_ratio": tombstones / base_count,
            "needs_compaction": (
                delta > 100000 or delta / base_count > 0.05 or tombstones / base_count > 0.10
            ),
        }

    def activate(self, cid: str, generation: int, backend: str | None = None) -> dict:
        collection = self.catalog.get_collection(cid)
        if not collection:
            raise KeyError(cid)
        row = self.catalog.generation(cid, generation, backend)
        if not row:
            raise KeyError(generation)
        if row["fingerprint_spec_id"] != collection["fingerprint_spec_id"]:
            raise RuntimeError("FINGERPRINT_SPEC_MISMATCH")
        self._load_row(row, get_spec(collection["fingerprint_spec_id"]))
        return self.catalog.activate_generation(cid, generation, row["backend"])

    def delete(self, cid: str, generation: int, backend: str | None = None) -> dict | None:
        row = self.catalog.delete_generation(cid, generation, backend)
        if row:
            key = (cid, int(row["generation"]), row["backend"])
            cached = self.cache.pop(key, None)
            if cached:
                cached["backend"].close()
            shutil.rmtree(row["disk_path"], ignore_errors=True)
        return row

    def load_duration_ms(self, cid: str, generation: int, backend: str) -> float:
        return float(self.load_times_ms.get((cid, int(generation), backend), 0.0))

    def close(self) -> None:
        for item in list(self.cache.values()):
            try:
                item["backend"].close()
            except Exception:
                pass
        self.cache.clear()
