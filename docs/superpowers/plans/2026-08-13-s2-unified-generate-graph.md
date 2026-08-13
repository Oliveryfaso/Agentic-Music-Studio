# S2 Unified Generate Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a durable `Brief -> DeepSeek or deterministic Plan -> human approval -> immutable Revision -> Master/four Stems/MP3/logical Bundle` generation path inside the single Parent Graph.

**Architecture:** Refactor the existing Plan v3 nodes into a side-effect-free planning subgraph and mount it in `motif-forge-parent.v2` through explicit adapters. Persist AI Run, immutable CompositionPlan, events, approval, usage, and output references in PostgreSQL; run Graph start/resume asynchronously through the existing outbox dispatcher; reuse the proven S1 media workers and artifact contracts for all audio output.

**Tech Stack:** Python 3.12, Pydantic v2, LangChain Core, LangGraph, FastAPI, SQLAlchemy 2 async, Alembic, PostgreSQL, Redis/Celery, httpx, React/TypeScript generated OpenAPI types, pytest, Ruff, Mypy, Docker Compose.

## Global Constraints

- Source-of-truth guide SHA-256 at plan creation: `21345f64304338777a9dd2603d34ad54448b6c4b82902bc743204ba1026c9f58`; recheck before every task handoff and final acceptance.
- Active roadmap gate is S2 only. Covered requirements: `MF-P02`, `MF-P04`, complete-song portion of `MF-P05`, `MF-P07`, `MF-P13`, `MF-P15`, `MF-P16`, `MF-P17`, `MF-P18`, and secrets/audit portion of `MF-P21`.
- Do not claim `MF-P09`: only `synth_ambient` is implemented; the other three styles return `STYLE_NOT_IMPLEMENTED` before any model request.
- S2 accepts instrumental, 4/4, 60–300 second briefs. Unsupported meter returns `METER_NOT_IMPLEMENTED` before any model request.
- DeepSeek model is exactly `deepseek-v4-flash`, thinking enabled with high reasoning effort, JSON Output, maximum 2,400 output tokens per logical planner call, at most one repair, at most three upstream requests including transport retries, and at most 12,000 total tokens.
- DeepSeek creates only `CompositionPlan`; deterministic code creates PatternSpec, commands, ArrangementIR, AudioGraph, files, jobs, and transactions.
- Provider failures route to an explicit deterministic fallback plan, which still requires the same human approval.
- From-zero generation is L3. Rejection creates no Candidate, Revision, Job, or Artifact.
- Use one finite Parent run/thread. Do not add a third production Graph, API-chain two Graphs, copy planner nodes, or place IR/audio/model reasoning in checkpoint state.
- PostgreSQL is authoritative. Redis/Celery and Graph delivery are at least once; every side effect is idempotent.
- Reuse S1's canonical 48 kHz PCM24 Master/four Stem render, 256 kbps MP3, MIDI/Project/manifests, and logical Bundle contracts without duplicating audio bytes.
- `DEEPSEEK_API_KEY` remains only in environment/secret configuration. Never print, trace, persist, return, fixture, or commit it.
- Do not run the paid DeepSeek acceptance until every deterministic and real-PostgreSQL gate is green. The live gate stops after one successful complete result.
- Use host-first tests. Do not rebuild Docker until the affected-service runtime gate. Do not run broad cache or volume prune.

---

## File structure

New files have one responsibility each:

- `services/api/src/motif_forge/domain/ai_runs.py`: strict AI Run, immutable Plan, event, approval, status, usage, and cost contracts.
- `services/api/src/motif_forge/application/ai_runs.py`: create/read/event/resume/cancel/retry/Plan-persist use cases.
- `services/api/src/motif_forge/infrastructure/persistence/ai_runs.py`: PostgreSQL implementation for AI Run transactions and replayable events.
- `infra/migrations/versions/20260813_0013_generate_ai_runs.py`: reversible S2 schema and truthful cost migration.
- `services/api/src/motif_forge/agent/planning_subgraph.py`: reusable side-effect-free Plan v3 planning node factory.
- `services/api/src/motif_forge/agent/generate.py`: generate-specific adapters, node contracts, routes, and Parent state updates.
- `services/api/src/motif_forge/domain/synth_ambient.py`: strategy compatibility policy and deterministic Plan-to-Pattern/Arrangement compiler.
- `services/api/src/motif_forge/application/generation.py`: approved Plan materialization and complete-export enqueue/collection application services.
- `services/api/src/motif_forge/api/ai_runs.py`: AI Run REST and persistent SSE router.
- `services/api/tests/eval/test_s2_generate_eval.py`: S2 baseline/routing/recovery evaluation cases.
- `evals/s2-synth-ambient-v1.json`: versioned deterministic S2 cases and failure labels.
- `scripts/run_s2_deterministic_smoke.py`: no-cost complete Parent Graph acceptance.
- `scripts/run_s2_live_deepseek_smoke.py`: opt-in, budgeted, single-success paid acceptance.
- `apps/web/src/generated/api-schema.d.ts`: generated OpenAPI TypeScript declarations; never hand-edit.

Existing files change only at their owned seams:

- `services/api/src/motif_forge/agent/graph.py`: standalone Plan regression wrapper built from the shared subgraph.
- `services/api/src/motif_forge/agent/parent_graph.py`: Parent v2 state and operation routing; delegates generate nodes to `agent/generate.py`.
- `services/api/src/motif_forge/providers/deepseek.py`: shared upstream-request budget and strategy-safe prompt.
- `services/api/src/motif_forge/application/ports.py`: AI Run transaction Protocol only.
- `services/api/src/motif_forge/application/composition.py`: plan-driven preview service, without changing the S1 service.
- `services/api/src/motif_forge/infrastructure/persistence/tables.py`: SQLAlchemy S2 rows.
- `services/api/src/motif_forge/infrastructure/observability.py`: truthful known/unknown/not-applicable cost persistence.
- `services/api/src/motif_forge/observability/models.py`: cost status and pricing-version contract.
- `services/api/src/motif_forge/worker/outbox.py`: Graph start/resume/cancel message schemas and publisher.
- `services/api/src/motif_forge/worker/resume_dispatcher.py`: construct Parent v2 with real or deterministic planner and process graph actions.
- `services/api/src/motif_forge/api/app.py`: register router and shared runtime dependencies, not another large route block.
- `services/api/src/motif_forge/config.py`, `.env.example`, `compose.yaml`: bounded provider/runtime configuration; no secret value.
- `package.json`, `package-lock.json`: pin `openapi-typescript` and add reproducible type generation.

---

### Task 1: Persisted AI Run, immutable Plan, events, and truthful usage

