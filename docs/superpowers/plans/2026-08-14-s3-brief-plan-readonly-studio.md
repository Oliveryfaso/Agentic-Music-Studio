# S3 Brief/Plan and Read-only Studio Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task by task. Do not implement more than one Task in a session. Every Task starts with the listed RED test, receives one independent review, and stops after at most one scoped repair re-review.

**Goal:** Turn the accepted S2 Parent Graph into a browser workflow for Project creation, Brief submission, real Plan approval/replan, persistent progress recovery, canonical MP3 playback, read-only Arrangement Timeline, and multiple imports into one Project.

**Architecture:** Add bounded PostgreSQL-backed Project/Revision/Plan read models, keep commands in existing application boundaries, and consume all new HTTP contracts through generated OpenAPI types. The web app uses a small native History API shell, a fetch-based persistent SSE client, and `HTMLAudioElement` playback synchronized to a Canvas read-only timeline. Plan adjustment creates an immutable child Run in the existing `motif-forge-parent.v2`; it never mutates a Plan or creates another production Graph.

**Tech stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2 async, PostgreSQL, LangGraph, React 19, TanStack Query, TypeScript, Canvas, HTMLAudioElement, Vitest/Testing Library, Playwright library, Docker Compose.

**Design source:** `docs/superpowers/specs/2026-08-14-s3-brief-plan-readonly-studio-design.md`

**Source-of-truth guide SHA-256 at plan creation:** `827ec37f30d6c04473b4e39e8c5e099cef3e0b2b09e3eac5e78692e99c2dd56d`. Recheck before every Task handoff; if it changes, reconcile this plan with the guide before product work.

## Global constraints

- Active gate is S3 only. Covered requirements: `MF-P01`, browser portion of `MF-P02`, `MF-P03`, UI portion of `MF-P07`, playback/read-only precursor of `MF-P11`, recovery visibility of `MF-P13`, `MF-P18`, `MF-P20`, and browser authority/secrets portion of `MF-P21`.
- Preserve the final product contracts in `docs/PROJECT_GUIDE.md`; do not claim S4 Style Packs, S5 candidate repair, S6 editing, or S7 production hardening.
- Use only `motif-forge-parent.v2` for production. Do not create a third Graph, chain Graph APIs, move approval out of LangGraph, or let the browser/model create Revision, Job, Artifact, or Bundle facts.
- A model may create only a structured Plan. Deterministic code and existing application services own compilation, materialization, rendering, and export.
- Plan adjustment creates a child AI Run and a new immutable Plan; never update the old Plan in place.
- PostgreSQL remains authoritative. SSE and TanStack Query caches are projections only.
- New web API types come from `apps/web/src/generated/api-schema.d.ts`; do not handwrite duplicate DTOs.
- DeepSeek secrets remain environment-only. S3 does not add a paid acceptance and must be demonstrable with no API key.
- Follow the global “avoid hashes” rule. Reuse hashes only at existing integrity/idempotency/approval protocol boundaries; do not add UI-only hashes, cache hashes, or hashed route state.
- Do not add React Router or another UI dependency. Use a bounded native History API adapter.
- Do not add realtime multitrack audio. The canonical delivery MP3 and `HTMLAudioElement` are S3 playback truth; Tone.js editing remains S6.
- Desktop owns creation. At 390 px guarantee review, approval, recovery, and playback only.
- Tests are portfolio-level: one meaningful RED per Task, focused unit/component checks, one real PostgreSQL boundary where persistence changes, and one final deterministic browser smoke. Do not add load/P95, soak, multi-tenant, exhaustive fault permutations, or a browser/device matrix.
- Run the full Python/web/audio/static/Compose gates only in Task 8. Tasks 1–7 run the narrow commands listed under that Task.
- Preserve unrelated dirty files. Never print or inspect secret values. Do not rebuild Docker per Task.

## Frozen page state machine

The implementation must use these business phases; display labels may be localized without changing semantics:

