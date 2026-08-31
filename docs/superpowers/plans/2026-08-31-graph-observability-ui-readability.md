# Graph Observability and Workbench Readability Implementation Plan

> **For Codex:** REQUIRED SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Execute inline in the current task; do not use subagents unless the user explicitly approves a genuinely independent need.

**Goal:** Make the existing `motif-forge-parent.v2` Generate execution visibly checkpoint-backed, then improve the current work pages so the Graph, result, arrangement timeline, and primary actions are easier to read without changing the product workflow.

**Architecture:** Add one bounded, read-only LangGraph PostgreSQL history adapter, combine its normalized task-path evidence with the existing Run Inspector facts in an application projection, and expose that projection through one Generate-only read endpoint. Render the result with native React/CSS components; reuse the existing Run SSE only as a query invalidation signal. Preserve the one Parent Graph, all approval and Revision contracts, and every existing mutation path.

**Tech stack:** Python 3.12, FastAPI, Pydantic, SQLAlchemy/PostgreSQL, LangGraph 1.x with `langgraph-checkpoint-postgres` 3.1.2, React 19, TypeScript, TanStack Query, Vite, Vitest/Testing Library, Playwright, native CSS.

**Stage and requirements:** Post-S7 portfolio explainability/readability slice covering `MF-P01`, `MF-P02`, `MF-P07`, `MF-P13`, `MF-P18`, `MF-P20`, and `MF-P21`. It makes the existing workflow easier to understand and operate; it does not reopen or weaken a completed product contract.

**Approved design:** `docs/superpowers/specs/2026-08-31-graph-observability-ui-readability-design.md`

## Execution constraints

- This is a portfolio-grade Agent/LangGraph observability and readability slice, not a production-hardening program.
- Do not create another production Graph, import the full Generate dependency graph into the API, or execute a Graph during a read.
- Do not bypass `PlanApproval`, `CandidateSelection`, Edit Preview approval, or deterministic Revision materialization.
- Do not query checkpoint blobs, channel values, checkpoint JSON, metadata JSON, prompts, messages, assertions, storage keys, or physical paths.
- Do not add a Graph/layout/design-system dependency. Use semantic HTML, lightweight SVG connectors, and the existing CSS system.
- Do not compute new content hashes or use hashes for semantic node IDs, cache keys, verification, or documentation.
- Keep the existing dirty launcher/documentation work intact. Before editing any already-modified file, inspect its current diff and make a surgical change around it.
- Use narrow RED/GREEN commands inside each Task. Run combined regression only after Task 4, after Task 6, and at final acceptance.
- No paid DeepSeek call is required. Do not run one unless a newly discovered provider-path defect makes it specifically necessary and the user reauthorizes that call.
- Do not commit, merge, or push as part of this plan unless the user explicitly asks after reviewing the implementation.

## Frozen implementation decisions

### Generate-only endpoint behavior

`GET /api/v1/runs/{run_id}/graph` supports Generate Runs only. A direct request for an Import or Edit Run returns the existing application error envelope with `RUN_GRAPH_UNSUPPORTED` and HTTP `422`. `RunInspectorPage` first reads the ordinary inspection model and enables the Graph query only when `run.run_type === "generate"`; Import and Edit continue to show the existing safe timeline without an avoidable error request.

### History query boundary

`PostgresRunGraphHistoryStore` owns all dependence on the pinned LangGraph PostgreSQL table shape. It validates the schema name with the same safe-identifier rule used by `infrastructure/checkpoints.py`, reads at most 4,097 distinct task rows, returns at most 4,096, and reports `truncated=true` when the extra row exists.

The production query may select only:

```sql
SELECT DISTINCT checkpoint_ns, checkpoint_id, task_id, task_path
FROM <validated_schema>.checkpoint_writes
WHERE thread_id = :thread_id AND task_path <> ''
ORDER BY checkpoint_id, checkpoint_ns, task_path, task_id
LIMIT 4097
```

The evidence count is a separate bounded scalar query:

```sql
SELECT count(*)
FROM <validated_schema>.checkpoints
WHERE thread_id = :thread_id
```

Missing tables/columns return `schema_compatible=false` and an empty/partial history model. Ordinary database read failures raise `ApplicationError("CHECKPOINT_HISTORY_READ_FAILED", ...)`; they are not disguised as empty evidence.

### Task-path normalization

- A pull path with the exact prefix `~__pregel_pull, ` yields its literal node name.
- A push path with the exact prefix `~__pregel_push, ` derives only a registered group node from the leaf checkpoint namespace before `:<task_id>`; it never opens payload data to infer a branch.
- Two ordered push occurrences registered to `CreateCandidateBranch` map to the semantic `candidate-a` and `candidate-b` nodes and use `grouped_parallel` evidence.
- Unknown/malformed paths return `technical_name=None`, `path_kind="unknown"`, and only bounded safe evidence.
- Namespace parsing uses the public persisted string format (`|` between namespaces and `:<task_id>` at a namespace leaf) without importing private LangGraph constants.

