# ImageDupe

ImageDupe is a local/self-hosted near-duplicate image search engine built around deterministic perceptual fingerprints and **Hamming distance**. It implements the supplied v1 PRD as a native Python application: browser UI, HTTP API, CLI, SQLite catalog, multicore fingerprinting, immutable binary-index generations, incremental cache reuse, and exact Hamming re-ranking.

## What is implemented

- Versioned pHash-64 and pHash-256 fingerprints with EXIF orientation normalization, fixed alpha compositing, stable big-endian bit packing, and golden-vector tests.
- SHA-256 byte identity kept separate from perceptual-hash identity.
- JPEG/JPG, PNG, and WEBP collection scans with recursive roots, include/exclude globs, optional symlink following, failed-file reporting, multicore hashing, per-file POSIX timeout protection, and content-addressed reuse after moves.
- Unique fingerprint buckets plus image posting lists: duplicate vectors are not repeatedly inserted into HNSW/NGT.
- Persisted immutable generations with manifests, configuration/version metadata, streaming checksums, load validation, smoke queries, atomic promotion, corrupt-generation fallback, and crash cleanup.
- Exact NumPy oracle/reference backend, production FAISS `IndexBinaryFlat`, FAISS `IndexBinaryHNSW`, and NGT Hamming/Byte adapters behind one manager interface.
- Base + exact-delta search for safe incremental additions; tombstones are filtered and compaction thresholds are exposed.
- Query-by-image and query-by-hash, Top-K, optional max-Hamming threshold, exact ANN candidate re-ranking, deterministic tie ordering, and byte/perceptual/near/nearest classifications.
- FastAPI OpenAPI 3.1 API with Problem Details errors, polling ETags, request IDs, rate limiting, bounded concurrent query decoding, derived thumbnails, system health, metrics, diagnostics, and benchmarks.
- Browser Search / Collections / Settings UI with image/hash tabs, keyboard-operated dropzone, preview, backend capability states, grid/list results, JSON/CSV export, collection jobs/failures/benchmarks/generations, status strip, and persisted search defaults.
- CLI for serving, diagnostics, collections, scanning, index build/list/activation, image/hash search, benchmark, and status.
- Native-only installation; there are intentionally no Docker/container artifacts.

## Windows desktop app (offline)

Download **ImageDupe-Setup.exe** from the release downloads, run it, then open **ImageDupe** from the desktop or Start menu. Python and the image-processing dependencies are included. No terminal, account, internet connection, or hosting subscription is needed to use the app.

ImageDupe opens in its own desktop window with a custom app icon and a bundled Qt renderer. In **Image folders → Add image folder**, click **Choose folder…**, select your local photo folder, and click **Add folder & scan images**. Close the window to stop the application. Opening ImageDupe again brings the existing window forward. CSV and JSON exports use a native Save dialog.

New desktop installs save data under `%LOCALAPPDATA%\ImageDupe\data`. Existing Windows CLI catalogs under `%USERPROFILE%\.local\share\imagedupe` are reused if present. Updates and uninstall preserve catalogs and original images. A portable ZIP is also available: extract the entire folder and open `ImageDupe.exe`.

See [Windows packaging and release instructions](docs/installation/windows-desktop.md).

## Native quick start

Python **3.11–3.13** is the tested matrix in CI.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
pip install -e '.[test]'
imagedupe doctor
imagedupe serve
```

Open <http://127.0.0.1:8765>.

### Using the browser

1. Choose **Image folders → Add image folder**.
2. Paste the full path to a folder containing JPG, PNG, or WEBP images. On Windows, copy it from File Explorer’s address bar (for example `C:\Users\theja\Downloads`). Quoted paths and spaces are accepted. The folder name is optional.
3. Choose **Add folder & scan images**. ImageDupe scans the folder and automatically prepares its search index. Wait for **Ready to search**.
4. Choose **Search this folder**, select or drop a reference image, and choose **Find similar images**.

Search defaults to **60% minimum similarity**. Images below that fingerprint-agreement score are filtered out; **Maximum results** is a cap, so requesting 100 does not add weaker matches to fill the list. Raise the minimum to 70–100% for stricter results, or explicitly choose **Show all · exploration** to browse nearest images without a cutoff. A custom Hamming limit in Advanced search overrides the percentage selection. Similarity is fingerprint agreement, not a probability that two photos are duplicates.

For a previously scanned folder without an index, choose **Prepare for search**. Use **Scan for changes** after adding or removing photos. An empty scan explains which image formats are supported; invalid paths and job failures remain visible so you can correct them. Technical controls are available under **Advanced** and **Folder details & management**.

The base install uses the NumPy exact implementation as an independent oracle/fallback. For the PRD's production FAISS BinaryFlat path and FAISS BinaryHNSW candidate:

```bash
pip install -e '.[faiss,test]'
imagedupe doctor
pytest tests/conformance tests/integration
```

NGT is optional and platform-dependent:

```bash
pip install -e '.[ngt,test]'
```

CUDA is optional and never required for correctness. ImageDupe only reports binary-GPU acceleration as available when the installed FAISS Python build actually exposes a compatible binary GPU index. Standard FAISS GPU support should not be assumed to cover binary indexes.

`requirements.lock` records the exact CPU/test dependency versions used for the final delivery verification. The looser `pyproject.toml` ranges remain the supported install contract across the Python matrix.

## CLI workflow

```bash
imagedupe collection add photos --root /absolute/path/to/images --exclude 'cache/**'
imagedupe collection list
imagedupe collection scan COLLECTION_ID
imagedupe index build COLLECTION_ID --backend auto
imagedupe search image COLLECTION_ID query.jpg --k 20
imagedupe search hash COLLECTION_ID 'phash:256:...'
imagedupe benchmark COLLECTION_ID --json-output benchmark.json
imagedupe status COLLECTION_ID
```

`imagedupe doctor` redacts full configured paths by default. Use `--show-paths` when you explicitly want them printed.

## Correctness invariants

1. Hamming distance is the ranking source of truth; “Hash similarity” is only bit agreement, not a duplicate probability.
2. SHA-256 means byte identity. Hamming distance 0 only means the perceptual fingerprint is equal.
3. ANN backends return candidates; ImageDupe computes exact Hamming distances before final ordering.
4. The active generation is never mutated in place. A new generation is built, validated, checksummed, persisted, then atomically promoted.
5. A failed/cancelled rebuild never removes the last known-good generation.
6. Explicit Exact search uses the current catalog and never silently routes through ANN.
7. Query uploads are untrusted input: byte/pixel limits, filename/content-type allowlists, Pillow decoded-format validation, decompression-bomb handling, traversal rejection, and bounded decode concurrency are enforced.

## Tests

```bash
pytest -q
```

The final delivery environment executes all core, API, security, lifecycle, benchmark, UI-structure, and NumPy conformance tests. FAISS BinaryFlat, FAISS BinaryHNSW, and NGT serialization/conformance tests automatically unskip when those optional native packages are installed.

See:

- `docs/installation/native.md`
- `docs/architecture/overview.md`
- `docs/security.md`
- `docs/benchmarking/methodology.md`
- `docs/release-report.md`
- `docs/references.md`