| Surface | States |
|---|---|
| Project Home | `booting -> empty | ready | load_error`; create mutation is `creating_project -> ready | mutation_error` |
| Generate | `draft -> submitting -> queued -> planning -> waiting_approval -> materializing -> waiting_worker -> succeeded` |
| Generate terminals | `rejected`, `cancelled`, `failed`; `partial_success` is derived when a Revision exists but export/playback is incomplete |
| Plan actions | `waiting_approval -> approving | rejecting | adjusting`; adjustment routes to `child_queued -> child_planning -> child_waiting_approval` |
| SSE | `initial_read -> connecting -> live`; reconnect is `reconnecting -> replaying -> live`; terminal is `terminal_closed` |
| Playback | `loading -> ready -> playing | paused | ended`; recovery is `evicted -> requesting_rehydrate -> rehydrating -> ready`; errors are `missing | root_unavailable | media_error` |
| Multi-stem import | `select_files -> queue_ready -> uploading_file -> analyzing_file -> revision_committed -> next_file -> queue_complete`, with per-file retry/skip/stop |

The server status and read model always win over local reducer state. Store only the last SSE sequence and harmless UI preferences in browser storage.

## Frozen public API/read model

- `GET /api/v1/projects?limit=50 -> ProjectSummaryData[]`
- `GET /api/v1/projects/{project_id} -> ProjectWorkspaceData`
- `GET /api/v1/projects/{project_id}/revisions/{revision_id}/studio -> RevisionStudioData`
- `GET /api/v1/runs/{run_id}` adds nullable `RunPlanData` and bounded progress facts.
- `POST /api/v1/runs/{run_id}/replan` creates/replays one child Run from strict `PlanAdjustment`.
- Existing create/resume/cancel/retry/SSE/upload/import/rehydrate/audio-content contracts remain the command paths.

`PlanAdjustment v1` has nullable `target_bpm`, `target_key`, replacement `sections` (`name`, `bars`, `energy`), replacement `instrumentation` (`name`, `role`), and a bounded `note`; at least one change is required. `RunProgressData` has `phase`, ordered `completed_export_steps`, `total_export_steps`, `latest_event_sequence`, and nullable `error_code`. The remaining exact fields and security boundary are frozen in the design source. Any change to these routes or state names requires updating the design before implementation.

---

### Task 1: PostgreSQL-backed Project and Studio read models

**Files:**

- Create: `services/api/src/motif_forge/application/project_reads.py`
- Create: `services/api/src/motif_forge/infrastructure/persistence/project_reads.py`
- Create: `services/api/src/motif_forge/api/project_reads.py`
- Modify: `services/api/src/motif_forge/api/app.py`
- Test: `services/api/tests/unit/application/test_project_reads.py`
- Test: `services/api/tests/unit/api/test_project_reads.py`
- Test: `services/api/tests/integration/test_postgres_project_reads.py`

**Produces:** `ProjectSummary`, `ProjectWorkspace`, `RevisionStudio`, query protocol/adapter, three public GET routes.

**Consumes:** existing Project/Branch/Revision/AI Run/Artifact/Bundle rows, `ArrangementIR`, audio-content route, storage-root status.

- [ ] **Step 1: Write the RED contracts**

Cover only:

- list ordering and bounded limit;
- active branch head, latest/recoverable Run, and recent Revision projection;
- strict stored `ArrangementIR` validation;
- playable delivery MP3 selection and artifact availability;
- no filesystem path or worker payload in serialized responses;
- 404 for wrong Project/Revision lineage.

- [ ] **Step 2: Capture RED**

```bash
.venv/bin/python -m pytest \
  services/api/tests/unit/application/test_project_reads.py \
  services/api/tests/unit/api/test_project_reads.py -q
```

Expected: collection fails because the read models/router do not exist.

- [ ] **Step 3: Implement the smallest query boundary**

Use a dedicated read protocol and PostgreSQL query adapter. Reuse existing tables; do not add a migration or general repository. Validate `RevisionRow.arrangement_ir` through `ArrangementIR.model_validate(..., strict=True)` before returning it. Choose `delivery-mp3.v1` for playback and expose IDs/metadata only.

Register the router in `api/app.py`; do not add its route bodies to that file.

- [ ] **Step 4: Run focused and real PostgreSQL acceptance**

```bash
.venv/bin/python -m pytest \
  services/api/tests/unit/application/test_project_reads.py \
  services/api/tests/unit/api/test_project_reads.py \
  services/api/tests/integration/test_postgres_project_reads.py -q
.venv/bin/ruff check \
  services/api/src/motif_forge/application/project_reads.py \
  services/api/src/motif_forge/infrastructure/persistence/project_reads.py \
  services/api/src/motif_forge/api/project_reads.py \
  services/api/tests/unit/application/test_project_reads.py \
  services/api/tests/unit/api/test_project_reads.py \
  services/api/tests/integration/test_postgres_project_reads.py
.venv/bin/mypy \
  services/api/src/motif_forge/application/project_reads.py \
  services/api/src/motif_forge/infrastructure/persistence/project_reads.py \
  services/api/src/motif_forge/api/project_reads.py
git diff --check
```

