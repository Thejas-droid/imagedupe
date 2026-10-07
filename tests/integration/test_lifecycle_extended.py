from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_image
from imagedupe.app import create_app
from imagedupe.catalog.db import Catalog
from imagedupe.core.config import Settings
from imagedupe.core.jobs import JobService
from imagedupe.indexes.manager import IndexManager


def build_collection(env, count=2):
    settings, catalog, indexes, collections, search, root = env
    for i in range(count):
        make_image(root / f"{i}.png", i + 10)
    collection = collections.create(
        "extended",
        [{"path": str(root), "recursive": True}],
        "phash-v1-256-exif-luma",
        "exact",
    )
    collections.scan(collection["id"])
    manifest = indexes.build(collection["id"], "numpy-exact")
    return collection["id"], manifest


def test_scan_globs_skip_counts_and_missing_revision(env):
    settings, catalog, indexes, collections, search, root = env
    make_image(root / "keep.png", 1)
    make_image(root / "exclude.png", 2)
    (root / "notes.txt").write_text("not an image")
    collection = collections.create(
        "scan",
        [{"path": str(root), "recursive": True, "exclude_globs": ["exclude.png"]}],
        "phash-v1-256-exif-luma",
        "exact",
    )
    stats = collections.scan(collection["id"])
    assert stats["hashed"] == 1
    assert stats["skipped"] == 1
    first = catalog.get_collection(collection["id"])
    assert first["counts"]["valid"] == 1
    assert first["counts"]["skipped"] == 1
    assert first["catalog_revision"] == 1
    (root / "keep.png").unlink()
    stats2 = collections.scan(collection["id"])
    assert stats2["missing"] == 1
    assert catalog.get_collection(collection["id"])["catalog_revision"] == 2


def test_stale_base_plus_delta_finds_new_image(env):
    settings, catalog, indexes, collections, search, root = env
    cid, manifest = build_collection(env, 2)
    new_path = make_image(root / "new.png", 99)
    scan = collections.scan(cid)
    assert scan["hashed"] == 1
    collection = catalog.get_collection(cid)
    assert collection["health"] == "degraded"
    delta = indexes.delta_status(cid)
    assert delta["delta_bucket_count"] >= 1
    response = search.image(cid, new_path.read_bytes(), "new.png", 10, "auto")
    assert response["results"][0]["filename"] == "new.png"
    assert response["results"][0]["hamming_distance"] == 0


def test_exact_override_uses_current_catalog_and_is_not_misreported(env):
    settings, catalog, indexes, collections, search, root = env
    cid, _ = build_collection(env, 2)
    query = (root / "0.png").read_bytes()
    response = search.image(cid, query, "0.png", 10, "exact")
    assert response["search"]["backend"] in {"numpy-exact", "faiss-binary-flat"}
    assert response["search"]["generation"] is None


def test_incompatible_spec_blocks_search_and_generation_activation(env):
    settings, catalog, indexes, collections, search, root = env
    cid, manifest = build_collection(env, 1)
    catalog.update_collection(cid, {"fingerprint_spec_id": "phash-v1-64-exif-luma"})
    with pytest.raises(Exception) as search_error:
        search.image(cid, (root / "0.png").read_bytes(), "0.png")
    assert "FINGERPRINT_SPEC_MISMATCH" in str(search_error.value)
    with pytest.raises(RuntimeError, match="FINGERPRINT_SPEC_MISMATCH"):
        indexes.activate(cid, manifest["generation"])


