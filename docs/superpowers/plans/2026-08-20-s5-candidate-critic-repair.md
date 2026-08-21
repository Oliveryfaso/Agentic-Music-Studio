# S5 Dual Candidate, Evidence Critic, and Bounded Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the single Parent Graph so an approved Plan produces two durable candidates, compares them with an evidence-grounded Critic, performs at most one local deterministic Repair, waits for A/B selection, and exports only the selected immutable Revision.

**Architecture:** Candidate compilation fans out inside `motif-forge-parent.v2`, persists immutable CandidateSnapshots, and renders sequential `candidate-preview.v1` Artifacts without temporary Revisions. One strict Critic request evaluates both evidence bundles, deterministic code owns Repair and budgets, and a second interrupt materializes exactly one selected Preview through the existing Revision transaction.

**Tech Stack:** Python 3.12, Pydantic v2, LangGraph, FastAPI/OpenAPI, SQLAlchemy/PostgreSQL, Celery, Chromium/Tone.js, FFmpeg, React 19, TypeScript, Vitest, Pytest.

**Spec:** `docs/superpowers/specs/2026-08-20-s5-candidate-critic-repair-design.md`

## Global Constraints

- Preserve one production Parent Graph; do not create a third Graph or hidden temporary Revisions.
- DeepSeek receives bounded evidence and emits strict structured Critique only; it never writes Candidate, Preview, Artifact, or Revision facts.
- Exactly two stable candidate families are produced; at most one Repair occurs across the pair.
- PlanApproval and CandidateSelection are separate durable HITL decisions.
- One explicit live Run may use at most two provider requests: Planner then pairwise Critic; all no-Key acceptance remains zero request/zero token.
- Candidate preview Jobs run sequentially and output only `candidate-preview.v1`; canonical export remains the existing seven-step service.
- S5 uses portfolio engineering mode: focused RED/GREEN, representative PostgreSQL and Compose boundaries, no P95/load/multi-tenant/exhaustive crash matrix.
- Do not add dependencies, expose Secrets, or compute incidental repository/file hashes. Existing content/integrity hashes remain protocol facts.

---

### Task 1: Candidate, Segment, Critique, and reducer domain contracts

**Files:**
- Create: `services/api/src/motif_forge/domain/candidates.py`
- Modify: `services/api/src/motif_forge/domain/__init__.py`
- Test: `services/api/tests/unit/domain/test_candidates.py`

**Interfaces:**
- Produces `CandidateLabel`, `CandidateSegment`, `CandidateEvidence`, `RepairProposal`, `CandidateAssessment`, `CandidateCritique`, `CandidateBranchResult`.
- Produces `derive_candidate_seed(base_seed: int, label: CandidateLabel) -> int`.
- Produces `project_candidate_segments(candidate_id: UUID, arrangement: ArrangementIR) -> tuple[CandidateSegment, ...]`.
- Produces `merge_candidate_branches(left: list[dict[str, object]], right: list[dict[str, object]]) -> list[dict[str, object]]` for LangGraph state reduction.

- [x] **Step 1: Write failing literal contract tests**

```python
def test_candidate_seed_and_reducer_are_stable_and_order_independent() -> None:
    assert derive_candidate_seed(0, CandidateLabel.A) == 0
    assert derive_candidate_seed(0, CandidateLabel.B) == 1_048_583
    left = [{"candidate_id": str(CANDIDATE_B), "label": "b"}]
    right = [{"candidate_id": str(CANDIDATE_A), "label": "a"}]
    assert merge_candidate_branches(left, right) == [
        {"candidate_id": str(CANDIDATE_A), "label": "a"},
        {"candidate_id": str(CANDIDATE_B), "label": "b"},
    ]

def test_segment_projection_is_acyclic_and_bounds_each_track_to_a_section() -> None:
    segments = project_candidate_segments(CANDIDATE_A, arrangement_fixture())
    assert {(item.section_name, item.track_role) for item in segments} == {
        ("Opening", "pad"), ("Opening", "melody"),
        ("Opening", "bass"), ("Opening", "rhythm"),
    }
    assert all(item.start_tick < item.end_tick for item in segments)
    assert all(item.segment_id not in item.depends_on for item in segments)

def test_critique_rejects_findings_without_real_evidence_refs() -> None:
    with pytest.raises(ValueError, match="evidence"):
        CandidateCritique.model_validate(invalid_critique_without_evidence())
```

- [x] **Step 2: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/domain/test_candidates.py -q`  
Expected: collection fails because `motif_forge.domain.candidates` does not exist.

- [x] **Step 3: Implement strict models, projection, seed derivation, and reducer**

```python
class CandidateLabel(StrEnum):
    A = "a"
    B = "b"

def derive_candidate_seed(base_seed: int, label: CandidateLabel) -> int:
    return base_seed if label is CandidateLabel.A else (base_seed + 1_048_583) % (2**31)

