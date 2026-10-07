# Benchmarking methodology

`imagedupe benchmark COLLECTION_ID` measures backend search latency and Recall@K against an independent NumPy brute-force Hamming ground truth. It emits a human-readable summary to stderr and machine-readable JSON to stdout; `--json-output path.json` persists the report.

Reports include:

- platform, Python and CPU count;
- NumPy/Pillow/SciPy and optional FAISS/NGT versions;
- fingerprint specification;
- image and unique-bucket counts;
- selected backend/generation and backend configuration;
- p50/p95/p99 backend-query latency;
- Recall@K;
- catalog revision and warm-index cache state.

The HTTP benchmark endpoint uses the same implementation and stores the latest report on a persisted generation so diagnostics can expose its measured recall.

## Release corpus

`python benchmarks/generate_corpus.py` creates a small smoke corpus with JPEG re-encoding, brightness, blur and resize variants. It is not a substitute for the PRD release corpus. Release quality evaluation should add the full positive/negative transformations described in the PRD and record a dataset-manifest hash and random seed.

The PRD's default ANN release target is Recall@20 >= 0.98 (and Recall@100 >= 0.98 for Top-100). Do not claim those values merely because the implementation exists: they must be measured with FAISS BinaryFlat/independent exact ground truth on release hardware and the labeled release corpus.