### Presentation registry

The versioned application registry is static presentation metadata, never executable Graph configuration. It uses literal semantic IDs and contains these stages:

1. `planning`: request/adapters plus `ValidateBrief`, `CompositionPlanner`, `ValidatePlan`, `RepairPlan`, fallback and terminal planning nodes;
2. `approval`: `PlanApproval`;
3. `candidates`: semantic Candidate A/B nodes backed by `CreateCandidateBranch`, then `CandidateFanIn`, preview enqueue/wait;
4. `critic`: `CriticizeCandidates`, `ApplyCriticRepair`, `CreateCandidateSelectionPreviews`;
5. `commit`: `CandidateSelection`, `MaterializeSelectedCandidate`, legacy `MaterializeApprovedComposition`, `StoragePressureGate`;
6. `export`: `EnqueueCompleteExportStep`, `WaitForGenerateJobEvent`, `CompleteGenerate`;
7. `error`: `RouteError`, default-hidden unless visited.

Adapters, internal routers, fallback terminals, and legacy alternatives remain in the registry but default to hidden. The UI expands them on demand.

---

## Task 1: RED/GREEN checkpoint history reader and Generate registry

**Files:**

- Create: `services/api/src/motif_forge/application/run_graph_history.py`
- Create: `services/api/src/motif_forge/application/run_graph_registry.py`
- Create: `services/api/src/motif_forge/infrastructure/persistence/run_graph_history.py`
- Create: `services/api/tests/unit/application/test_run_graph_registry.py`
- Create: `services/api/tests/unit/infrastructure/persistence/test_run_graph_history.py`
- Create: `services/api/tests/integration/test_postgres_run_graph_history.py`
- Reference only: `services/api/src/motif_forge/infrastructure/checkpoints.py`
- Reference only: `services/api/src/motif_forge/agent/parent_graph.py`

### Step 1: Write the registry RED tests

Assert that:

- `motif-forge-parent.v2` returns stages in the frozen order;
- semantic IDs are stable literal strings and unique;
- every edge endpoint exists;
- Candidate A and B share technical name `CreateCandidateBranch` but have different semantic IDs;
- approval/selection nodes are `human`, planner/critic nodes are `agent`, and worker boundaries are `worker`;
- all actual Parent/Planning technical node names listed in the design spec are represented;
- adapters, routers, error, fallback terminal, and legacy materialization are default-hidden;
- the registry has no callable, compiled graph, checkpointer, prompt, state value, coordinate, or hash field.

Run:

```bash
.venv/bin/pytest services/api/tests/unit/application/test_run_graph_registry.py -q
```

Expected RED: module import fails because the registry does not exist.

### Step 2: Implement the static registry

In `run_graph_registry.py`, add frozen Pydantic models or frozen slot dataclasses:

```python
GraphNodeKind = Literal["deterministic", "agent", "human", "worker"]
GraphRelation = Literal["sequence", "parallel", "join", "loop", "worker_boundary"]

GraphPhaseDefinition(id, label, order, collapsed_by_default)
GraphNodeDefinition(id, phase_id, label, technical_name, kind, order,
                    default_visible, group_id=None)
GraphEdgeDefinition(source, target, relation)
GenerateGraphRegistry(graph_version, phases, nodes, edges)
```

Export one immutable `GENERATE_GRAPH_REGISTRY`. Keep Chinese action labels primary and exact English technical names intact. Encode parallel candidate edges, the preview/export loops, legacy mutually exclusive materialization, and the error route as presentation relationships only.

Re-run the registry test and expect PASS.

### Step 3: Write the history model/parser RED tests

In `run_graph_history.py` application models, the tests should expect:

```python
PathKind = Literal["pull", "push", "unknown"]

RunGraphTaskPath(
    checkpoint_ns: str,
    checkpoint_id: str,
    task_id: str,
    task_path: str,
    technical_name: str | None,
    path_kind: PathKind,
)

RunGraphHistory(
    checkpoint_count: int,
    task_paths: tuple[RunGraphTaskPath, ...],
    truncated: bool,
    schema_compatible: bool,
)

class RunGraphHistoryStore(Protocol):
    async def read_run_graph_history(self, thread_id: str) -> RunGraphHistory: ...
```

Cover exact pull parsing, push/namespace parsing, nested planning namespace parsing, malformed paths, unknown registered names, deterministic order, row deduplication, the 4,096-row cap, and invalid schema identifiers.

Run:

```bash
.venv/bin/pytest services/api/tests/unit/infrastructure/persistence/test_run_graph_history.py -q
```

Expected RED: parser/store imports fail.

### Step 4: Implement the isolated persistence adapter

