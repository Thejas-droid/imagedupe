# ImageDupe v1 implementation and verification report

## Delivery status

The repository implements the supplied ImageDupe v1 product surface as a native single-host Python application. The implementation keeps the PRD's correctness invariants: binary perceptual fingerprints, Hamming ranking, SHA-256 for byte identity, unique fingerprint buckets/posting lists, exact re-ranking after ANN candidate retrieval, immutable index generations, incremental cache reuse, and CPU-first operation.

The code is implementation-complete for the P0 application surface. A few **release-certification gates are intentionally not claimed as passed in this delivery environment** because they require optional native libraries, the labeled release corpus, reference-scale hardware, or a real browser accessibility audit. Those gates are called out below rather than being replaced with synthetic claims.

## Implemented product surface

- Collection CRUD with multiple roots, recursion, symlink policy, include/exclude globs, incremental scans, skipped/failed/missing-file reporting, cache statistics, and source files treated read-only.
- Secure JPEG/PNG/WEBP decoding with encoded-size limits, decoded-pixel limits, decompression-bomb handling, decoded-format validation, EXIF transpose, deterministic alpha compositing, first-frame WEBP behavior, and bounded query decode concurrency.
- Deterministic pHash-64 and pHash-256 specifications with stable byte packing and canonical textual hashes.
- SHA-256 byte identity, content-addressed fingerprint cache, move reuse, spec invalidation, and unique fingerprint buckets with member posting lists.
- Multicore cold hashing with configurable worker count, cooperative cancellation, per-file timeout protection on POSIX, and progress/error accounting.
- Independent NumPy exact-Hamming oracle/fallback, FAISS BinaryFlat, FAISS BinaryHNSW, and NGT Hamming/Byte adapters behind one index manager.
- Immutable generation build/validate/checksum/persist/promote lifecycle, load-time manifest/checksum validation, corrupt-generation fallback, crash cleanup, and in-flight old-generation safety.
- Base + exact delta search for incremental additions, tombstone filtering, and PRD compaction-threshold reporting.
- Query-by-image and query-by-hash, Top-K, max-Hamming filtering, exact candidate reranking, deterministic tie order, and BYTE_EXACT / PERCEPTUAL_HASH_EXACT / NEAR_DUPLICATE / NEAREST_RESULT classification.
- JSON/CSV export semantics including spreadsheet-formula neutralization.
- OpenAPI 3.1 HTTP API, Problem Details responses, collection/jobs/index endpoints, ETag job polling, health/readiness/status/metrics/doctor endpoints, derived thumbnails, request IDs, local rate limiting, and backend availability reporting.
- CLI: `serve`, `doctor`, collection add/list/show/scan/failures, index build/list/activate, image/hash search, benchmark, and status.
- Browser Search / Collections / Settings UI with keyboard-accessible tabs/dropzone, preview, backend states, grid/list results, expanded metadata, exports, status strip, collection lifecycle actions, settings groups, and diagnostics.
- Native installation docs, locked delivery-environment dependency snapshot, benchmark/corpus tooling, security docs, CI, smoke checks, and repository audit. No Docker/container deliverables are present.

## Automated verification in this delivery environment

Final local suite:

- **42 tests collected**
- **39 passed**
- **3 skipped**
- **0 failed**

The three skips are the native backend round-trip tests for FAISS BinaryFlat, FAISS BinaryHNSW, and NGT because `faiss` and `ngtpy` are not installed in this execution environment. Those tests are part of the repository and automatically execute when their optional packages are installed. CI also has a required FAISS conformance job and an optional NGT conformance job.

Passing coverage includes:

- golden pHash-64/pHash-256 vectors, EXIF orientation equivalence, deterministic alpha handling, hash parsing/length checks, Hamming identity/symmetry;
- NumPy exact-backend serialization and independent exact-Hamming conformance;
- create → scan → build → image search and image/hash parity;
- incremental unchanged reuse, moved-content reuse, file add/update/delete, delta search, tombstone filtering, stale-index behavior;
- byte-exact versus perceptual-hash-exact classification and max-Hamming behavior;
- rebuild concurrency, cancellation before promotion, failed/corrupt generation recovery, process-restart index loading, incompatible-spec activation rejection;
- include/exclude globs, skipped/failed reporting, multicore scan configuration, settings persistence, health/metrics/problem-response behavior;
- encoded/decode validation, fake extension, invalid MIME, traversal-like upload name, decompression-bomb warning path, rate limiting, decoded-pixel ceiling, CSV formula neutralization;
- benchmark exact-ground-truth metadata and static browser workflow/accessibility contract checks.