def merge_candidate_branches(left, right):
    by_id = {str(item["candidate_id"]): item for item in (*left, *right)}
    if len(by_id) > 2:
        raise ValueError("candidate fan-in cannot exceed two stable candidates")
    return [by_id[key] for key in sorted(by_id)]
```

Implement segment IDs from candidate/section/track identity using the existing UUID identity convention; validate tick bounds, dependency existence, and acyclicity. `CandidateCritique` must contain exactly A/B assessments and every negative finding must reference an input `CandidateEvidence.evidence_ref`.

- [x] **Step 4: Run GREEN and static checks**

Run: `.venv/bin/pytest services/api/tests/unit/domain/test_candidates.py -q`  
Run: `.venv/bin/ruff check services/api/src/motif_forge/domain/candidates.py services/api/tests/unit/domain/test_candidates.py`  
Run: `.venv/bin/mypy services/api/src/motif_forge/domain/candidates.py`

- [x] **Step 5: Commit Task 1**

```bash
git add services/api/src/motif_forge/domain services/api/tests/unit/domain/test_candidates.py
git commit -m "feat: add S5 candidate evidence contracts"
```

### Task 2: Durable CandidateSnapshot and candidate-preview lineage

**Files:**
- Create: `infra/migrations/versions/20260820_0018_s5_candidate_preview_lineage.py`
- Modify: `services/api/src/motif_forge/application/ports.py`
- Modify: `services/api/src/motif_forge/domain/media_jobs.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/tables.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/database.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/media_jobs.py`
- Test: `services/api/tests/unit/domain/test_media_jobs.py`
- Test: `services/api/tests/unit/infrastructure/persistence/test_tables.py`
- Test: `services/api/tests/integration/test_postgres_s5_candidates.py`

**Interfaces:**
- `ProjectTransaction.insert_candidate_snapshot(snapshot: CandidateSnapshot) -> None`.
- `ProjectTransaction.insert_selection_preview(snapshot_id, preview, preview_artifact_ids, evidence_refs) -> None`.
- `MediaJobTransaction.get_candidate_snapshot(candidate_snapshot_id: UUID) -> CandidateSnapshot | None`.
- `AudioArtifact.candidate_snapshot_id: UUID | None` with exclusive candidate-vs-Revision render lineage.

- [x] **Step 1: Write RED domain and PostgreSQL tests**

```python
def test_candidate_preview_artifact_requires_snapshot_lineage() -> None:
    artifact = audio_artifact(
        quality_profile=MediaQualityProfile.CANDIDATE_PREVIEW_V1,
        candidate_snapshot_id=SNAPSHOT_ID,
        arrangement_hash="a" * 64,
        render_scope=RenderScope.MASTER,
        revision_id=None,
    )
    assert artifact.candidate_snapshot_id == SNAPSHOT_ID

async def test_postgres_persists_snapshot_then_candidate_preview_artifact(pg_uow) -> None:
    await insert_snapshot(pg_uow, SNAPSHOT_ID)
    await insert_preview_artifact(pg_uow, SNAPSHOT_ID, ARTIFACT_ID)
    loaded = await load_artifact(pg_uow, ARTIFACT_ID)
    assert loaded.candidate_snapshot_id == SNAPSHOT_ID
    assert loaded.revision_id is None
```

Add a migration-head assertion for `20260820_0018` and a downgrade/upgrade contract covering the new nullable FK and revised Artifact lineage constraint.

- [x] **Step 2: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/domain/test_media_jobs.py services/api/tests/unit/infrastructure/persistence/test_tables.py services/api/tests/integration/test_postgres_s5_candidates.py -q`  
Expected: failures for the missing field, migration, and transaction methods.

- [x] **Step 3: Implement schema and persistence**

Migration behavior:

```python
op.add_column("artifacts", sa.Column("candidate_snapshot_id", postgresql.UUID(), nullable=True), schema="app")
op.create_foreign_key(
    "fk_artifacts_candidate_snapshot",
    "artifacts", "candidate_snapshots",
    ["candidate_snapshot_id"], ["id"], source_schema="app", referent_schema="app",
)
```

Replace `artifacts_final_revision_lineage` so `candidate-preview.v1` requires `candidate_snapshot_id`, arrangement identity, Master scope, and no Revision; canonical/delivery profiles retain Revision lineage; unrelated profiles carry neither. Persist and load the new field in all `AudioArtifact` mappings. Add one transaction method that inserts a standalone immutable snapshot with conflict-safe identity verification.

- [x] **Step 4: Run GREEN with one real PostgreSQL boundary**

Run the unit command from Step 2.  
Run: `MOTIF_FORGE_TEST_POSTGRES_DSN=postgresql://motif_forge:motif_forge@127.0.0.1:5432/motif_forge_s5_test .venv/bin/pytest services/api/tests/integration/test_postgres_s5_candidates.py -q` after creating the dedicated disposable `motif_forge_s5_test` database with the repository's established PostgreSQL test setup.  
Expected: exact snapshot/artifact counts remain unchanged across replay.

