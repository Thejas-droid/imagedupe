# Security and privacy

ImageDupe treats query uploads and collection files as untrusted image input.

## Query upload controls

- Encoded request limit (20 MiB default).
- JPG/JPEG/PNG/WEBP filename extension allowlist.
- HTTP content-type allowlist when a content type is supplied; it is never accepted as proof of the decoded type.
- Pillow `Image.open(..., formats=[...])` decoded-format restriction.
- Decompression-bomb warnings become errors on the query path.
- Independent decoded-pixel ceiling (50 MP default).
- Traversal-style upload names are rejected and never select filesystem paths.
- Query decoding concurrency is bounded and requests are rate-limited.
- Query bytes are processed in memory and are not permanently persisted.

## Collection behavior

Original source images are read-only. Derived thumbnails are re-encoded JPEGs and do not preserve source EXIF/XMP. Normal search results expose relative paths, not absolute source paths. Browser collection roots honor the privacy-path setting.

## CSV export

CSV cells beginning with spreadsheet formula prefixes (`=`, `+`, `-`, `@`) are neutralized before export. The same behavior has a Python unit-tested helper and the browser export implementation.

## Network exposure

The default bind is loopback. Remote binding is an explicit operator choice and produces a CLI warning. v1 is not a multi-tenant authenticated SaaS service; use an authenticated reverse proxy/network boundary if exposing it remotely.