**Files:**
- Create: `services/api/src/motif_forge/domain/ai_runs.py`
- Create: `services/api/src/motif_forge/application/ai_runs.py`
- Create: `services/api/src/motif_forge/infrastructure/persistence/ai_runs.py`
- Create: `infra/migrations/versions/20260813_0013_generate_ai_runs.py`
- Modify: `services/api/src/motif_forge/application/ports.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/tables.py`
- Modify: `services/api/src/motif_forge/observability/models.py`
- Modify: `services/api/src/motif_forge/infrastructure/observability.py`
- Test: `services/api/tests/unit/domain/test_ai_runs.py`
- Test: `services/api/tests/unit/application/test_ai_runs.py`
- Test: `services/api/tests/unit/infrastructure/persistence/test_tables.py`
- Test: `services/api/tests/unit/infrastructure/test_observability.py`
- Test: `services/api/tests/integration/test_postgres_ai_runs.py`

**Interfaces:**
- Produces: `AIRun`, `AIRunEvent`, `PersistedCompositionPlan`, `AIRunApproval`, `ModelCost`, `CreateAIRun`, `PersistCompositionPlan`, `RecordAIRunEvent`, `ReadAIRun`, `ListAIRunEvents`, `RequestAIRunAction`, `ReserveModelRequest`, `RecordModelUsage`, and `PostgresAIRunUnitOfWork`.
- Consumes: existing `CompositionBrief`, `CompositionPlan`, `IdempotencyRow`, `OutboxEventRow`, project/branch/Revision tables, and telemetry records.

- [ ] **Step 1: Write strict domain and migration-shape tests**

```python
def test_ai_run_rejects_terminal_status_without_terminal_timestamp() -> None:
    with pytest.raises(ValidationError):
        AIRun(
            run_id=uuid4(), project_id=uuid4(), branch_id=uuid4(),
            base_revision_id=uuid4(), thread_id="generate-abc",
            status=AIRunStatus.SUCCEEDED, terminal_at=None,
        )

def test_unknown_cost_is_not_serialized_as_zero() -> None:
    cost = ModelCost(status=CostStatus.UNKNOWN)
    assert cost.amount_microusd is None
    assert cost.pricing_version is None
```

Also assert allowed transitions, immutable Plan hash verification, approval assertion hashing, monotonic event sequence, atomic model-request reservation, one shared repair allowance, token accounting, and rejection of raw reasoning/secret-like fields in event payloads.

- [ ] **Step 2: Run the narrow tests and capture RED**

Run:

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/domain/test_ai_runs.py \
  services/api/tests/unit/application/test_ai_runs.py \
  services/api/tests/unit/infrastructure/test_observability.py -q
```

Expected: collection fails because S2 domain/application types do not exist.

- [ ] **Step 3: Implement the strict domain contracts**

Use these public shapes:

```python
class AIRunStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    WAITING_APPROVAL = "waiting_approval"
    MATERIALIZING = "materializing"
    WAITING_WORKER = "waiting_worker"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"

class CostStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"

class PersistedCompositionPlan(DomainModel):
    plan_id: UUID
    run_id: UUID
    plan: CompositionPlan
    content_hash: str
    provider: str
    model: str
    prompt_version: str
    schema_version: str
    style_pack_version: str
    fallback_reason: str | None
    created_at: datetime

class AIRunEvent(DomainModel):
    sequence: int
    event_id: UUID
    run_id: UUID
    event_type: str
    phase: str
    payload: dict[str, object]
    created_at: datetime

class ModelRequestKind(StrEnum):
    INITIAL = "initial"
    TRANSPORT_RETRY = "transport_retry"
    SCHEMA_REPAIR = "schema_repair"
    STRATEGY_REPAIR = "strategy_repair"
```

Implement canonical Plan hashing with the existing canonical JSON rules. Store only an approval assertion hash, never the raw assertion, in `AIRun`.

- [ ] **Step 4: Add migration `0013` and SQLAlchemy rows**

Add `app.ai_runs`, `app.composition_plans`, `app.ai_run_events`, and `app.ai_model_request_reservations`. Use a `BIGSERIAL`/identity primary event sequence so SSE `Last-Event-ID` is ordered. Add foreign keys to Project/Branch/Revision where the referenced resource exists, unique constraints for `(project_id, idempotency_key)`, `(run_id, content_hash)`, `(run_id, event_type, dedupe_key)`, and `(run_id, request_ordinal)`. A model reservation stores request kind, status (`reserved|observed`), provider operation ID, token fields, and timestamps without prompt/response/reasoning.

Alter `observability.usage_ledger`:

```sql
ALTER COLUMN estimated_cost_microusd DROP NOT NULL;
ADD COLUMN cost_status varchar(24) NOT NULL DEFAULT 'unknown';
ADD COLUMN pricing_version varchar(80) NULL;
```

Backfill historical zero rows as `unknown`, not `known`.

- [ ] **Step 5: Implement transactional application use cases and PostgreSQL adapter**

The create transaction must atomically insert `AIRun`, `ai_run.created`, an idempotency record, and `graph.start.requested` outbox event. `PersistCompositionPlan` verifies canonical hash and inserts exactly one immutable row for `(run_id, hash)`. `RequestAIRunAction` uses optimistic run version and inserts resume/cancel/retry outbox intent in the same transaction.

`ReserveModelRequest(run_id, kind)` locks the AI Run row, refuses a fourth upstream request, refuses a second schema/strategy repair, then increments `submitted_model_requests` before network I/O. `RecordModelUsage(run_id, reservation_id, usage)` idempotently adds provider-reported tokens and marks the reservation observed. A crash after reservation remains conservatively counted; restart never resets paid budget.

- [ ] **Step 6: Run unit, migration, and real PostgreSQL tests**

Run:

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/domain/test_ai_runs.py \
  services/api/tests/unit/application/test_ai_runs.py \
  services/api/tests/unit/infrastructure/test_observability.py \
  services/api/tests/unit/infrastructure/persistence/test_tables.py -q
uv run alembic upgrade head --sql >/private/tmp/motif-forge-s2-up.sql
uv run alembic downgrade 20260813_0013:20260812_0012 --sql >/private/tmp/motif-forge-s2-down.sql
MOTIF_FORGE_TEST_POSTGRES_DSN="$MOTIF_FORGE_TEST_POSTGRES_DSN" \
  /private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/integration/test_postgres_ai_runs.py -q
```

Expected: unit tests pass; upgrade/downgrade SQL renders; real PostgreSQL proves create/idempotent replay, Plan immutability, monotonic event replay, approval persistence, cancel, and isolated transaction rollback.

- [ ] **Step 7: Commit**