- [x] **Step 5: Commit Task 2**

```bash
git add infra/migrations/versions/20260820_0018_s5_candidate_preview_lineage.py services/api/src/motif_forge/application/ports.py services/api/src/motif_forge/domain/media_jobs.py services/api/src/motif_forge/infrastructure/persistence services/api/tests
git commit -m "feat: persist candidate preview lineage"
```

### Task 3: Candidate creation and selected-candidate materialization services

**Files:**
- Create: `services/api/src/motif_forge/application/generation_candidates.py`
- Modify: `services/api/src/motif_forge/application/generation.py`
- Modify: `services/api/src/motif_forge/application/previews.py`
- Test: `services/api/tests/unit/application/test_generation_candidates.py`
- Test: `services/api/tests/integration/test_postgres_s5_candidates.py`

**Interfaces:**
- `CreateCompositionCandidate(request: CreateCompositionCandidateRequest) -> CreateCompositionCandidateResult`.
- `CreateCandidateSelectionPreview(request: CreateCandidateSelectionPreviewRequest) -> CreateCandidateSelectionPreviewResult`.
- `MaterializeSelectedCompositionCandidate(request: MaterializeSelectedCompositionCandidateRequest) -> MaterializeSelectedCompositionCandidateResult`.
- Consumes Task 1 labels/seeds and Task 2 standalone snapshot persistence.

- [x] **Step 1: Write RED service tests**

```python
async def test_two_labels_create_distinct_stable_snapshots_without_revision() -> None:
    a = await service(request(label=CandidateLabel.A, seed=0))
    b = await service(request(label=CandidateLabel.B, seed=1_048_583))
    replay = await service(request(label=CandidateLabel.A, seed=0))
    assert a.candidate_id != b.candidate_id
    assert replay.candidate_snapshot_id == a.candidate_snapshot_id
    assert uow.revision_count == 0

async def test_only_selected_preview_materializes_one_revision() -> None:
    result = await materialize(selection_request(preview_id=PREVIEW_B))
    replay = await materialize(selection_request(preview_id=PREVIEW_B))
    assert result.revision_id == replay.revision_id
    assert uow.revision_count == 1
    assert uow.branch_head == result.revision_id
```

Also assert reject/cancel produces zero Revision and selection of a Preview from another Run or Candidate pair fails closed.

- [x] **Step 2: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/application/test_generation_candidates.py -q`  
Expected: missing application module and service contracts.

- [x] **Step 3: Split compile/persist from decision/materialization**

`CreateCompositionCandidate` reloads authoritative Run/Plan/Branch, validates Plan and Style Pack identity, compiles via `MusicStrategyRouter`, derives Candidate ID from Run/Plan/label/seed, persists one CandidateSnapshot, and records a deduplicated `candidate.created` Run event. It never calls `approve_preview_in_transaction`.

`CreateCandidateSelectionPreview` creates one pending Preview from an already persisted final snapshot and attaches the exact preview Artifact/evidence IDs. `MaterializeSelectedCompositionCandidate` calls the established `approve_preview_in_transaction`, writes the existing materialization receipt using the selected seed/snapshot/preview, and returns the single Revision.

- [x] **Step 4: Run GREEN and real PostgreSQL replay**

Run the unit command from Step 2.  
Run the Task 2 PostgreSQL command with tests for exactly two snapshots, two pending previews, zero pre-selection Revisions, then one selected Revision and unchanged replay counts.

- [x] **Step 5: Commit Task 3**

```bash
git add services/api/src/motif_forge/application/generation.py services/api/src/motif_forge/application/generation_candidates.py services/api/src/motif_forge/application/previews.py services/api/tests/unit/application/test_generation_candidates.py services/api/tests/integration/test_postgres_s5_candidates.py
git commit -m "feat: separate candidate creation from selection"
```

### Task 4: Candidate preview render Job and Worker execution

**Files:**
- Modify: `services/api/src/motif_forge/domain/media_jobs.py`
- Modify: `services/api/src/motif_forge/application/rendering.py`
- Create: `services/api/src/motif_forge/application/candidate_previews.py`
- Modify: `services/api/src/motif_forge/audio/chromium_render.py`
- Modify: `services/api/src/motif_forge/worker/execution.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/media_jobs.py`
- Test: `services/api/tests/unit/application/test_candidate_previews.py`
- Test: `services/api/tests/unit/worker/test_candidate_preview_execution.py`
- Test: `services/api/tests/integration/test_postgres_s5_candidate_preview_jobs.py`

**Interfaces:**
- `CandidatePreviewJobPayload` with Project/Snapshot/content identity, Master AudioGraph, seed, 160 kbps MP3 profile, time/byte limits.
- `EnqueueCandidatePreview(request) -> CandidatePreviewCursor` and `CollectCandidatePreview(cursor, completed_job_id) -> CandidatePreviewCursor`.
- Worker supports `MediaJobType.RENDER_PREVIEW` and returns one rebuildable `candidate-preview.v1` MP3 Artifact.

- [x] **Step 1: Write RED payload, enqueue, lineage, and physical-output tests**

```python
def test_candidate_preview_payload_forbids_revision_and_non_preview_profile() -> None:
    payload = build_candidate_preview_payload(snapshot_fixture(), seed=0)
    assert payload.candidate_snapshot_id == SNAPSHOT_ID
    assert payload.quality_profile is MediaQualityProfile.CANDIDATE_PREVIEW_V1
    assert payload.render_scope is RenderScope.MASTER

