# Graph Observability and Workbench Readability Design

**Date:** 2026-08-31

**Status:** Approved

**Stage:** Portfolio product refinement; Type C agent observability plus compatibility-preserving UI upgrade

## 1. Outcome

This upgrade makes Motif Forge's existing Agent and LangGraph work visible and easier to use. It does not add another orchestration path or widen the music feature set. A user must be able to:

1. see the current generation phase while a Run is active;
2. open a full, readable view of the actual Parent Graph path confirmed by LangGraph checkpoints;
3. distinguish deterministic code, model-backed Agent work, human decisions, and worker boundaries;
4. inspect exact technical node names and bounded evidence without seeing prompts, chain-of-thought, secrets, assertions, or physical paths;
5. reach the Project, Brief, Run result, and Studio timeline without fighting oversized headings or long card stacks; and
6. use the same workflow and mutation contracts that exist today.

The visual signature is a restrained musical signal path. The Graph is the one expressive element; the surrounding product becomes quieter, denser, and easier to scan.

## 2. Current Evidence and Bottleneck

The production graph remains `motif-forge-parent.v2`. The inspected successful Generate Run had 44 persisted LangGraph checkpoints but the existing Run Inspector rendered only 10 application events in a table. The actual path included:

```text
ValidateRequest
→ planning subgraph with deterministic fallback
→ PlanApproval
→ two candidate Send branches
→ CandidateFanIn
→ preview loops
→ Critic and bounded Repair
→ CandidateSelection
→ MaterializeSelectedCandidate
→ StoragePressureGate
→ repeated export enqueue/wait loop
→ CompleteGenerate
```

The Graph is already real. The product gap is the absence of a read projection that turns checkpoint history into a safe, user-facing execution path.

The main UI bottlenecks are information hierarchy:

- Run Inspector leads with an audit table instead of the Graph.
- Studio places a large project header, playback, AI Edit, and MP3 panels before the timeline.
- Project Home expands all historical and test Projects into one long grid.
- Brief presents basic creative direction and advanced music constraints at the same level.
- working pages reuse portfolio-sized hero typography and excessive vertical spacing.

## 3. Scope and Invariants

### 3.1 In scope

- one read-only Graph projection over existing checkpoints and persisted facts;
- a compact live execution strip on the Run page;
- a full Graph-first Run Inspector with a secondary evidence timeline;
- targeted readability upgrades for App Shell, Project Home, Brief, Run, and Studio;
- light visual normalization for Export, Eval, and About without changing their flows;
- desktop, narrow viewport, keyboard, reduced-motion, loading, empty, partial, and error behavior;
- focused tests plus one real PostgreSQL/LangGraph checkpoint boundary.

### 3.2 Invariants

- Keep one production Parent Graph. Do not create a third production Graph.
- Do not bypass PlanApproval, CandidateSelection, or Edit Preview approval.
- Models never write a Revision directly.
- PostgreSQL remains authoritative; Redis/Celery events do not become a competing source of truth.
- The Graph endpoint is read-only and creates no Run, checkpoint, Job, Artifact, approval, or usage row.
- Do not expose prompts, chain-of-thought, secrets, approval assertions, arbitrary state values, storage keys, or physical paths.
- Do not add a content hash for Graph node IDs, UI cache keys, source files, or visual assets.
- Do not add a frontend Graph library, canvas engine, design-system framework, or font dependency.
- Existing dirty workspace changes remain outside this upgrade unless they directly conflict with an edited file.

## 4. Frozen Visual Direction

### 4.1 Signal Path

The Run page contains a compact `ExecutionPathStrip` that answers only:

- what has completed;
- what is active or waiting;
- what comes next; and
- where to open the full Graph.

The Run Inspector contains the full Graph. It shows stages as left-aligned lanes with content-sized nodes. Nodes do not stretch to fill both edges. Chinese action labels are primary; exact LangGraph node names are secondary monospace evidence.

Visual semantics are structural:

- circle: automatic node;
- diamond: human decision;
- cyan: deterministic execution;
- purple: Agent/model-backed work;
- magenta: preview, artifact, or worker boundary;
- mint: verified success state;
- dashed container: grouped or collapsed execution evidence.

Color is never the only status indicator. Text and shape repeat the state.

The default Inspector hides unvisited technical routing detail and groups low-level adapters. Expanding a stage exposes every confirmed technical node. Candidate `Send` branches appear as a parallel pair that joins at `CandidateFanIn`. The seven-step export loop appears as one collapsed `Export pipeline × 7` node and expands to the repeated Parent Graph iterations plus Job evidence.

### 4.2 Studio

Studio becomes a compact workstation:

```text
global navigation
project / Revision + transport + save/export toolbar
arrangement timeline                         AI / selection / export inspector
```