Use SQLAlchemy `text()` only after validating the schema identifier; identifiers cannot be bind parameters. Keep the two approved SQL statements as module-local constants built from the validated identifier. Catch only table/column compatibility failures for `schema_compatible=false`; translate all other SQLAlchemy/database failures to `CHECKPOINT_HISTORY_READ_FAILED`.

Do not add a migration and do not modify the shared LangGraph checkpointer. Return only normalized strings and counts.

Re-run both Task 1 unit test files and expect PASS.

### Step 5: Add one real PostgreSQL/LangGraph boundary

The integration test must:

1. use `isolated_postgres_schemas` and the existing opt-in `test_postgres_dsn` fixture;
2. initialize an `AsyncPostgresSaver` in the isolated primary schema;
3. compile and invoke a minimal `START -> Alpha -> Beta -> END` `StateGraph` with a unique `thread_id`;
4. verify through `information_schema.columns` that the pinned `checkpoint_writes.task_path` column exists;
5. read through `PostgresRunGraphHistoryStore`, not direct test SQL, and assert Alpha/Beta pull task paths and a positive checkpoint count;
6. call the store twice and assert stable order/equality;
7. assert the returned model contains no `blob`, `channel`, `type`, checkpoint, metadata, state, message, or payload field;
8. use the secondary isolated schema to prove missing/incompatible history returns `schema_compatible=false` without falling back to the production schema.

Run with the already-running local PostgreSQL only:

```bash
MOTIF_FORGE_TEST_POSTGRES_DSN=postgresql://motif_forge:motif_forge@127.0.0.1:5432/motif_forge \
  .venv/bin/pytest services/api/tests/integration/test_postgres_run_graph_history.py -q
```

Expected GREEN: one real schema-contract test passes. If PostgreSQL is not running, report that boundary as not run; do not silently accept a skipped result as proof.

### Task 1 acceptance

```bash
.venv/bin/pytest \
  services/api/tests/unit/application/test_run_graph_registry.py \
  services/api/tests/unit/infrastructure/persistence/test_run_graph_history.py -q
.venv/bin/ruff check \
  services/api/src/motif_forge/application/run_graph_history.py \
  services/api/src/motif_forge/application/run_graph_registry.py \
  services/api/src/motif_forge/infrastructure/persistence/run_graph_history.py \
  services/api/tests/unit/application/test_run_graph_registry.py \
  services/api/tests/unit/infrastructure/persistence/test_run_graph_history.py \
  services/api/tests/integration/test_postgres_run_graph_history.py
```

---

## Task 2: RED/GREEN Graph projection and read API

**Files:**

- Create: `services/api/src/motif_forge/application/run_graph.py`
- Create: `services/api/src/motif_forge/api/run_graph.py`
- Create: `services/api/tests/unit/application/test_run_graph.py`
- Create: `services/api/tests/unit/api/test_run_graph.py`
- Modify: `services/api/src/motif_forge/application/run_inspection.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/run_inspection.py`
- Modify: `services/api/src/motif_forge/api/app.py`
- Modify: `services/api/tests/unit/application/test_run_inspection.py`
- Modify: `services/api/tests/unit/api/test_run_inspection.py`
- Modify: `services/api/tests/integration/test_postgres_s7_run_inspection.py`
- Modify: all test fixtures constructing `InspectionRunSummary`

### Step 1: Add `thread_id` to the existing safe inspection fact

Write/adjust tests first so `InspectionRunSummary` requires `thread_id: str`. Update `PostgresRunInspectionStore` to select it from the existing `ai_runs` row. Confirm it is a safe opaque graph correlation ID and never expose approval assertions or state.

Run:

```bash
.venv/bin/pytest \
  services/api/tests/unit/application/test_run_inspection.py \
  services/api/tests/unit/api/test_run_inspection.py -q
```

Expected RED before implementation: validation/construction failures for missing `thread_id`. Expected GREEN after updating every fixture and store projection.

### Step 2: Write Graph projection RED tests

Define the exact public models in `application/run_graph.py`:

```python
RunGraphReadModel
GraphPhaseView
GraphNodeView
GraphEdgeView
GraphEvidenceSummary
```

Use the exact literals and fields frozen in the design spec. Test `ReadRunGraph` with in-memory inspection/history stores for:

- Run not found;
- non-Generate Run rejected with `RUN_GRAPH_UNSUPPORTED`;
- queued Generate with topology and no fabricated confirmations;
- planning fallback and nested Planning nodes;
- `waiting_approval` mapping only to the Plan Approval diamond;
- two ordered anonymous candidate branches plus `CandidateFanIn`;
- Critic/Repair and candidate-selection wait;
- repeated preview/export tasks increasing `iteration_count` without unbounded arrays;
- selected materialization route marking its terminal alternative `skipped` only after terminal status;
- safe application-event timestamp supplying `occurred_at`, while checkpoint-only evidence keeps it `None`;
- failure, unknown path, truncated history, incompatible schema, and empty history;
- deterministic phases/nodes/edges and stable literal IDs;
- evidence summary counts for checkpoints, events, human decisions, and Jobs;
- absence of prompt, brief, payload, assertion, blob, storage key, and path fields in `model_dump_json()`.

