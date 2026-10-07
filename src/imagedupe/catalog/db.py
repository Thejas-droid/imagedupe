from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS collections(
    id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    fingerprint_spec_id TEXT NOT NULL,
    backend_policy TEXT NOT NULL DEFAULT 'auto',
    active_generation INTEGER,
    catalog_revision INTEGER NOT NULL DEFAULT 0,
    last_scan_at TEXT,
    last_scan_stats_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collection_roots(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    recursive INTEGER NOT NULL DEFAULT 1,
    follow_symlinks INTEGER NOT NULL DEFAULT 0,
    include_globs_json TEXT NOT NULL DEFAULT '[]',
    exclude_globs_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS images(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    byte_size INTEGER NOT NULL DEFAULT 0,
    mtime_ns INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT,
    width INTEGER,
    height INTEGER,
    format TEXT,
    status TEXT NOT NULL DEFAULT 'valid',
    last_seen_scan_id TEXT,
    error_code TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(collection_id,path)
);
CREATE INDEX IF NOT EXISTS idx_images_sha ON images(collection_id,sha256);
CREATE INDEX IF NOT EXISTS idx_images_status ON images(collection_id,status);

CREATE TABLE IF NOT EXISTS fingerprint_buckets(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    fingerprint_spec_id TEXT NOT NULL,
    hash_bytes BLOB NOT NULL,
    member_count INTEGER NOT NULL DEFAULT 0,
    tombstoned INTEGER NOT NULL DEFAULT 0,
    UNIQUE(collection_id,fingerprint_spec_id,hash_bytes)
);

CREATE TABLE IF NOT EXISTS fingerprints(
    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
    fingerprint_spec_id TEXT NOT NULL,
    hash_bytes BLOB NOT NULL,
    bucket_id INTEGER REFERENCES fingerprint_buckets(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY(image_id,fingerprint_spec_id)
);
CREATE INDEX IF NOT EXISTS idx_fp_bucket ON fingerprints(bucket_id);

CREATE TABLE IF NOT EXISTS index_generations(
    collection_id TEXT NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    generation INTEGER NOT NULL,
    backend TEXT NOT NULL,
    backend_version TEXT,
    fingerprint_spec_id TEXT NOT NULL,
    config_json TEXT NOT NULL,
    vector_count INTEGER NOT NULL,
    image_count INTEGER NOT NULL,
    catalog_revision INTEGER NOT NULL DEFAULT 0,
    disk_path TEXT NOT NULL,
    checksum TEXT NOT NULL,
    build_started_at TEXT,
    build_ended_at TEXT,
    status TEXT NOT NULL,
    benchmark_json TEXT,
    PRIMARY KEY(collection_id,generation,backend)
);

CREATE TABLE IF NOT EXISTS jobs(
    id TEXT PRIMARY KEY,
    collection_id TEXT,
    type TEXT NOT NULL,
    state TEXT NOT NULL,
    progress_json TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    stats_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS query_metrics(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    collection_id TEXT,
    backend TEXT,
    generation INTEGER,
    elapsed_ms REAL NOT NULL,
    backend_ms REAL NOT NULL,
    hash_ms REAL NOT NULL DEFAULT 0,
    result_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metric_counters(
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS app_settings(
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL
);
"""


class Catalog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            self._migrate(connection)
            connection.execute(
                "UPDATE jobs SET state='ABORTED',ended_at=? "
                "WHERE state NOT IN ('SUCCEEDED','FAILED','CANCELLED','ABORTED')",
                (utcnow(),),
            )

    def _migrate(self, connection: sqlite3.Connection) -> None:
        def columns(table: str) -> set[str]:
            return {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}

        collection_columns = columns("collections")
        for name, definition in {
            "catalog_revision": "INTEGER NOT NULL DEFAULT 0",
            "last_scan_at": "TEXT",
            "last_scan_stats_json": "TEXT NOT NULL DEFAULT '{}'",
        }.items():
            if name not in collection_columns:
                connection.execute(f"ALTER TABLE collections ADD COLUMN {name} {definition}")

        generation_columns = columns("index_generations")
        if "catalog_revision" not in generation_columns:
            connection.execute(
                "ALTER TABLE index_generations ADD COLUMN catalog_revision INTEGER NOT NULL DEFAULT 0"
            )

        query_columns = columns("query_metrics")
        if "hash_ms" not in query_columns:
            connection.execute("ALTER TABLE query_metrics ADD COLUMN hash_ms REAL NOT NULL DEFAULT 0")
        if "result_count" not in query_columns:
            connection.execute("ALTER TABLE query_metrics ADD COLUMN result_count INTEGER NOT NULL DEFAULT 0")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            yield connection
        finally:
            connection.close()

    def ping(self) -> bool:
        try:
            with self.connect() as connection:
                return connection.execute("SELECT 1").fetchone()[0] == 1
        except sqlite3.Error:
            return False

    def create_collection(
        self, name: str, roots: list[dict], spec_id: str, backend_policy: str = "auto"
    ) -> dict:
        cid = str(uuid.uuid4())
        now = utcnow()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO collections(" 
                "id,name,fingerprint_spec_id,backend_policy,active_generation,catalog_revision,"
                "last_scan_at,last_scan_stats_json,created_at,updated_at"
                ") VALUES(?,?,?,?,NULL,0,NULL,'{}',?,?)",
                (cid, name, spec_id, backend_policy, now, now),
            )
            for root in roots:
                connection.execute(
                    "INSERT INTO collection_roots("
                    "collection_id,path,recursive,follow_symlinks,include_globs_json,exclude_globs_json"
                    ") VALUES(?,?,?,?,?,?)",
                    (
                        cid,
                        str(Path(root["path"]).expanduser().resolve()),
                        int(root.get("recursive", True)),
                        int(root.get("follow_symlinks", False)),
                        json.dumps(root.get("include_globs", [])),
                        json.dumps(root.get("exclude_globs", [])),
                    ),
                )
            connection.execute("COMMIT")
        return self.get_collection(cid)

    def list_collections(self) -> list[dict]:
        with self.connect() as connection:
            ids = [row["id"] for row in connection.execute("SELECT id FROM collections ORDER BY name")]
        return [self.get_collection(cid) for cid in ids]

    def get_collection(self, cid: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM collections WHERE id=?", (cid,)).fetchone()
            if not row:
                return None
            roots = [
                dict(root)
                for root in connection.execute(
                    "SELECT * FROM collection_roots WHERE collection_id=? ORDER BY id", (cid,)
                )
            ]
            counts = connection.execute(
                "SELECT COUNT(*) total,"
                "COALESCE(SUM(status='valid'),0) valid,"
                "COALESCE(SUM(status='failed'),0) failed,"
                "COALESCE(SUM(status='missing'),0) missing "
                "FROM images WHERE collection_id=?",
                (cid,),
            ).fetchone()
            buckets = connection.execute(
                "SELECT COUNT(*) n FROM fingerprint_buckets "
                "WHERE collection_id=? AND fingerprint_spec_id=? AND tombstoned=0",
                (cid, row["fingerprint_spec_id"]),
            ).fetchone()["n"]
            active = self._active_generation_row(connection, cid, row["active_generation"])
            latest_build = connection.execute(
                "SELECT build_ended_at FROM index_generations WHERE collection_id=? "
                "AND status IN ('ACTIVE','READY','STALE') ORDER BY generation DESC LIMIT 1",
                (cid,),
            ).fetchone()

        for root in roots:
            root["recursive"] = bool(root["recursive"])
            root["follow_symlinks"] = bool(root["follow_symlinks"])
            root["include_globs"] = json.loads(root.pop("include_globs_json"))
            root["exclude_globs"] = json.loads(root.pop("exclude_globs_json"))

        data = dict(row)
        scan_stats = json.loads(data.pop("last_scan_stats_json") or "{}")
        data["last_scan_stats"] = scan_stats
        data["cache_hit_rate"] = self._cache_hit_rate(scan_stats)
        data["roots"] = roots
        data["counts"] = {
            "total": counts["total"] or 0,
            "valid": counts["valid"] or 0,
            "failed": counts["failed"] or 0,
            "missing": counts["missing"] or 0,
            "skipped": int(scan_stats.get("skipped", 0)),
            "unique_buckets": buckets or 0,
        }
        data["active_index"] = self._decode_generation(active) if active else None
        data["active_index_size_bytes"] = 0
        if data["active_index"]:
            try:
                data["active_index_size_bytes"] = sum(
                    path.stat().st_size
                    for path in Path(data["active_index"]["disk_path"]).rglob("*")
                    if path.is_file()
                )
            except OSError:
                data["active_index_size_bytes"] = 0
        data["last_successful_build"] = latest_build["build_ended_at"] if latest_build else None
        data["health"] = self.collection_health_from(data)
        return data

    @staticmethod
    def _cache_hit_rate(stats: dict) -> float:
        considered = int(stats.get("cached", 0)) + int(stats.get("content_reused", 0)) + int(
            stats.get("hashed", 0)
        )
        if considered <= 0:
            return 0.0
        return round(
            100.0
            * (int(stats.get("cached", 0)) + int(stats.get("content_reused", 0)))
            / considered,
            2,
        )

    def collection_health_from(self, collection: dict) -> str:
        active = collection.get("active_index")
        if not active:
            return "building" if self.active_job_for_collection(collection["id"]) else "degraded"
        if active.get("fingerprint_spec_id") != collection.get("fingerprint_spec_id"):
            return "degraded"
        if int(active.get("catalog_revision", 0)) < int(collection.get("catalog_revision", 0)):
            return "degraded"
        if active.get("status") in {"DEGRADED", "FAILED"}:
            return "degraded"
        if self.active_job_for_collection(collection["id"]):
            return "building"
        return "healthy"

    def update_collection(self, cid: str, changes: dict) -> dict:
        allowed = {"name", "fingerprint_spec_id", "backend_policy"}
        fields: list[str] = []
        values: list[Any] = []
        current = self.get_collection(cid)
        if not current:
            raise KeyError(cid)
        revision_change = False
        for key, value in changes.items():
            if key in allowed and value is not None:
                fields.append(f"{key}=?")
                values.append(value)
                if key == "fingerprint_spec_id" and value != current["fingerprint_spec_id"]:
                    revision_change = True
        if fields:
            fields.append("updated_at=?")
            values.append(utcnow())
            if revision_change:
                fields.append("catalog_revision=catalog_revision+1")
            values.append(cid)
            with self.connect() as connection:
                connection.execute(
                    f"UPDATE collections SET {','.join(fields)} WHERE id=?", values
                )
        return self.get_collection(cid)

    def replace_roots(self, cid: str, roots: list[dict]) -> dict:
        if not self.get_collection(cid):
            raise KeyError(cid)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM collection_roots WHERE collection_id=?", (cid,))
            for root in roots:
                connection.execute(
                    "INSERT INTO collection_roots("
                    "collection_id,path,recursive,follow_symlinks,include_globs_json,exclude_globs_json"
                    ") VALUES(?,?,?,?,?,?)",
                    (
                        cid,
                        str(Path(root["path"]).expanduser().resolve()),
                        int(root.get("recursive", True)),
                        int(root.get("follow_symlinks", False)),
                        json.dumps(root.get("include_globs", [])),
                        json.dumps(root.get("exclude_globs", [])),
                    ),
                )
            connection.execute(
                "UPDATE collections SET catalog_revision=catalog_revision+1,updated_at=? WHERE id=?",
                (utcnow(), cid),
            )
            connection.execute("COMMIT")
        return self.get_collection(cid)

    def delete_collection(self, cid: str) -> bool:
        with self.connect() as connection:
            return connection.execute("DELETE FROM collections WHERE id=?", (cid,)).rowcount > 0

    def cached_stat(self, cid: str, path: str, size: int, mtime_ns: int, spec_id: str):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT i.*,f.hash_bytes,f.bucket_id FROM images i "
                "JOIN fingerprints f ON f.image_id=i.id "
                "WHERE i.collection_id=? AND i.path=? AND i.byte_size=? AND i.mtime_ns=? "
                "AND f.fingerprint_spec_id=? AND i.status='valid'",
                (cid, path, size, mtime_ns, spec_id),
            ).fetchone()
            return dict(row) if row else None

    def content_cache(self, cid: str, sha256: str, spec_id: str):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT i.width,i.height,i.format,f.hash_bytes FROM images i "
                "JOIN fingerprints f ON f.image_id=i.id "
                "WHERE i.collection_id=? AND i.sha256=? AND f.fingerprint_spec_id=? "
                "ORDER BY (i.status='valid') DESC,i.id LIMIT 1",
                (cid, sha256, spec_id),
            ).fetchone()
            return dict(row) if row else None

    def touch(self, image_id: int, scan_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE images SET last_seen_scan_id=?,status='valid',updated_at=? WHERE id=?",
                (scan_id, utcnow(), image_id),
            )

    def upsert_image_fp(self, cid: str, row: dict, spec_id: str, fp: bytes, scan_id: str) -> int:
        now = utcnow()
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute(
                "SELECT id FROM images WHERE collection_id=? AND path=?", (cid, row["path"])
            ).fetchone()
            if old:
                image_id = old["id"]
                connection.execute(
                    "UPDATE images SET relative_path=?,filename=?,byte_size=?,mtime_ns=?,sha256=?,"
                    "width=?,height=?,format=?,status='valid',last_seen_scan_id=?,error_code=NULL,"
                    "updated_at=? WHERE id=?",
                    (
                        row["relative_path"],
                        row["filename"],
                        row["byte_size"],
                        row["mtime_ns"],
                        row["sha256"],
                        row["width"],
                        row["height"],
                        row["format"],
                        scan_id,
                        now,
                        image_id,
                    ),
                )
            else:
                image_id = connection.execute(
                    "INSERT INTO images(collection_id,path,relative_path,filename,byte_size,mtime_ns,"
                    "sha256,width,height,format,status,last_seen_scan_id,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,'valid',?,?)",
                    (
                        cid,
                        row["path"],
                        row["relative_path"],
                        row["filename"],
                        row["byte_size"],
                        row["mtime_ns"],
                        row["sha256"],
                        row["width"],
                        row["height"],
                        row["format"],
                        scan_id,
                        now,
                    ),
                ).lastrowid

            bucket = connection.execute(
                "SELECT id FROM fingerprint_buckets WHERE collection_id=? "
                "AND fingerprint_spec_id=? AND hash_bytes=?",
                (cid, spec_id, fp),
            ).fetchone()
            bucket_id = (
                bucket["id"]
                if bucket
                else connection.execute(
                    "INSERT INTO fingerprint_buckets(collection_id,fingerprint_spec_id,hash_bytes) "
                    "VALUES(?,?,?)",
                    (cid, spec_id, fp),
                ).lastrowid
            )
            connection.execute(
                "UPDATE fingerprint_buckets SET tombstoned=0 WHERE id=?", (bucket_id,)
            )
            connection.execute(
                "INSERT INTO fingerprints(image_id,fingerprint_spec_id,hash_bytes,bucket_id,created_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(image_id,fingerprint_spec_id) DO UPDATE SET "
                "hash_bytes=excluded.hash_bytes,bucket_id=excluded.bucket_id,created_at=excluded.created_at",
                (image_id, spec_id, fp, bucket_id, now),
            )
            self._recount(connection, cid, spec_id)
            connection.execute("COMMIT")
            return int(image_id)

    def mark_failed(
        self,
        cid: str,
        path: str,
        relative: str,
        filename: str,
        size: int,
        mtime: int,
        scan_id: str,
        code: str,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO images(collection_id,path,relative_path,filename,byte_size,mtime_ns,status,"
                "last_seen_scan_id,error_code,updated_at) VALUES(?,?,?,?,?,?,'failed',?,?,?) "
                "ON CONFLICT(collection_id,path) DO UPDATE SET relative_path=excluded.relative_path,"
                "filename=excluded.filename,byte_size=excluded.byte_size,mtime_ns=excluded.mtime_ns,"
                "status='failed',last_seen_scan_id=excluded.last_seen_scan_id,error_code=excluded.error_code,"
                "updated_at=excluded.updated_at",
                (cid, path, relative, filename, size, mtime, scan_id, code, utcnow()),
            )

    def finish_scan(self, cid: str, scan_id: str, spec_id: str) -> int:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            missing = connection.execute(
                "SELECT COUNT(*) FROM images WHERE collection_id=? AND status='valid' "
                "AND COALESCE(last_seen_scan_id,'')<>?",
                (cid, scan_id),
            ).fetchone()[0]
            connection.execute(
                "UPDATE images SET status='missing',updated_at=? WHERE collection_id=? "
                "AND COALESCE(last_seen_scan_id,'')<>? AND status='valid'",
                (utcnow(), cid, scan_id),
            )
            self._recount(connection, cid, spec_id)
            connection.execute("COMMIT")
            return int(missing)

    def _recount(self, connection, cid: str, spec: str) -> None:
        connection.execute(
            "UPDATE fingerprint_buckets SET member_count=(SELECT COUNT(*) FROM fingerprints f "
            "JOIN images i ON i.id=f.image_id WHERE f.bucket_id=fingerprint_buckets.id "
            "AND i.status='valid') WHERE collection_id=? AND fingerprint_spec_id=?",
            (cid, spec),
        )
        connection.execute(
            "UPDATE fingerprint_buckets SET tombstoned=(member_count=0) "
            "WHERE collection_id=? AND fingerprint_spec_id=?",
            (cid, spec),
        )

    def bump_catalog_revision(self, cid: str) -> int:
        with self.connect() as connection:
            connection.execute(
                "UPDATE collections SET catalog_revision=catalog_revision+1,updated_at=? WHERE id=?",
                (utcnow(), cid),
            )
            row = connection.execute(
                "SELECT catalog_revision FROM collections WHERE id=?", (cid,)
            ).fetchone()
            return int(row[0])

    def record_scan(self, cid: str, stats: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE collections SET last_scan_at=?,last_scan_stats_json=?,updated_at=? WHERE id=?",
                (utcnow(), json.dumps(stats), utcnow(), cid),
            )

    def list_images(self, cid: str, status: str | None = None, limit: int = 500) -> list[dict]:
        query = "SELECT * FROM images WHERE collection_id=?"
        values: list[Any] = [cid]
        if status:
            query += " AND status=?"
            values.append(status)
        query += " ORDER BY relative_path,id LIMIT ?"
        values.append(max(1, min(int(limit), 5000)))
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(query, values)]

    def bucket_vectors(self, cid: str, spec: str) -> tuple[list[int], list[bytes]]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id,hash_bytes FROM fingerprint_buckets WHERE collection_id=? "
                "AND fingerprint_spec_id=? AND tombstoned=0 ORDER BY id",
                (cid, spec),
            ).fetchall()
        return [int(row["id"]) for row in rows], [bytes(row["hash_bytes"]) for row in rows]

    def bucket_hashes(self, ids: list[int]) -> dict[int, bytes]:
        ids = list(map(int, ids))
        if not ids:
            return {}
        placeholders = ",".join("?" * len(ids))
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT id,hash_bytes FROM fingerprint_buckets WHERE id IN ({placeholders}) "
                "AND tombstoned=0",
                ids,
            ).fetchall()
        return {int(row["id"]): bytes(row["hash_bytes"]) for row in rows}

    def images_for_buckets(self, ids: list[int]) -> dict[int, list[dict]]:
        ids = list(map(int, ids))
        output: dict[int, list[dict]] = {}
        if not ids:
            return output
        placeholders = ",".join("?" * len(ids))
        with self.connect() as connection:
            rows = connection.execute(
                f"SELECT f.bucket_id,i.* FROM fingerprints f JOIN images i ON i.id=f.image_id "
                f"WHERE f.bucket_id IN ({placeholders}) AND i.status='valid' "
                "ORDER BY i.relative_path,i.id",
                ids,
            ).fetchall()
        for row in rows:
            output.setdefault(int(row["bucket_id"]), []).append(dict(row))
        return output

    def image(self, image_id: int) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM images WHERE id=? AND status='valid'", (image_id,)
            ).fetchone()
            return dict(row) if row else None

    def next_generation(self, cid: str) -> int:
        with self.connect() as connection:
            return int(
                connection.execute(
                    "SELECT COALESCE(MAX(generation),0)+1 FROM index_generations WHERE collection_id=?",
                    (cid,),
                ).fetchone()[0]
            )

    def add_generation(self, manifest: dict, path: str, checksum: str, active: bool = True) -> None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if active:
                connection.execute(
                    "UPDATE index_generations SET status='READY' WHERE collection_id=? AND status='ACTIVE'",
                    (manifest["collection_id"],),
                )
            connection.execute(
                "INSERT OR REPLACE INTO index_generations("
                "collection_id,generation,backend,backend_version,fingerprint_spec_id,config_json,"
                "vector_count,image_count,catalog_revision,disk_path,checksum,build_started_at,build_ended_at,"
                "status,benchmark_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    manifest["collection_id"],
                    manifest["generation"],
                    manifest["backend"],
                    manifest.get("backend_version"),
                    manifest["fingerprint_spec_id"],
                    json.dumps(manifest.get("config", {})),
                    manifest["vector_count"],
                    manifest["image_count"],
                    manifest.get("catalog_revision", 0),
                    path,
                    checksum,
                    manifest.get("build_started_at"),
                    manifest.get("created_at"),
                    "ACTIVE" if active else "READY",
                    json.dumps(manifest.get("benchmark_summary")),
                ),
            )
            if active:
                connection.execute(
                    "UPDATE collections SET active_generation=?,updated_at=? WHERE id=?",
                    (manifest["generation"], utcnow(), manifest["collection_id"]),
                )
            connection.execute("COMMIT")

    @staticmethod
    def _decode_generation(row: sqlite3.Row | dict | None) -> dict | None:
        if not row:
            return None
        data = dict(row)
        data["config"] = json.loads(data.pop("config_json") or "{}")
        data["benchmark"] = json.loads(data.pop("benchmark_json") or "null")
        return data

    @staticmethod
    def _active_generation_row(connection, cid: str, active_generation: int | None = None):
        if active_generation is None:
            selected = connection.execute(
                "SELECT active_generation FROM collections WHERE id=?", (cid,)
            ).fetchone()
            active_generation = selected[0] if selected else None
        if active_generation is None:
            return None
        return connection.execute(
            "SELECT * FROM index_generations WHERE collection_id=? AND generation=? "
            "ORDER BY (status='ACTIVE') DESC LIMIT 1",
            (cid, active_generation),
        ).fetchone()

    def active_generation(self, cid: str) -> dict | None:
        with self.connect() as connection:
            row = self._active_generation_row(connection, cid)
            return self._decode_generation(row)

    def generations(self, cid: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM index_generations WHERE collection_id=? ORDER BY generation DESC,backend",
                (cid,),
            ).fetchall()
        return [self._decode_generation(row) for row in rows]

    def generation(self, cid: str, generation: int, backend: str | None = None) -> dict | None:
        query = "SELECT * FROM index_generations WHERE collection_id=? AND generation=?"
        values: list[Any] = [cid, generation]
        if backend:
            query += " AND backend=?"
            values.append(backend)
        query += " ORDER BY (status='ACTIVE') DESC LIMIT 1"
        with self.connect() as connection:
            return self._decode_generation(connection.execute(query, values).fetchone())

    def latest_generation_for_backend(self, cid: str, backend: str, spec_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM index_generations WHERE collection_id=? AND backend=? "
                "AND fingerprint_spec_id=? AND status IN ('ACTIVE','READY','STALE','DEGRADED') "
                "ORDER BY generation DESC LIMIT 1",
                (cid, backend, spec_id),
            ).fetchone()
            return self._decode_generation(row)

    def compatible_generations(self, cid: str, spec_id: str) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM index_generations WHERE collection_id=? AND fingerprint_spec_id=? "
                "AND status IN ('ACTIVE','READY','STALE','DEGRADED') "
                "ORDER BY (status='ACTIVE') DESC,generation DESC",
                (cid, spec_id),
            ).fetchall()
        return [self._decode_generation(row) for row in rows]

    def activate_generation(self, cid: str, generation: int, backend: str | None = None) -> dict | None:
        selected = self.generation(cid, generation, backend)
        if not selected:
            return None
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE index_generations SET status='READY' WHERE collection_id=? AND status='ACTIVE'",
                (cid,),
            )
            connection.execute(
                "UPDATE index_generations SET status='ACTIVE' WHERE collection_id=? AND generation=? AND backend=?",
                (cid, generation, selected["backend"]),
            )
            connection.execute(
                "UPDATE collections SET active_generation=?,updated_at=? WHERE id=?",
                (generation, utcnow(), cid),
            )
            connection.execute("COMMIT")
        return self.generation(cid, generation, selected["backend"])

    def update_generation_status(self, cid: str, generation: int, backend: str, status: str) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE index_generations SET status=? WHERE collection_id=? AND generation=? AND backend=?",
                (status, cid, generation, backend),
            )

    def delete_generation(self, cid: str, generation: int, backend: str | None = None) -> dict | None:
        selected = self.generation(cid, generation, backend)
        if not selected:
            return None
        active = self.active_generation(cid)
        if active and active["generation"] == selected["generation"] and active["backend"] == selected["backend"]:
            raise ValueError("cannot delete active generation")
        with self.connect() as connection:
            connection.execute(
                "DELETE FROM index_generations WHERE collection_id=? AND generation=? AND backend=?",
                (cid, selected["generation"], selected["backend"]),
            )
        return selected

    def create_job(self, cid: str, kind: str) -> str:
        job_id = str(uuid.uuid4())
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO jobs(id,collection_id,type,state,progress_json,started_at,stats_json) "
                "VALUES(?,?,?,'QUEUED','{}',?,'{}')",
                (job_id, cid, kind, utcnow()),
            )
        return job_id

    def update_job(
        self,
        job_id: str,
        state: str | None = None,
        progress: dict | None = None,
        stats: dict | None = None,
        error: str | None = None,
        end: bool = False,
    ) -> None:
        fields: list[str] = []
        values: list[Any] = []
        for key, value in (
            ("state", state),
            ("progress_json", json.dumps(progress) if progress is not None else None),
            ("stats_json", json.dumps(stats) if stats is not None else None),
            ("error", error),
        ):
            if value is not None:
                fields.append(f"{key}=?")
                values.append(value)
        if end:
            fields.append("ended_at=?")
            values.append(utcnow())
        if fields:
            values.append(job_id)
            with self.connect() as connection:
                connection.execute(
                    f"UPDATE jobs SET {','.join(fields)} WHERE id=?", values
                )

    def get_job(self, job_id: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        data = dict(row)
        data["progress"] = json.loads(data.pop("progress_json") or "{}")
        data["stats"] = json.loads(data.pop("stats_json") or "{}")
        data["cancel_requested"] = bool(data["cancel_requested"])
        return data

    def active_job_for_collection(self, cid: str) -> dict | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE collection_id=? AND state NOT IN "
                "('SUCCEEDED','FAILED','CANCELLED','ABORTED') ORDER BY started_at DESC LIMIT 1",
                (cid,),
            ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["progress"] = json.loads(data.pop("progress_json") or "{}")
        data["stats"] = json.loads(data.pop("stats_json") or "{}")
        return data

    def request_cancel(self, job_id: str) -> bool:
        with self.connect() as connection:
            return (
                connection.execute(
                    "UPDATE jobs SET cancel_requested=1,state=CASE WHEN state IN "
                    "('QUEUED','SCANNING','HASHING','BUILDING','VALIDATING','PROMOTING') "
                    "THEN 'CANCELLING' ELSE state END WHERE id=?",
                    (job_id,),
                ).rowcount
                > 0
            )

    def is_cancel_requested(self, job_id: str) -> bool:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM jobs WHERE id=?", (job_id,)
            ).fetchone()
            return bool(row and row[0])

    def record_query(
        self,
        cid: str,
        backend: str,
        generation: int | None,
        elapsed: float,
        backend_ms: float,
        hash_ms: float = 0.0,
        result_count: int = 0,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO query_metrics(collection_id,backend,generation,elapsed_ms,backend_ms,hash_ms,result_count,created_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (cid, backend, generation, elapsed, backend_ms, hash_ms, result_count, utcnow()),
            )

    def increment_counter(self, key: str, amount: int = 1) -> None:
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO metric_counters(key,value) VALUES(?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=value+excluded.value",
                (key, int(amount)),
            )

    def counter(self, key: str) -> int:
        with self.connect() as connection:
            row = connection.execute("SELECT value FROM metric_counters WHERE key=?", (key,)).fetchone()
            return int(row[0]) if row else 0

    def set_generation_benchmark(self, cid: str, generation: int, backend: str, report: dict) -> None:
        with self.connect() as connection:
            connection.execute(
                "UPDATE index_generations SET benchmark_json=? WHERE collection_id=? AND generation=? AND backend=?",
                (json.dumps(report), cid, generation, backend),
            )

    def system_stats(self, cid: str | None = None) -> dict:
        with self.connect() as connection:
            if cid:
                images = connection.execute(
                    "SELECT COUNT(*) FROM images WHERE collection_id=? AND status='valid'", (cid,)
                ).fetchone()[0]
                fingerprints = connection.execute(
                    "SELECT COUNT(*) FROM fingerprints f JOIN images i ON i.id=f.image_id "
                    "WHERE i.collection_id=? AND i.status='valid'",
                    (cid,),
                ).fetchone()[0]
                unique_buckets = connection.execute(
                    "SELECT COUNT(*) FROM fingerprint_buckets b JOIN collections c ON c.id=b.collection_id "
                    "WHERE b.collection_id=? AND b.fingerprint_spec_id=c.fingerprint_spec_id "
                    "AND b.tombstoned=0",
                    (cid,),
                ).fetchone()[0]
                indexes = connection.execute(
                    "SELECT COUNT(*) FROM index_generations WHERE collection_id=? "
                    "AND status IN ('ACTIVE','READY','STALE','DEGRADED')",
                    (cid,),
                ).fetchone()[0]
                recent = [
                    row[0]
                    for row in connection.execute(
                        "SELECT elapsed_ms FROM query_metrics WHERE collection_id=? "
                        "ORDER BY id DESC LIMIT 100",
                        (cid,),
                    )
                ]
            else:
                images = connection.execute(
                    "SELECT COUNT(*) FROM images WHERE status='valid'"
                ).fetchone()[0]
                fingerprints = connection.execute(
                    "SELECT COUNT(*) FROM fingerprints f JOIN images i ON i.id=f.image_id "
                    "WHERE i.status='valid'"
                ).fetchone()[0]
                unique_buckets = connection.execute(
                    "SELECT COUNT(*) FROM fingerprint_buckets WHERE tombstoned=0"
                ).fetchone()[0]
                indexes = connection.execute(
                    "SELECT COUNT(*) FROM index_generations WHERE status IN "
                    "('ACTIVE','READY','STALE','DEGRADED')"
                ).fetchone()[0]
                recent = []
        recent_sorted = sorted(recent)
        p95 = 0.0
        if recent_sorted:
            p95 = recent_sorted[min(len(recent_sorted) - 1, int(0.95 * (len(recent_sorted) - 1)))]
        return {
            "total_images": int(images),
            "hashes_generated": int(fingerprints),
            "unique_fingerprints": int(unique_buckets),
            "total_indexes": int(indexes),
            "avg_query_ms": sum(recent) / len(recent) if recent else 0.0,
            "p95_query_ms": float(p95),
        }

    def metrics(self, cid: str | None = None) -> dict:
        stats = self.system_stats(cid)
        with self.connect() as connection:
            if cid:
                args = (cid,)
                query_row = connection.execute(
                    "SELECT COUNT(*) n,AVG(backend_ms) backend_avg,AVG(hash_ms) hash_avg,AVG(result_count) result_avg "
                    "FROM query_metrics WHERE collection_id=?", args
                ).fetchone()
                job_rows = connection.execute(
                    "SELECT state,COUNT(*) n FROM jobs WHERE collection_id=? GROUP BY state", args
                ).fetchall()
                scan_rows = connection.execute(
                    "SELECT stats_json FROM jobs WHERE collection_id=? AND type='scan' AND state='SUCCEEDED'",
                    args,
                ).fetchall()
            else:
                query_row = connection.execute(
                    "SELECT COUNT(*) n,AVG(backend_ms) backend_avg,AVG(hash_ms) hash_avg,AVG(result_count) result_avg FROM query_metrics"
                ).fetchone()
                job_rows = connection.execute("SELECT state,COUNT(*) n FROM jobs GROUP BY state").fetchall()
                scan_rows = connection.execute(
                    "SELECT stats_json FROM jobs WHERE type='scan' AND state='SUCCEEDED'"
                ).fetchall()
        cache_hits = cache_misses = hash_failures = scanned = 0
        for row in scan_rows:
            scan = json.loads(row["stats_json"] or "{}")
            scanned += int(scan.get("discovered", 0))
            cache_hits += int(scan.get("cached", 0)) + int(scan.get("content_reused", 0))
            cache_misses += int(scan.get("hashed", 0)) + int(scan.get("failed", 0))
            hash_failures += int(scan.get("failed", 0))
        return {
            "search_requests_total": self.counter("search_requests_total"),
            "search_errors_total": self.counter("search_errors_total"),
            "search_success_total": int(query_row["n"] or 0),
            "search_duration_ms_avg": stats["avg_query_ms"],
            "search_duration_ms_p95": stats["p95_query_ms"],
            "backend_search_duration_ms_avg": float(query_row["backend_avg"] or 0),
            "query_hash_duration_ms_avg": float(query_row["hash_avg"] or 0),
            "result_count_avg": float(query_row["result_avg"] or 0),
            "index_vector_count": stats["unique_fingerprints"],
            "scan_files_total": scanned,
            "hash_cache_hits_total": cache_hits,
            "hash_cache_misses_total": cache_misses,
            "hash_failures_total": hash_failures,
            "jobs_by_state": {row["state"]: row["n"] for row in job_rows},
        }

    def all_settings(self) -> dict:
        with self.connect() as connection:
            return {
                row["key"]: json.loads(row["value_json"])
                for row in connection.execute("SELECT * FROM app_settings")
            }

    def set_settings(self, values: dict) -> None:
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            for key, value in values.items():
                connection.execute(
                    "INSERT INTO app_settings(key,value_json) VALUES(?,?) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json",
                    (key, json.dumps(value)),
                )
            connection.execute("COMMIT")
