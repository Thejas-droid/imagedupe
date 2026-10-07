from __future__ import annotations

import importlib
import json
import os
import platform
import sys
import time
from pathlib import Path

import numpy as np

from imagedupe.hashing.hamming import hamming_many


def _version(module: str) -> str | None:
    try:
        loaded = importlib.import_module(module)
        return getattr(loaded, "__version__", "installed")
    except Exception:
        return None


def run_benchmark(catalog, indexes, cid: str, k: int = 20, queries: int = 50, backend: str = "auto") -> dict:
    collection = catalog.get_collection(cid)
    if not collection:
        raise KeyError(cid)
    bucket_ids, hashes = catalog.bucket_vectors(cid, collection["fingerprint_spec_id"])
    vectors = (
        np.vstack([np.frombuffer(value, np.uint8) for value in hashes])
        if hashes
        else np.empty((0, 0), np.uint8)
    )
    selected_queries = min(max(0, int(queries)), len(hashes))
    latencies: list[float] = []
    recalls: list[float] = []
    selected_backend = None
    selected_generation = None
    candidate_factor = 5

    for query_index in range(selected_queries):
        query = hashes[query_index]
        started = time.perf_counter()
        got_ids, _, generation, _ = indexes.search(
            cid, query, max(k * candidate_factor, 100), backend
        )
        latencies.append((time.perf_counter() - started) * 1000)
        selected_backend = generation["backend"]
        selected_generation = generation.get("generation")
        truth_distances = hamming_many(query, vectors)
        truth_order = np.lexsort((np.asarray(bucket_ids), truth_distances))[:k]
        truth = set(np.asarray(bucket_ids)[truth_order].tolist())
        got = set(got_ids[:k].tolist())
        recalls.append(len(truth & got) / len(truth) if truth else 1.0)

    generation_row = (
        catalog.generation(cid, selected_generation, selected_backend)
        if selected_generation is not None
        else None
    )
    report = {
        "collection_id": cid,
        "queries": selected_queries,
        "k": k,
        "backend": selected_backend,
        "generation": selected_generation,
        "p50_ms": float(np.percentile(latencies, 50)) if latencies else 0.0,
        "p95_ms": float(np.percentile(latencies, 95)) if latencies else 0.0,
        "p99_ms": float(np.percentile(latencies, 99)) if latencies else 0.0,
        "recall_at_k": float(np.mean(recalls)) if recalls else 1.0,
        "ground_truth": "NumPy brute-force Hamming",
        "fingerprint_spec": collection["fingerprint_spec_id"],
        "image_count": collection["counts"]["valid"],
        "unique_fingerprint_buckets": collection["counts"]["unique_buckets"],
        "backend_config": generation_row.get("config", {}) if generation_row else {},
        "catalog_revision": collection["catalog_revision"],
        "environment": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "cpu_count": os.cpu_count(),
            "numpy": np.__version__,
            "pillow": _version("PIL"),
            "scipy": _version("scipy"),
            "faiss": _version("faiss"),
            "ngtpy": _version("ngtpy"),
        },
        "cache_state": "warm-index",
    }
    if selected_generation is not None and selected_backend:
        catalog.set_generation_benchmark(cid, selected_generation, selected_backend, report)
    return report


def write_benchmark_report(report: dict, path: Path) -> None:
    Path(path).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