async def test_worker_rejects_payload_snapshot_lineage_mismatch() -> None:
    result = await execute_candidate_preview(job_with_snapshot(SNAPSHOT_ID), loader=wrong_snapshot)
    assert result.error_code == "CANDIDATE_PREVIEW_LINEAGE_MISMATCH"
```

The success test must inspect the produced MP3 with the existing FFprobe boundary and assert 48 kHz stereo, 160 kbps target, non-silence, source Job ID, source Snapshot ID, and exact duration tolerance.

- [x] **Step 2: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/application/test_candidate_previews.py services/api/tests/unit/worker/test_candidate_preview_execution.py services/api/tests/integration/test_postgres_s5_candidate_preview_jobs.py -q`  
Expected: missing payload/orchestration and unsupported Worker job type.

- [x] **Step 3: Implement sequential preview rendering**

Compile authoritative Snapshot ArrangementIR to the existing AudioGraph. Generalize `ChromiumRenderClient.render` to accept the common render fields, render a temporary PCM24 WAV, then invoke the existing controlled FFmpeg wrapper to encode candidate MP3 at 160 kbps. Promote under:

```text
rebuildable/candidate-previews/<project_id>/<candidate_snapshot_id>/<content>-preview.mp3
```

Register one `AudioArtifact` with Snapshot lineage and a complete render/transcode rebuild recipe. Cleanup temporary WAV/partial output on cancellation or failure. Enqueue/collect validates ordered cursor, source Job, Snapshot, Project, profile, availability, and content identity.

- [x] **Step 4: Run GREEN, Audio regression, and PostgreSQL boundary**

Run the Step 2 tests.  
Run: `npm run test:audio && npm run build:audio`  
Run the dedicated PostgreSQL test and assert duplicate completion does not add a Job or Artifact.

- [x] **Step 5: Commit Task 4**

```bash
git add services/api/src/motif_forge/domain/media_jobs.py services/api/src/motif_forge/application/candidate_previews.py services/api/src/motif_forge/application/rendering.py services/api/src/motif_forge/audio/chromium_render.py services/api/src/motif_forge/worker/execution.py services/api/src/motif_forge/infrastructure/persistence/media_jobs.py services/api/tests
git commit -m "feat: render durable candidate previews"
```

### Task 5: Pairwise Evidence Critic and persistent model budget

**Files:**
- Create: `services/api/src/motif_forge/agent/critic.py`
- Modify: `services/api/src/motif_forge/agent/planner.py`
- Modify: `services/api/src/motif_forge/providers/deepseek.py`
- Modify: `services/api/src/motif_forge/worker/resume_dispatcher.py`
- Test: `services/api/tests/unit/agent/test_critic.py`
- Test: `services/api/tests/unit/providers/test_deepseek.py`
- Test: `services/api/tests/integration/test_postgres_ai_runs.py`

**Interfaces:**
- `EvidenceCritic` Protocol: `evaluate(request: CriticRequest) -> CriticResult`.
- `DeterministicEvidenceCritic.evaluate` returns strict `CandidateCritique` with zero usage.
- `DeepSeekEvidenceCritic` uses `DeepSeekJsonClient` with request kind `critic`, one attempt, strict schema, and no tools.

- [x] **Step 1: Write RED evidence and budget tests**

```python
async def test_deterministic_critic_cites_only_supplied_evidence() -> None:
    result = await DeterministicEvidenceCritic().evaluate(pair_request())
    supplied = {item.evidence_ref for item in pair_request().evidence}
    assert all(ref in supplied for finding in result.critique.findings for ref in finding.evidence_refs)
    assert result.usage.model_requests == 0

async def test_deepseek_critic_reserves_second_request_before_http() -> None:
    result = await critic.evaluate(pair_request())
    assert ledger.reservations == [(RUN_ID, "critic", 2)]
    assert transport.request_count == 1
    assert result.usage.model_requests == 1

async def test_invalid_critic_schema_uses_fallback_without_third_http_request() -> None:
    result = await critic.evaluate(pair_request())
    assert result.provider == "deterministic-fallback"
    assert transport.request_count == 1
    assert ledger.submitted_model_requests == 2
```

