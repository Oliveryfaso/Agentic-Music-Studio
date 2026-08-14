# S3 Brief/Plan and Read-only Studio Design

Status: frozen for S3 implementation planning

Date: 2026-08-14

Target stage: S3 — Brief/Plan and Read-only Studio

Production topology: existing `motif-forge-parent.v2`

## 1. Decision summary

S3 turns the accepted S2 API workflow into the first complete browser product journey:

```text
Project Home
  -> New Composition Brief
  -> durable Parent Graph planning
  -> Plan Review / approve, reject, or adjust and replan
  -> deterministic Revision and export
  -> persistent progress recovery
  -> read-only Arrangement Timeline and final MP3 playback
```

The selected approach is a vertical Agent journey. The backend first exposes only the read models the browser needs; each page then connects to authoritative PostgreSQL facts and the existing AI Run/SSE contracts. This makes the portfolio demonstrate LangGraph state, human interrupt/resume, immutable plan lineage, worker handoff, and restart recovery rather than a fixture-driven UI.

S3 remains portfolio engineering, not production hardening. It requires focused RED tests, one real PostgreSQL boundary for new persistence queries, and one deterministic browser acceptance at the end. It does not repeat S1/S2 fault matrices, load tests, P95 work, multi-tenant isolation, or every possible viewport/status permutation.

## 2. Goals and requirement coverage

S3 must prove:

1. A user can create or open a Project without using an API client.
2. A user can submit a strict `CompositionBrief`, see the Parent Graph plan, and approve or reject the real persisted interrupt.
3. A user can adjust plan intent and create an immutable child replan Run without mutating the original Plan or creating another production Graph.
4. Refreshing or reconnecting restores the authoritative AI Run and replays persistent events from the last seen sequence.
5. A successful Revision opens in a read-only Studio with sections, tracks, clips, a synchronized playhead, and canonical MP3 playback.
6. Partial export, terminal failure, cancellation, stale Revision, unavailable Artifact Root, and artifact availability are visible and recoverable where the existing backend supports recovery.
7. Multiple imported stems can be added sequentially to the same Project and branch; each successful import advances the next base Revision.
8. Desktop supports the whole creation journey; 390 px supports review, playback, approval, and recovery without horizontal page overflow.

Covered requirements: `MF-P01`, browser portion of `MF-P02`, `MF-P03`, UI portion of `MF-P07`, playback/read-only precursor of `MF-P11`, recovery visibility of `MF-P13`, `MF-P18`, `MF-P20`, and browser secret/authority boundary of `MF-P21`.

## 3. Non-goals

S3 does not include:

- a third production Graph or API chaining between Graphs;
- a second composition candidate, Critic/Repair fan-out, or the three remaining Style Packs;
- piano-roll editing, clip drag/trim/split, mixer automation, realtime stem mixing, or AI local edits;
- direct in-place mutation of an immutable `CompositionPlan`;
- a new audio engine, renderer, export format, or model provider;
- browser access to the DeepSeek key, model settings, filesystem paths, or raw reasoning;
- direct browser writes to Revision, Job, Artifact, or Bundle tables;
- WebGL, a component-library rewrite, or fine mobile editing;
- exhaustive concurrency, crash, cancellation, browser, device, accessibility, or visual-regression matrices;
- another paid DeepSeek acceptance. S3 final acceptance uses the deterministic no-key planner path.

## 4. Alternatives considered

### 4.1 Selected: vertical Agent journey

Build the minimum read models, then connect Project Home, Brief/Plan, progress recovery, and Studio as end-to-end slices.

Why selected:

- demonstrates the accepted LangGraph workflow rather than hiding it behind mocks;
- discovers missing read boundaries early;
- keeps each task user-visible and reviewable;
- avoids building a general project/query platform before a real consumer exists.

### 4.2 Rejected: UI-first fixture prototype

This would produce screenshots quickly but would not prove PlanApproval, persistent SSE, worker progress, or refresh recovery. It is useful for a design spike, not sufficient as the S3 product gate.

### 4.3 Rejected: complete backend query platform first

A generic list/filter/search/permissions platform would exceed a personal portfolio's needs and delay the Agent journey. S3 uses bounded, purpose-built projections and defers pagination scale, multi-user authorization, and analytics queries.

## 5. Route and page model

S3 freezes these browser routes:

| Route | Page | Primary purpose |
|---|---|---|
| `/` | Project Home | list/create Projects, open latest Revision, recover recent Run |
| `/projects/:projectId/new-composition` | Brief | create a Generate AI Run on the active branch |
| `/runs/:runId` | Plan and Progress | review/approve/reject/replan and follow persistent progress |
| `/projects/:projectId/studio/:revisionId` | Read-only Studio | inspect ArrangementIR and play the delivery MP3 |
| `/projects/:projectId/import` | Import Review | add one or more selected files to the existing Project |

No router dependency is added for this bounded route set. A small typed History API adapter owns parse, navigate, and `popstate`; feature components do not parse URLs themselves. If later S6 routing genuinely outgrows this adapter, a router may be adopted then.

The existing Import Review remains available and is moved under the shared application shell rather than rewritten.