Expected: one real Project with two Revisions and one generated MP3 is projected correctly; wrong lineage is rejected; all narrow gates pass.

- [ ] **Step 5: Independent review and commit**

Review for authoritative joins, path/secret leakage, bounded result sizes, and accidental command behavior. Allow at most one scoped repair.

```bash
git add services/api/src/motif_forge/application/project_reads.py \
  services/api/src/motif_forge/infrastructure/persistence/project_reads.py \
  services/api/src/motif_forge/api/project_reads.py \
  services/api/src/motif_forge/api/app.py \
  services/api/tests/unit/application/test_project_reads.py \
  services/api/tests/unit/api/test_project_reads.py \
  services/api/tests/integration/test_postgres_project_reads.py
git commit -m "feat: expose project studio read models"
```

---

### Task 2: Plan projection and immutable child replan

**Files:**

- Modify: `services/api/src/motif_forge/agent/schemas.py`
- Modify: `services/api/src/motif_forge/domain/ai_runs.py`
- Modify: `services/api/src/motif_forge/application/ai_runs.py`
- Modify: `services/api/src/motif_forge/application/ports.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/ai_runs.py`
- Modify: `services/api/src/motif_forge/agent/generate.py`
- Modify: `services/api/src/motif_forge/worker/outbox.py`
- Modify: `services/api/src/motif_forge/api/ai_runs.py`
- Create: `evals/s3-plan-replan-v1.json`
- Test: `services/api/tests/unit/agent/test_generate_replan.py`
- Test: `services/api/tests/unit/application/test_ai_run_replan.py`
- Test: `services/api/tests/unit/api/test_ai_run_replan.py`
- Test: `services/api/tests/integration/test_postgres_ai_run_replan.py`
- Test: `services/api/tests/eval/test_s3_replan_eval.py`

**Produces:** `RunPlanData`, strict `PlanAdjustment`, `/replan`, child Run lineage, adjusted planning input in the existing Parent Graph.

**Consumes:** persisted Plan, existing create/idempotency/outbox/checkpoint contracts, `motif-forge-parent.v2` generate branch.

- [ ] **Step 1: Write the RED contracts**

Assert:

- `GET /runs/{id}` returns the strict persisted Plan and existing approval hash/version;
- valid BPM/key/instrument/section-energy adjustments create one child Run;
- original Run and Plan remain byte-for-byte/row-for-row unchanged;
- same key/body replays the child; changed body or stale version/hash conflicts;
- child planning reaches its own `waiting_approval` checkpoint through `motif-forge-parent.v2`;
- no Revision or media Job exists before child approval;
- unsupported style/meter still fails before a model request.
- the two-case S3 Eval records one valid adjustment and one stable stale-plan/invalid-adjustment failure label.

- [ ] **Step 2: Capture RED**

```bash
.venv/bin/python -m pytest \
  services/api/tests/unit/agent/test_generate_replan.py \
  services/api/tests/unit/application/test_ai_run_replan.py \
  services/api/tests/unit/api/test_ai_run_replan.py -q
```

Expected: missing `PlanAdjustment`, child replan service, and API route.

- [ ] **Step 3: Implement immutable replan**

Deterministically project the strict adjustment onto the parent Run's `CompositionBrief`: typed BPM/key/instruments replace their Brief fields; section order/energy directions and the bounded note become normalized preferences. Persist that derived Brief on the child Run. Do not add a migration, an adjustment hash, or a second mutable Plan representation. The reviewed Plan hash remains only to bind the replan action to the Plan the user saw. The HTTP transaction creates the child Run and canonical start outbox intent; it does not call the model synchronously.

Adapt the child's derived Brief into the existing planning subgraph. The reviewed Plan binds the replan action but is not mutable state. The new Plan passes the same strict schema/strategy validation and reaches the same Parent `PlanApproval` interrupt.

- [ ] **Step 4: Run the one real boundary**