Run:

```bash
.venv/bin/pytest services/api/tests/unit/application/test_run_graph.py -q
```

Expected RED: projection types/use case do not exist.

### Step 3: Implement `ReadRunGraph`

Constructor dependencies:

```python
ReadRunGraph(
    inspection_store: RunInspectionStore,
    history_store: RunGraphHistoryStore,
    registry: GenerateGraphRegistry = GENERATE_GRAPH_REGISTRY,
)
```

Projection order:

1. read safe inspection facts;
2. return not-found before any checkpoint query;
3. reject non-Generate Runs;
4. read history using `run.thread_id`;
5. initialize registry nodes as `not_visited`/`none`;
6. apply checkpoint evidence and counts;
7. apply only allowlisted application-event/decision/Job boundary evidence;
8. derive active/waiting phase from persisted Run/event state without guessing an exact node;
9. derive terminal `skipped` alternatives;
10. derive traversed edges only from ordered evidence and registered topology.

Evidence status rules:

- `unavailable`: compatible read produced no root task rows;
- `partial`: schema incompatible, truncated, or supporting facts cannot fully map confirmed paths;
- `available`: relevant readable evidence exists, even when topology nodes are intentionally unvisited.

Re-run the projection test and expect PASS.

### Step 4: Write and implement the API RED/GREEN tests

Add `build_run_graph_router(read_run_graph: ReadRunGraph)`. Test:

- `GET /api/v1/runs/{run_id}/graph` returns `200` and `run-graph-view.v1`;
- unknown Run returns `404` in the existing envelope;
- non-Generate returns `422`/`RUN_GRAPH_UNSUPPORTED`;
- ordinary history database failure returns `503`/`CHECKPOINT_HISTORY_READ_FAILED`;
- incompatible schema returns `200` partial/unavailable rather than `503`;
- response serialization omits every forbidden field.

In `create_app`, accept an optional `run_graph_history_store` for tests. When PostgreSQL is configured, instantiate `PostgresRunGraphHistoryStore(session_factory)` and include the router alongside the existing Inspector router. Do not create a checkpointer or compiled Graph here.

Run:

```bash
.venv/bin/pytest services/api/tests/unit/api/test_run_graph.py -q
```

Expected RED before the route/wiring and GREEN after it.

### Step 5: Extend the real read-only boundary

Surgically extend `test_postgres_s7_run_inspection.py` or add a focused adjacent test so a persisted Generate Run with a real `thread_id` can be inspected and projected twice without changing counts in `ai_runs`, `ai_run_events`, `outbox_events`, checkpoints, or checkpoint writes. Reuse the Task 1 minimal Graph where practical; do not invoke DeepSeek, Workers, rendering, or artifact creation.

Run:

```bash
MOTIF_FORGE_TEST_POSTGRES_DSN=postgresql://motif_forge:motif_forge@127.0.0.1:5432/motif_forge \
  .venv/bin/pytest \
    services/api/tests/integration/test_postgres_run_graph_history.py \
    services/api/tests/integration/test_postgres_s7_run_inspection.py -q
```

### Task 2 acceptance

```bash
.venv/bin/pytest \
  services/api/tests/unit/application/test_run_graph_registry.py \
  services/api/tests/unit/infrastructure/persistence/test_run_graph_history.py \
  services/api/tests/unit/application/test_run_graph.py \
  services/api/tests/unit/application/test_run_inspection.py \
  services/api/tests/unit/api/test_run_graph.py \
  services/api/tests/unit/api/test_run_inspection.py -q
.venv/bin/ruff check services/api/src/motif_forge services/api/tests/unit services/api/tests/integration/test_postgres_run_graph_history.py
.venv/bin/mypy services/api/src/motif_forge
```

---

## Task 3: RED/GREEN shared Graph UI and Graph-first Inspector

**Files:**

- Modify: `scripts/export_openapi.py` only if required by the existing generator contract
- Modify generated: `apps/web/src/generated/api-schema.d.ts`
- Modify: `apps/web/src/shared/openapi.ts`
- Modify: `apps/web/src/features/inspection/inspectionApi.ts`
- Create: `apps/web/src/features/inspection/ExecutionPathStrip.tsx`
- Create: `apps/web/src/features/inspection/GraphStageLane.tsx`
- Create: `apps/web/src/features/inspection/GraphNode.tsx`
- Create: `apps/web/src/features/inspection/GraphEvidencePanel.tsx`
- Create: `apps/web/src/features/inspection/RunGraphView.tsx`
- Create: `apps/web/src/features/inspection/ExecutionPathStrip.test.tsx`
- Create: `apps/web/src/features/inspection/RunGraphView.test.tsx`
- Modify: `apps/web/src/features/inspection/RunInspectorPage.tsx`
- Modify: `apps/web/src/features/inspection/RunInspectorPage.test.tsx`
- Modify: `apps/web/src/styles.css`

