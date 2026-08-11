#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${MOTIF_FORGE_TEST_POSTGRES_DSN:-}" ]]; then
  echo "MOTIF_FORGE_TEST_POSTGRES_DSN is required for real PostgreSQL integration tests." >&2
  exit 2
fi

uv run --frozen pytest -q services/api/tests/integration