The timeline is visible in the first desktop viewport. Project identity, Revision state, playback, save, and export share one workbar. AI local Edit moves into a right inspector and continues to generate a reviewable Patch before application. Below the narrow breakpoint, the inspector moves below the timeline as a collapsible region.

### 4.3 Work page family

- Project Home shows six recent Projects first, with title search, status filtering, and a collapsed entry to all historical/test Projects. No data is deleted or silently hidden.
- Brief shows title, style, duration, mood, purpose, and creative direction first. BPM, key, instruments, and constraints remain in an expandable advanced section. Collapsing the section never clears values.
- A terminal Run leads with the result, Revision, output readiness, Studio action, and compact execution path. Approved Plan and technical evidence become progressive disclosure.
- About retains portfolio-scale typography and architectural storytelling. Export and Eval receive only shared spacing, typography, focus, and state treatment.

## 5. Graph Read Architecture

```text
LangGraph PostgreSQL checkpoint schema
              │
              │ bounded, read-only task-path query
              ▼
PostgresRunGraphHistoryStore
              │ normalized task names, paths, namespaces, and checkpoint order
              ▼
RunGraphProjectionService
   ├─ Generate Graph presentation registry
   ├─ AI Run events
   ├─ approval facts
   ├─ Jobs and Artifacts
   └─ existing Run summary
              │
              ▼
RunGraphReadModel v1
   ├─ phase summary for Run
   └─ nodes, edges, and evidence for Inspector
```

### 5.1 History reader

The API process does not construct the Run-specific full Generate Graph used by the Resume Dispatcher. LangGraph's public state-history projection requires that matching compiled topology, while `AsyncPostgresSaver.alist()` omits `checkpoint_writes.task_path`. Reconstructing the full execution graph inside the API would pull Planner, Critic, candidate, and Worker dependencies into a read path and create a second runtime construction contract.

The approved design therefore uses one isolated `PostgresRunGraphHistoryStore` against the pinned `langgraph-checkpoint-postgres` schema. Its query is read-only and selects only:

```text
checkpoint_writes.thread_id
checkpoint_writes.checkpoint_ns
checkpoint_writes.checkpoint_id
checkpoint_writes.task_id
checkpoint_writes.task_path
```

It also counts matching `checkpoints` rows for the evidence summary. It never selects `blob`, `type`, `channel`, checkpoint JSON, metadata JSON, serialized pending writes, or state values. Results are bounded, deduplicated by checkpoint/task identity, and ordered by checkpoint ID before projection.

Pull paths map their literal node segment to the presentation registry. Anonymous push paths use the checkpoint namespace plus the registered Parent Graph fan-out to produce `grouped_parallel` evidence. Unknown or malformed paths remain safe unmapped evidence; they do not trigger blob inspection or topology inference.

All dependency on LangGraph's internal PostgreSQL schema lives in this one infrastructure file and one real schema-contract integration test. A missing `task_path` column or incompatible table shape returns partial/unavailable evidence instead of starting the Generate Graph or fabricating history.

### 5.2 Presentation registry

The backend owns a versioned, static presentation registry for `motif-forge-parent.v2` Generate Runs. The registry contains:

- semantic node ID;
- exact technical node name;
- Chinese display label;
- stage membership and order;
- node kind;
- fixed topology relationships;
- default visibility;
- collapse/group behavior.

This registry is not executable and is never passed to LangGraph. It cannot create state transitions. Semantic IDs are literal values such as `planning:validate-brief` and `commit:materialize-revision`; they are not hashes.

The first registry covers Generate because the requested proof concerns the full Generate loop. Existing Import and Edit inspection continue to use the current event timeline until a later, separately approved registry is added.

### 5.3 Evidence sources

Evidence has four explicit values:

- `checkpoint_confirmed`: a LangGraph checkpoint/task confirms the node;
- `event_confirmed`: approval, Job, Artifact, or application event confirms a boundary;
- `grouped_parallel`: checkpoints confirm anonymous `Send` execution but the UI groups the branches rather than pretending to know a literal node task name;
- `none`: the topology contains the node but this Run provides no execution evidence.

The projection never labels a node confirmed merely because a later output exists.

## 6. Status Derivation

Run status is copied from the existing `AIRunStatus` values:

```text
queued | planning | waiting_approval | waiting_edit_approval
| materializing | waiting_worker | succeeded | rejected | failed | cancelled
```

Node status is derived as follows:

- `completed`: history confirms execution and no later task error targets the node;
- `active`: a safe persisted application event identifies the current node or phase; otherwise only the phase is active and no exact node is fabricated;
- `waiting`: an unresolved interrupt or approval fact targets a human node;
- `failed`: task error or safe application error evidence identifies the node/boundary;
- `skipped`: the Run is terminal and a mutually exclusive registered route was not selected;
- `not_visited`: the Run is still non-terminal and the registered node has no evidence.