### Step 1: Regenerate and type the contract

After Task 2 API tests pass:

```bash
npm run generate:openapi
```

Add aliases for `RunGraphReadModel` and directly consumed nested view types in `shared/openapi.ts`. Add `readRunGraph(runId, signal?)` in `inspectionApi.ts` using the existing fetch/error conventions.

Do not hand-edit generated declarations except to diagnose generator output; the final generated file must come from `generate:openapi`.

### Step 2: Write component RED tests

`ExecutionPathStrip.test.tsx` must cover completed/active/waiting/failed labels, current-phase accessibility, compact stage count, partial/unavailable messages, and the Inspector link.

`RunGraphView.test.tsx` must cover:

- Chinese node label primary and exact technical name secondary;
- natural-width nodes rather than equal stretched columns;
- checkpoint/event/grouped/unvisited evidence text;
- Candidate A/B parallel group joining at fan-in;
- collapsed `Export pipeline × N` and expansion to repeated evidence;
- default-hidden adapters/router internals with an expand control;
- button keyboard selection and an accessible evidence region;
- unknown node shown only as `未映射节点` with bounded technical evidence;
- loading, partial, unavailable, failed, and empty states;
- reduced-motion class/attribute contract;
- no raw prompt/payload/path text from fixtures rendered into the DOM.

Run:

```bash
npm run test:web -- \
  apps/web/src/features/inspection/ExecutionPathStrip.test.tsx \
  apps/web/src/features/inspection/RunGraphView.test.tsx
```

Expected RED: components do not exist.

### Step 3: Implement native Graph components

Use semantic stage sections and native `<button>` nodes. Keep layout data out of the API. Use CSS grid/flex wrapping and small inline SVG or pseudo-element connectors; do not implement drag, pan, zoom, or editable topology.

Node visuals:

- circle/rounded automatic node treatment;
- diamond wrapper for human decisions without rotating its text;
- kind/status text always visible;
- cyan deterministic, purple Agent, magenta worker/artifact, mint verified success;
- focus ring and selected state independent of color;
- motion only on a genuinely active node, disabled under `prefers-reduced-motion`.

The evidence panel displays only fields already present in the read model. It never accepts arbitrary event payload objects.

Re-run the component tests and expect PASS.

### Step 4: Make Inspector Graph-first

`RunInspectorPage` continues to query inspection facts first. For Generate only, query the Graph and render in this order:

1. compact Run identity/status/version header;
2. full `RunGraphView`;
3. safe evidence panel;
4. existing decisions/Jobs/artifacts/recovery summaries;
5. existing event timeline in a secondary `details` section.

For Import/Edit, graph unavailable, or Graph request error, keep the existing timeline usable and show a specific evidence message rather than a blank page. An Inspector facts error still uses the existing page error state.

Update `RunInspectorPage.test.tsx` for Generate Graph-first order, Import/Edit no-Graph request, unavailable fallback, error isolation, and narrow text wrapping.

Run:

```bash
npm run test:web -- \
  apps/web/src/features/inspection/ExecutionPathStrip.test.tsx \
  apps/web/src/features/inspection/RunGraphView.test.tsx \
  apps/web/src/features/inspection/RunInspectorPage.test.tsx
npm run build:web
```

---

## Task 4: RED/GREEN live Run strip and results-first Run page

**Files:**

- Modify: `apps/web/src/features/generate/RunPage.tsx`
- Modify: `apps/web/src/features/generate/RunPage.test.tsx`
- Modify: `apps/web/src/features/generate/RunProgress.tsx`
- Modify: `apps/web/src/styles.css`
- Reuse: `apps/web/src/features/inspection/ExecutionPathStrip.tsx`
- Reuse: `apps/web/src/features/inspection/inspectionApi.ts`

### Step 1: Add Run page RED tests

Cover:

- Generate Run queries the graph by `runId`;
- a relevant existing SSE event invalidates/refetches `['run-graph', runId]` without opening a second event stream;
- active and human-wait states show the compact execution strip;
- `waiting_approval` keeps the Plan and approval action expanded;
- candidate selection remains prominent when waiting;
- a terminal success leads with Revision/output readiness and the Studio action;
- terminal Plan and technical evidence are collapsed progressive disclosure;
- Graph failure does not disable approval, selection, cancellation, result, or Studio actions;
- 390 px contract uses horizontal strip overflow only and creates no page-level horizontal overflow.

Run:

```bash
npm run test:web -- apps/web/src/features/generate/RunPage.test.tsx
```

Expected RED: no graph query/path strip and old terminal hierarchy.

### Step 2: Implement one-query live behavior

