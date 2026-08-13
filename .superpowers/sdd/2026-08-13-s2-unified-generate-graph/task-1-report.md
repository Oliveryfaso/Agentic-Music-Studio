# S2 Task 1 Report — Persisted AI Run, immutable Plan, events, and truthful usage

**Status:** DONE_WITH_CONCERNS

## Scope

Implemented the Task 1 domain/application/persistence ledger only: finite `AIRun`, immutable
canonical `CompositionPlan` persistence, ordered replayable events, one-way approval assertion
hashes, atomic model request reservations, provider token accounting, and unknown-cost telemetry.
No DeepSeek client, dispatcher, Graph wiring, API, or project planning documents were changed.

Covered roadmap requirements: MF-P02, MF-P04, MF-P05, MF-P07, MF-P13, MF-P16, and MF-P18.

## RED evidence

Command:

```bash
/private/tmp/motif-forge-s2-venv/bin/python -m pytest \
  services/api/tests/unit/domain/test_ai_runs.py \
  services/api/tests/unit/application/test_ai_runs.py \
  services/api/tests/unit/infrastructure/test_observability.py -q
```

Result: collection failed as expected with `ModuleNotFoundError` for
`motif_forge.domain.ai_runs` and `motif_forge.application.ai_runs` before either production
module existed. The third test also exposed an existing import-cycle fragility; the package
initialization is now lazy while retaining the public agent exports.

## GREEN evidence

```bash
/private/tmp/motif-forge-s2-venv/bin/python -m pytest \
  services/api/tests/unit/domain/test_ai_runs.py \
  services/api/tests/unit/application/test_ai_runs.py \
  services/api/tests/unit/infrastructure/test_observability.py \
  services/api/tests/unit/infrastructure/persistence/test_tables.py \
  services/api/tests/unit/agent/test_graph.py -q
# 21 passed

/private/tmp/motif-forge-s2-venv/bin/python -m ruff check <Task 1 files>
# All checks passed

git diff --check
# clean

/private/tmp/motif-forge-s2-venv/bin/alembic upgrade head --sql \
  >/private/tmp/motif-forge-s2-up.sql
/private/tmp/motif-forge-s2-venv/bin/alembic downgrade \
  20260813_0013:20260812_0012 --sql >/private/tmp/motif-forge-s2-down.sql
# both render; upgrade 769 lines, downgrade 28 lines
```

`PROJECT_GUIDE.md` SHA-256 was checked before handoff and remains
`21345f64304338777a9dd2603d34ad54448b6c4b82902bc743204ba1026c9f58`.

## Schema, migration, rollback

Migration `20260813_0013` creates `app.ai_runs`, `app.composition_plans`,
`app.ai_run_events` (identity-backed `BIGINT` sequence), and
`app.ai_model_request_reservations`. It adds all requested uniqueness and foreign-key
relationships. The migration makes `observability.usage_ledger.estimated_cost_microusd` nullable,
adds `cost_status` and `pricing_version`, and changes historical zero cost rows to unknown/null.
Downgrade removes the four Task 1 tables and new ledger columns, restoring the prior non-null
cost column shape, targeting `20260812_0012`.

## Changed files

- `services/api/src/motif_forge/domain/ai_runs.py`
- `services/api/src/motif_forge/application/ai_runs.py`
- `services/api/src/motif_forge/application/ports.py`
- `services/api/src/motif_forge/infrastructure/persistence/ai_runs.py`
- `services/api/src/motif_forge/infrastructure/persistence/tables.py`
- `services/api/src/motif_forge/observability/models.py`
- `services/api/src/motif_forge/infrastructure/observability.py`
- `services/api/src/motif_forge/agent/__init__.py` (lazy package exports to break import cycle)
- `infra/migrations/versions/20260813_0013_generate_ai_runs.py`
- focused Task 1 unit/integration tests

## Self-review and concerns

- PostgreSQL requests are reserved under a row lock before caller-visible network work; a
  reserved-but-unobserved row remains counted after a crash. The shared repair allowance is
  enforced across schema and strategy repair.
- Outbox start/action payloads contain only stable IDs, thread/action/version and schema labels;
  no prompt, response, reasoning, or secret fields are persisted in events/reservations.
- `MOTIF_FORGE_TEST_POSTGRES_DSN` is absent in this environment. The real PostgreSQL test exists
  and is safely skipped rather than using SQLite or implicit credentials. This is the sole concern.
- Initial `uv run` migration invocation was blocked by inherited AppleDouble files in the checked-in
  local `.venv`; the required SQL rendering was completed with the provided isolated Python venv.

## Commit

`353aeca8e814db0c3584989c499b9a10c1fc9c2c` — `feat: persist S2 AI runs and plans`
