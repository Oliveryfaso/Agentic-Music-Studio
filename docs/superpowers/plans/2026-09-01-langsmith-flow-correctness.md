# LangSmith And Parent Graph Flow Correctness Implementation Plan

> **For agentic workers:** Execute inline in this session. Do not use subagents. Follow RED/GREEN for every production behavior and do not commit, merge, or push without explicit user authorization.

**Goal:** Make cancellation, stale actions, persisted Graph visualization, Run inspection, and test tracing agree with PostgreSQL-authoritative AI Run state.

**Architecture:** PostgreSQL remains authoritative. Human and Worker wake-ups continue through the existing single Parent Graph and Outbox; cancellation is delivered into an interrupted Graph and late Worker resumes become idempotent no-ops. Read models derive pre-Revision evidence from existing checkpoint, AI Run event, media Run, Job, and Artifact facts without adding a third Graph or a new persistence spine.

**Tech Stack:** Python 3.12, FastAPI, LangGraph, SQLAlchemy/PostgreSQL, Pytest, React/TypeScript, Vitest.

**Spec:** `docs/PROJECT_GUIDE.md` plus the user-approved 2026-09-01 trace diagnosis in this session.

**Status (2026-09-01):** Implemented and verified on `codex/langsmith-flow-correctness`;
awaiting the user's integration choice.

## Global Constraints

- Keep `motif-forge-parent.v2` as the only production Parent Graph.
- Never bypass PlanApproval or CandidateSelection.
- Never expose prompts, outputs, reasoning, API keys, or secret-bearing environment values.
- Preserve fail-open LangSmith tracing and hidden inputs/outputs.
- Do not add dependencies.
- Do not compute new content hashes for verification.
- Run only one paid DeepSeek smoke after all local verification passes.

---

### Task 1: Cancellation Wins Over Late Candidate Preview Resumes

**Files:**
- Modify: `services/api/src/motif_forge/agent/generate.py`
- Modify: `services/api/src/motif_forge/agent/parent_graph.py`
- Modify: `services/api/src/motif_forge/worker/outbox.py`
- Modify: `services/api/src/motif_forge/worker/resume_dispatcher.py`
- Test: `services/api/tests/unit/agent/test_generate_graph.py`
- Test: `services/api/tests/unit/worker/test_outbox.py`

**Interfaces:**
- `GenerateNodes.wait_for_candidate_preview(state)` accepts `{"action": "cancel"}` and returns `{"phase": "cancelled", "terminal_status": "cancelled"}`.
- `ParentGraphActionPublisher.publish()` resumes cancellation at candidate-preview interrupts.
- `ParentGraphResumePublisher.publish()` treats a terminal checkpoint as an acknowledged no-op.

- [ ] Add a RED graph test that cancels while `phase == "rendering_candidate_previews"` and asserts terminal cancellation before Critic or selection.
- [ ] Add a RED publisher test that delivers a late Worker resume to a terminal checkpoint and asserts no invocation and no exception.
- [ ] Run the two tests and confirm the current code fails on the missing cancel branch/terminal no-op.
- [ ] Implement only the cancel branch, route-to-END behavior, and terminal resume no-op.
- [ ] Run the focused graph and Outbox test files.

### Task 2: Stale Approval Is An HTTP Conflict

**Files:**
- Modify: `services/api/src/motif_forge/api/app.py`
- Test: `services/api/tests/unit/api/test_ai_runs.py`

**Interfaces:**
- Expected stale AI Run action codes return RFC 9457 responses with HTTP `409`, retaining their existing `error_code`.

- [ ] Add RED API tests for `PLAN_HASH_MISMATCH`, `AI_RUN_ACTION_STATE_CONFLICT`, and `AI_RUN_VERSION_CONFLICT`.
- [ ] Confirm they currently return `500`.
- [ ] Add the three codes to the existing conflict mapping.
- [ ] Run focused API tests.