Use TanStack Query for `readRunGraph`. Keep the current SSE watcher and invalidate the Graph query after relevant Run events; do not add polling or another `EventSource`. Preserve all current action state and error handling.

Render `ExecutionPathStrip` below the compact Run status. For terminal runs, render result/Revision/Studio first and move the approved Plan into a closed `<details>`. Never collapse the Plan while it still requires approval.

Reduce the Run header/spacing in `RunProgress` without changing status derivation.

### Step 3: Run the first combined regression checkpoint

```bash
npm run test:web -- \
  apps/web/src/features/inspection/ExecutionPathStrip.test.tsx \
  apps/web/src/features/inspection/RunGraphView.test.tsx \
  apps/web/src/features/inspection/RunInspectorPage.test.tsx \
  apps/web/src/features/generate/RunPage.test.tsx
npm run build:web
.venv/bin/pytest \
  services/api/tests/unit/application/test_run_graph_registry.py \
  services/api/tests/unit/infrastructure/persistence/test_run_graph_history.py \
  services/api/tests/unit/application/test_run_graph.py \
  services/api/tests/unit/api/test_run_graph.py -q
```

Do not run the S1/S7 Worker/cancellation matrix because this slice has not changed those contracts.

---

## Task 5: RED/GREEN recent-first Home and progressive Brief

**Files:**

- Create: `apps/web/src/features/projects/ProjectFilters.tsx`
- Create: `apps/web/src/features/projects/RecentProjectList.tsx`
- Modify: `apps/web/src/features/projects/ProjectHomePage.tsx`
- Modify: `apps/web/src/features/projects/ProjectHomePage.test.tsx`
- Create: `apps/web/src/features/generate/AdvancedBriefFields.tsx`
- Modify: `apps/web/src/features/generate/BriefPage.tsx`
- Modify: `apps/web/src/features/generate/BriefPage.test.tsx`
- Modify: `apps/web/src/styles.css`

### Step 1: Write Home RED tests

Assert that:

- Projects sort by `updated_at` descending;
- the default view shows at most six recent Projects;
- title search and status filtering compose correctly;
- “全部项目与测试历史” reveals the remaining Projects and can collapse again;
- filtered empty state explains how to clear filters;
- Project links/status/recovery actions remain unchanged;
- no Project is deleted or mutated by display filtering.

Run:

```bash
npm run test:web -- apps/web/src/features/projects/ProjectHomePage.test.tsx
```

Expected RED: all Projects are rendered in the old flat grid.

### Step 2: Implement focused Home components

Keep data fetching/state ownership in `ProjectHomePage`. `ProjectFilters` owns only controlled search/status UI; `RecentProjectList` owns only sorting, recent/all grouping, and rendering existing `ProjectCard` instances. Use native controls and visible labels.

### Step 3: Write Brief RED tests

Assert that:

- title, style, purpose, moods, and duration are visible initially;
- meter, BPM, key, instruments, hard/soft/negative constraints are inside a closed advanced `<details>`;
- entered advanced values survive close/reopen;
- validation focuses or opens the advanced section when an invalid advanced field blocks submission;
- submitted request body is unchanged from the existing API contract;
- Generate and navigation/error behavior remain unchanged.

Run:

```bash
npm run test:web -- apps/web/src/features/generate/BriefPage.test.tsx
```

Expected RED: advanced fields are always expanded and no extracted component exists.

### Step 4: Implement progressive Brief

Extract only the advanced field group; keep the form state and submission owner in `BriefPage`. Use a native `<details>` so keyboard behavior works without a custom disclosure dependency. Closing it must never reset controlled values.

### Task 5 acceptance

```bash
npm run test:web -- \
  apps/web/src/features/projects/ProjectHomePage.test.tsx \
  apps/web/src/features/generate/BriefPage.test.tsx
npm run build:web
```

---

## Task 6: RED/GREEN timeline-first Studio restructuring

**Files:**

- Create: `apps/web/src/features/studio/StudioWorkbar.tsx`
- Create: `apps/web/src/features/studio/StudioInspector.tsx`
- Modify: `apps/web/src/features/studio/StudioPage.tsx`
- Modify: `apps/web/src/features/studio/StudioPage.test.tsx`
- Modify only if composition requires: `apps/web/src/features/studio/StudioToolbar.tsx`
- Modify only if accessible composition requires: `apps/web/src/features/studio/EditPanel.tsx`
- Modify: `apps/web/src/features/studio/EditPanel.test.tsx`
- Modify: `apps/web/src/styles.css`
- Reuse unchanged where possible: `Transport.tsx`, `EditPreviewCard.tsx`, `StudioDock.tsx`

### Step 1: Write Studio layout RED tests

Assert DOM/landmark order and behavior:

1. compact project/Revision workbar;
2. arrangement timeline main region;
3. AI/selection/export inspector complementary region;
4. existing Studio dock after the main workspace.