```bash
git add services/api/src/motif_forge/domain/ai_runs.py \
  services/api/src/motif_forge/application/ai_runs.py \
  services/api/src/motif_forge/application/ports.py \
  services/api/src/motif_forge/infrastructure/persistence/ai_runs.py \
  services/api/src/motif_forge/infrastructure/persistence/tables.py \
  services/api/src/motif_forge/observability/models.py \
  services/api/src/motif_forge/infrastructure/observability.py \
  infra/migrations/versions/20260813_0013_generate_ai_runs.py \
  services/api/tests/unit/domain/test_ai_runs.py \
  services/api/tests/unit/application/test_ai_runs.py \
  services/api/tests/unit/infrastructure/test_observability.py \
  services/api/tests/unit/infrastructure/persistence/test_tables.py \
  services/api/tests/integration/test_postgres_ai_runs.py
git commit -m "feat: persist S2 AI runs and plans"
```

---

### Task 2: Extract the reusable planning subgraph

**Files:**
- Create: `services/api/src/motif_forge/agent/planning_subgraph.py`
- Modify: `services/api/src/motif_forge/agent/graph.py`
- Modify: `services/api/src/motif_forge/agent/schemas.py`
- Test: `services/api/tests/unit/agent/test_planning_subgraph.py`
- Modify: `services/api/tests/unit/agent/test_graph.py`
- Modify: `services/api/tests/integration/test_postgres_checkpoint_resume.py`

**Interfaces:**
- Produces: `PlanningSubgraphState`, `initial_planning_state()`, `build_composition_planning_subgraph(planner, telemetry)`, and `PlanningResult`.
- Consumes: `CompositionPlanner`, `CompositionBrief`, `CompositionPlan`, deterministic fallback, error policy, and telemetry.

- [ ] **Step 1: Write failing extraction tests**

Assert the reusable subgraph:

```python
result = await subgraph.ainvoke(initial_planning_state(...))
assert result["phase"] == "planning_complete"
assert result["plan"]["schema_version"] == "composition-plan.v1"
assert "__interrupt__" not in result
```

Also test invalid brief, one repair, provider failure to fallback, budget exhaustion, no hidden approval, and no raw `reasoning_content` field.

- [ ] **Step 2: Run tests and capture RED**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/agent/test_planning_subgraph.py \
  services/api/tests/unit/agent/test_graph.py -q
```

Expected: import failure for `planning_subgraph`.

- [ ] **Step 3: Move node construction without copying logic**

Move brief validation, planner, generic Plan validation, repair, error classification, and fallback into the new builder. Its terminal result is one of:

```python
class PlanningResult(TypedDict):
    phase: Literal["planning_complete", "planning_failed"]
    plan: NotRequired[dict[str, object]]
    provider_metadata: NotRequired[dict[str, str]]
    usage: NotRequired[dict[str, int]]
    counters: dict[str, int]
    fallback_reason: NotRequired[str]
    warnings: NotRequired[list[str]]
    error: NotRequired[dict[str, object]]
```

No subgraph node may call `interrupt`, persist a Plan, create a Revision, or enqueue work.

- [ ] **Step 4: Rebuild the standalone Plan graph as a regression wrapper**

`build_composition_plan_graph()` invokes the shared planning subgraph, then appends its legacy approval/final terminal nodes. Existing topology/version remains for old checkpoints. New Parent integration will mount only the planning-only builder.

- [ ] **Step 5: Prove behavior and old checkpoint regression**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/agent/test_planning_subgraph.py \
  services/api/tests/unit/agent/test_graph.py \
  services/api/tests/integration/test_postgres_checkpoint_resume.py -q
uv run ruff check services/api/src/motif_forge/agent services/api/tests/unit/agent
uv run mypy services/api/src/motif_forge/agent
```

Expected: standalone approval/restart tests remain green; planning-only tests prove no interrupt.

- [ ] **Step 6: Commit**

```bash
git add services/api/src/motif_forge/agent/planning_subgraph.py \
  services/api/src/motif_forge/agent/graph.py \
  services/api/src/motif_forge/agent/schemas.py \
  services/api/tests/unit/agent/test_planning_subgraph.py \
  services/api/tests/unit/agent/test_graph.py \
  services/api/tests/integration/test_postgres_checkpoint_resume.py
git commit -m "refactor: extract reusable composition planning subgraph"
```

---

### Task 3: Enforce one shared DeepSeek request/token budget and safe strategy prompt

**Files:**
- Modify: `services/api/src/motif_forge/agent/planner.py`
- Modify: `services/api/src/motif_forge/providers/deepseek.py`
- Modify: `services/api/src/motif_forge/config.py`
- Modify: `.env.example`
- Test: `services/api/tests/unit/providers/test_deepseek.py`
- Modify: `services/api/tests/unit/test_config.py`

**Interfaces:**
- Produces: `ProviderBudgetLedger`, `ProviderBudgetExceeded`, budget-aware `DeepSeekJsonClient`, and `build_synth_ambient_planner(settings, run_id, budget_ledger)`.
- Consumes: `DEEPSEEK_API_KEY`, exact model/base URL settings, current JSON client and `CompositionPlanner` Protocol.

- [ ] **Step 1: Write failing budget and prompt tests**

Use `httpx.MockTransport` to prove:

```python
ledger = RecordingProviderBudgetLedger(max_requests=3, max_total_tokens=12_000)
client = DeepSeekJsonClient(..., max_attempts=3, run_id=run_id, budget_ledger=ledger)
```

- two 503 responses plus one success consume all three upstream requests;
- a schema repair is refused after those three requests;
- token usage over 12,000 returns `MODEL_TOKEN_BUDGET_EXHAUSTED`;
- unsupported style is never placed in the prompt;
- request payload uses exact model, thinking enabled, high effort, JSON Output, and bounded `max_tokens`;
- repr, exception text, and telemetry contain no API key or `reasoning_content`.

- [ ] **Step 2: Run provider tests and capture RED**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/providers/test_deepseek.py \
  services/api/tests/unit/test_config.py -q
```

- [ ] **Step 3: Implement one persistent per-Run budget ledger**

The client receives the PostgreSQL-backed ledger from Task 1. Every submission reserves before network I/O:

```python
class ProviderBudgetLedger(Protocol):
    async def reserve_request(
        self, *, run_id: UUID, kind: ModelRequestKind
    ) -> ModelRequestReservation: ...

    async def record_usage(
        self, *, reservation_id: UUID, usage: PlannerUsage
    ) -> ModelBudgetSnapshot: ...