- [x] **Step 2: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/agent/test_critic.py services/api/tests/unit/providers/test_deepseek.py services/api/tests/integration/test_postgres_ai_runs.py -q`  
Expected: missing critic boundary and unsupported `critic` request kind.

- [x] **Step 3: Implement one pairwise call and fallback**

Add `ModelRequestKind.CRITIC`. Serialize only bounded evidence summaries, use `temperature=0`, one transport attempt, strict `CandidateCritique`, and no schema-repair HTTP request. Reject unknown evidence refs before returning. `build_generate_critic(settings, run, uow)` selects DeepSeek only when the existing explicit live boundary is enabled and the Run retains request budget; otherwise it returns `DeterministicEvidenceCritic`.

- [x] **Step 4: Run GREEN and static checks**

Run the Step 2 command.  
Run: `.venv/bin/ruff check services/api/src/motif_forge/agent/critic.py services/api/src/motif_forge/providers/deepseek.py services/api/tests/unit/agent/test_critic.py`  
Run: `.venv/bin/mypy services/api/src/motif_forge/agent/critic.py services/api/src/motif_forge/providers/deepseek.py`

- [x] **Step 5: Commit Task 5**

```bash
git add services/api/src/motif_forge/agent/critic.py services/api/src/motif_forge/agent/planner.py services/api/src/motif_forge/providers/deepseek.py services/api/src/motif_forge/worker/resume_dispatcher.py services/api/tests
git commit -m "feat: add evidence-grounded candidate critic"
```

### Task 6: Bounded local Repair and quality gate

**Files:**
- Create: `services/api/src/motif_forge/application/candidate_repair.py`
- Modify: `services/api/src/motif_forge/application/generation_candidates.py`
- Test: `services/api/tests/unit/application/test_candidate_repair.py`
- Test: `services/api/tests/integration/test_postgres_s5_candidates.py`

**Interfaces:**
- `EvaluateCandidatePair(evidence, critique, budget) -> QualityDecision`.
- `ApplyBoundedCandidateRepair(request: BoundedRepairRequest) -> BoundedRepairResult`.
- Repair allowlist: one segment-scoped density reduction, velocity rebalance, register shift, or quantized onset alignment expressed with existing EditorCommands.

- [x] **Step 1: Write RED scope, improvement, and replay tests**

```python
async def test_repair_changes_only_target_track_and_tick_range() -> None:
    result = await repair(repair_request(operation="velocity_rebalance"))
    assert result.child_snapshot.parent_candidate_snapshot_id == ORIGINAL_SNAPSHOT
    assert unchanged_events(result.before, result.after, outside=TARGET_SEGMENT)

async def test_non_improving_repair_keeps_original_candidate() -> None:
    result = await gate.compare(original_score=72, repaired_score=71)
    assert result.selected_snapshot_id == ORIGINAL_SNAPSHOT
    assert result.repair_status == "non_improving"

async def test_replay_never_creates_second_repair_child() -> None:
    first = await repair(request)
    second = await repair(request)
    assert second.child_snapshot_id == first.child_snapshot_id
    assert uow.child_snapshot_count == 1
```

- [x] **Step 2: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/application/test_candidate_repair.py services/api/tests/integration/test_postgres_s5_candidates.py -q`  
Expected: missing repair service and quality gate.

- [x] **Step 3: Implement allowlisted commands and one-repair budget**

Validate the referenced evidence and Segment against the authoritative Snapshot. Build existing EditorCommands with target track/ticks, apply them in memory, reject any diff outside the Segment, run Theory again, and persist a child Snapshot only once. The quality gate selects the child only when the targeted metric improves and blocking Theory errors do not increase; otherwise it keeps the parent and records a deduplicated `candidate.repair.non_improving` event.

- [x] **Step 4: Run GREEN and Task 1-6 combined regression**

Run the Step 2 tests.  
Run: `.venv/bin/pytest services/api/tests/unit/domain/test_candidates.py services/api/tests/unit/application/test_generation_candidates.py services/api/tests/unit/application/test_candidate_previews.py services/api/tests/unit/agent/test_critic.py services/api/tests/unit/application/test_candidate_repair.py -q`

- [x] **Step 5: Commit Task 6**

```bash
git add services/api/src/motif_forge/application/candidate_repair.py services/api/src/motif_forge/application/generation_candidates.py services/api/tests
git commit -m "feat: apply one bounded candidate repair"
```

### Task 7: Parent Graph fan-out/fan-in, preview loop, and A/B interrupt

**Files:**
- Modify: `services/api/src/motif_forge/agent/generate.py`
- Modify: `services/api/src/motif_forge/agent/parent_graph.py`
- Modify: `services/api/src/motif_forge/worker/outbox.py`
- Modify: `services/api/src/motif_forge/worker/resume_dispatcher.py`
- Test: `services/api/tests/unit/agent/test_generate_graph.py`
- Test: `services/api/tests/unit/worker/test_outbox.py`
- Test: `services/api/tests/integration/test_s5_parent_graph.py`

