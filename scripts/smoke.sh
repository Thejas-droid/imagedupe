#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export IMAGEDUPE_HOME="${IMAGEDUPE_HOME:-$(mktemp -d)}"
trap '[[ "${IMAGEDUPE_HOME}" == /tmp/* ]] && rm -rf "${IMAGEDUPE_HOME}" || true' EXIT
cd "$ROOT"
python scripts/audit_repo.py
python -m compileall -q src tests benchmarks
if command -v node >/dev/null 2>&1; then
  node --check src/imagedupe/web/app.js
fi
pytest -q
imagedupe doctor --json > /dev/null
imagedupe --help > /dev/null
printf 'ImageDupe smoke checks passed\n'