Also cover:

- playback, save, export, Inspector link, selection, local Edit request, Patch preview, approve/reject, and delivery states remain reachable;
- local Edit still creates a reviewable Patch and cannot directly mutate a Revision;
- timeline appears before AI Edit and MP3 delivery in DOM order;
- desktop grid gives the timeline the primary width without a fixed height;
- narrow layout stacks a collapsible inspector below the timeline;
- long track/instrument/error labels wrap or scroll within their own region;
- unavailable delivery and empty arrangement retain clear next actions.

Run:

```bash
npm run test:web -- \
  apps/web/src/features/studio/StudioPage.test.tsx \
  apps/web/src/features/studio/EditPanel.test.tsx
```

Expected RED: current page places large header/playback/edit/export panels ahead of the timeline.

### Step 2: Extract composition-only components

`StudioWorkbar` composes Project/Revision identity, the existing `StudioToolbar`, transport, and save/export/Inspector actions. It receives state/actions from `StudioPage`; it does not duplicate data fetching or mutation logic.

`StudioInspector` composes Edit, selection/preview, and delivery/export status. Move the existing private delivery presentation into it or pass a typed render model. Do not change API calls or approval assertions.

`StudioPage` remains the state owner and renders a responsive two-column workspace: arrangement first, inspector second. Below the existing narrow breakpoint, use a native disclosure/stack with no clipped fixed heights.

### Step 3: Run the second combined regression checkpoint

```bash
npm run test:web -- \
  apps/web/src/features/studio/StudioPage.test.tsx \
  apps/web/src/features/studio/EditPanel.test.tsx \
  apps/web/src/features/generate/RunPage.test.tsx \
  apps/web/src/features/inspection/RunInspectorPage.test.tsx \
  apps/web/src/features/projects/ProjectHomePage.test.tsx \
  apps/web/src/features/generate/BriefPage.test.tsx
npm run build:web
```

Only if these tests reveal a changed approval, Worker, Artifact, cancellation, or Revision contract should execution expand into the corresponding older backend matrix.

---

## Task 7: Shared polish, accessible browser proof, and documentation

**Files:**

- Modify: `apps/web/src/styles.css`
- Modify only as needed: shared App Shell/navigation components under `apps/web/src/app/`
- Modify only as needed: Export/Eval/About page wrappers for shared spacing/focus treatment
- Create: `scripts/run_graph_ui_browser_smoke.mjs`
- Modify: `package.json`
- Modify surgically: `README.md`
- Modify surgically: `docs/IMPLEMENTATION_STATUS.md`
- Modify surgically: `docs/TECH_EVOLUTION.md`
- Do not modify: `docs/PROJECT_GUIDE.md` unless a verified user-facing contract is factually wrong

### Step 1: Normalize work-page styling without a redesign rewrite

Introduce or consolidate a small token set for work-page heading scale, surface/divider, status, focus, and spacing. Apply it to Home, Brief, Run, Inspector, Studio, Export, and Eval. Keep About's larger portfolio typography.

Check explicitly:

- visible `:focus-visible` on links, buttons, inputs, summaries, and Graph nodes;
- no fixed-height clipping;
- no page-level horizontal overflow at 390 px;
- long Chinese/English technical names wrap inside nodes/evidence;
- only the compact path and timeline tracks may own intentional local horizontal scrolling;
- loading/empty/partial/error/success states identify the next action;
- `prefers-reduced-motion` disables active signal/pulse transitions;
- color is not the only state cue.

### Step 2: Add one browser smoke flow

Base the script on the cleanup and API-wait conventions in `run_s5_browser_smoke.mjs`, but keep it focused on this slice. Add:

```json
"smoke:graph-ui": "node scripts/run_graph_ui_browser_smoke.mjs"
```

The script must use public UI/API behavior to:

1. open Home and verify recent-first controls;
2. create/open a Project;
3. submit a no-key Synth Ambient Brief;
4. approve the Plan;
5. select a candidate when required;
6. wait for the materialized Revision/export-ready terminal state;
7. verify the compact path on Run;
8. open Inspector and verify Chinese labels plus exact technical node evidence;
9. expand candidate/export detail;
10. open Studio and verify the arrangement precedes the inspector;
11. repeat the key layout assertions at a 390 px viewport and assert no document-level horizontal overflow.

Use the existing deterministic/no-key path; do not enable DeepSeek. Clean up only the browser/processes started by this script in `finally`, and verify they exited. Do not close a pre-existing user browser.

Run:

```bash
npm run smoke:graph-ui
```

Expected GREEN: one real browser flow proves the UI is connected to persisted Graph evidence. A screenshot may be retained only if it is an intentional documented acceptance artifact; remove temporary Playwright profiles/screenshots/logs afterward.

### Step 3: Synchronize documentation after evidence exists