An edge is `traversed` only when ordered evidence confirms movement between its endpoints. Parallel and loop edges use checkpoint order plus the registered relationship. A completed downstream artifact does not retroactively fabricate missing intermediate checkpoint evidence.

## 7. API Contract

Endpoint:

```http
GET /api/v1/runs/{run_id}/graph
```

Response:

```text
RunGraphReadModel
  schema_version: "run-graph-view.v1"
  run_id: UUID
  graph_version: str
  graph_kind: "generate"
  run_status: AIRunStatus
  evidence_status: "available" | "partial" | "unavailable"
  current_phase_id: str | null
  phases: tuple[GraphPhaseView, ...]
  nodes: tuple[GraphNodeView, ...]
  edges: tuple[GraphEdgeView, ...]
  evidence_summary: GraphEvidenceSummary
```

`GraphPhaseView`:

```text
id: str
label: str
status: "completed" | "active" | "waiting" | "failed" | "skipped" | "not_visited"
summary: str
node_ids: tuple[str, ...]
collapsed_by_default: bool
iteration_count: int
```

`GraphNodeView`:

```text
id: str
phase_id: str
label: str
technical_name: str
kind: "deterministic" | "agent" | "human" | "worker"
status: "completed" | "active" | "waiting" | "failed" | "skipped" | "not_visited"
evidence: "checkpoint_confirmed" | "event_confirmed" | "grouped_parallel" | "none"
occurred_at: datetime | null
iteration_count: int
default_visible: bool
```

`occurred_at` is the most recent safe application-event timestamp that can be joined to the node. Checkpoint task paths have stable order but no timestamp column, so checkpoint-only nodes return `null`. Repeated occurrences remain represented by `iteration_count` and the expanded evidence timeline rather than an unbounded timestamp array.

`GraphEdgeView`:

```text
source: str
target: str
relation: "sequence" | "parallel" | "join" | "loop" | "worker_boundary"
status: "traversed" | "available" | "not_visited"
```

`GraphEvidenceSummary` contains checkpoint, event, human-decision, and Job counts. It contains no raw payload.

The API returns:

- `404` when the Run does not exist;
- `200` with `evidence_status=unavailable` when the Run exists but has no readable root checkpoint history;
- `200` with `evidence_status=partial` when root history is readable but a required nested namespace or supporting fact source cannot be read completely;
- `200` with `evidence_status=available` when the relevant history sources are readable, regardless of whether the Run has intentionally skipped or not yet visited registered nodes;
- the existing bounded application error envelope when the history store cannot be read.

No layout coordinates are part of the API. The backend defines facts and semantic relationships; the frontend defines responsive placement.

## 8. Frontend Components

### 8.1 Shared Graph components

- `ExecutionPathStrip`: compact phase summary used by Run.
- `RunGraphView`: full Inspector container and selection owner.
- `GraphStageLane`: content-sized node layout for one stage.
- `GraphNode`: node shape, state text, keyboard behavior, and accessible description.
- `GraphEvidencePanel`: safe evidence for the selected node.
- `GraphTimelineFallback`: current application event timeline used when checkpoint evidence is unavailable or when the user selects the evidence view.

The components render semantic DOM with light SVG/CSS connectors. They do not implement pan, zoom, drag, free layout, or graph editing.

### 8.2 Focused page components

- Project Home extracts `ProjectFilters` and `RecentProjectList`.
- Brief extracts `AdvancedBriefFields`.
- Studio extracts `StudioToolbar` and `StudioInspector` while preserving the existing page state owner.
- Run reuses `ExecutionPathStrip` and keeps the existing approval/selection actions.

This is not a component-library rewrite. Files are split only where the unit has a clear contract and is independently testable.

### 8.3 Styling

The current dark graphite, cyan, purple, magenta, and mint palette remains. Typography uses the existing local/system font stack; technical evidence uses the existing monospace stack. The upgrade introduces a small token layer for work-page heading scale, surface, divider, status, focus, and spacing values. It reduces oversized work-page heroes and duplicated card elevation while preserving the larger About presentation.

## 9. Live Updates, States, and Accessibility

The existing Run SSE remains the invalidation signal. A relevant event invalidates/refetches the Graph query. No second event stream and no high-frequency polling are introduced.

Required Graph states:

- loading: structure-matched skeleton;
- queued: topology present, no confirmed nodes;
- active: latest confirmed path plus one active node;
- human wait: explicit approval/selection message and diamond node;
- worker wait: collapsed export/preview boundary and existing Job state;
- succeeded: static completed path with motion stopped;
- failed: last confirmed path, failed boundary, error code, and existing recovery action;
- partial: warning plus only confirmed nodes;
- unavailable: explicit evidence-unavailable message plus event timeline;
- not found: existing bounded not-found state.

