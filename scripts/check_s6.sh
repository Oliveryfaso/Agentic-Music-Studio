#!/usr/bin/env bash
set -euo pipefail

.venv/bin/pytest services/api/tests/eval/test_s6_edit_eval.py tests/test_s6_script_contract.py -q
.venv/bin/pytest services/api/tests/unit -q --ignore-glob='**/._*'
npm run test:web
npm run build:web
npm run generate:openapi
.venv/bin/ruff check . --exclude '._*'
.venv/bin/mypy
git diff --check

if [[ -n "${MOTIF_FORGE_TEST_POSTGRES_DSN:-}" ]]; then
  .venv/bin/pytest services/api/tests/integration/test_postgres_s6_edit_human_loop.py \
    services/api/tests/integration/test_generate_dispatcher.py -q
fi