Before editing the already-dirty documentation files, inspect their current diffs. Preserve launcher changes and append only Graph/readability facts that passed verification.

- `README.md`: add a concise “查看 Agent/LangGraph 执行路径” usage section: Run compact strip, Inspector full Graph, evidence meanings, and no-key flow.
- `IMPLEMENTATION_STATUS.md`: record this slice as complete only after API, PostgreSQL, web, and browser evidence passes; otherwise record the exact remaining check.
- `TECH_EVOLUTION.md`: append the architecture decision—isolated `task_path` reader, presentation registry, no second Graph, SSE invalidation reuse, and progressive-disclosure UI.
- Do not add hashes, paid-call claims, production P95/load claims, or broad S1/S7 revalidation claims.

### Step 4: Final focused verification

Backend:

```bash
.venv/bin/pytest \
  services/api/tests/unit/application/test_run_graph_registry.py \
  services/api/tests/unit/infrastructure/persistence/test_run_graph_history.py \
  services/api/tests/unit/application/test_run_graph.py \
  services/api/tests/unit/application/test_run_inspection.py \
  services/api/tests/unit/api/test_run_graph.py \
  services/api/tests/unit/api/test_run_inspection.py -q
MOTIF_FORGE_TEST_POSTGRES_DSN=postgresql://motif_forge:motif_forge@127.0.0.1:5432/motif_forge \
  .venv/bin/pytest \
    services/api/tests/integration/test_postgres_run_graph_history.py \
    services/api/tests/integration/test_postgres_s7_run_inspection.py -q
.venv/bin/ruff check services/api/src/motif_forge services/api/tests/unit services/api/tests/integration/test_postgres_run_graph_history.py
.venv/bin/mypy services/api/src/motif_forge
```

Frontend:

```bash
npm run test:web -- \
  apps/web/src/features/inspection/ExecutionPathStrip.test.tsx \
  apps/web/src/features/inspection/RunGraphView.test.tsx \
  apps/web/src/features/inspection/RunInspectorPage.test.tsx \
  apps/web/src/features/generate/RunPage.test.tsx \
  apps/web/src/features/projects/ProjectHomePage.test.tsx \
  apps/web/src/features/generate/BriefPage.test.tsx \
  apps/web/src/features/studio/StudioPage.test.tsx \
  apps/web/src/features/studio/EditPanel.test.tsx
npm run generate:openapi
npm run build:web
npm run smoke:graph-ui
```

Repository hygiene:

```bash
git diff --check
git status --short
git diff -- docs/PROJECT_GUIDE.md
```

Expected: targeted tests, real PostgreSQL boundary, build, and one browser smoke pass; `PROJECT_GUIDE.md` has no incidental change; no temporary browser/cache files, generated test projects outside normal persisted application data, or task-owned browser processes remain.

### Step 5: One independent review, at most one repair review

Because the user asked to avoid unnecessary subagents, perform the implementation review inline unless the user separately authorizes an independent reviewer. Review only current-slice diffs against the approved spec, with priority on:

- accidental second-Graph/runtime construction;
- sensitive checkpoint/event data exposure;
- fabricated node/edge confirmation;
- approval or Revision contract regression;
- Graph failure blocking primary workflow;
- mobile overflow, inaccessible node selection, or motion violations;
- edits that overwrite the existing dirty launcher/documentation work.

Fix current-path Critical/Important findings once, re-run only affected narrow tests plus final focused verification, then stop. Do not widen into load, P95, multi-tenant, exhaustive concurrency, or the historical S1 failure matrix without concrete evidence that this slice changed those contracts.

## Final acceptance checklist

- [ ] A real Generate Run exposes a compact live path and full checkpoint-backed Inspector Graph.
- [ ] Planning fallback, PlanApproval, parallel candidates, fan-in, Critic/Repair, CandidateSelection, deterministic Revision materialization, and repeated export are represented from bounded evidence.
- [ ] Checkpoint/event/grouped/unvisited evidence is distinguishable and unknown nodes remain safe.
- [ ] No checkpoint payload, prompt, assertion, secret, storage key, or physical path is selected or serialized.
- [ ] API reads never execute or compile a Generate Graph and never mutate facts.
- [ ] Graph failure/unavailability leaves approvals, result actions, Studio, and the existing timeline usable.
- [ ] Inspector is Graph-first; Run is result/path-first; Home is recent-first; Brief uses preserved advanced disclosure; Studio is timeline-first.
- [ ] Desktop and 390 px layouts have readable labels, keyboard focus, local overflow only, and reduced-motion support.
- [ ] Focused backend/frontend tests, one real PostgreSQL boundary, OpenAPI generation, web build, and one no-key browser flow pass.
- [ ] No new dependency, migration, production Graph, provider call, incidental hash, or unrelated rewrite was introduced.
- [ ] Existing dirty launcher/documentation changes were preserved and temporary browser/test artifacts were cleaned.
