# Native installation

ImageDupe v1 is intentionally container-free. The supported CI matrix is Python 3.11, 3.12 and 3.13 on Linux; macOS is Tier 2 and Windows is best effort per the PRD.

## CPU/reference install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[test]'
imagedupe doctor
pytest
```

This path includes the independent NumPy exact backend used as the conformance oracle and fallback.

## FAISS production binary path

```bash
pip install -e '.[faiss,test]'
imagedupe doctor
pytest tests/conformance tests/integration
```

`imagedupe doctor` must report `faiss_binary_flat: true`. If the installed FAISS build exposes `IndexBinaryHNSW`, it also reports `faiss_binary_hnsw: true`. On platforms without a compatible PyPI wheel, install FAISS through the platform/Conda mechanism first, then install ImageDupe.

## NGT

```bash
pip install -e '.[ngt,test]'
imagedupe doctor
pytest tests/conformance/test_backend_roundtrip.py
```

NGT is optional at runtime. An unavailable NGT package never prevents exact/FAISS operation.

## CUDA

CUDA is capability-gated. `CUDA mode = On` without a detected compatible **binary** GPU index produces degraded health and CPU fallback rather than changing correctness. The standard FAISS GPU documentation primarily describes floating-point Flat/IVF/PQ indexes, so ImageDupe does not infer binary GPU capability merely from the presence of a GPU.

## Reproducibility

`requirements.lock` is a delivery-environment snapshot. To reproduce that verified CPU/test environment:

```bash
pip install -r requirements.lock
pip install -e . --no-deps
pytest
```

For cross-platform supported installs, use `pyproject.toml` dependency ranges.

## Storage and environment variables

Data defaults to `~/.local/share/imagedupe`; set `IMAGEDUPE_HOME` before startup to choose a different catalog/index/thumbnail root. Common overrides include:

- `IMAGEDUPE_HOST`, `IMAGEDUPE_PORT`
- `IMAGEDUPE_WORKERS`, `IMAGEDUPE_WORKER_CAP`
- `IMAGEDUPE_MAX_UPLOAD_BYTES`, `IMAGEDUPE_MAX_DECODED_PIXELS`
- `IMAGEDUPE_INGEST_MAX_DECODED_PIXELS`
- `IMAGEDUPE_HASH_TIMEOUT_SECONDS`
- `IMAGEDUPE_RATE_LIMIT`
- `IMAGEDUPE_QUERY_DECODE_CONCURRENCY`

The default bind is loopback. Binding beyond loopback emits a warning because v1 is local/single-user and does not implement multi-tenant authentication.
