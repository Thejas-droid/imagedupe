# Diagnostics and troubleshooting

Run:

```bash
imagedupe doctor
```

It reports Python, NumPy, Pillow, SciPy, FAISS BinaryFlat/BinaryHNSW capability, NGT, GPU count/binary-GPU capability, CPU/RAM/disk, writable catalog/index/thumbnail paths, supported fingerprint specs, and collection/index fingerprint compatibility.

Full filesystem paths are redacted by default. Use `imagedupe doctor --show-paths` only when needed.

Common states:

- `faiss_binary_flat: false`: install the `faiss` extra or platform FAISS package for the production exact backend. NumPy exact remains available as the independent oracle/fallback.
- `faiss_binary_hnsw: false`: HNSW is disabled in the UI; use exact or NGT if available.
- `ngt_available: false`: NGT is skipped; this does not block exact/FAISS operation.
- `cuda_status: requested-but-unavailable`: CPU remains correct and system health is degraded until CUDA mode is Auto/Off or compatible binary GPU support is installed.
- collection health `degraded` after a scan: the immutable base generation is stale. New unique buckets are searched through the exact delta, but rebuild/compaction is recommended when the displayed threshold is reached.
