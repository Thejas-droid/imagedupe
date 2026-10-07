from __future__ import annotations

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    "pyproject.toml",
    "requirements.lock",
    "README.md",
    "prd.md",
    "src/imagedupe/app.py",
    "src/imagedupe/cli.py",
    "src/imagedupe/desktop.py",
    "scripts/windows_entry.py",
    "packaging/windows/imagedupe.spec",
    "packaging/windows/installer.nsi",
    "packaging/windows/build.ps1",
    "docs/installation/windows-desktop.md",
    "src/imagedupe/catalog/db.py",
    "src/imagedupe/core/collections.py",
    "src/imagedupe/core/search.py",
    "src/imagedupe/core/jobs.py",
    "src/imagedupe/core/benchmark.py",
    "src/imagedupe/hashing/phash.py",
    "src/imagedupe/indexes/backends.py",
    "src/imagedupe/indexes/manager.py",
    "src/imagedupe/web/index.html",
    "src/imagedupe/web/styles.css",
    "src/imagedupe/web/app.js",
    "docs/installation/native.md",
    "docs/benchmarking/methodology.md",
    "docs/security.md",
    "docs/release-report.md",
    "tests/conformance/test_exact_backend.py",
    "tests/conformance/test_backend_roundtrip.py",
]

FORBIDDEN_NAMES = {
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "compose.yml",
    "compose.yaml",
}


def main() -> int:
    errors: list[str] = []
    for rel in REQUIRED:
        if not (ROOT / rel).is_file():
            errors.append(f"missing required file: {rel}")

    generated = {".git", ".venv", ".build-venv", "build", "dist", "release", "__pycache__", ".pytest_cache"}
    for directory, children, filenames in os.walk(ROOT):
        children[:] = [name for name in children if name not in generated]
        for name in filenames:
            if name in FORBIDDEN_NAMES:
                path = Path(directory) / name
                errors.append(f"container artifact is out of v1 scope: {path.relative_to(ROOT)}")

    text = (ROOT / "src/imagedupe/app.py").read_text(encoding="utf-8")
    for route in (
        "/api/v1/search/image",
        "/api/v1/search/hash",
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/system/status",
    ):
        if route not in text:
            errors.append(f"missing required API route: {route}")

    cli = (ROOT / "src/imagedupe/cli.py").read_text(encoding="utf-8")
    for token in ("serve", "doctor", "benchmark", "collection", "index", "search"):
        if token not in cli:
            errors.append(f"missing required CLI surface: {token}")

    if errors:
        print("ImageDupe repository audit FAILED", file=sys.stderr)
        for item in errors:
            print(f"- {item}", file=sys.stderr)
        return 1

    print("ImageDupe repository audit passed")
    print(f"required_files={len(REQUIRED)} container_artifacts=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