```bash
.venv/bin/python -m pytest \
  services/api/tests/unit/agent/test_generate_replan.py \
  services/api/tests/unit/application/test_ai_run_replan.py \
  services/api/tests/unit/api/test_ai_run_replan.py \
  services/api/tests/integration/test_postgres_ai_run_replan.py \
  services/api/tests/eval/test_s3_replan_eval.py \
  services/api/tests/integration/test_generate_dispatcher.py -q
.venv/bin/ruff check \
  services/api/src/motif_forge/agent/schemas.py \
  services/api/src/motif_forge/domain/ai_runs.py \
  services/api/src/motif_forge/application/ai_runs.py \
  services/api/src/motif_forge/infrastructure/persistence/ai_runs.py \
  services/api/src/motif_forge/agent/generate.py \
  services/api/src/motif_forge/worker/outbox.py \
  services/api/src/motif_forge/api/ai_runs.py
.venv/bin/mypy \
  services/api/src/motif_forge/agent/schemas.py \
  services/api/src/motif_forge/domain/ai_runs.py \
  services/api/src/motif_forge/application/ai_runs.py \
  services/api/src/motif_forge/infrastructure/persistence/ai_runs.py \
  services/api/src/motif_forge/agent/generate.py \
  services/api/src/motif_forge/worker/outbox.py \
  services/api/src/motif_forge/api/ai_runs.py
git diff --check
```

Expected: one authoritative child Run reaches approval; replay produces no second child/model reservation; original Plan remains unchanged.

- [ ] **Step 5: Independent review and commit**

Review specifically for a hidden second Graph, in-place Plan mutation, model call before ledger/outbox delivery, lost lineage, and hashes without a protocol need. Allow at most one repair.

```bash
git add services/api/src/motif_forge/agent/schemas.py \
  services/api/src/motif_forge/domain/ai_runs.py \
  services/api/src/motif_forge/application/ai_runs.py \
  services/api/src/motif_forge/application/ports.py \
  services/api/src/motif_forge/infrastructure/persistence/ai_runs.py \
  services/api/src/motif_forge/agent/generate.py \
  services/api/src/motif_forge/worker/outbox.py \
  services/api/src/motif_forge/api/ai_runs.py \
  evals/s3-plan-replan-v1.json \
  services/api/tests/unit/agent/test_generate_replan.py \
  services/api/tests/unit/application/test_ai_run_replan.py \
  services/api/tests/unit/api/test_ai_run_replan.py \
  services/api/tests/integration/test_postgres_ai_run_replan.py \
  services/api/tests/eval/test_s3_replan_eval.py
git commit -m "feat: add immutable plan replan runs"
```

---

### Task 3: Generated web API boundary and persistent Run stream

**Files:**

- Modify: `apps/web/src/shared/api.ts`
- Create: `apps/web/src/shared/openapi.ts`
- Create: `apps/web/src/features/projects/projectApi.ts`
- Create: `apps/web/src/features/generate/generateApi.ts`
- Create: `apps/web/src/features/generate/runEvents.ts`
- Create: `apps/web/src/features/generate/runState.ts`
- Regenerate: `apps/web/src/generated/api-schema.d.ts`
- Test: `apps/web/src/features/projects/projectApi.test.ts`
- Test: `apps/web/src/features/generate/generateApi.test.ts`
- Test: `apps/web/src/features/generate/runEvents.test.ts`
- Test: `apps/web/src/features/generate/runState.test.ts`

**Produces:** generated aliases, Project/Run query and command functions, fetch-SSE replay client, frozen UI state reducer.

**Consumes:** Task 1/2 OpenAPI, existing shared HTTP error/envelope behavior.

- [ ] **Step 1: Write RED state/API tests**

Cover:

- exact generated response types compile without handwritten copies;
- `Last-Event-ID` header is sent from the stored sequence;
- duplicate/out-of-order events do not regress the reducer;
- authoritative GET replaces local phase after reconnect;
- terminal GET closes reconnect attempts;
- failure with `revision_id` derives `partial_success`;
- stale action conflict triggers a Run reload.

- [ ] **Step 2: Capture RED**

```bash
npm run test:web -- \
  apps/web/src/features/projects/projectApi.test.ts \
  apps/web/src/features/generate/generateApi.test.ts \
  apps/web/src/features/generate/runEvents.test.ts \
  apps/web/src/features/generate/runState.test.ts
```

Expected: the feature clients/reducer do not exist.

- [ ] **Step 3: Generate types and implement clients**

