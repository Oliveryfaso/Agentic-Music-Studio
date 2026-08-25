#!/usr/bin/env bash
set -euo pipefail

.venv/bin/pytest tests/test_s7_script_contract.py services/api/tests/eval/test_s7_portfolio_eval.py tests/test_s7_eval_report_contract.py -q
.venv/bin/pytest services/api/tests/eval -q
.venv/bin/pytest services/api/tests/unit -q --ignore-glob='**/._*'
npm run test:web
npm run build:web
npm run eval:s7
npm run generate:openapi
npm run build:web
.venv/bin/ruff check . --exclude '._*'
.venv/bin/mypy
git diff --check

if [[ -n "${MOTIF_FORGE_TEST_POSTGRES_DSN:-}" ]]; then
  .venv/bin/pytest \
    services/api/tests/integration/test_postgres_s7_export_reads.py \
    services/api/tests/integration/test_postgres_s7_run_inspection.py \
    services/api/tests/integration/test_generate_dispatcher.py -q
fi
