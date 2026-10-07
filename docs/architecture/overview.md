# Architecture overview

ImageDupe is a single-host application. FastAPI and the CLI call the same application services; search/index logic is not duplicated in the presentation layers.

## Data path

1. **Collection scan** enumerates configured roots with include/exclude policies and extension allowlisting.
2. A stat tuple provides the fast unchanged path. Changed/new paths receive a streaming SHA-256 digest.
3. `content_sha256 + fingerprint_spec_id` is the durable reuse identity. Content recognized at a new path reuses the stored fingerprint.
4. Missing hashes are decoded/hashes in worker processes. Pillow validates the actual decoded format and preprocessing applies EXIF transpose, first-frame WEBP handling, fixed-background alpha compositing and luminance conversion.
5. The SQLite catalog stores image metadata, multiple versioned fingerprints, unique fingerprint buckets and posting-list membership.
6. Index builds consume one packed byte vector per live unique bucket.
7. A generation is saved off-path, manifested, checksummed, reloaded, count-checked and smoke-queried before atomic promotion.
8. Queries retrieve bucket candidates. New buckets after the active base generation are merged from an exact delta. Final candidate distances are independently recomputed with exact Hamming before bucket posting lists expand to image rows.

## Generation safety

The active backend handle is not closed when a new generation is promoted, so a query already holding the previous handle can finish safely. Loaded handles remain cached until process shutdown. Startup/fresh loads verify manifest compatibility and checksums; a corrupt active generation can fall back to a compatible ready generation while health remains degraded.

A catalog revision increments when scan/spec/root changes can affect search state. Generation manifests record the catalog revision they represent. This makes stale base indexes explicit, enables delta/tombstone accounting, and drives the PRD compaction thresholds.

## Backend contract

The adapters expose build/load/search/save/health/stats/close and a staging method. Implemented adapters are:

- `numpy-exact`: independent exact Hamming oracle/fallback.
- `faiss-binary-flat`: production exact baseline when FAISS is installed.
- `faiss-binary-hnsw`: Hamming-native ANN candidate backend.
- `ngt-hamming`: NGT Byte/Hamming ANN candidate backend.

No binary fingerprint is converted to a float embedding to fit a non-Hamming metric.

## Concurrency

Index jobs run off the request path. Fingerprinting uses a spawn-based `ProcessPoolExecutor`; query uploads use a bounded decode semaphore and run CPU decoding in FastAPI's worker threadpool. Rebuild promotion occurs only after cancellation and validation checkpoints.
