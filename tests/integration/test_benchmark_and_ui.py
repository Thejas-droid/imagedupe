from pathlib import Path

from fastapi.testclient import TestClient

from conftest import make_image
from imagedupe.app import create_app
from imagedupe.core.benchmark import run_benchmark
from imagedupe.core.config import Settings


def test_benchmark_reports_ground_truth_and_environment(env):
    settings, catalog, indexes, collections, search, root = env
    for i in range(4):
        make_image(root / f"{i}.png", i + 1)
    collection = collections.create(
        "bench", [{"path": str(root)}], "phash-v1-256-exif-luma", "exact"
    )
    collections.scan(collection["id"])
    indexes.build(collection["id"], "numpy-exact")
    report = run_benchmark(catalog, indexes, collection["id"], k=2, queries=3)
    assert report["ground_truth"] == "NumPy brute-force Hamming"
    assert report["recall_at_k"] == 1.0
    assert report["unique_fingerprint_buckets"] > 0
    assert report["environment"]["python"]


def test_static_ui_contains_accessible_core_workflow(tmp_path):
    settings = Settings(home=tmp_path / "home", worker_count=1)
    with TestClient(create_app(settings)) as client:
        html = client.get("/").text
        assert 'role="tablist"' in html
        assert 'aria-live="polite"' in html
        assert 'id="collectionCards"' in html
        assert 'id="settingsForm"' in html
        assert 'id="detailDialog"' in html