## 6. Frozen page state machines

### 6.1 Project Home

```text
booting -> empty
booting -> ready
booting -> load_error -> retry -> booting

empty -> creating_project -> ready
ready -> creating_project -> ready | mutation_error
ready -> opening_project
```

`ready` may contain an empty Project, a latest Revision, a recoverable nonterminal Run, or a terminal failed Run. Those are facts displayed on cards, not separate navigation systems.

### 6.2 Brief and Generate Run

```text
draft
  -> validation_error -> draft
  -> submitting -> queued -> planning -> waiting_approval
                                      -> failed | cancelled

waiting_approval
  -> approving -> materializing -> waiting_worker -> succeeded
  -> rejecting -> rejected
  -> adjusting -> child_queued -> child_planning -> child_waiting_approval

materializing | waiting_worker
  -> succeeded
  -> partial_success
  -> failed
  -> cancelling -> cancelled
```

`partial_success` is a UI projection, not a new `AIRunStatus`: a Revision exists but the run failed or one or more expected delivery artifacts are unavailable. The page must still offer “open Revision” when safe.

### 6.3 Connection and recovery

Connection state is orthogonal to business state:

```text
initial_read -> connecting -> live
live -> reconnecting -> replaying -> live
live | replaying -> terminal_closed
any -> offline_error -> retry -> initial_read
```

On page load the browser reads `GET /runs/{id}` first, then opens a fetch-based SSE stream with the stored `Last-Event-ID`. Event sequence is stored in `sessionStorage` only as a replay cursor. The server projection always wins; no client event log is treated as authoritative.

### 6.4 Artifact playback

```text
loading -> ready -> playing | paused | ended
loading -> evicted -> requesting_rehydrate -> rehydrating -> ready
loading -> missing
loading -> root_unavailable
ready | playing -> media_error
```

The S3 time authority is the final delivery MP3 in an `HTMLAudioElement`. Timeline playhead follows media time. Tone.js remains reserved for S6 realtime editing and is not introduced into this read-only path.

### 6.5 Existing-Project multi-stem import

```text
select_files -> queue_ready
queue_ready -> uploading_file -> analyzing_file
analyzing_file -> confirm | override | skip | cancel_file
confirm | override | skip -> revision_committed -> next_file
next_file -> uploading_file | queue_complete
any_file -> file_failed -> retry_file | skip_file | stop_queue
```

Files are processed sequentially. After each successful import the client reloads the Project read model and uses the new active branch head as the next `base_revision_id`. S3 does not add a parallel batch-import API.

## 7. Frozen API and read models

All new response types are defined by FastAPI/Pydantic and consumed through regenerated OpenAPI TypeScript declarations. New handwritten duplicate DTOs are prohibited.

### 7.1 Project reads

`GET /api/v1/projects?limit=50`

Returns `ProjectSummaryData[]`:

- `project_id`, `name`, `status`, `updated_at`;
- `active_branch_id`, `head_revision_id`;
- latest AI Run identity/status when present;
- a bounded `has_playable_revision` flag.

`GET /api/v1/projects/{project_id}`

Returns `ProjectWorkspaceData`:

- Project identity and active branch/head;
- up to 20 newest Revision summaries;
- up to 10 newest AI Run summaries;
- current recoverable Run, if any;
- storage-root availability as a safe enum, never a filesystem path.

`GET /api/v1/projects/{project_id}/revisions/{revision_id}/studio`

Returns `RevisionStudioData`:

- Revision identity, parent, source Run, reason, author, created time;
- schema-validated canonical `ArrangementIR` JSON;
- available delivery assets: artifact ID, quality profile, media type, availability, byte size, duration when known;
- logical Bundle ID when present;
- no local paths, signed secrets, or worker payloads.

The read adapter queries existing tables and validates stored `ArrangementIR` before returning it. It does not create a second persistence model or cache.

### 7.2 AI Run plan projection

`GET /api/v1/runs/{run_id}` keeps the existing `AIRunData` and adds a nullable `plan`:

```text
RunPlanData
  plan_id
  content_hash
  hash_version
  plan: CompositionPlan
  provider
  model
  fallback_reason
```

The content hash remains because approval and stale-plan protection require it. The browser must not invent any other hashes.

The response also exposes `RunProgressData`, derived from durable events/jobs:

- `phase`;
- ordered `completed_export_steps`;
- `total_export_steps` (seven for the current complete export);
- `latest_event_sequence`;
- nullable safe `error_code`.

Raw provider messages, reasoning, prompts, and worker payloads remain private.

### 7.3 Plan adjustment and replan

`POST /api/v1/runs/{run_id}/replan` accepts:

- `expected_version` and `expected_plan_hash`;
- a strict `PlanAdjustment`;
- `Idempotency-Key`.

The adjustment contract is frozen as:

```text
PlanAdjustment
  schema_version: "plan-adjustment.v1"
  target_bpm: 40..220 | null
  target_key: nonempty string <= 80 | null
  sections: 2..12 SectionAdjustment items | null
  instrumentation: 1..12 InstrumentAdjustment items | null
  note: string <= 500

SectionAdjustment
  name: nonempty string <= 80
  bars: 1..128
  energy: 0.0..1.0

InstrumentAdjustment
  name: nonempty string <= 80
  role: nonempty string <= 80
```

