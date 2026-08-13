# Task 5 implementation report

Status: DONE after independent-review fix round 2

Base implementation commit: `fb17efb11ef48848f182b1895264a88803eadb3d`

Guide SHA-256: `21345f64304338777a9dd2603d34ad54448b6c4b82902bc743204ba1026c9f58`

## Final scope

- `PersistPlanningResult` performs strict JSON-mode revalidation, lossless-v2 canonical hashing,
  complete provenance comparison, concurrency-safe `ON CONFLICT` reload, and the authoritative
  `Plan -> waiting_approval` transition in one Run-locked PostgreSQL transaction. Failure leaves no
  orphan Plan; replay returns the original Plan ID/hash/version/interrupt.
- `MaterializeApprovedComposition` uses a composite PostgreSQL Unit of Work. Lock order is AI Run
  then Project Branch. It re-reads the live Run, approval, strict Plan JSONB and authoritative Brief;
  verifies actor/assertion/hash/target identity; reruns the Task 4 policy/compiler; and commits the
  Candidate, Preview, approved immutable Revision, Branch CAS, project approvals/audit, durable
  receipt and bounded AI Run event in one `AsyncSession`.
- The composite Unit of Work is now a required constructor dependency. The former optional
  multi-transaction compatibility path and its injectable Preview/decision delegates were removed,
  so approval and rejection have one Run-locked authority boundary and no non-atomic use-case
  construction is possible.
- `LoadCompositionPlan` and composite materialization share `verify_loaded_plan_identity`. Both
  recompute the stored versioned digest; compilation additionally rejects legacy rounded-v1
  identities whose v1 and lossless-v2 canonical bytes differ before compiler or Project writes.
- The public `CreateCommandPreview` / `DecidePreview` paths and Task 5's composite transaction call
  the same transaction-scoped Preview core. The public path retains its auditable superseded result;
  Task 5 selects rollback-on-conflict. There is no alternate/direct Revision writer.
- Migration `20260813_0016` adds the versioned materialization receipt with logical uniqueness over
  Run/Plan/hash/seed and exact request hash, actor/assertion hash, Candidate, Preview, Revision,
  command-batch, Plan hash version, Style Pack and compiler references. It refuses an online
  downgrade while receipts exist and round-trips safely when empty.
- Successful Task 5 materialization intentionally keeps the Run `MATERIALIZING`. Task 6 alone owns
  media Job creation and the later `WAITING_WORKER` transition.

## Review findings closed

- **C1:** cancellation and materialization serialize on the Run lock; cancellation that commits
  first is re-read as terminal and produces zero project writes/receipt/event.
- **I1:** Plan insert and pending interrupt are atomic, concurrency-safe and exact-replayable.
- **I2:** caller idempotency keys cannot create duplicate logical materializations; concurrent keys
  share one receipt and one Candidate/Preview/Revision/Branch advance.
- **I3:** persisted JSONB is revalidated with strict JSON semantics and emits stable
  `PLAN_INTEGRITY_ERROR` before compilation.
- **I4:** restart/replay reads exact output references from the durable receipt and bounded event.
- **I5:** this slice admits only literal `synth-ambient.v1`; Candidate/Revision/command provenance
  records verified Style Pack and `synth-ambient-compiler.v1` identities.
- **I6:** real PostgreSQL fault/interleaving tests cover cancellation, concurrent caller keys,
  Plan/pending rollback and concurrency, branch change after Preview creation, corrupt JSONB/style
  identity, receipt-write failure, restart replay, and migration downgrade protection.
- **M1:** unit approved-state setup now uses public `RecordAIRunApproval` through a contract-enforcing
  fake rather than manually mutating approval/Run state.
- **M2:** transaction evidence and the Task 5-to-Task 6 status boundary are now stated exactly.
- **Round-2 C1:** the atomic UoW is mandatory and the complete stale-read/multi-commit path is gone;
  a constructor-signature regression prevents reintroducing optional AI/Project/Preview seams.
- **Round-2 I7:** real PostgreSQL proves an approved collision-unsafe rounded-v1 Plan returns
  `PLAN_HASH_VERSION_UNSAFE`, does not call the compiler, and leaves zero Candidate, Preview,
  generated Revision, receipt or materialization Event.

## TDD and focused PostgreSQL evidence

The new tests were introduced against the reviewed implementation and first exposed the absent
composite transaction/receipt, non-atomic Plan boundary, permissive JSONB load and missing
provenance. Final focused evidence:

```text
Task 5 PostgreSQL transaction/interleaving/migration tests: 12 passed
Public Preview + composition + Task 5 unit tests: 12 passed
```

The success test additionally queries and agrees on exact receipt/event/output IDs, actor/assertion
hash, Plan/hash version, Style Pack/compiler, Branch head, five ordered command payloads,
Candidate/Revision versions, and `source_run_id`. Raw approval assertion text is never persisted.

## Final verification

```text
services/api/tests/unit + services/api/tests/eval: 389 passed
Task 1 + Task 5 + PostgreSQL project contract: 36 passed, 1 optional Celery E2E skipped
mypy motif_forge: Success, 80 source files
ruff source/unit/eval/relevant integration/migration: All checks passed
Alembic offline upgrade/downgrade SQL: 926 / 10 lines
git diff --check: clean
PROJECT_GUIDE SHA-256: 21345f64304338777a9dd2603d34ad54448b6c4b82902bc743204ba1026c9f58
```

No Docker image was rebuilt and no paid model/API request was made. The existing local PostgreSQL
service was reused; each test removed only its exact Project/Run rows. External-drive AppleDouble
sidecars were removed by exact path and are not source or committed evidence.

## Boundary

Task 5 ends at one durable approved Revision and materialization receipt. No media Job, Artifact,
Parent Graph wiring, Docker rebuild or Task 6 behavior was added.
