#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${MOTIF_FORGE_POSTGRES_DSN:-}" ]]; then
  echo "MOTIF_FORGE_POSTGRES_DSN is required" >&2
  exit 2
fi
if [[ -z "${MOTIF_FORGE_ARTIFACT_ROOT:-}" ]]; then
  echo "MOTIF_FORGE_ARTIFACT_ROOT is required" >&2
  exit 2
fi
approval_assertion="${MOTIF_FORGE_S1_APPROVAL_ASSERTION:-}"
if [[ ${#approval_assertion} -lt 16 || -z "${MOTIF_FORGE_S1_APPROVAL_ACTOR:-}" ]]; then
  echo "MOTIF_FORGE_S1_APPROVAL_ASSERTION (16+ chars) and MOTIF_FORGE_S1_APPROVAL_ACTOR are required" >&2
  exit 2
fi
if find . -type f -name '._*.py' -print -quit | grep -q .; then
  echo "AppleDouble Python sidecar detected; run the documented stage hygiene cleanup first" >&2
  exit 2
fi

dev_storage_root="${MOTIF_FORGE_DEV_STORAGE_ROOT:-/Volumes/KINGSTON/idea/.motif-forge-data}"
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/private/tmp/motif-forge-venv}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$dev_storage_root/cache/uv}"

uv run pytest \
  services/api/tests/unit/domain/test_composition.py \
  services/api/tests/unit/domain/test_render_jobs.py \
  services/api/tests/unit/application/test_composition.py \
  services/api/tests/unit/application/test_rendering.py \
  services/api/tests/unit/application/test_exporting.py \
  services/api/tests/unit/audio/test_chromium_render.py \
  services/api/tests/unit/audio/test_export_transcode.py \
  services/api/tests/unit/audio/test_midi.py \
  services/api/tests/eval/test_s1_deterministic_eval.py \
  services/api/tests/eval/test_s2_generate_eval.py \
  tests/test_s2_script_contract.py
npm run test:audio
uv run python scripts/check_s1_render_service.py
MOTIF_FORGE_S1_USE_QUEUE=1 uv run python scripts/run_s1_deterministic_smoke.py
uv run python scripts/run_s2_deterministic_smoke.py