### Task 3: Graph Read Model Distinguishes Visited, Interrupted, And Completed

**Files:**
- Modify: `services/api/src/motif_forge/application/run_graph.py`
- Test: `services/api/tests/unit/application/test_run_graph.py`
- Test: `services/api/tests/unit/infrastructure/persistence/test_run_graph_history.py`

**Interfaces:**
- Two `composition.candidate-created` facts confirm candidate A and B when LangGraph push task namespaces are unavailable.
- `CandidateSelection` is `waiting` while visited without a selection fact, and `skipped` after cancellation without a selection fact.
- An actual `composition.candidate-selected` event remains the completion authority.

- [ ] Add RED fixtures matching the real empty-namespace `~__pregel_push` checkpoint rows.
- [ ] Add RED read-model tests for two persisted candidate events and interrupted/cancelled selection.
- [ ] Confirm candidate nodes are currently skipped and CandidateSelection is incorrectly completed.
- [ ] Implement event-backed candidate counts and selection status precedence.
- [ ] Run focused history/read-model tests.

### Task 4: Inspector Includes Pre-Revision Preview Jobs And Artifacts

**Files:**
- Modify: `services/api/src/motif_forge/infrastructure/persistence/run_inspection.py`
- Test: `services/api/tests/integration/test_postgres_s7_run_inspection.py`

**Interfaces:**
- `PostgresRunInspectionStore.read_run_inspection(run_id)` includes media Runs sharing the AI Run `thread_id`, plus the existing Revision-correlated export evidence.
- Artifact evidence is selected through included Job IDs and remains payload-free.

- [ ] Add a real PostgreSQL RED fixture with an AI Run, same-thread media Run, Preview Job, and audio Artifact before Revision materialization.
- [ ] Confirm Inspector currently returns zero Jobs and Artifacts.
- [ ] Extend the read query using existing `RunRow`, `MediaJobRow`, and `AudioArtifactRow` relationships; deduplicate by ID.
- [ ] Run the real PostgreSQL inspection test.

### Task 5: Tests Never Emit Remote LangSmith Traces

**Files:**
- Create: `services/api/tests/conftest.py`
- Test: existing provider and observability unit tests.

**Interfaces:**
- Pytest collection sets `LANGSMITH_TRACING=false` and `LANGCHAIN_TRACING_V2=false` before importing the module-global FastAPI application.
- Tests that explicitly pass `Settings.for_test(langsmith_tracing=True, ...)` can still test the adapter with monkeypatched clients.

- [ ] Add collection-time test environment isolation in `conftest.py`.
- [ ] Run provider failure tests with a deliberately trace-enabled checkout `.env`; verify no network trace is emitted through the process configuration.
- [ ] Run `test_langsmith_observability.py` to ensure explicit adapter tests remain valid.
- [ ] Confirm the repository contains no deprecated `list_runs()`/`read_run()` LangSmith query call sites; do not add diagnostic code when none exists.

### Task 6: Verification And One Complete Flow

**Files:**
- Update only documentation if a user-facing behavior or launch instruction changed.

- [ ] Run Python focused unit tests for Graph, Outbox, API status mapping, inspection, and LangSmith isolation.
- [ ] Run focused web tests for Run state/conflict rendering.
- [ ] Run one real PostgreSQL boundary covering cancellation and pre-Revision inspection.
- [ ] Treat actions for a deleted AI Run as acknowledged no-ops and remove the test fixture's
  orphan-Outbox leak.
- [ ] Run Ruff, mypy, TypeScript checks, and repository diff checks.
- [ ] Rebuild only changed Compose images.
- [ ] Run one new Generate flow through PlanApproval, CandidateSelection, Revision materialization, Render, Transcode, and Bundle without cancellation.
- [ ] If local flow is green and a DeepSeek key is configured, run at most one low-budget paid planning smoke; otherwise report it as intentionally skipped.
- [ ] Inspect the final diff and report remaining caveats. Do not merge or push.