**Interfaces:**
- Parent state adds `Annotated[list[dict[str, object]], merge_candidate_branches]`, preview cursor, critique summary, repair count/status, and selection refs.
- `CandidateSelectionDecision` is a strict resume union distinct from `PlanApprovalDecision`.
- `GraphActionPayload.decision` becomes a discriminated PlanApproval/CandidateSelection union.

- [x] **Step 1: Write RED Graph behavior tests**

```python
async def test_parent_graph_fans_out_two_candidates_and_waits_for_selection() -> None:
    result = await run_until_selection(graph, approved_plan_state())
    assert [item["label"] for item in result["candidate_branches"]] == ["a", "b"]
    assert result["phase"] == "waiting_candidate_selection"
    assert materializer.revision_count == 0

async def test_selection_resume_materializes_only_b_and_enters_existing_export() -> None:
    result = await graph.ainvoke(Command(resume=select_b_decision()), config)
    assert result["selected_candidate_id"] == str(CANDIDATE_B)
    assert result["phase"] in {"revision_materialized", "waiting_generate_worker"}
    assert materializer.revision_count == 1

async def test_restart_and_duplicate_resume_do_not_repeat_critic_repair_or_revision() -> None:
    await deliver_selection_twice_after_restart()
    assert counts() == {"candidates": 2, "critic_calls": 1, "repairs": 1, "revisions": 1}
```

Also cover reject/cancel, wrong Preview/content identity, wrong worker lineage, non-improving Repair, and order-independent fan-in.

- [x] **Step 2: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/agent/test_generate_graph.py services/api/tests/unit/worker/test_outbox.py services/api/tests/integration/test_s5_parent_graph.py -q`  
Expected: current Graph materializes immediately after PlanApproval and has no selection phase.

- [x] **Step 3: Mount S5 nodes into the existing Parent Graph**

Use LangGraph `Send` for A/B candidate branch inputs and the Task 1 reducer for fan-in. Add sequential preview enqueue/wait/collect, pairwise Critic, optional one-repair re-render, final Preview creation, CandidateSelection interrupt, selected materialization, then reuse the unchanged complete-export nodes. Persist progress after every durable boundary. Generalize action publishing so authoritative plan and selection decisions resume only their matching checkpoint phase.

- [x] **Step 4: Run GREEN and real PostgreSQL checkpoint restart**

Run the Step 2 command with the existing PostgreSQL checkpointer. Assert exact SQL counts before and after duplicate deliveries.  
Run: `.venv/bin/pytest services/api/tests/integration/test_generate_dispatcher.py services/api/tests/integration/test_s5_parent_graph.py -q`

- [x] **Step 5: Commit Task 7**

```bash
git add services/api/src/motif_forge/agent/generate.py services/api/src/motif_forge/agent/parent_graph.py services/api/src/motif_forge/worker/outbox.py services/api/src/motif_forge/worker/resume_dispatcher.py services/api/tests
git commit -m "feat: orchestrate S5 candidate selection graph"
```

### Task 8: REST, persistent Read Model, SSE, and OpenAPI

**Files:**
- Modify: `services/api/src/motif_forge/domain/ai_runs.py`
- Modify: `services/api/src/motif_forge/application/ai_runs.py`
- Modify: `services/api/src/motif_forge/application/ports.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/ai_runs.py`
- Modify: `services/api/src/motif_forge/api/ai_runs.py`
- Modify: `services/api/src/motif_forge/api/app.py`
- Regenerate: `apps/web/src/generated/api-schema.d.ts`
- Test: `services/api/tests/unit/api/test_ai_runs.py`
- Test: `services/api/tests/integration/test_ai_run_sse.py`

**Interfaces:**
- `POST /api/v1/runs/{run_id}/select-candidate` with expected version, preview ID, expected candidate identity, actor, assertion, decision, note, and Idempotency-Key.
- `AIRunData.pending_action` adds `select_candidate` and `AIRunData.candidates`, `critique`, `selected_candidate_id`, `selected_preview_id`.
- Persistent projection reconstructs the fields from Candidate/Preview/Artifact/Run events, not checkpoint-only memory.

- [x] **Step 1: Write RED HTTP and recreated-app SSE tests**

```python
def test_get_run_exposes_two_ordered_playable_candidates_and_critique(client) -> None:
    data = client.get(f"/api/v1/runs/{RUN_ID}").json()["data"]
    assert data["pending_action"] == "select_candidate"
    assert [item["label"] for item in data["candidates"]] == ["a", "b"]
    assert data["critique"]["recommended_candidate_id"] == str(CANDIDATE_B)

