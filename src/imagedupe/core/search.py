from __future__ import annotations

import time
from pathlib import PurePath

from imagedupe.api.errors import ImageDupeError
from imagedupe.hashing.base import get_spec
from imagedupe.hashing.hamming import hamming_bytes, similarity_pct
from imagedupe.hashing.phash import encode_hash, fingerprint_bytes, parse_hash


class SearchService:
    def __init__(self, catalog, indexes, settings):
        self.catalog = catalog
        self.indexes = indexes
        self.settings = settings

    def coll(self, cid: str) -> dict:
        collection = self.catalog.get_collection(cid)
        if not collection:
            raise ImageDupeError(
                "COLLECTION_NOT_FOUND",
                "Collection does not exist",
                404,
                "Collection not found",
            )
        return collection

    def image(
        self,
        cid: str,
        data: bytes,
        filename: str,
        k: int = 20,
        backend: str = "auto",
        max_hamming: int | None = None,
        content_type: str | None = None,
    ) -> dict:
        self.catalog.increment_counter("search_requests_total")
        try:
            if len(data) > self.settings.max_upload_bytes:
                raise ImageDupeError(
                    "UPLOAD_TOO_LARGE",
                    "Encoded upload exceeded configured limit",
                    413,
                    "Upload too large",
                )
            if not filename or filename in {".", ".."} or "/" in filename or "\\" in filename or "\x00" in filename:
                raise ImageDupeError(
                    "UNSUPPORTED_IMAGE_FORMAT",
                    "Upload filename is invalid or contains path traversal characters",
                    415,
                    "Unsupported image",
                )
            suffix = PurePath(filename).suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                raise ImageDupeError(
                    "UNSUPPORTED_IMAGE_FORMAT",
                    "Query uploads require a JPG, JPEG, PNG, or WEBP filename",
                    415,
                    "Unsupported image",
                )
            if content_type and content_type.lower() not in {"image/jpeg", "image/png", "image/webp"}:
                raise ImageDupeError(
                    "UNSUPPORTED_IMAGE_FORMAT",
                    "Query upload content type is not JPEG, PNG, or WEBP",
                    415,
                    "Unsupported image",
                )
            spec = get_spec(self.coll(cid)["fingerprint_spec_id"])
            hash_started = time.perf_counter()
            fingerprint, metadata = fingerprint_bytes(
                data, spec.spec_id, self.settings.max_decoded_pixels, True
            )
            hash_ms = (time.perf_counter() - hash_started) * 1000
            query = {
                "filename": filename,
                "sha256": metadata["sha256"],
                "fingerprint_spec": spec.spec_id,
                "hash_hex": encode_hash(fingerprint, spec),
                "width": metadata["width"],
                "height": metadata["height"],
                "bytes": metadata["bytes"],
            }
            return self._search(
                cid,
                fingerprint,
                k,
                backend,
                max_hamming,
                metadata["sha256"],
                query,
                hash_ms,
            )
        except Exception:
            self.catalog.increment_counter("search_errors_total")
            raise

    def hash(
        self,
        cid: str,
        text: str,
        k: int = 20,
        backend: str = "auto",
        max_hamming: int | None = None,
    ) -> dict:
        self.catalog.increment_counter("search_requests_total")
        try:
            spec = get_spec(self.coll(cid)["fingerprint_spec_id"])
            try:
                fingerprint = parse_hash(text, spec)
            except ValueError as exc:
                message = str(exc)
                code = (
                    "FINGERPRINT_SPEC_MISMATCH"
                    if "mismatch" in message
                    else ("INVALID_HASH_LENGTH" if "length" in message else "INVALID_HASH_FORMAT")
                )
                raise ImageDupeError(
                    code,
                    message,
                    409 if code == "FINGERPRINT_SPEC_MISMATCH" else 422,
                    "Invalid perceptual hash",
                ) from exc
            return self._search(
                cid,
                fingerprint,
                k,
                backend,
                max_hamming,
                None,
                {
                    "filename": None,
                    "sha256": None,
                    "fingerprint_spec": spec.spec_id,
                    "hash_hex": encode_hash(fingerprint, spec),
                },
                0.0,
            )
        except Exception:
            self.catalog.increment_counter("search_errors_total")
            raise

    def _search(
        self,
        cid: str,
        fingerprint: bytes,
        k: int,
        backend: str,
        max_hamming: int | None,
        query_sha256: str | None,
        query_info: dict,
        query_hash_ms: float = 0.0,
    ) -> dict:
        collection = self.coll(cid)
        spec = get_spec(collection["fingerprint_spec_id"])
        try:
            k = int(k)
        except (TypeError, ValueError) as exc:
            raise ImageDupeError("INVALID_TOP_K", "Top K must be an integer", 422, "Invalid Top K") from exc
        if k < 1 or k > self.settings.max_top_k:
            raise ImageDupeError(
                "INVALID_TOP_K",
                f"Top K must be between 1 and {self.settings.max_top_k}",
                422,
                "Invalid Top K",
            )
        if max_hamming is not None:
            try:
                max_hamming = int(max_hamming)
            except (TypeError, ValueError) as exc:
                raise ImageDupeError(
                    "INVALID_MAX_HAMMING", "Max Hamming must be an integer", 422, "Invalid distance"
                ) from exc
            if max_hamming < 0 or max_hamming > spec.bits:
                raise ImageDupeError(
                    "INVALID_MAX_HAMMING",
                    f"Max Hamming must be between 0 and {spec.bits}",
                    422,
                    "Invalid distance",
                )

        candidate_k = max(self.settings.candidate_multiplier * k, 100)
        started = time.perf_counter()
        try:
            bucket_ids, _, generation, backend_ms = self.indexes.search(
                cid, fingerprint, candidate_k, backend
            )
        except RuntimeError as exc:
            raw = str(exc)
            known = {
                "INDEX_NOT_READY",
                "BACKEND_UNAVAILABLE",
                "FINGERPRINT_SPEC_MISMATCH",
                "INDEX_CHECKSUM_MISMATCH",
                "INDEX_MANIFEST_MISSING",
                "INDEX_MANIFEST_MISMATCH",
                "INDEX_VECTOR_COUNT_MISMATCH",
            }
            code = raw if raw in known else "INDEX_NOT_READY"
            status = 409 if code == "FINGERPRINT_SPEC_MISMATCH" else 503
            raise ImageDupeError(code, raw, status, "Search index unavailable") from exc

        hashes = self.catalog.bucket_hashes(bucket_ids.tolist())
        scored = sorted(
            ((bucket_id, hamming_bytes(fingerprint, hash_bytes)) for bucket_id, hash_bytes in hashes.items()),
            key=lambda item: (item[1], item[0]),
        )
        if max_hamming is not None:
            scored = [item for item in scored if item[1] <= max_hamming]

        members = self.catalog.images_for_buckets([item[0] for item in scored])
        expanded = []
        for bucket_id, distance in scored:
            for image in members.get(bucket_id, []):
                byte_exact = bool(query_sha256 and image.get("sha256") == query_sha256)
                if byte_exact:
                    classification = "BYTE_EXACT"
                elif distance == 0:
                    classification = "PERCEPTUAL_HASH_EXACT"
                elif max_hamming is not None and distance <= max_hamming:
                    classification = "NEAR_DUPLICATE"
                else:
                    classification = "NEAREST_RESULT"
                expanded.append(
                    (
                        distance,
                        not byte_exact,
                        image["relative_path"],
                        image["id"],
                        image,
                        classification,
                    )
                )
        expanded.sort(key=lambda item: item[:4])

        results = []
        for rank, (distance, _, _, _, image, classification) in enumerate(expanded[:k], 1):
            results.append(
                {
                    "rank": rank,
                    "image_id": image["id"],
                    "filename": image["filename"],
                    "relative_path": image["relative_path"],
                    "width": image["width"],
                    "height": image["height"],
                    "bytes": image["byte_size"],
                    "sha256": (image.get("sha256") or "")[:16],
                    "hamming_distance": distance,
                    "fingerprint_bits": spec.bits,
                    "hash_similarity_pct": round(similarity_pct(distance, spec.bits), 4),
                    "classification": classification,
                    "backend": generation["backend"],
                    "index_generation": generation.get("generation"),
                    "fingerprint_spec": spec.spec_id,
                    "thumbnail_url": f"/api/v1/images/{image['id']}/thumbnail",
                }
            )

        elapsed = (time.perf_counter() - started) * 1000
        self.catalog.record_query(
            cid,
            generation["backend"],
            generation.get("generation"),
            elapsed,
            backend_ms,
            query_hash_ms,
            len(results),
        )
        return {
            "query": query_info,
            "search": {
                "collection_id": cid,
                "backend": generation["backend"],
                "generation": generation.get("generation"),
                "k": k,
                "candidate_k": candidate_k,
                "backend_elapsed_ms": round(backend_ms, 3),
                "elapsed_ms": round(elapsed, 3),
                "max_hamming": max_hamming,
                "catalog_revision": collection["catalog_revision"],
            },
            "results": results,
        }