```

Reserve immediately before every HTTP POST, including retries and repairs. Record usage after every valid provider envelope. Transport attempts use `TRANSPORT_RETRY` after the first request. Schema and strategy repair share one persisted repair allowance. Never permit a recursive repair call or dispatcher restart to receive a fresh budget.

- [ ] **Step 4: Freeze the Synth Ambient planning prompt**

The prompt version becomes `composition-planner.synth-ambient.v2` and explicitly requires role coverage `pad|melody|bass|rhythm`, contiguous sections, 4/4, brief-aligned duration/BPM/key, broad style attributes, and JSON only. User strings are delimited as untrusted data. No tools are exposed in S2 planning.

- [ ] **Step 5: Verify provider contracts**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/providers/test_deepseek.py \
  services/api/tests/unit/agent/test_planning_subgraph.py \
  services/api/tests/unit/test_config.py -q
uv run ruff check services/api/src/motif_forge/providers services/api/src/motif_forge/agent
uv run mypy services/api/src/motif_forge/providers services/api/src/motif_forge/agent
```

- [ ] **Step 6: Commit**

```bash
git add services/api/src/motif_forge/agent/planner.py \
  services/api/src/motif_forge/providers/deepseek.py \
  services/api/src/motif_forge/config.py .env.example \
  services/api/tests/unit/providers/test_deepseek.py \
  services/api/tests/unit/test_config.py
git commit -m "feat: bound DeepSeek planning requests and tokens"
```

---

### Task 4: Deterministic Synth Ambient compatibility policy and compiler

**Files:**
- Create: `services/api/src/motif_forge/domain/synth_ambient.py`
- Modify: `services/api/src/motif_forge/domain/composition.py`
- Test: `services/api/tests/unit/domain/test_synth_ambient.py`
- Modify: `services/api/tests/unit/domain/test_composition.py`

**Interfaces:**
- Produces: `SYNTH_AMBIENT_POLICY_VERSION`, `validate_synth_ambient_plan(brief, plan) -> StrategyValidation`, and `compile_synth_ambient_plan(project_id, plan, seed) -> CompositionBuild`.
- Consumes: `CompositionBrief`, `CompositionPlan`, `PatternSpec`, ArrangementIR, existing command application, built-in presets.

- [ ] **Step 1: Write policy boundary tests**

Create parameterized cases for:

- style mismatch, 3/4 meter, duration mismatch above tolerance, explicit BPM/key mismatch;
- missing/duplicate role mapping;
- noncontiguous sections already rejected by generic schema;
- negative constraint not represented;
- all twelve tonics and seven admitted modes;
- stable ordered rule IDs and conservative no-match failure.

Expected policy result:

```python
StrategyValidation(
    compatible=False,
    policy_version="synth-ambient-plan-policy.v1",
    issues=(StrategyIssue(rule_id="SAP-004", code="ROLE_COVERAGE_INVALID", ...),),
)
```

- [ ] **Step 2: Write compiler determinism tests**

Assert identical Plan/project/seed produces identical command payload and Arrangement hash; different approved Plan energy/sections/key changes expected patterns; all notes remain in bounds; arrangement duration matches Plan; exactly four supported tracks exist; S1 fixed build hash remains unchanged.

- [ ] **Step 3: Run tests and capture RED**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/domain/test_synth_ambient.py \
  services/api/tests/unit/domain/test_composition.py -q
```

- [ ] **Step 4: Implement ordered compatibility rules**

Rules consume only validated facts and return issue codes; the model never interprets the rule prose. Duration tolerance is the larger of one bar or 10% of requested seconds. Explicit key/BPM must match exactly. The required semantic roles are `pad`, `melody`, `bass`, and `rhythm`.

- [ ] **Step 5: Implement the plan-driven compiler without changing S1**

Keep `build_s1_composition()` byte-for-byte behavior. Add a new compiler with:

```python
def compile_synth_ambient_plan(
    project_id: UUID,
    *,
    plan: CompositionPlan,
    seed: int,
) -> CompositionBuild:
    ...
```

Use PPQ ticks, Plan sections/energy/BPM/key/mode, deterministic scale interval tables, stable UUIDv5 IDs, four existing built-in instruments, and existing commands. Avoid any model call or external asset lookup.

- [ ] **Step 6: Verify domain and baseline**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/domain/test_synth_ambient.py \
  services/api/tests/unit/domain/test_composition.py \
  services/api/tests/eval/test_s1_deterministic_eval.py -q
uv run ruff check services/api/src/motif_forge/domain services/api/tests/unit/domain
uv run mypy services/api/src/motif_forge/domain
```

- [ ] **Step 7: Commit**

```bash
git add services/api/src/motif_forge/domain/synth_ambient.py \
  services/api/src/motif_forge/domain/composition.py \
  services/api/tests/unit/domain/test_synth_ambient.py \
  services/api/tests/unit/domain/test_composition.py
git commit -m "feat: compile approved synth ambient plans"
```

---

### Task 5: Persist Plan and materialize one approved Revision

**Files:**
- Create: `services/api/src/motif_forge/application/generation.py`
- Modify: `services/api/src/motif_forge/application/composition.py`
- Test: `services/api/tests/unit/application/test_generation.py`
- Test: `services/api/tests/integration/test_postgres_generate_materialization.py`

**Interfaces:**
- Produces: `PersistPlanningResult`, `LoadCompositionPlan`, `PreparePlanDrivenCompositionPreview`, and `MaterializeApprovedComposition`.
- Consumes: Task 1 AI Run/Plan persistence, Task 4 compiler, existing `CreateCommandPreview` and `DecidePreview`.

- [ ] **Step 1: Write failing materialization tests**

Cover:

- persisted Plan hash mismatch fails before compile;
- rejection path never calls compiler/preview;
- approval requires actor, 16+ character assertion, and expected Plan hash;
- one approved Plan creates a Candidate with complete generated commands and `source_run_id`;
- approval creates one immutable Revision and advances one Branch head;
- replay returns the same Candidate/Revision;
- concurrent Branch change returns `REVISION_CONFLICT` and creates no second Revision.

- [ ] **Step 2: Run tests and capture RED**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/application/test_generation.py \
  services/api/tests/integration/test_postgres_generate_materialization.py -q
```

- [ ] **Step 3: Implement Plan persistence adapter**

`PersistPlanningResult` accepts a validated planning output, revalidates `CompositionPlan`, canonicalizes it, persists it, and updates the AI Run to `waiting_approval` with `plan_id/hash`. It is idempotent by `run_id + plan_hash`.

- [ ] **Step 4: Implement approved materialization**

Use these request fields:

```python
class MaterializeApprovedCompositionRequest(DomainModel):
    run_id: UUID
    project_id: UUID
    branch_id: UUID
    base_revision_id: UUID
    plan_id: UUID
    expected_plan_hash: str
    seed: int
    actor_id: str
    approval_assertion: str = Field(min_length=16, max_length=500)
    idempotency_key: str