At least one field must change. Section bars must total 8..256. `null` means “keep the parent Brief intent”; an explicit list replaces that intent. Unknown fields and coercion are rejected.

The application deterministically projects the adjustment onto the parent Run's strict `CompositionBrief`: BPM, key, and instrumentation remain typed Brief fields; section order/energy directions and the bounded note become normalized preferences. It then creates or replays one child AI Run with `parent_run_id` set to the reviewed Run and the same Project, branch, and base Revision. The reviewed Plan hash binds the action, while the derived Brief is the child planning input. The same `generate` operation in `motif-forge-parent.v2` produces a new immutable Plan and reaches the same PlanApproval interrupt. The old Plan and Run remain unchanged. No schema migration is required.

The endpoint does not approve, create a Revision, enqueue media, or call the model inside the HTTP request. Duplicate key/body replays the same child; a changed body conflicts.

### 7.4 Existing commands retained

- `POST /api/v1/projects/{project_id}/ai-runs`
- `POST /api/v1/runs/{run_id}/resume`
- `POST /api/v1/runs/{run_id}/cancel`
- `POST /api/v1/runs/{run_id}/retry`
- `GET /api/v1/runs/{run_id}/events`
- existing upload/import/analysis/rehydrate/audio-content endpoints.

Approval continues to require the server-provided Plan hash and optimistic Run version. No browser code receives the DeepSeek key or can write a Revision directly.

## 8. Component boundaries

### 8.1 Backend

- A dedicated Project read router owns read endpoints; the already large `api/app.py` only registers it.
- A bounded query service and PostgreSQL adapter own joins/projections. Command UoWs remain unchanged.
- `api/ai_runs.py` owns public Run/Plan/replan contracts.
- The existing Parent Graph owns adjusted planning and child-run recovery. No new graph object is allowed.
- Existing artifact content and rehydration services remain the only path to audio bytes.

### 8.2 Frontend

- `app/` owns shell, route parsing, top-level query client, and navigation.
- `features/projects/` owns Project Home and project query hooks.
- `features/generate/` owns Brief, Plan Review, progress reducer, SSE replay, and approval/replan actions.
- `features/studio/` owns read-only timeline projection, Canvas drawing, DOM track headers, and MP3 transport.
- `features/import-review/` keeps its current review components and gains an existing-Project queue adapter.
- `shared/` owns the HTTP envelope/error helper and generated-schema aliases only.

Canvas renders the scale, sections, clips, and playhead. DOM renders controls, track names, status, focusable actions, and textual fallbacks.

## 9. Error and recovery behavior

- Validation errors stay on the Brief or adjustment form and do not create a Run.
- Model/fallback/worker errors display stable error codes and safe messages from the API.
- A stale Plan version/hash reloads the authoritative Run before allowing another action.
- SSE disconnect never changes the business phase; the UI marks connection state and retries from the last sequence.
- A terminal Run closes the stream after the authoritative projection is read.
- An evicted artifact offers the existing rehydrate action. `rehydrating` polls the authoritative projection. `missing` explains that the recipe/source is unavailable.
- An unavailable external root blocks playback/import with a recovery message; the UI does not expose or guess a path.
- A Revision conflict stops the import queue and reloads the new head rather than silently rebasing.

## 10. Portfolio-level verification policy

Required evidence:

- focused reducer/component tests for the frozen state machine;
- focused API tests for response validation and action conflicts;
- one real PostgreSQL integration for Project/Revision/Plan read projections and replan idempotency;
- existing S2 Parent Graph recovery tests remain green where touched;
- one deterministic no-key browser smoke for the two S3 journeys;
- one desktop viewport and one 390 px review/play/recovery viewport;
- OpenAPI regeneration is deterministic and web/Python type checks pass.

Explicitly deferred to S7 unless a current change breaks the contract:

- load/P95, soak, multi-tenant, broad browser matrix;
- exhaustive SSE disconnect positions and every Graph checkpoint permutation;
- every artifact-loss combination and full S1 worker fault matrix;
- pixel-perfect visual regression across devices;
- another paid DeepSeek call.

Each task starts with one meaningful RED contract, implements the smallest slice, runs its narrow gate, and receives one independent review with at most one repair round. Full workspace and Compose/browser gates run only at the final S3 task.

## 11. Acceptance boundary

S3 is complete only when a real browser can:

1. create a Project, submit a Synth Ambient Brief, observe planning, review the real Plan, approve it, follow durable progress, play the generated MP3, and reopen its read-only Studio after refresh;
2. adjust the reviewed plan intent and observe a new child Run/Plan without altering the original;
3. add at least two audio files sequentially to the same Project and see the branch head advance;
4. at 390 px, review/approve a Plan, recover a Run, and play a finished composition without page-level horizontal overflow.

Passing unit tests without these browser journeys is not S3 completion. Passing the browser journey does not claim S4–S7 features.