Expose or extract only the reusable HTTP envelope/error helper from `shared/api.ts`; keep Import behavior unchanged. Use `ReadableStream` parsing so the browser can set `Last-Event-ID`. Persist only the last integer sequence under a per-Run `sessionStorage` key.

```bash
npm run generate:openapi
cp apps/web/src/generated/api-schema.d.ts /private/tmp/s3-api-schema.d.ts
npm run generate:openapi
cmp /private/tmp/s3-api-schema.d.ts apps/web/src/generated/api-schema.d.ts
```

- [ ] **Step 4: Run focused acceptance**

```bash
npm run test:web -- \
  apps/web/src/shared/api.test.ts \
  apps/web/src/features/projects/projectApi.test.ts \
  apps/web/src/features/generate/generateApi.test.ts \
  apps/web/src/features/generate/runEvents.test.ts \
  apps/web/src/features/generate/runState.test.ts
npm run build:web
git diff --check
```

Expected: tests/build pass and OpenAPI regeneration is stable.

- [ ] **Step 5: Independent review and commit**

Review for duplicate DTOs, EventSource/custom-header mismatch, client-authoritative phases, leaked model settings, and regressions in Import API helpers.

```bash
git add apps/web/src/shared apps/web/src/features/projects \
  apps/web/src/features/generate apps/web/src/generated/api-schema.d.ts
git commit -m "feat: add typed project and run clients"
```

---

### Task 4: Application shell and Project Home

**Files:**

- Modify: `apps/web/src/app/App.tsx`
- Create: `apps/web/src/app/routes.ts`
- Create: `apps/web/src/app/AppShell.tsx`
- Create: `apps/web/src/app/StatusBanner.tsx`
- Create: `apps/web/src/features/projects/ProjectHomePage.tsx`
- Create: `apps/web/src/features/projects/ProjectCard.tsx`
- Modify: `apps/web/src/styles.css`
- Test: `apps/web/src/app/routes.test.ts`
- Test: `apps/web/src/features/projects/ProjectHomePage.test.tsx`

**Produces:** native URL routing, shared shell, Project list/create/open/recover UI, empty/loading/error states.

**Consumes:** Task 3 clients and current TanStack Query provider.

- [ ] **Step 1: Write the Project Home RED journey**

One Testing Library test must cover loading, no Projects, create, populated cards, open latest Revision, recover nonterminal Run, and retry after API error. A route unit test covers parse/navigate/back-forward for all five frozen routes.

- [ ] **Step 2: Capture RED**

```bash
npm run test:web -- \
  apps/web/src/app/routes.test.ts \
  apps/web/src/features/projects/ProjectHomePage.test.tsx
```

Expected: shell/routes/Home do not exist.

- [ ] **Step 3: Implement shell and responsive Home**

Use semantic DOM, visible focus, text plus color for statuses, and content-driven heights. Preserve the deep graphite/cyan/purple/magenta visual language. Long names wrap or ellipsize inside cards without page overflow.

- [ ] **Step 4: Run focused acceptance**

```bash
npm run test:web -- \
  apps/web/src/app/routes.test.ts \
  apps/web/src/features/projects/ProjectHomePage.test.tsx \
  apps/web/src/features/import-review/ImportReviewPage.test.tsx
npm run build:web
git diff --check
```

Expected: routes/Home pass and existing Import Review still renders.

- [ ] **Step 5: Independent review and commit**

Review empty/loading/error/overflow, keyboard navigation, route restoration, and accidental Import removal.

```bash
git add apps/web/src/app apps/web/src/features/projects apps/web/src/styles.css
git commit -m "feat: add project home shell"
```

---

### Task 5: Brief, Plan Review, approval, and replan pages

**Files:**

- Create: `apps/web/src/features/generate/BriefPage.tsx`
- Create: `apps/web/src/features/generate/BriefForm.tsx`
- Create: `apps/web/src/features/generate/RunPage.tsx`
- Create: `apps/web/src/features/generate/PlanReview.tsx`
- Create: `apps/web/src/features/generate/RunProgress.tsx`
- Create: `apps/web/src/features/generate/PlanAdjustmentForm.tsx`
- Modify: `apps/web/src/app/AppShell.tsx`
- Modify: `apps/web/src/styles.css`
- Test: `apps/web/src/features/generate/BriefPage.test.tsx`
- Test: `apps/web/src/features/generate/RunPage.test.tsx`