```

Load and hash-check the immutable Plan, compile it, call `CreateCommandPreview` with the complete command tuple and `source_run_id`, then call `DecidePreview(APPROVE)` using the already-persisted human authorization. Do not add a direct Revision write.

- [ ] **Step 5: Verify real transaction behavior**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/application/test_generation.py -q
MOTIF_FORGE_TEST_POSTGRES_DSN="$MOTIF_FORGE_TEST_POSTGRES_DSN" \
  /private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/integration/test_postgres_generate_materialization.py -q
uv run ruff check services/api/src/motif_forge/application services/api/tests/unit/application
uv run mypy services/api/src/motif_forge/application
```

- [ ] **Step 6: Commit**

```bash
git add services/api/src/motif_forge/application/generation.py \
  services/api/src/motif_forge/application/composition.py \
  services/api/tests/unit/application/test_generation.py \
  services/api/tests/integration/test_postgres_generate_materialization.py
git commit -m "feat: materialize approved composition plans"
```

---

### Task 6: Reusable complete-song export orchestration

**Files:**
- Modify: `services/api/src/motif_forge/application/generation.py`
- Modify: `services/api/src/motif_forge/application/rendering.py`
- Test: `services/api/tests/unit/application/test_generation_export.py`
- Test: `services/api/tests/integration/test_postgres_generate_export_jobs.py`
- Modify: `scripts/run_s1_deterministic_smoke.py`

**Interfaces:**
- Produces: `CompleteExportCursor`, `EnqueueNextCompleteExportJob`, `CollectCompleteExportArtifact`, and `build_export_bundle_payload`.
- Consumes: existing `EnqueueMediaJob`, `EnqueueFollowupMediaJob`, Revision loader, Audio/Bundle Artifact loaders, AudioGraph compiler, and S1 media payloads.

- [ ] **Step 1: Write failing orchestration tests**

Assert ordered scopes:

```python
assert cursor.pending_steps == (
    "master", "stem:pad", "stem:melody", "stem:bass", "stem:rhythm", "mp3", "bundle"
)
```

Verify deterministic idempotency keys, Revision/Arrangement binding, artifact profile validation, duplicate completion replay, partial artifact preservation, no copied audio in Bundle, and terminal failure when a returned artifact has wrong lineage.

- [ ] **Step 2: Run tests and capture RED**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/application/test_generation_export.py \
  services/api/tests/integration/test_postgres_generate_export_jobs.py -q
```

- [ ] **Step 3: Extract the S1 script orchestration into application services**

Application services create payloads and enqueue jobs but do not execute Worker code. The first Master creates one existing `MediaRun`; every later step uses `EnqueueFollowupMediaJob` on that run. Each step reloads authoritative Revision/artifact data and validates hashes before enqueue.

- [ ] **Step 4: Keep S1 smoke on the shared service**

Refactor `run_s1_deterministic_smoke.py` to call the extracted orchestration rather than maintaining a second payload-building implementation. Its fixed S1 user flow remains unchanged.

- [ ] **Step 5: Verify job contracts**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/application/test_generation_export.py \
  services/api/tests/unit/application/test_rendering.py \
  services/api/tests/unit/application/test_exporting.py -q
MOTIF_FORGE_TEST_POSTGRES_DSN="$MOTIF_FORGE_TEST_POSTGRES_DSN" \
  /private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/integration/test_postgres_generate_export_jobs.py \
  services/api/tests/integration/test_s1_render_job_contract.py -q
```

- [ ] **Step 6: Commit**

```bash
git add services/api/src/motif_forge/application/generation.py \
  services/api/src/motif_forge/application/rendering.py \
  services/api/tests/unit/application/test_generation_export.py \
  services/api/tests/integration/test_postgres_generate_export_jobs.py \
  scripts/run_s1_deterministic_smoke.py
git commit -m "refactor: expose reusable complete-song export chain"
```

---

### Task 7: Mount `generate` in Parent Graph v2

**Files:**
- Create: `services/api/src/motif_forge/agent/generate.py`
- Modify: `services/api/src/motif_forge/agent/parent_graph.py`
- Modify: `services/api/tests/unit/agent/test_parent_graph.py`
- Test: `services/api/tests/unit/agent/test_generate_graph.py`
- Modify: `services/api/tests/integration/test_postgres_checkpoint_resume.py`

**Interfaces:**
- Produces: `GenerateRequest`, `PlanApprovalDecision`, `initial_generate_state()`, and generate node factory mounted by `build_parent_graph()`.
- Consumes: planning subgraph, Plan persistence/materialization, storage gate, complete-export orchestration, media worker resume payload.

- [ ] **Step 1: Write Parent v2 route tests**

Cover:

- existing import/time-stretch/rehydrate branches still route unchanged;
- generate state records Parent v2/state v2 and finite IDs;
- unsupported style/meter returns terminal error with planner calls `0`;
- valid plan persists then interrupts once with Plan hash and summary;
- reject terminates with no materialization/enqueue calls;
- approve materializes Revision then sequentially waits for all seven job steps;
- worker failure routes terminal with partial artifact refs;
- fallback still interrupts;
- cancellation at each phase terminates without later side effects.

- [ ] **Step 2: Run Graph tests and capture RED**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/agent/test_generate_graph.py \
  services/api/tests/unit/agent/test_parent_graph.py -q
```

- [ ] **Step 3: Add Parent v2 state and generate adapters**

Extend operation to `Literal["generate", "time_stretch", "import_audio", "artifact_rehydrate"]`. Generate state stores only Plan/Revision/Job/Artifact IDs, hashes, counters, cursor, approval metadata, and compact errors. `PlanInputAdapter` builds planning state. `PlanOutputAdapter` invokes `PersistPlanningResult` and returns only `plan_id/hash/summary`.

- [ ] **Step 4: Add the single approval interrupt**

Use:

```python
class PlanApprovalDecision(DomainModel):
    decision: Literal["approve", "reject"]
    actor_id: str = Field(min_length=1, max_length=160)
    approval_assertion: str = Field(min_length=16, max_length=500)
    expected_plan_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    note: str = Field(default="", max_length=500)
```

Reject ends before Candidate creation. Approve records the authorization and invokes materialization once.

- [ ] **Step 5: Add render cursor and worker wait loop**

Each completion resumes the same Parent thread, verifies expected job/run/event, collects the authoritative artifact, advances the finite cursor, checkpoints, and enqueues the next step. Duplicate resume event IDs return without side effects. There is no model-based error routing for media errors.

- [ ] **Step 6: Verify restart without repeated model/materialization/enqueue**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/agent/test_generate_graph.py \
  services/api/tests/unit/agent/test_parent_graph.py -q
MOTIF_FORGE_TEST_POSTGRES_DSN="$MOTIF_FORGE_TEST_POSTGRES_DSN" \
  /private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/integration/test_postgres_checkpoint_resume.py -q
```

