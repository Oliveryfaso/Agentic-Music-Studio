#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${MOTIF_FORGE_TEST_POSTGRES_DSN:-}" ]]; then
  echo "MOTIF_FORGE_TEST_POSTGRES_DSN is required for real PostgreSQL integration tests." >&2
  exit 2
fi

export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-/private/tmp/motif-forge-venv}"
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
dev_storage_root="${MOTIF_FORGE_DEV_STORAGE_ROOT:-$(cd "$project_root/.." && pwd -P)/.motif-forge-data}"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$dev_storage_root/cache/uv}"
export UV_LINK_MODE="${UV_LINK_MODE:-copy}"

uv run --frozen pytest -q services/api/tests/integration