**Produces:** browser Brief creation, real Plan display, approve/reject/cancel/retry/replan, SSE progress and refresh recovery.

**Consumes:** existing AI Run actions plus Task 2/3 Plan/replan/replay contracts.

- [ ] **Step 1: Write two RED user journeys**

The tests must prove:

1. invalid Brief stays local; valid Synth Ambient Brief creates a Run and navigates to it;
2. Run first reads authoritative state, replays events, displays structure/BPM/key/instruments/energy/references/fallback, approves with the server version/hash, and opens Studio on success;
3. adjustment creates/navigates to a child Run while the old Plan remains visible;
4. reject/cancel/failure/partial success/stale conflict render safe actions;
5. 390 px markup keeps primary review/actions accessible without relying on hover.

- [ ] **Step 2: Capture RED**

```bash
npm run test:web -- \
  apps/web/src/features/generate/BriefPage.test.tsx \
  apps/web/src/features/generate/RunPage.test.tsx
```

Expected: pages and components do not exist.

- [ ] **Step 3: Implement the Agent-facing workflow**

Do not simulate progress with timers. Render the server phase/event facts. Keep the approval actor/assertion as explicit user intent, but never persist the raw assertion in browser storage. Treat fallback Plan as visibly labeled and approval-required.

On refresh: GET authoritative Run, then replay SSE from stored sequence. On terminal success: fetch Project/Studio read model rather than inferring artifact IDs from events.

- [ ] **Step 4: Run focused acceptance**

```bash
npm run test:web -- \
  apps/web/src/features/generate/BriefPage.test.tsx \
  apps/web/src/features/generate/RunPage.test.tsx \
  apps/web/src/features/generate/runEvents.test.ts \
  apps/web/src/features/generate/runState.test.ts
npm run build:web
git diff --check
```

Expected: both browser-level component journeys pass with no network fixture bypass of public client functions.

- [ ] **Step 5: Independent review and commit**

Review specifically for bypassed PlanApproval, client-fabricated success, lost SSE recovery, inaccessible 390 px actions, and model/provider details exposed to the browser.

```bash
git add apps/web/src/features/generate apps/web/src/app/AppShell.tsx apps/web/src/styles.css
git commit -m "feat: add brief and plan review workflow"
```

---

### Task 6: Read-only Arrangement Studio and MP3 transport

**Files:**

- Create: `apps/web/src/features/studio/StudioPage.tsx`
- Create: `apps/web/src/features/studio/Transport.tsx`
- Create: `apps/web/src/features/studio/ArrangementTimeline.tsx`
- Create: `apps/web/src/features/studio/TrackHeaders.tsx`
- Create: `apps/web/src/features/studio/timelineProjection.ts`
- Create: `apps/web/src/features/studio/useAudioTransport.ts`
- Modify: `apps/web/src/app/AppShell.tsx`
- Modify: `apps/web/src/styles.css`
- Test: `apps/web/src/features/studio/timelineProjection.test.ts`
- Test: `apps/web/src/features/studio/StudioPage.test.tsx`

**Produces:** read-only Canvas timeline, DOM track headers/sections/status, play/pause/stop/seek, synchronized playhead, artifact recovery UI.

**Consumes:** `RevisionStudioData`, existing audio content/rehydrate endpoints, `ArrangementIR` timing facts.

- [ ] **Step 1: Write RED projection and playback tests**

Cover:

- tick-to-pixel and media-second mapping from PPQ/BPM/meter;
- ordered tracks/clips/sections and long-name overflow;
- play/pause/stop/seek calls the media element and updates accessible labels;
- `available`, `evicted`, `rehydrating`, `missing`, root unavailable, media error, empty tracks, and partial success;
- Canvas has a DOM text fallback; controls remain usable at 390 px.

- [ ] **Step 2: Capture RED**

```bash
npm run test:web -- \
  apps/web/src/features/studio/timelineProjection.test.ts \
  apps/web/src/features/studio/StudioPage.test.tsx
```

Expected: Studio modules do not exist.

- [ ] **Step 3: Implement read-only Studio**

Use a horizontally scrollable Canvas whose width derives from bars/zoom, not viewport. Use `requestAnimationFrame` only while playing; cancel it on pause/unmount. The MP3 `HTMLAudioElement` is the only clock. Track controls are display-only in S3; do not add fake mute/solo editing.

- [ ] **Step 4: Run focused acceptance**