- [ ] **Step 7: Commit**

```bash
git add services/api/src/motif_forge/agent/generate.py \
  services/api/src/motif_forge/agent/parent_graph.py \
  services/api/tests/unit/agent/test_generate_graph.py \
  services/api/tests/unit/agent/test_parent_graph.py \
  services/api/tests/integration/test_postgres_checkpoint_resume.py
git commit -m "feat: mount generation in Parent Graph v2"
```

---

### Task 8: Asynchronous Graph start/resume/cancel dispatcher

**Files:**
- Modify: `services/api/src/motif_forge/worker/outbox.py`
- Modify: `services/api/src/motif_forge/worker/resume_dispatcher.py`
- Modify: `services/api/src/motif_forge/config.py`
- Modify: `compose.yaml`
- Test: `services/api/tests/unit/worker/test_outbox.py`
- Test: `services/api/tests/integration/test_generate_dispatcher.py`

**Interfaces:**
- Produces: `GraphActionPayload v1`, `ParentGraphActionPublisher`, and a dispatcher configured with real DeepSeek only when the key is present.
- Consumes: Task 1 outbox rows, Parent v2, `PostgresTelemetryRecorder`, Plan/Generation/Media/Storage application services.

- [ ] **Step 1: Write action delivery tests**

Assert `graph.start.requested`, `graph.resume.requested`, and `graph.cancel.requested` validate strict payloads, target only `parent.generate.v1`, reject arbitrary node names/state, and replay safely. Prove start delivery twice makes one planner call; resume delivery twice makes one Revision; cancel wakes the same thread.

- [ ] **Step 2: Run tests and capture RED**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/worker/test_outbox.py \
  services/api/tests/integration/test_generate_dispatcher.py -q
```

- [ ] **Step 3: Implement one strict action publisher**

Use a discriminated payload:

```python
class GraphActionPayload(DomainModel):
    schema_version: Literal["graph-action.v1"] = "graph-action.v1"
    action: Literal["start", "resume", "cancel"]
    run_id: UUID
    thread_id: str
    run_type: Literal["parent.generate.v1"]
    decision: PlanApprovalDecision | None = None
```

For `start`, load authoritative Run/Brief and call `ainvoke(initial_generate_state(...))`. For `resume`, load the pending Run action and use `Command(resume=...)`. For `cancel`, update authoritative state first and resume/wake only when needed.

- [ ] **Step 4: Wire the real planner and telemetry in the dispatcher**

Construct one PostgreSQL budget ledger per AI Run. Use `DeepSeekCompositionPlanner` only when `DEEPSEEK_API_KEY` is configured; otherwise inject a planner that raises `DEEPSEEK_API_KEY_MISSING`, allowing the existing fallback route. Override `DEEPSEEK_API_KEY` to an empty value for API, migration, ordinary dispatcher, media-worker, storage-init, and render-worker services; only `resume-dispatcher` may inherit the key from `.env`.

- [ ] **Step 5: Verify real PostgreSQL at-least-once behavior**

```bash
MOTIF_FORGE_TEST_POSTGRES_DSN="$MOTIF_FORGE_TEST_POSTGRES_DSN" \
  /private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/integration/test_generate_dispatcher.py \
  services/api/tests/integration/test_postgres_checkpoint_resume.py -q
uv run ruff check services/api/src/motif_forge/worker
uv run mypy services/api/src/motif_forge/worker
docker compose config >/private/tmp/motif-forge-s2-compose.yaml
```

- [ ] **Step 6: Commit**

```bash
git add services/api/src/motif_forge/worker/outbox.py \
  services/api/src/motif_forge/worker/resume_dispatcher.py \
  services/api/src/motif_forge/config.py compose.yaml \
  services/api/tests/unit/worker/test_outbox.py \
  services/api/tests/integration/test_generate_dispatcher.py
git commit -m "feat: dispatch durable generation graph actions"
```

---

### Task 9: AI Run REST, persistent SSE, and generated TypeScript contracts

**Files:**
- Create: `services/api/src/motif_forge/api/ai_runs.py`
- Modify: `services/api/src/motif_forge/api/app.py`
- Test: `services/api/tests/unit/api/test_ai_runs.py`
- Test: `services/api/tests/integration/test_ai_run_sse.py`
- Create: `scripts/export_openapi.py`
- Modify: `package.json`
- Modify: `package-lock.json`
- Create: `apps/web/src/generated/api-schema.d.ts`

**Interfaces:**
- Produces: create/read/events/resume/cancel/retry routes and generated TypeScript declarations.
- Consumes: Task 1 application use cases and persistent event sequence.

- [ ] **Step 1: Write API contract tests**

Cover:

- create returns `202`, never invokes Graph/model inline, and replays by `Idempotency-Key`;
- unsupported style/meter returns 422 and inserts no Run/outbox/model usage;
- GET returns `pending_action`, budget/usage/fallback, Revision/Bundle refs, and safe error;
- resume requires expected Plan hash, actor, assertion, and idempotency key;
- cancel is idempotent; retry creates a child Run rather than rewinding terminal state;
- clients cannot submit model name, max tokens, file paths, render job payloads, or Graph node names.

- [ ] **Step 2: Write persistent SSE replay tests**

Create events with sequences 11–14, connect with `Last-Event-ID: 12`, and assert only 13–14 are emitted in order with `id`, `event`, and JSON `data`. Recreate the FastAPI app/database connection and prove replay still works. Assert terminal event closes and heartbeat comments do not advance event ID.

- [ ] **Step 3: Run tests and capture RED**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/api/test_ai_runs.py \
  services/api/tests/integration/test_ai_run_sse.py -q
```

- [ ] **Step 4: Implement router and SSE without a new runtime dependency**

Use `StreamingResponse` and bounded PostgreSQL polling. The event stream queries `sequence > last_seen`, emits ordered persisted events, sleeps for the configured interval only when empty, emits a heartbeat comment, checks disconnect, and closes on a terminal event. Redis is not required for replay correctness.

- [ ] **Step 5: Generate, do not hand-maintain, TypeScript API types**

Add:

```json
{
  "scripts": {
    "generate:openapi": "python3 scripts/export_openapi.py && openapi-typescript /private/tmp/motif-forge-openapi.json -o apps/web/src/generated/api-schema.d.ts"
  },
  "devDependencies": {
    "openapi-typescript": "7.10.1"
  }
}
```

Run `npm install --package-lock-only` for the lockfile, then `npm run generate:openapi`. The Python exporter constructs the app with test settings and writes only `/private/tmp/motif-forge-openapi.json`.

- [ ] **Step 6: Verify API and generated contracts**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/unit/api/test_ai_runs.py \
  services/api/tests/integration/test_ai_run_sse.py -q
