from __future__ import annotations

import importlib.util
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np

from imagedupe.hashing.hamming import hamming_many


class NumpyExact:
    backend_id = "numpy-exact"

    def __init__(self, bits: int):
        self.bits = bits
        self.vectors = np.empty((0, bits // 8), np.uint8)
        self.ids = np.empty(0, np.int64)

    def build(self, vectors, ids, config) -> None:
        self.vectors = np.ascontiguousarray(vectors, np.uint8)
        self.ids = np.asarray(ids, np.int64)

    def search(self, query, k: int):
        if not len(self.ids):
            return np.empty(0, np.int64), np.empty(0, np.int32)
        distances = hamming_many(query, self.vectors).astype(np.int32)
        order = np.lexsort((self.ids, distances))[: min(k, len(distances))]
        return self.ids[order], distances[order]

    def append_or_stage(self, vectors, ids) -> None:
        vectors = np.ascontiguousarray(vectors, np.uint8)
        ids = np.asarray(ids, np.int64)
        self.vectors = np.vstack((self.vectors, vectors)) if len(self.vectors) else vectors
        self.ids = np.concatenate((self.ids, ids))

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        np.save(path / "vectors.npy", self.vectors)
        np.save(path / "ids.npy", self.ids)

    def load(self, path: Path) -> None:
        self.vectors = np.load(path / "vectors.npy", allow_pickle=False)
        self.ids = np.load(path / "ids.npy", allow_pickle=False)

    def health(self) -> dict:
        return {"healthy": True, "vector_count": len(self.ids)}

    def stats(self) -> dict:
        return {"vector_count": len(self.ids), "bits": self.bits}

    def close(self) -> None:
        return None


class FaissFlat:
    backend_id = "faiss-binary-flat"

    def __init__(self, bits: int):
        self.bits = bits
        self.index = None
        self.ids = np.empty(0, np.int64)

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("faiss") is not None

    def build(self, vectors, ids, config) -> None:
        if not self.available():
            raise RuntimeError("BACKEND_UNAVAILABLE")
        import faiss

        self.index = faiss.IndexBinaryFlat(self.bits)
        self.index.add(np.ascontiguousarray(vectors, np.uint8))
        self.ids = np.asarray(ids, np.int64)

    def search(self, query, k: int):
        if not len(self.ids):
            return np.empty(0, np.int64), np.empty(0, np.int32)
        distances, positions = self.index.search(
            np.ascontiguousarray(np.asarray(query, np.uint8).reshape(1, -1)),
            min(k, len(self.ids)),
        )
        positions = positions[0]
        distances = distances[0]
        valid = positions >= 0
        return self.ids[positions[valid]], distances[valid].astype(np.int32)

    def append_or_stage(self, vectors, ids) -> None:
        self.index.add(np.ascontiguousarray(vectors, np.uint8))
        self.ids = np.concatenate((self.ids, np.asarray(ids, np.int64)))

    def save(self, path: Path) -> None:
        import faiss

        path.mkdir(parents=True, exist_ok=True)
        faiss.write_index_binary(self.index, str(path / "index.faiss"))
        np.save(path / "ids.npy", self.ids)

    def load(self, path: Path) -> None:
        import faiss

        self.index = faiss.read_index_binary(str(path / "index.faiss"))
        self.ids = np.load(path / "ids.npy", allow_pickle=False)

    def health(self) -> dict:
        return {"healthy": self.index is not None, "vector_count": len(self.ids)}

    def stats(self) -> dict:
        return {"vector_count": len(self.ids), "bits": self.bits}

    def close(self) -> None:
        self.index = None


class FaissHNSW:
    backend_id = "faiss-binary-hnsw"

    def __init__(self, bits: int):
        self.bits = bits
        self.index = None
        self.ids = np.empty(0, np.int64)
        self.config: dict = {}

    @staticmethod
    def available() -> bool:
        if importlib.util.find_spec("faiss") is None:
            return False
        import faiss

        return hasattr(faiss, "IndexBinaryHNSW")

    def build(self, vectors, ids, config) -> None:
        if not self.available():
            raise RuntimeError("BACKEND_UNAVAILABLE")
        import faiss

        self.config = {
            "M": int(config.get("M", 16)),
            "efConstruction": int(config.get("efConstruction", 200)),
            "efSearch": int(config.get("efSearch", 64)),
        }
        self.index = faiss.IndexBinaryHNSW(self.bits, self.config["M"])
        self.index.hnsw.efConstruction = self.config["efConstruction"]
        self.index.hnsw.efSearch = self.config["efSearch"]
        self.index.add(np.ascontiguousarray(vectors, np.uint8))
        self.ids = np.asarray(ids, np.int64)

    def search(self, query, k: int):
        if not len(self.ids):
            return np.empty(0, np.int64), np.empty(0, np.int32)
        self.index.hnsw.efSearch = self.config.get("efSearch", 64)
        distances, positions = self.index.search(
            np.ascontiguousarray(np.asarray(query, np.uint8).reshape(1, -1)),
            min(k, len(self.ids)),
        )
        positions = positions[0]
        distances = distances[0]
        valid = positions >= 0
        return self.ids[positions[valid]], distances[valid].astype(np.int32)

    def append_or_stage(self, vectors, ids) -> None:
        self.index.add(np.ascontiguousarray(vectors, np.uint8))
        self.ids = np.concatenate((self.ids, np.asarray(ids, np.int64)))

    def save(self, path: Path) -> None:
        import faiss

        path.mkdir(parents=True, exist_ok=True)
        faiss.write_index_binary(self.index, str(path / "index.faiss"))
        np.save(path / "ids.npy", self.ids)
        (path / "backend.json").write_text(json.dumps(self.config), encoding="utf-8")

    def load(self, path: Path) -> None:
        import faiss

        self.index = faiss.read_index_binary(str(path / "index.faiss"))
        self.ids = np.load(path / "ids.npy", allow_pickle=False)
        self.config = (
            json.loads((path / "backend.json").read_text(encoding="utf-8"))
            if (path / "backend.json").exists()
            else {}
        )

    def health(self) -> dict:
        return {"healthy": self.index is not None, "vector_count": len(self.ids)}

    def stats(self) -> dict:
        return {"vector_count": len(self.ids), "bits": self.bits, **self.config}

    def close(self) -> None:
        self.index = None


class NGT:
    backend_id = "ngt-hamming"

    def __init__(self, bits: int):
        self.bits = bits
        self.index = None
        self.ids = np.empty(0, np.int64)
        self.path: Path | None = None
        self.config: dict = {}
        self._temporary_root: Path | None = None

    @staticmethod
    def available() -> bool:
        return importlib.util.find_spec("ngtpy") is not None

    def build(self, vectors, ids, config) -> None:
        if not self.available():
            raise RuntimeError("BACKEND_UNAVAILABLE")
        import ngtpy

        self.ids = np.asarray(ids, np.int64)
        self.config = {
            "edge_size_for_creation": int(config.get("edge_size_for_creation", 10)),
            "edge_size_for_search": int(config.get("edge_size_for_search", 40)),
            "epsilon": float(config.get("epsilon", 0.1)),
        }
        self._temporary_root = Path(tempfile.mkdtemp(prefix="imagedupe-ngt-"))
        self.path = self._temporary_root / "index"
        ngtpy.create(
            str(self.path),
            self.bits // 8,
            edge_size_for_creation=self.config["edge_size_for_creation"],
            edge_size_for_search=self.config["edge_size_for_search"],
            distance_type="Hamming",
            object_type="Byte",
        )
        self.index = ngtpy.Index(str(self.path), zero_based_numbering=True)
        if len(self.ids):
            self.index.batch_insert(np.asarray(vectors, np.uint8))
        self.index.save()

    def search(self, query, k: int):
        if not len(self.ids):
            return np.empty(0, np.int64), np.empty(0, np.int32)
        results = self.index.search(
            np.asarray(query, np.uint8),
            min(k, len(self.ids)),
            self.config.get("epsilon", 0.1),
            self.config.get("edge_size_for_search", 40),
        )
        positions = np.array([int(item[0]) for item in results], dtype=int)
        distances = np.array([int(round(item[1])) for item in results], dtype=np.int32)
        return self.ids[positions], distances

    def append_or_stage(self, vectors, ids) -> None:
        if len(ids):
            self.index.batch_insert(np.asarray(vectors, np.uint8))
            self.ids = np.concatenate((self.ids, np.asarray(ids, np.int64)))
            self.index.save()

    def save(self, path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        np.save(path / "ids.npy", self.ids)
        (path / "backend.json").write_text(json.dumps(self.config), encoding="utf-8")
        target = path / "ngt-index"
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(self.path, target)

    def load(self, path: Path) -> None:
        import ngtpy

        self.ids = np.load(path / "ids.npy", allow_pickle=False)
        self.path = path / "ngt-index"
        self.config = (
            json.loads((path / "backend.json").read_text(encoding="utf-8"))
            if (path / "backend.json").exists()
            else {}
        )
        self.index = ngtpy.Index(
            str(self.path), zero_based_numbering=True, read_only=True, log_disabled=True
        )

    def health(self) -> dict:
        return {"healthy": self.index is not None, "vector_count": len(self.ids)}

    def stats(self) -> dict:
        return {"vector_count": len(self.ids), "bits": self.bits, **self.config}

    def close(self) -> None:
        if self.index:
            try:
                self.index.close()
            except Exception:
                pass
        self.index = None
        if self._temporary_root:
            shutil.rmtree(self._temporary_root, ignore_errors=True)
            self._temporary_root = None
