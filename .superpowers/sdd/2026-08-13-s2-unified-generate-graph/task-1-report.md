# S2 Task 1 Report — Persisted AI Run, immutable Plan, events, and truthful usage

**Status:** DONE

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

Migration `20260813_0013` creates `app.ai_runs`, `app.ai_run_approvals`,
`app.composition_plans`, `app.ai_run_events` (identity-backed `BIGINT` sequence), and
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
- Initial PostgreSQL evidence was deferred until review round 2; real PostgreSQL evidence is now
  recorded below and did not use SQLite or implicit credentials.
- Initial `uv run` migration invocation was blocked by inherited AppleDouble files in the checked-in
  local `.venv`; the required SQL rendering was completed with the provided isolated Python venv.

## Commit

Original Task 1 commit: `e0176d6929f92b700ea652be6c43eef369d1c469` —
`feat: persist S2 AI runs and plans`. The review-fix commit is the current Git HEAD with subject
`fix: harden S2 AI run persistence`; this avoids the stale pre-amend SHA previously recorded here.
Review fix round 2 commit: `c7897d4add419ce0e7e185326e27187c73987a0c` —
`fix: close S2 AI run ledger review gaps`.
Review fix round 3 code commit: `b8390babf9fb5567d877eeca0834e5f5d4a18474` —
`fix: bind S2 approvals to pending plans`.
Review fix round 3 evidence commit: `7fbfab5298085ad8f64f69cc773be1f3f0e8cdde` —
`docs: record S2 task 1 final closure`.

## Review fix round 2 — RED/GREEN audit

**Status:** DONE

### RED

```bash
MOTIF_FORGE_TEST_POSTGRES_DSN='postgresql://motif_forge:motif_forge@localhost:5432/motif_forge_s2_task1' \
  /private/tmp/motif-forge-s2-venv/bin/pytest -q \
  services/api/tests/integration/test_postgres_ai_runs.py
# 4 failed before the AppleDouble migration artifact was removed; Alembic reported
# SyntaxError: source code string cannot contain null bytes for the exact `._0013` file.
```

The new red cases then drove the approval-resume bypass closure, assertion-length validation,
approval projection/hash write, rejection terminal handling, head-revision validation, child retry,
and deployed PostgreSQL constraints. The migration artifact was removed exactly before test runs;
it is not source and was not committed.

### GREEN

```bash
MOTIF_FORGE_TEST_POSTGRES_DSN='postgresql://motif_forge:motif_forge@localhost:5432/motif_forge_s2_task1' \
  /private/tmp/motif-forge-s2-venv/bin/pytest -q \
  services/api/tests/integration/test_postgres_ai_runs.py
# 6 passed

/private/tmp/motif-forge-s2-venv/bin/pytest -q \
  services/api/tests/unit/domain/test_ai_runs.py
# 8 passed

/private/tmp/motif-forge-s2-venv/bin/mypy \
  services/api/src/motif_forge/domain/ai_runs.py \
  services/api/src/motif_forge/application/ai_runs.py \
  services/api/src/motif_forge/application/ports.py \
  services/api/src/motif_forge/infrastructure/persistence/ai_runs.py \
  services/api/src/motif_forge/infrastructure/persistence/tables.py
# Success: no issues found in 5 source files

/private/tmp/motif-forge-s2-venv/bin/ruff check <Task 1 source and tests>
# All checks passed

MOTIF_FORGE_POSTGRES_DSN='postgresql://motif_forge:motif_forge@localhost:5432/motif_forge_s2_task1' \
  /private/tmp/motif-forge-s2-venv/bin/alembic upgrade head --sql \
  >/private/tmp/motif-forge-s2-review2-up.sql
MOTIF_FORGE_POSTGRES_DSN='postgresql://motif_forge:motif_forge@localhost:5432/motif_forge_s2_task1' \
  /private/tmp/motif-forge-s2-venv/bin/alembic downgrade \
  20260813_0013:20260812_0012 --sql \
  >/private/tmp/motif-forge-s2-review2-down.sql
# rendered: 793 / 32 lines

git diff --check
# clean
```

The real PostgreSQL tests prove idempotent/concurrent create, immutable plan provenance,
strictly monotonic events and `after_sequence` replay, approval/rejection hash binding and replay,
atomic write failure rollback of run/event/outbox/natural key, child-run retry, head/branch identity
rejection with no Run side effects, reservation/usage accounting, and migration `0013 -> 0012` with
an actual trace/span/NULL usage-ledger row restored to legacy cost `0`. The latter also asserts the
five Task 1 tables are removed on rollback.

### Schema and rollback update

`ai_runs` now includes `parent_run_id`, a parent/idempotency uniqueness guard, and deployed checks
for `submitted_model_requests BETWEEN 0 AND 3` and nonnegative aggregate token counters.
`ai_run_approvals` contains the expected Plan content hash and pending interrupt reference. The
Task 1 table inventory is five tables: `ai_runs`, `ai_run_approvals`, `composition_plans`,
`ai_run_events`, and `ai_model_request_reservations`. `downgrade()` removes all five and restores
the legacy usage-ledger columns/value semantics at revision `20260812_0012`.

### Concerns

No remaining Task 1 concern. Directly invoking generic `alembic downgrade -1` from the shared test
database encountered a pre-existing 0012 artifact-constraint downgrade defect outside this task;
the required populated `0013 -> 0012` rollback was instead executed and passed by the real test.

## Review fix round 3 — final focused closure

**Status:** DONE

### RED