npm run generate:openapi
npm run build:web
cp apps/web/src/generated/api-schema.d.ts /private/tmp/motif-forge-api-schema.d.ts
npm run generate:openapi
cmp /private/tmp/motif-forge-api-schema.d.ts apps/web/src/generated/api-schema.d.ts
```

- [ ] **Step 7: Commit**

```bash
git add services/api/src/motif_forge/api/ai_runs.py \
  services/api/src/motif_forge/api/app.py \
  services/api/tests/unit/api/test_ai_runs.py \
  services/api/tests/integration/test_ai_run_sse.py \
  scripts/export_openapi.py package.json package-lock.json \
  apps/web/src/generated/api-schema.d.ts
git commit -m "feat: expose durable AI run and SSE APIs"
```

---

### Task 10: Recovery, cancellation, and complete Parent Graph integration

**Files:**
- Test: `services/api/tests/integration/test_s2_generate_parent_graph.py`
- Modify: `services/api/src/motif_forge/agent/generate.py`
- Modify: `services/api/src/motif_forge/worker/resume_dispatcher.py`
- Modify: `services/api/src/motif_forge/application/ai_runs.py`

**Interfaces:**
- Produces: real PostgreSQL checkpoint/restart and fault-injection evidence for the whole no-cost Graph path.
- Consumes: Tasks 1–9.

- [ ] **Step 1: Write a deterministic end-to-end integration harness**

Use a recording static planner and fake media completion publisher backed by real PostgreSQL/checkpointer. Drive:

```text
create -> dispatch start -> approval interrupt -> resume approve
-> Revision -> master/stems/mp3/bundle waits -> succeeded
```

Assert one planner call, one Plan, one Candidate, one Revision, seven Jobs, six audio artifacts, one logical Bundle, and ordered event projection.

- [ ] **Step 2: Add crash and duplicate fault cases**

Parameterize restart after:

- validated/persisted Plan;
- approval interrupt;
- materialized Revision;
- Master completion;
- third Stem completion;
- MP3 completion;
- Bundle completion before final Run projection.

Deliver every start/resume/completion event twice. Counts must remain unchanged.

- [ ] **Step 3: Add cancellation and terminal error cases**

Cancel before model, while waiting approval, after Revision before render, and while waiting on a Worker. Also inject storage pressure, Branch conflict, wrong artifact lineage, terminal render failure, and missing external root. Assert authoritative terminal status, partial refs, no later side effects, and safe error codes.

- [ ] **Step 4: Run tests and fix only demonstrated gaps**

```bash
MOTIF_FORGE_TEST_POSTGRES_DSN="$MOTIF_FORGE_TEST_POSTGRES_DSN" \
  /private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/integration/test_s2_generate_parent_graph.py -q
```

Use systematic debugging for every unexpected failure. Do not weaken assertions or add another retry layer.

- [ ] **Step 5: Run affected Python quality gates**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest services/api/tests/unit -q
uv run ruff check services/api/src services/api/tests
uv run mypy
git diff --check
```

- [ ] **Step 6: Commit**

```bash
git add services/api/tests/integration/test_s2_generate_parent_graph.py \
  services/api/src/motif_forge/agent/generate.py \
  services/api/src/motif_forge/worker/resume_dispatcher.py \
  services/api/src/motif_forge/application/ai_runs.py
git commit -m "test: prove S2 generation recovery and idempotency"
```

---

### Task 11: S2 Eval set and no-cost complete runtime smoke

**Files:**
- Create: `evals/s2-synth-ambient-v1.json`
- Create: `services/api/tests/eval/test_s2_generate_eval.py`
- Create: `scripts/run_s2_deterministic_smoke.py`
- Modify: `scripts/check_s1.sh`
- Test: `tests/test_s2_script_contract.py`

**Interfaces:**
- Produces: versioned S2 eval cases, three-baseline result summary, and deterministic Compose acceptance evidence.
- Consumes: full Parent v2, deterministic fallback/static planner, real media workers, Render Worker, and AI Run APIs.

- [ ] **Step 1: Add at least 24 versioned S2 cases**

The JSON fixture includes:

- 8 valid Synth Ambient briefs across duration/key/mode/energy shapes;
- 4 unsupported style/meter pre-model cases;
- 4 malformed/repair/fallback cases;
- 4 approval/rejection/conflict cases;
- 4 restart/duplicate/cancel/storage cases.

Every case includes `id`, `version`, tags, brief, expected route, hard constraints, forbidden behavior, latency/token budget, and failure label.

- [ ] **Step 2: Write Eval assertions and three baselines**

Compare:

1. fixed S1 deterministic template;
2. one valid Plan directly compiled;
3. full Parent Graph.

Measure schema pass, hard-constraint satisfaction, first playable rate, fallback rate, duplicate side effects, resume success, render/export success, calls/tokens, and known/unknown cost status. Keep deterministic feature checks separate from subjective audio judgment.

- [ ] **Step 3: Write a deterministic runtime smoke**

The script creates a Project and AI Run through the public API or application boundary, uses deterministic planner/fallback without a key, inspects the persisted PlanApproval interrupt, requires real approval actor/assertion environment variables, resumes the same thread, lets existing queue workers produce Master/four Stems/MP3/Bundle, then verifies DB lineage and physical checksums. It never calls `execute_media_job()` directly.

- [ ] **Step 4: Run no-cost Eval and host smoke contract**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest \
  services/api/tests/eval/test_s2_generate_eval.py \
  tests/test_s2_script_contract.py -q
```

- [ ] **Step 5: Rebuild only affected API image and recreate shared API processes**

The runtime wiring and migration require fresh container evidence:

```bash
docker compose build api
docker compose up -d --force-recreate migrate api dispatcher resume-dispatcher
docker compose ps
docker compose exec -T api uv run alembic current
```

Do not rebuild the Chromium Render image unless `packages/audio-engine` or `services/render-worker` changed.

- [ ] **Step 6: Run deterministic S2 Compose smoke**

```bash
MOTIF_FORGE_API_URL="http://127.0.0.1:8000" \
MOTIF_FORGE_S2_APPROVAL_ACTOR="local-user" \
MOTIF_FORGE_S2_APPROVAL_ASSERTION="I reviewed and approve this S2 composition plan" \
/private/tmp/motif-forge-venv/bin/python scripts/run_s2_deterministic_smoke.py
```

Expected: one Parent thread reaches `succeeded`; six audio Artifact refs and one logical Bundle share the approved Revision/Arrangement lineage; no paid model usage exists.

- [ ] **Step 7: Commit**

```bash
git add evals/s2-synth-ambient-v1.json \
  services/api/tests/eval/test_s2_generate_eval.py \
  scripts/run_s2_deterministic_smoke.py scripts/check_s1.sh \
  tests/test_s2_script_contract.py