```bash
npm run test:web -- \
  apps/web/src/features/studio/timelineProjection.test.ts \
  apps/web/src/features/studio/StudioPage.test.tsx \
  apps/web/src/features/generate/RunPage.test.tsx
npm run build:web
git diff --check
```

Expected: timeline/playback/recovery states pass; build has no fixed-height or overflow error introduced by types/styles.

- [ ] **Step 5: Independent review and commit**

Review timebase math, RAF/media cleanup, Canvas/DOM accessibility, horizontal timeline versus page overflow, and any accidental S6 editing behavior.

```bash
git add apps/web/src/features/studio apps/web/src/app/AppShell.tsx apps/web/src/styles.css
git commit -m "feat: add read-only arrangement studio"
```

---

### Task 7: Add multiple stems to one existing Project

**Files:**

- Modify: `apps/web/src/shared/api.ts`
- Modify: `apps/web/src/features/import-review/ImportReviewPage.tsx`
- Modify: `apps/web/src/features/import-review/ImportFlowPanel.tsx`
- Create: `apps/web/src/features/import-review/importQueue.ts`
- Modify: `apps/web/src/app/AppShell.tsx`
- Modify: `apps/web/src/styles.css`
- Test: `apps/web/src/shared/api.test.ts`
- Test: `apps/web/src/features/import-review/importQueue.test.ts`
- Test: `apps/web/src/features/import-review/ImportReviewPage.test.tsx`

**Produces:** Project-targeted upload/import functions and sequential multi-file queue with per-file analysis decision/retry/skip.

**Consumes:** current upload/import/analysis APIs and Project Workspace head refresh.

- [ ] **Step 1: Write the RED same-Project journey**

Assert that two files:

- reuse one `project_id` and active `branch_id`;
- do not call create Project when an existing target is supplied;
- upload/import sequentially;
- use the refreshed head Revision as the second base;
- stop and reload on Revision conflict;
- preserve single-file “create new Project” behavior;
- show independent progress/error/rights declarations per file.

- [ ] **Step 2: Capture RED**

```bash
npm run test:web -- \
  apps/web/src/shared/api.test.ts \
  apps/web/src/features/import-review/importQueue.test.ts \
  apps/web/src/features/import-review/ImportReviewPage.test.tsx
```

Expected: existing `uploadAndStartImport` always creates a Project and no queue exists.

- [ ] **Step 3: Split target selection from upload/import**

Introduce an explicit `ProjectTarget` argument for the shared upload/import path. Keep browser checksum because upload integrity requires it; do not add hashes to queue/UI state. Run one file at a time and reload the Project after each committed Revision.

- [ ] **Step 4: Run focused acceptance**

```bash
npm run test:web -- \
  apps/web/src/shared/api.test.ts \
  apps/web/src/features/import-review/importQueue.test.ts \
  apps/web/src/features/import-review/ImportReviewPage.test.tsx \
  apps/web/src/features/projects/ProjectHomePage.test.tsx
npm run build:web
git diff --check
```

Expected: both new-Project single import and existing-Project two-file queue pass.

- [ ] **Step 5: Independent review and commit**

Review branch-head refresh, raw Artifact immutability, checksum necessity, error isolation, mobile overflow, and accidental batch/concurrency complexity.

```bash
git add apps/web/src/shared/api.ts apps/web/src/features/import-review \
  apps/web/src/app/AppShell.tsx apps/web/src/styles.css
git commit -m "feat: import multiple stems into a project"
```

---

### Task 8: Deterministic browser acceptance and S3 closeout

**Files:**