```bash
MOTIF_FORGE_TEST_POSTGRES_DSN='postgresql://motif_forge:motif_forge@localhost:5432/motif_forge_s2_task1' \
  /private/tmp/motif-forge-s2-venv/bin/pytest -q services/api/tests/integration/test_postgres_ai_runs.py
# 6 failed initially with PostgreSQL `UndefinedColumn: ai_runs.pending_plan_id`.
```

This was the expected schema RED after adding the authoritative pending-interrupt projection to the
ORM before rebuilding the isolated migration database. The Plan A/B and forged-reference assertions
then drove replacement of raw waiting-status test setup with the transaction-owned pending Plan API.

### GREEN

```bash
# Fresh database: motif_forge_s2_task1_r3
MOTIF_FORGE_POSTGRES_DSN='postgresql://motif_forge:motif_forge@localhost:5432/motif_forge_s2_task1_r3' \
  /private/tmp/motif-forge-s2-venv/bin/alembic downgrade 20260812_0012
MOTIF_FORGE_POSTGRES_DSN='postgresql://motif_forge:motif_forge@localhost:5432/motif_forge_s2_task1_r3' \
  /private/tmp/motif-forge-s2-venv/bin/alembic upgrade head

MOTIF_FORGE_TEST_POSTGRES_DSN='postgresql://motif_forge:motif_forge@localhost:5432/motif_forge_s2_task1_r3' \
  /private/tmp/motif-forge-s2-venv/bin/pytest -q services/api/tests/integration/test_postgres_ai_runs.py
# 7 passed

/private/tmp/motif-forge-s2-venv/bin/pytest -q services/api/tests/unit/domain/test_ai_runs.py
# 8 passed

/private/tmp/motif-forge-s2-venv/bin/mypy <five Task 1 source files>
# Success: no issues found in 5 source files

/private/tmp/motif-forge-s2-venv/bin/ruff check <Task 1 source/tests/migration>
# All checks passed

git diff --check
# clean
```

`ai_runs` now keeps the authoritative nullable pending Plan ID, content hash and server-generated
unpredictable interrupt reference, with a grouped `waiting_approval` CHECK. The pending marker
transaction locks the Run and Plan, advances status/version, and the approval transaction compares
only these locked fields before consuming them atomically. PostgreSQL Plan A/B tests prove that a
persisted alternate Plan or forged ref cannot approve the Run; only the server-issued A/ref pair
can proceed.

Retries now use a dedicated parent/action/idempotency ledger rather than the project create-key
namespace. They lock the parent and current Branch, bind the child to the live head, create the
child `ai_run.created` Event and retry Outbox atomically, and return the recorded child only when
the request hash matches. Real PostgreSQL coverage includes same-project distinct parents sharing a
retry key, conflict replay, child-event presence, and branch-head advancement. The migration adds
and downgrades the action ledger; Task 1 inventory is now six tables: `ai_runs`,
`ai_run_approvals`, `ai_run_action_idempotency`, `composition_plans`, `ai_run_events`, and
`ai_model_request_reservations`.

### Concerns

None for Task 1. The guide SHA remains
`21345f64304338777a9dd2603d34ad54448b6c4b82902bc743204ba1026c9f58`.

## Review fix round 1 — RED/GREEN audit

### RED

```bash
/private/tmp/motif-forge-s2-venv/bin/python -m pytest \
  services/api/tests/unit/domain/test_ai_runs.py \
  services/api/tests/unit/application/test_ai_runs.py -q
```

Result: collection failed with `ImportError: cannot import name 'ModelUsageFactError'` before
the negative-token/terminal-budget contract implementation existed. The added PostgreSQL concurrent
create/action, approval persistence, immutable-provenance, usage conflict, cross-project identity,
and populated downgrade tests then exposed their target missing behavior during development.

### GREEN

Used the existing local PostgreSQL Compose service only: started Colima and `docker compose up -d
postgres`; no image rebuild or Dockerfile change.

```bash
MOTIF_FORGE_TEST_POSTGRES_DSN='postgresql://motif_forge:motif_forge@localhost:5432/motif_forge_s2_task1' \
  /private/tmp/motif-forge-s2-venv/bin/python -m pytest \
  services/api/tests/integration/test_postgres_ai_runs.py -q
# 4 passed

/private/tmp/motif-forge-s2-venv/bin/python -m pytest \
  services/api/tests/unit/domain/test_ai_runs.py \
  services/api/tests/unit/application/test_ai_runs.py \
  services/api/tests/unit/infrastructure/test_observability.py \
  services/api/tests/unit/infrastructure/persistence/test_tables.py \
  services/api/tests/unit/agent/test_graph.py -q
# 25 passed

/private/tmp/motif-forge-s2-venv/bin/python -m ruff check <Task 1 files>
# All checks passed

/private/tmp/motif-forge-s2-venv/bin/alembic upgrade head --sql \
  >/private/tmp/motif-forge-s2-review-up.sql
/private/tmp/motif-forge-s2-venv/bin/alembic downgrade \
  20260813_0013:20260812_0012 --sql >/private/tmp/motif-forge-s2-review-down.sql
# rendered: 783 / 32 lines
```

The populated live rollback test now performs `0013 -> 0012` and proves the previous non-null
ledger shape after NULL costs are first converted to legacy zero. The fixed implementation adds
atomic `ai_run_approvals`, graph/state compatibility versions, action finite-state/idempotency,
project-scoped create replay, cross-project identity validation, reservation terminal refusal,
usage fact validation/conflict detection, and safe token-count event fields. Guide SHA stayed
`21345f64304338777a9dd2603d34ad54448b6c4b82902bc743204ba1026c9f58`.