git commit -m "test: add S2 generation eval and deterministic smoke"
```

---

### Task 12: Budgeted live DeepSeek acceptance, final verification, docs, and hygiene

**Files:**
- Create: `scripts/run_s2_live_deepseek_smoke.py`
- Test: `tests/test_s2_live_smoke_contract.py`
- Modify after fresh evidence: `docs/IMPLEMENTATION_STATUS.md`
- Modify after fresh evidence: `docs/TECH_EVOLUTION.md`
- Modify only if acceptance details change: `docs/NEXT_DEVELOPMENT_ROADMAP.md`
- Modify: `AGENTS.md`
- Modify: `README.md`

**Interfaces:**
- Produces: one secret-safe paid acceptance record, final S2 verification evidence, S3 handoff, and stage-end cache inventory.
- Consumes: all S2 tasks and configured `DEEPSEEK_API_KEY`.

- [ ] **Step 1: Write live-smoke guard tests before the script**

Assert the script:

- exits before HTTP when key is absent;
- refuses model other than `deepseek-v4-flash`;
- enforces three upstream requests and 12,000 tokens;
- requires explicit approval actor/assertion;
- stops after one success;
- redacts key, authorization headers, reasoning, and raw provider response;
- writes evidence only under configured external Artifact root or prints a bounded safe summary.

- [ ] **Step 2: Run guard tests and capture RED**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest tests/test_s2_live_smoke_contract.py -q
```

- [ ] **Step 3: Implement the opt-in live acceptance**

Use one reviewed brief: 72–90 seconds, Synth Ambient, instrumental, 4/4, four supported roles, broad mood/style language, no artist imitation. Create through the public AI Run API, wait through persistent SSE, inspect the Plan, submit the explicit approval, and wait for final Bundle. Stop on the first complete success. Do not silently fall back and report the paid acceptance as passed; `fallback_used=true` makes the paid gate incomplete.

- [ ] **Step 4: Run all deterministic gates before spending**

```bash
/private/tmp/motif-forge-venv/bin/python -m pytest services/api/tests tests -q
uv run ruff check services/api/src services/api/tests tests scripts
uv run mypy
npm run test:audio
npm run test:web
npm run build:audio
npm run build:web
npm run generate:openapi
git diff --exit-code apps/web/src/generated/api-schema.d.ts
docker compose config >/private/tmp/motif-forge-s2-compose-final.yaml
scripts/check_compose_runtime.sh
```

All must pass before the next step.

- [ ] **Step 5: Run exactly one paid acceptance**

Run from the configured environment without echoing the key:

```bash
MOTIF_FORGE_API_URL="http://127.0.0.1:8000" \
MOTIF_FORGE_S2_LIVE=1 \
MOTIF_FORGE_S2_APPROVAL_ACTOR="local-user" \
MOTIF_FORGE_S2_APPROVAL_ASSERTION="I reviewed and approve this live S2 composition plan" \
/private/tmp/motif-forge-venv/bin/python scripts/run_s2_live_deepseek_smoke.py
```

Expected evidence: `provider=deepseek`, `model=deepseek-v4-flash`, calls `<=3`, total tokens `<=12000`, schema valid, `fallback_used=false`, persisted approval, immutable Revision, complete Master/four Stems/MP3/Bundle, checksums, latency, and truthful cost status. Stop immediately after success.

- [ ] **Step 6: Independently inspect persisted evidence**

Query PostgreSQL by the printed safe Run ID. Verify Plan hash, usage, no false-zero cost, approval actor/assertion hash, Revision source Run, seven Jobs, six final audio artifacts, one logical Bundle, and terminal event sequence. Search logs and tracked diff for key material or `reasoning_content`.

- [ ] **Step 7: Update factual docs only from fresh evidence**

Update capability rows and S2/S3 active gate in `IMPLEMENTATION_STATUS.md` and `AGENTS.md`; append actual commands, counts, IDs, latency/tokens/cost status, failure classifications, image/cache facts, and known limitations to `TECH_EVOLUTION.md`; update README setup/API examples. Do not rewrite `PROJECT_GUIDE.md` because the product contract did not change. Change the roadmap only to mark S2 accepted and S3 active.

- [ ] **Step 8: Execute stage-end storage hygiene**

Freeze keep set: current tagged/running images, PostgreSQL/Redis volumes, final accepted Artifacts, lockfiles, external dependencies, and current source. Inventory first:

```bash
docker system df -v
docker builder du
du -sh . node_modules /private/tmp/motif-forge-venv
```

Remove only project test caches, generated build outputs, AppleDouble sidecars, obsolete failed build records, and cold project-owned BuildKit entries using the existing audited script. Never use `docker system prune --volumes`, delete images in use, or delete Artifact/PostgreSQL data. Re-run readiness and access the accepted Bundle afterward.

- [ ] **Step 9: Final verification and guide hash check**

```bash
openssl dgst -sha256 docs/PROJECT_GUIDE.md
git diff --check
git status --short
scripts/check_compose_runtime.sh
```

The guide hash must still be `21345f64304338777a9dd2603d34ad54448b6c4b82902bc743204ba1026c9f58` unless the user explicitly approved a contract change during execution.

- [ ] **Step 10: Commit and push only after independent code review**

```bash
git add scripts/run_s2_live_deepseek_smoke.py \
  tests/test_s2_live_smoke_contract.py \
  docs/IMPLEMENTATION_STATUS.md docs/TECH_EVOLUTION.md \
  docs/NEXT_DEVELOPMENT_ROADMAP.md AGENTS.md README.md
git commit -m "feat: complete unified DeepSeek generation slice"
git push origin main
```

Before the commit, use `superpowers:requesting-code-review`; resolve every Critical/Important issue with focused tests, then use `superpowers:verification-before-completion` against fresh outputs.

---

## Final acceptance summary

S2 may be marked complete only when:

- one `motif-forge-parent.v2` thread owns planning through Bundle completion;
- unsupported styles/meters are proven no-cost failures;
- DeepSeek and deterministic fallback produce auditable, schema-valid Plans;
- one real hash-bound human approval gates every from-zero Revision;
- replay/restart/cancel does not duplicate model calls, Plans, Revisions, Jobs, or Artifacts;
- the complete S1 media chain is reused, including exact lineage and logical Bundle behavior;
- persistent REST/SSE projections survive API restart;
- real PostgreSQL, deterministic Compose, and one budgeted paid DeepSeek acceptance pass;
- docs state the remaining truth: no S3 generation page, no other three style strategies, no multiple candidates, and no DAW editing yet;
- stage-end storage cleanup preserves runnable services and accepted artifacts.
