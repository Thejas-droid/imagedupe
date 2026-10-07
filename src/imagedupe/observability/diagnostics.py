from __future__ import annotations

import importlib
import importlib.util
import os
import platform
import shutil
import sys
from pathlib import Path

import numpy
import PIL
import psutil

from imagedupe.hashing.base import SPECS
from imagedupe.indexes.backends import FaissFlat, FaissHNSW, NGT


def version(name: str):
    try:
        return getattr(importlib.import_module(name), "__version__", "installed")
    except Exception:
        return None


def _path_info(path: Path, show_paths: bool) -> dict:
    return {
        "path": str(path) if show_paths else f"…/{path.name}",
        "exists": path.exists(),
        "writable": os.access(path, os.W_OK) if path.exists() else os.access(path.parent, os.W_OK),
    }


def doctor(settings, catalog=None, show_paths: bool = False) -> dict:
    gpu_devices = 0
    binary_gpu = False
    if importlib.util.find_spec("faiss"):
        try:
            import faiss

            gpu_devices = int(faiss.get_num_gpus()) if hasattr(faiss, "get_num_gpus") else 0
            # Standard Faiss GPU docs list float Flat/IVF/PQ indexes. Keep binary support capability-gated.
            binary_gpu = bool(hasattr(faiss, "GpuIndexBinaryFlat")) and gpu_devices > 0
        except Exception:
            gpu_devices = 0
            binary_gpu = False

    disk = shutil.disk_usage(settings.home)
    result = {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": numpy.__version__,
        "pillow": PIL.__version__,
        "scipy": version("scipy"),
        "faiss": version("faiss"),
        "faiss_binary_flat": FaissFlat.available(),
        "faiss_binary_hnsw": FaissHNSW.available(),
        "faiss_gpu_devices": gpu_devices,
        "faiss_binary_gpu_compatible": binary_gpu,
        "cuda_mode": settings.cuda_mode,
        "ngt": version("ngtpy"),
        "ngt_available": NGT.available(),
        "logical_cpu_count": os.cpu_count(),
        "ram_total": psutil.virtual_memory().total,
        "disk_free": disk.free,
        "paths": {
            "home": _path_info(settings.home, show_paths),
            "catalog": _path_info(settings.db_path, show_paths),
            "indexes": _path_info(settings.index_dir, show_paths),
            "thumbnails": _path_info(settings.thumb_dir, show_paths),
        },
        "fingerprint_specs": list(SPECS),
    }
    if settings.cuda_mode == "On" and not binary_gpu:
        result["cuda_status"] = "requested-but-unavailable; CPU fallback required"
    elif binary_gpu:
        result["cuda_status"] = "binary GPU capability detected"
    else:
        result["cuda_status"] = "CPU"

    if catalog is not None:
        collections = []
        for collection in catalog.list_collections():
            active = collection.get("active_index")
            collections.append(
                {
                    "id": collection["id"],
                    "name": collection["name"],
                    "fingerprint_spec": collection["fingerprint_spec_id"],
                    "active_generation": active.get("generation") if active else None,
                    "active_backend": active.get("backend") if active else None,
                    "spec_compatible": bool(
                        active and active.get("fingerprint_spec_id") == collection["fingerprint_spec_id"]
                    ),
                    "catalog_revision": collection["catalog_revision"],
                    "index_catalog_revision": active.get("catalog_revision") if active else None,
                    "health": collection["health"],
                }
            )
        result["collections"] = collections
    return result