def test_select_candidate_is_persistently_idempotent(client) -> None:
    first = post_selection(client, key="select-key", preview_id=PREVIEW_B)
    replay = post_selection(client, key="select-key", preview_id=PREVIEW_B)
    conflict = post_selection(client, key="select-key", preview_id=PREVIEW_A)
    assert first.status_code == replay.status_code == 200
    assert conflict.status_code == 409
```

SSE test recreates the FastAPI app, resumes from Last-Event-ID before `candidate.preview.ready`, receives ordered Critic/selection events, and closes after terminal status.

- [x] **Step 2: Run RED**

Run: `.venv/bin/pytest services/api/tests/unit/api/test_ai_runs.py services/api/tests/integration/test_ai_run_sse.py -q`  
Expected: route/schema/projection fields missing.

- [x] **Step 3: Implement public selection and projection**

Add an application service that performs persistent selection idempotency lookup before validating live pending state, mirroring the repaired Plan resume contract. Store the canonical selection resume outbox payload in the same transaction. Projection joins the two final Previews, Snapshot labels/lineage, candidate-preview Artifacts, and latest Critic/Repair events; absent facts remain nullable rather than fabricated.

- [x] **Step 4: Run GREEN, regenerate OpenAPI, and build Web types**

Run the Step 2 command.  
Run: `npm run generate:openapi`  
Run: `npm run build:web`  
Run OpenAPI generation twice and verify `git diff --exit-code -- apps/web/src/generated/api-schema.d.ts` after the second generation.

- [x] **Step 5: Commit Task 8**

```bash
git add services/api/src/motif_forge/domain/ai_runs.py services/api/src/motif_forge/application/ai_runs.py services/api/src/motif_forge/application/ports.py services/api/src/motif_forge/infrastructure/persistence/ai_runs.py services/api/src/motif_forge/api services/api/tests apps/web/src/generated/api-schema.d.ts
git commit -m "feat: expose S5 candidate selection API"
```

### Task 9: Web A/B Compare and CandidateSelection UX

**Files:**
- Create: `apps/web/src/features/generate/CandidateCompare.tsx`
- Create: `apps/web/src/features/generate/CandidateCompare.test.tsx`
- Modify: `apps/web/src/features/generate/generateApi.ts`
- Modify: `apps/web/src/features/generate/RunPage.tsx`
- Modify: `apps/web/src/features/generate/RunPage.test.tsx`
- Modify: `apps/web/src/features/generate/RunProgress.tsx`
- Modify: `apps/web/src/features/generate/runState.ts`
- Modify: `apps/web/src/features/generate/runState.test.ts`
- Modify: `apps/web/src/styles.css`

**Interfaces:**
- `selectCandidate(runId, input, idempotencyKey) -> Promise<AIRun>` generated DTO boundary.
- `CandidateCompare` consumes authoritative ordered candidate summaries and emits one selection request.

- [x] **Step 1: Write RED responsive behavior tests**

```tsx
it("plays only one authoritative candidate preview and selects B", async () => {
  render(<CandidateCompare run={waitingSelectionRun()} onSelect={onSelect} />);
  await user.click(screen.getByRole("button", { name: "试听候选 B" }));
  expect(screen.getByLabelText("候选 B 试听")).not.toBePaused();
  await user.click(screen.getByRole("button", { name: "选择候选 B" }));
  expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ preview_id: PREVIEW_B }));
});

it("shows evidence recommendation without auto-selecting", () => {
  render(<CandidateCompare run={waitingSelectionRun()} onSelect={onSelect} />);
  expect(screen.getByText("Agent 建议：候选 B")).toBeVisible();
  expect(onSelect).not.toHaveBeenCalled();
});
```

RunPage tests cover loading, preview unavailable/rehydrating/missing, selection conflict refresh, reject/cancel, refresh recovery, and 390 px DOM order/no overflow contract.

- [x] **Step 2: Run RED**

Run: `npx vitest run --config apps/web/vitest.config.ts apps/web/src/features/generate/CandidateCompare.test.tsx apps/web/src/features/generate/RunPage.test.tsx apps/web/src/features/generate/runState.test.ts`  
Expected: missing component and S5 phases.

- [x] **Step 3: Implement Compare cards and selection flow**

Add phases `generating_candidates`, `rendering_candidate_previews`, `criticizing`, `repairing_candidate`, and `waiting_candidate_selection`. Render a desktop two-column/390 px single-column Compare view. Use one HTML audio element at a time; show Style/structure/Theory/Critic/repair facts; label recommendation as evidence; require explicit assertion and selection; reuse existing conflict/readback behavior.

- [x] **Step 4: Run GREEN and Web build**

Run: `npm run test:web`  
Run: `npm run build:web`  
Expected: all Web tests pass and Vite build completes without overflow-specific fixed heights.

- [x] **Step 5: Commit Task 9**

```bash
git add apps/web/src/features/generate apps/web/src/styles.css
git commit -m "feat: add candidate A B comparison flow"
```

### Task 10: S5 Eval, deterministic Compose/browser acceptance, and stage close

**Files:**
- Create: `evals/s5-candidate-critic-repair-v1.json`
- Create: `services/api/tests/eval/test_s5_candidate_eval.py`
- Create: `scripts/run_s5_deterministic_smoke.py`
- Create: `tests/test_s5_script_contract.py`
- Create: `scripts/run_s5_browser_smoke.mjs`
- Modify: `package.json`
- Modify: `scripts/check_s1.sh`
- Modify: `AGENTS.md`
- Modify: `docs/PROJECT_GUIDE.md`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/NEXT_DEVELOPMENT_ROADMAP.md`
- Modify: `docs/TECH_EVOLUTION.md`
- Modify: this plan, checking every completed step.

