from pathlib import Path

import numpy as np
import pytest

from imagedupe.hashing.hamming import hamming_many
from imagedupe.indexes.backends import FaissFlat, FaissHNSW, NGT, NumpyExact


def _exercise(backend_cls, tmp_path):
    rng = np.random.default_rng(123)
    vectors = rng.integers(0, 256, size=(80, 32), dtype=np.uint8)
    ids = np.arange(200, 280, dtype=np.int64)
    query = vectors[11]
    backend = backend_cls(256)
    backend.build(vectors, ids, {})
    first_ids, first_distances = backend.search(query, 15)
    target = tmp_path / backend.backend_id
    backend.save(target)
    backend.close()
    restored = backend_cls(256)
    restored.load(target)
    second_ids, second_distances = restored.search(query, 15)
    restored.close()
    assert second_ids.tolist() == first_ids.tolist()
    assert second_distances.tolist() == first_distances.tolist()
    assert all(distance >= 0 for distance in second_distances)
    assert set(second_ids).issubset(set(ids))


def test_numpy_exact_serialization_roundtrip(tmp_path):
    _exercise(NumpyExact, tmp_path)


@pytest.mark.skipif(not FaissFlat.available(), reason='faiss not installed')
def test_faiss_flat_conformance(tmp_path):
    _exercise(FaissFlat, tmp_path)


@pytest.mark.skipif(not FaissHNSW.available(), reason='FAISS BinaryHNSW not installed')
def test_faiss_hnsw_conformance(tmp_path):
    _exercise(FaissHNSW, tmp_path)


@pytest.mark.skipif(not NGT.available(), reason='ngtpy not installed')
def test_ngt_hamming_conformance(tmp_path):
    _exercise(NGT, tmp_path)