- Create: `scripts/run_s3_browser_smoke.mjs`
- Create: `tests/test_s3_browser_smoke_contract.py`
- Modify: `package.json`
- Modify: `scripts/check_s1.sh`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/NEXT_DEVELOPMENT_ROADMAP.md`
- Modify: `docs/DECISION_LOG.md` only if implementation changed a frozen decision

**Produces:** reproducible no-key browser acceptance, S3 stage gate, truthful status closeout.

**Consumes:** public browser UI/API only, deterministic fallback planner, real PostgreSQL/Redis/workers/artifacts.

- [ ] **Step 1: Write the RED smoke contract**

The host contract test must require the smoke to:

- fail closed unless the live API container attests no DeepSeek key/model request path;
- use browser-visible controls and public HTTP only, never import Graph/application/worker execution functions;
- complete desktop `Project -> Brief -> Plan -> approve -> progress -> Studio -> play`;
- refresh once at `waiting_approval` or `waiting_worker` and prove the same Run/thread recovers;
- create a child replan Run and prove the old Plan remains readable;
- import two small fixtures to the same Project and prove the head advances;
- visit the Run/Studio at 390 px and assert no page-level horizontal overflow;
- report bounded IDs/counts/statuses without secrets or filesystem paths.

- [ ] **Step 2: Capture host RED**

```bash
.venv/bin/python -m pytest tests/test_s3_browser_smoke_contract.py -q
```

Expected: the S3 smoke/script entry does not exist.

- [ ] **Step 3: Implement one deterministic smoke**

Use the installed Playwright library from Node. Use the no-key deterministic planner; do not perform another paid model acceptance. Reuse small existing audio fixtures or generate deterministic fixture bytes inside the test boundary without adding a production dependency.

The smoke may wait for real workers, but it must not reproduce the S1/S2 failure matrix. One desktop journey plus one 390 px review/play/recovery check is sufficient.

- [ ] **Step 4: Run the combined host gates**

```bash
.venv/bin/python -m pytest services/api/tests/unit tests/test_s3_browser_smoke_contract.py -q
npm run test:audio
npm run test:web
npm run generate:openapi
cp apps/web/src/generated/api-schema.d.ts /private/tmp/s3-final-api-schema.d.ts
npm run generate:openapi
cmp /private/tmp/s3-final-api-schema.d.ts apps/web/src/generated/api-schema.d.ts
npm run build:web
.venv/bin/ruff check services/api/src services/api/tests tests scripts
.venv/bin/mypy services/api/src
git diff --check
```

Expected: existing Python/audio/web regressions and all S3 checks pass.

- [ ] **Step 5: Run one Compose/browser gate**

Use the repository's normal Compose startup/check script, then:

```bash
npm run smoke:s3
```

Expected bounded summary:

- one original Generate Run and one child replan Run;
- approval survives refresh and both Plans remain immutable/readable;
- original approved Run reaches `succeeded` with one Revision, seven media Jobs, six audio artifacts, and one Bundle;
- Studio loads the authoritative ArrangementIR and plays the delivery MP3;
- two imports share one Project and advance its branch head;
- provider requests/tokens remain zero;
- 390 px review/play/recovery has no page-level overflow.

- [ ] **Step 6: Update status documents truthfully**

Only after the browser gate passes:

- mark S3 complete in `IMPLEMENTATION_STATUS.md`;
- advance the single active gate to S4 in `NEXT_DEVELOPMENT_ROADMAP.md` and `PROJECT_GUIDE.md` if those files contain a current-stage pointer;
- record measured browser evidence and any explicitly deferred S7 hardening;
- do not claim editing, four Style Packs, two candidates, or full release readiness.

- [ ] **Step 7: Final independent review and commit**

Review the actual browser evidence against both acceptance journeys, confirm no secret/model call, and check that tests stayed portfolio-sized. Allow at most one repair.

```bash
git add scripts/run_s3_browser_smoke.mjs \
  tests/test_s3_browser_smoke_contract.py \
  package.json package-lock.json scripts/check_s1.sh \
  docs/IMPLEMENTATION_STATUS.md docs/NEXT_DEVELOPMENT_ROADMAP.md \
  docs/PROJECT_GUIDE.md docs/DECISION_LOG.md
git commit -m "feat: complete S3 browser composition workflow"
```

## Final S3 definition of done

- The browser, not an API script, completes Brief → PlanApproval → Parent Graph generation → playback → Project reopen.
- Plan adjustment creates an immutable child Run and still passes through the same Parent Graph approval.
- Refresh recovery uses authoritative GET plus persistent SSE replay from the last event sequence.
- Studio displays real stored ArrangementIR and plays the real delivery MP3 through the validated artifact route.
- Two imports enter one Project sequentially and use the latest branch head.
- Desktop creation and 390 px review/play/recovery work.
- No paid model call, secret exposure, third Graph, direct Revision write, fake progress, or S6 editing is introduced.
- Focused tests, one real PostgreSQL boundary per changed persistence slice, one deterministic browser smoke, full static/build gates, and one independent final review pass.
- Deferred load, P95, multi-tenant, broad fault, and browser matrices remain recorded for S7 rather than being pulled into S3.