**Interfaces:**
- `npm run smoke:s5` runs the no-Key public HTTP/Graph/queue/selection/export acceptance.
- Eval fixture contains 12 representative cases: two per style plus repair, non-improving, restart replay, reject/cancel.

- [x] **Step 1: Write RED Eval and executable smoke contracts**

```python
def test_s5_eval_has_four_styles_and_behavioral_recovery_cases() -> None:
    fixture = load_fixture()
    assert len(fixture["cases"]) == 12
    assert {case["style"] for case in fixture["cases"] if "style" in case} == {
        "synth_ambient", "minimal_electronic", "classical_chamber", "jazz_harmony_improvisation"
    }

def test_smoke_uses_public_actions_and_never_executes_worker_inline() -> None:
    result = run_smoke_contract_fixture()
    assert result["provider_requests"] == 0
    assert result["candidate_snapshots"] in {2, 3}
    assert result["selection_previews"] == 2
    assert result["selected_revisions"] == 1
    assert result["export_jobs"] == 7
```

The contract test executes controlled fakes; it must not grep source text. Browser smoke starts from Brief, approves Plan, waits for A/B, plays both candidates one at a time, selects one, reaches succeeded, opens Studio, and verifies the selected Preview/Revision lineage through read-only SQL.

- [x] **Step 2: Run RED**

Run: `.venv/bin/pytest services/api/tests/eval/test_s5_candidate_eval.py tests/test_s5_script_contract.py -q`  
Expected: missing fixture and smoke entrypoint.

- [x] **Step 3: Implement Eval/smoke and truthfully close S5 docs**

No-Key smoke must attest the live API container has an empty DeepSeek key before creating a Run, use public PlanApproval and CandidateSelection routes, poll queue-produced facts, and verify exactly two final Previews, one Revision, seven canonical export Jobs, six canonical audio Artifacts, one Bundle, and zero request/token usage. Physical candidate previews and canonical outputs are verified inside the owning container when Docker Desktop bind visibility requires it.

Update current-stage docs only after the smoke is green: S5 complete, S6 the only active gate. Record candidate/repair counts, provider usage, exact test commands, known limitations, and no claim of full DAW/edit/release readiness.

- [x] **Step 4: Run the complete S5 stage gate**

Run:

```bash
.venv/bin/pytest services/api/tests/unit services/api/tests/eval tests -q --ignore-glob='**/._*'
.venv/bin/pytest services/api/tests/integration/test_postgres_s5_candidates.py services/api/tests/integration/test_postgres_s5_candidate_preview_jobs.py services/api/tests/integration/test_s5_parent_graph.py services/api/tests/integration/test_ai_run_sse.py -q
npm run test:audio
npm run build:audio
npm run test:web
npm run build:web
.venv/bin/ruff check services/api/src services/api/tests services/render-worker tests scripts
.venv/bin/mypy services/api/src
npm run generate:openapi
npm run smoke:s5
git diff --check
```

Expected no-Key runtime facts: two candidate families, two final selection Previews, zero or one child Repair Snapshot, one selected Revision, seven canonical export Jobs, six canonical audio Artifacts, one Bundle, zero provider requests, zero tokens.

- [x] **Step 5: Perform one bounded self-review and fix only current-path blockers**

Review against every minimum acceptance item in the S5 spec. Critical and current-path Important findings for Candidate integrity, model spend, HITL, side-effect idempotency, or recovery block completion. Record non-core production hardening in roadmap section 14; do not expand into S7 matrices.

- [x] **Step 6: Commit Task 10**

```bash
git add AGENTS.md apps/web/src/generated/api-schema.d.ts docs evals package.json scripts services/api/tests/eval tests/test_s5_script_contract.py
git commit -m "feat: complete S5 candidate critic repair workflow"
```

## Execution mode

The user requested the whole S5 in this session and previously restricted subagents to exceptional necessity. Execute inline with `superpowers:executing-plans`; do not dispatch subagents. Commit after every Task and stop only for an actual architecture blocker, unauthorized external spend, or repeated verification failure.