Accessibility requirements:

- Node state must be available in text and shape, not color alone.
- Interactive nodes use native buttons with visible focus.
- The selected node controls an evidence region through accessible labelling/description.
- `prefers-reduced-motion` removes pulse and signal movement.
- The compact path may scroll horizontally at narrow widths, while full stages stack vertically.
- No fixed-height panel may clip labels, evidence, timeline tracks, or actions.
- Loading, empty, partial, error, and success messages state the next available action.

## 10. Security and Privacy

The history store allowlists task-path columns before returning application data. The endpoint forbids:

- raw checkpoint JSON, metadata JSON, blobs, channels, types, or serialized pending writes;
- prompts, messages, model reasoning, and chain-of-thought;
- approval assertions and bearer material;
- API keys and environment values;
- storage keys, absolute paths, and filesystem metadata;
- arbitrary event payload keys.

Unknown technical nodes may appear only as bounded technical names with the safe label `未映射节点` in developer evidence; their state and payload remain omitted. Unknown nodes do not silently inherit the meaning of a known registry entry.

## 11. Verification Contract

Verification matches portfolio scope rather than production hardening.

### 11.1 Backend

- unit tests for normal Generate execution, planning fallback, human approval, anonymous parallel candidates, Critic/Repair, repeated export, failure, partial evidence, missing checkpoints, and unknown nodes;
- one real PostgreSQL boundary that executes a minimal compiled LangGraph, verifies the pinned `checkpoint_writes.task_path` schema contract, and asserts real pull/push task paths reach the projection without selecting blobs or checkpoint payloads;
- API tests for Run not found, available/partial/unavailable evidence, stable semantic IDs, safe field omission, and deterministic ordering.

### 11.2 Frontend

- component tests for phase summary, content-sized nodes, natural wrapping, selected evidence, grouped parallel branches, collapsed export loop, keyboard selection, reduced-motion classes, fallback timeline, and error states;
- existing page tests updated for recent-first Home, advanced Brief preservation, terminal Run disclosure, and Studio timeline-first layout;
- one browser flow covering Brief → PlanApproval → CandidateSelection → Revision → Export → Graph Inspector;
- desktop and narrow visual checks for Home, Brief, Run, Inspector, and Studio.

There is no requirement to rerun the full S1/S7 failure matrix unless implementation changes Worker, Artifact, cancellation, approval, or Revision mutation contracts. A paid DeepSeek request is not required because the upgrade reads persisted orchestration evidence and changes presentation, not provider behavior.

## 12. Acceptance Criteria

The upgrade is accepted when:

1. a real Generate Run shows a compact live path and a full checkpoint-backed Inspector Graph;
2. the Graph distinguishes checkpoint-confirmed, event-confirmed, grouped-parallel, and unvisited evidence;
3. planning fallback, two candidate branches, HITL decisions, Critic/Repair, Revision materialization, and export repetition are visible without exposing sensitive state;
4. a Run without checkpoints never receives a fabricated Graph;
5. Inspector defaults to readable Chinese labels and exposes exact node names on demand;
6. Studio shows the arrangement timeline in the first desktop viewport and moves AI Edit into the inspector;
7. Home, Brief, and terminal Run follow the approved progressive-disclosure design;
8. the UI remains usable at 390 px, with keyboard focus and reduced motion;
9. no new production Graph, model mutation path, database migration, frontend Graph dependency, or content hash is added; and
10. focused unit, API, PostgreSQL, component, and one browser-flow verification pass.

## 13. Planned Task Boundaries

The implementation plan will decompose the work into independently testable tasks:

1. LangGraph history reader and Generate presentation registry.
2. Graph projection service and read API.
3. Shared Graph frontend components and Inspector integration.
4. Run live execution strip and SSE invalidation.
5. Project Home and Brief progressive disclosure.
6. Studio timeline-first restructuring.
7. Shared work-page polish, accessibility, browser flow, and documentation synchronization.

Tasks use RED/GREEN tests and narrow acceptance commands. Combined regression is required after the Graph slice, after the Studio slice, and at final acceptance. One independent review and at most one repair review are sufficient unless a current-path Critical or Important defect remains.

## 14. Non-goals

- No new Agent, supervisor, multi-agent framework, prompt, model provider, or tool router.
- No Graph editor, generic topology explorer, pan/zoom canvas, React Flow, G6, or WebGL visualization.
- No import/edit Graph registry in this slice.
- No changes to music generation, candidate scoring, Revision materialization, render/transcode/bundle behavior, or DAW commands.
- No deletion of historical/test Projects.
- No multi-tenant permissions, load/P95 certification, exhaustive concurrency, broad migration compatibility, long soak, or production alerting work.
- No source, repository, document, cache, checkpoint, or generated-artifact hashing for incidental verification.
- No required paid API call.