Additional final checks run by `scripts/smoke.sh`:

- repository audit;
- Python bytecode compilation for source/tests/benchmark tools;
- frontend JavaScript syntax validation when Node is available;
- full pytest suite;
- CLI help and `imagedupe doctor` startup.

Packaging/reference-flow verification also succeeded: a wheel was built from `pyproject.toml`, installed into an isolated target directory without dependency downloads, imported from that installed target, and used for a real CLI create → scan → exact build → image search → hash search → benchmark workflow. Image/hash result IDs matched and the independent exact benchmark reported recall@K = 1.0 for the smoke fixture.

## PRD acceptance matrix

| # | Acceptance criterion | Delivery status |
|---:|---|---|
| 1 | Create/index JPEG/PNG/WEBP collection and image search | Implemented + automated integration test |
| 2 | Search same index by perceptual hash | Implemented + parity test |
| 3 | Exact results match independent NumPy Hamming oracle | Implemented + conformance test |
| 4 | ANN Recall@20 >= 0.98 on release corpus | **Release-corpus/native-backend gate; not claimed here** |
| 5 | Exact-Hamming re-rank after ANN candidate retrieval | Implemented + search/conformance coverage |
| 6 | Hash-equal byte-different is not mislabeled byte-exact | Implemented + test |
| 7 | Incremental rescans reuse unchanged fingerprints | Implemented + test |
| 8 | Indexing/fingerprinting is multicore | Implemented + test/config coverage |
| 9 | Failed rebuild leaves previous generation searchable | Implemented + reliability tests |
| 10 | Query upload byte/pixel limits | Implemented + security tests |
| 11 | Search UI follows required information architecture/interactions | Implemented + static/API workflow checks |
| 12 | Grid/list and JSON/CSV export | Implemented + tests/contracts |
| 13 | Health, active generation, backend, query latency | Implemented + API tests |
| 14 | CPU-only installation/core tests | Implemented; verified in delivery environment |
| 15 | CUDA failure degrades cleanly to CPU | Capability-gated; degradation test without CUDA |
| 16 | Native installation documentation | Complete |
| 17 | No Docker/container runtime requirement | Repository audit enforces absence |
| 18 | WCAG 2.2 AA critical checks | Semantics/keyboard/focus/live-status design implemented; **full browser/manual AA certification remains a release gate** |
| 19 | Benchmark reports ground truth/hardware/config/dependencies | Implemented + automated report test; reference-scale runs remain release-hardware work |
| 20 | Required repository CI checks | CI definitions supplied; local equivalents pass |

## Performance and ANN release gates

The repository intentionally does **not** assert the PRD's 100k/1M/10M latency targets or ANN Recall@20/Recall@100 targets from this machine. Those require:

1. the labeled release evaluation corpus;
2. installed FAISS and/or NGT native backends;
3. the documented reference CPU host (and optional GPU profile);
4. warm/cold runs with backend tuning recorded.

`imagedupe benchmark` reports independent exact ground truth, recall@K, p50/p95/p99, backend configuration, fingerprint specification, collection/vector counts, dependency versions, platform/Python facts, and reproducibility metadata. `benchmarks/generate_corpus.py` supplies controlled local fixtures for development; it is not a substitute for the labeled release corpus.

## Optional native and CUDA status

This delivery runtime does not include FAISS, NGT, or CUDA. Core correctness therefore runs through the independent NumPy binary-Hamming path. Optional backend capability is detected at runtime and unavailable backends do not prevent startup/search through the exact fallback.

The CUDA control only reports binary GPU acceleration as usable when the installed FAISS Python build exposes a compatible binary-GPU index path; generic FAISS GPU availability is not treated as proof that binary Hamming GPU search exists.

## Reproduce the verification

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[test]'
./scripts/smoke.sh
```

FAISS conformance:

```bash
pip install -e '.[test,faiss]'
pytest tests/conformance tests/integration tests/security
```

NGT conformance, on supported hosts:

```bash
pip install -e '.[test,ngt]'
pytest tests/conformance/test_backend_roundtrip.py
```

For exact delivery-environment CPU/test package versions, see `requirements.lock`.