def test_corrupt_active_generation_falls_back_to_previous(tmp_path):
    root = tmp_path / "images"
    root.mkdir()
    make_image(root / "a.png", 1)
    settings = Settings(home=tmp_path / "home", worker_count=1)
    catalog = Catalog(settings.db_path)
    from imagedupe.core.collections import CollectionService
    from imagedupe.core.search import SearchService

    collections = CollectionService(catalog, settings)
    indexes = IndexManager(catalog, settings.index_dir, settings)
    collection = collections.create(
        "fallback", [{"path": str(root)}], "phash-v1-256-exif-luma", "exact"
    )
    collections.scan(collection["id"])
    first = indexes.build(collection["id"], "numpy-exact")
    second = indexes.build(collection["id"], "numpy-exact")
    # Simulate corruption before a fresh process loads the active generation.
    active = catalog.active_generation(collection["id"])
    vectors = Path(active["disk_path"]) / "vectors.npy"
    with vectors.open("ab") as handle:
        handle.write(b"corruption")
    fresh = IndexManager(catalog, settings.index_dir, settings)
    search = SearchService(catalog, fresh, settings)
    response = search.image(collection["id"], (root / "a.png").read_bytes(), "a.png")
    assert response["search"]["generation"] == first["generation"]
    assert catalog.active_generation(collection["id"])["status"] == "DEGRADED"


def test_job_conflict_is_reported(env):
    settings, catalog, indexes, collections, search, root = env
    make_image(root / "a.png", 1)
    collection = collections.create(
        "jobs", [{"path": str(root)}], "phash-v1-256-exif-luma", "exact"
    )
    catalog.create_job(collection["id"], "scan")
    jobs = JobService(catalog, collections, indexes)
    try:
        with pytest.raises(Exception) as error:
            jobs.scan(collection["id"])
        assert "JOB_CONFLICT" in str(error.value)
    finally:
        jobs.close()


def test_content_cache_can_reuse_previously_missing_content(env):
    settings, catalog, indexes, collections, search, root = env
    original = make_image(root / "original.png", 7)
    collection = collections.create(
        "reuse", [{"path": str(root)}], "phash-v1-256-exif-luma", "exact"
    )
    collections.scan(collection["id"])
    payload = original.read_bytes()
    original.unlink()
    collections.scan(collection["id"])
    moved = root / "returned.png"
    moved.write_bytes(payload)
    stats = collections.scan(collection["id"])
    assert stats["content_reused"] == 1
    assert stats["hashed"] == 0


def test_settings_are_applied_and_validation_is_problem_details(tmp_path):
    settings = Settings(home=tmp_path / "home", worker_count=1)
    with TestClient(create_app(settings)) as client:
        response = client.patch(
            "/api/v1/settings",
            json={
                "default_top_k": 50,
                "worker_count": 2,
                "ann_tuning_profile": "high-recall",
                "thumbnail_cache_enabled": False,
                "privacy_paths": False,
            },
        )
        assert response.status_code == 200
        runtime = response.json()["runtime"]
        assert runtime["default_top_k"] == 50
        assert runtime["worker_count_configured"] == 2
        assert runtime["ann_tuning_profile"] == "high-recall"
        bad = client.post("/api/v1/collections", json={"name": "missing roots", "roots": []})
        assert bad.status_code == 422
        assert bad.headers["content-type"].startswith("application/problem+json")
        assert bad.json()["code"] == "VALIDATION_ERROR"


def test_doctor_redacts_paths_by_default(tmp_path):
    settings = Settings(home=tmp_path / "very-secret-home", worker_count=1)
    with TestClient(create_app(settings)) as client:
        hidden = client.get("/api/v1/system/doctor").json()
        shown = client.get("/api/v1/system/doctor?show_paths=true").json()
        assert hidden["paths"]["home"]["path"].startswith("…/")
        assert shown["paths"]["home"]["path"] == str(settings.home)

def test_multicore_scan_configuration_executes(tmp_path):
    from imagedupe.core.collections import CollectionService
    from imagedupe.catalog.db import Catalog
    from imagedupe.core.config import Settings
    root=tmp_path/'images';root.mkdir()
    for i in range(6):make_image(root/f'{i}.png',i+30)
    settings=Settings(home=tmp_path/'home',worker_count=2,worker_cap=4)
    catalog=Catalog(settings.db_path);service=CollectionService(catalog,settings)
    collection=service.create('multi',[{'path':str(root)}],'phash-v1-256-exif-luma','exact')
    stats=service.scan(collection['id'])
    assert settings.effective_workers==2
    assert stats['hashed']==6 and stats['failed']==0
