# S7 Portfolio Release Design

**Date:** 2026-08-25

**Status:** Approved direction; implementation contract

**Stage:** Functionally complete MVP → portfolio productization and evaluation

**Covers:** MF-P01, MF-P02, MF-P09, MF-P13, MF-P15, MF-P16, MF-P18, MF-P20, MF-P21

## 1. Outcome

S7 turns the existing Motif Forge creative loop into a public, explainable portfolio product. It does not add another generation architecture or widen the DAW feature set. A reviewer must be able to:

1. complete or reopen a real Project;
2. inspect the finite Parent Graph journey, approvals, candidate evidence, usage, recovery, Revision, Jobs, and Artifacts;
3. download the already-generated delivery files from a formal Export page;
4. open a reproducible Eval report containing at least 96 internal cases and at least 50 public measured cases; and
5. run one deterministic no-key demonstration without a paid provider call.

The product remains local-first, single-user, instrumental-only, and portfolio-grade. Multi-tenant isolation, long soak tests, exhaustive checkpoint permutations, disaster recovery, and production alerting remain out of scope unless S7 reveals a current-path data, secret, cost, approval, idempotency, or recovery defect.

## 2. Current Stage and Bottleneck

The core product loop is implemented through S6:

```text
Brief → Plan/HITL → two Candidates → Critic/one Repair → A/B selection
→ immutable Revision → seven-step Export → Studio
→ manual commands/Undo/Redo → bounded AI Edit → Revision or Preview/HITL
```

The bottleneck is presentation and evidence, not missing orchestration. The current UI exposes the work itself but scatters delivery files, graph facts, model usage, errors, and evaluation evidence across separate APIs, tables, and developer scripts. S7 adds bounded read projections and portfolio-facing pages over those existing facts.

## 3. Product Surfaces

### 3.1 Export page

Route:

```text
/projects/{project_id}/exports/{revision_id}
```

States:

```text
loading
  ├─ not_found
  ├─ partial (safe Revision exists; Bundle incomplete or files unavailable)
  ├─ failed (authoritative export failure; safe completed files remain visible)
  └─ ready
       ├─ downloading one file
       └─ rehydrating one audio Artifact
```

The page shows:

- Revision and source Run identity;
- seven ordered export steps and their authoritative Job state;
- Master WAV, delivery MP3, four Stems, MIDI, canonical project JSON, credits/license/provenance/trace/export manifests;
- media profile, bytes, duration, availability, and checksum as existing protocol evidence;
- a clear distinction between playable audio, downloadable files, unavailable/rehydratable artifacts, and the logical Bundle;
- links back to Studio and the Run Inspector.

S7 does not rerender on page load and does not synthesize missing success. A partial export is explicitly represented.

### 3.2 Run Inspector

Route:

```text
/runs/{run_id}/inspect
```

States:

```text
loading → not_found | ready | terminal_failure
ready → overview | graph_timeline | decisions | usage | outputs
```

The Inspector is read-only. It projects:

- Run type/status/version, Parent Graph topology and state schema versions;
- ordered persisted AI Run events with stable sequence, event type, timestamp, safe payload summary, and error code;
- Plan provider/model/fallback and prompt/schema versions when present;
- candidate A/B, Critic, Repair, selection, Edit Preview, and approval facts already exposed by the authoritative Run projection;
- submitted model request count, token facts, cost status/value, and configured ceilings;
- Revision, Media Run, seven Jobs, six Audio Artifacts, Bundle, and failure/partial-success lineage;
- recovery facts derived from persisted replay/resume/cancel/retry events, without inventing distributed tracing spans.

Raw prompts, approval assertions, secrets, local storage paths, and full arbitrary event payloads are never returned.

### 3.3 Eval Lab and portfolio entry

Routes:

```text
/evaluation
/about
```

`/evaluation` loads one committed, deterministic public report generated from versioned local Eval assets. `/about` explains the architecture and links to a Project, Run Inspector, Export page, and Eval Lab. Both work without a model key.

The public report contains:

- dataset version and generation timestamp policy (`generated_at` is omitted for deterministic output);
- internal case count >= 96;
- public measured case count >= 50;
- counts by stage, behavior, style, and measurement class;
- schema validity, deterministic constraint pass, render/export contract pass, edit locality pass, recovery/replay pass, and measured failure labels;
- measured latency samples with P50/P95 only where the runner actually executes cases;
- provider request/token facts, distinguishing deterministic 0/0 cases from historical paid acceptance evidence;
- explicit `not_measured` for perceptual audio qualities not established by deterministic facts.

No headline metric may count rejected, unsupported, cancelled, or runtime-only cases as playable success. No structural or audio claim may be marked measured merely because a negative-constraint string exists.

## 4. Backend Read Contracts

### 4.1 Export projection

Endpoint:

```http
GET /api/v1/projects/{project_id}/revisions/{revision_id}/exports
```

Response data is `RevisionExportProjection`:

```text
project_id: UUID
revision_id: UUID
source_run_id: UUID | null
bundle: ExportBundleSummary | null
steps: tuple[ExportStepSummary, ...]       # exactly seven, canonical order
files: tuple[ExportFileSummary, ...]
status: partial | failed | ready
error_code: str | null
```

`ExportStepSummary` includes `step`, `job_id`, `status`, `artifact_id`, and `error_code`. `ExportFileSummary` includes stable public identity, filename, category, media type, byte size, availability, checksum, and a server-generated content URL. Storage keys are not returned.

The projection joins only existing Revision, AI Run, Media Run/Job, Audio Artifact, and Export Bundle facts. It validates that every returned Job/Artifact/Bundle belongs to the exact Project and Revision and that Artifact `source_job_id` belongs to the one selected Media Run. Cross-lineage rows are excluded and turn the projection into `failed` with `EXPORT_LINEAGE_INVALID` rather than becoming download links.

### 4.2 Bundle file delivery

Endpoint:

```http
GET /api/v1/export-bundles/{bundle_id}/files/{filename}
```

The server loads the authoritative Bundle row, requires `availability=available`, resolves its `storage_prefix` below the configured Artifact root, reads the canonical `export-manifest.json`, and allows only a normalized filename listed in that manifest. It rejects separators, traversal, symlinks, missing files, byte-size mismatch, and checksum mismatch. Existing protocol-required checksums are verified; no incidental repository or source hashing is added.

Audio Artifact content continues through the existing `/api/v1/audio-artifacts/{artifact_id}/content` route. Bundle delivery never exposes an absolute path.

### 4.3 Inspector projection

Endpoint:

```http
GET /api/v1/runs/{run_id}/inspect
```

Response data is `AIRunInspection`:

```text
run: existing AIRunData
versions: RunVersionSummary
timeline: tuple[InspectionEvent, ...]
decisions: tuple[DecisionSummary, ...]
jobs: tuple[InspectionJob, ...]
artifacts: tuple[InspectionArtifact, ...]
recovery: RecoverySummary
```

Timeline is capped at 200 persisted events and ordered by stable sequence. Safe payload summarization uses an allowlist per event family. Unknown payload keys are discarded. `RecoverySummary` reports counts of resume, replay/deduplication, retry-child, cancel, and terminal outcomes only when supported by persisted facts.

These are read APIs. They create no Run, checkpoint, Job, Artifact, usage entry, or audit mutation.

## 5. Frontend Contracts

The existing hand-written router gains `export`, `inspect`, `evaluation`, and `about` route variants. Pages use current TanStack Query/fetch helpers and generated OpenAPI types; no frontend dependency is added.

Desktop and narrow viewport requirements:

- the main information hierarchy remains readable at 390 px;
- wide timelines/tables use horizontal overflow rather than fixed page widths;
- download controls wrap and retain visible labels;
- loading, empty, partial, failed, unavailable, and ready states have text, not color alone;
- no fixed-height panel may hide evidence or actions;
- the Studio and Run pages receive small contextual links to Export and Inspector without changing their existing state machines.

## 6. Eval Architecture

S7 adds 24 lightweight, versioned cases to bring the internal inventory to at least 96. They are not 24 paid model calls. The cases cover:

- 8 export/read-lineage cases;
- 6 Run Inspector/event-redaction cases;
- 6 recovery, budget, approval, and idempotency cases;
- 4 portfolio navigation and error-state cases.

The report runner inventories existing S1–S6 assets, executes only deterministic evaluators, and writes bounded JSON plus Markdown. It records each case as one of:

- `measured_pass`;
- `measured_fail`;
- `expected_reject`;
- `not_measured`.

Only `measured_pass` and `measured_fail` enter measured denominators. Historical live DeepSeek evidence is reported separately from the current deterministic run. A paid S7 request is optional and requires the existing one-request persistent budget guard; it is not a release blocker because S2 already has paid provider acceptance evidence.

## 7. Demonstration Contract

One command, `scripts/run_s7_portfolio_smoke.py`, exercises the public HTTP path against the full Compose profile with the model key absent:

```text
create/reuse Project → Generate Run → fallback Plan → approval
→ two Candidates/Critic → selection → Revision → seven-step Export
→ Studio read → Run Inspector read → Export read/download → Eval report read
```

The smoke never calls Worker implementation functions directly. It polls public APIs and queue-produced PostgreSQL facts. It asserts 0 provider requests and 0 tokens for its Run, exact Revision/Job/Artifact/Bundle lineage, and physical download availability. It prints only bounded IDs, counts, status labels, and file sizes; never keys, prompts, assertions, storage paths, or raw event payloads.

A browser smoke covers the portfolio landing page, Run Inspector, Export page, Eval Lab, and a 390 px review pass. It reuses one deterministic fixture Project where practical and does not add a broad UI matrix.

## 8. Risk-Driven Hardening

S7 blocks only defects affecting the current public path or these boundaries:

- secrets/path/event-payload disclosure;
- paid-call budget or duplicate side effects;
- approval/selection/edit HITL bypass;
- incorrect Project/Revision/Run/Job/Artifact lineage;
- unsafe file delivery or traversal;
- inability to refresh/recover the public demo;
- falsified Eval denominators or metrics.

Representative tests cover one duplicate event, one restart/resume, one terminal render failure with safe partial output, one storage-unavailable projection, one version conflict, and one unsafe filename. Exhaustive concurrency, load/P95 capacity, all historical downgrade combinations, multi-tenant access control, full OTel deployment, and CI/CD release automation are explicitly deferred.

## 9. Task Boundaries

1. **Export read model and secure delivery API** — authoritative projection, exact lineage, safe file resolver, OpenAPI.
2. **Export page** — route, query state, files/steps, partial/error/mobile behavior, Studio/Run links.
3. **Run Inspector read model and API** — safe event summary, decisions, usage, jobs/artifacts, recovery facts.
4. **Run Inspector page** — overview/timeline/decision/usage/output presentation and mobile overflow.
5. **Eval inventory and report** — 24 S7 cases, >=96 internal inventory, >=50 public measured cases, deterministic JSON/Markdown.
6. **Portfolio entry and guided demo UX** — `/about`, `/evaluation`, contextual navigation, empty/error states.
7. **Deterministic product smoke and release gate** — full no-key Compose/browser path, representative hardening, docs synchronization.

Each persisted slice uses RED/GREEN unit tests plus one representative real PostgreSQL boundary. Combined regression runs after Tasks 2, 4, and 7. One independent stage review and at most one repair round are sufficient unless a Critical or current-path Important remains.

## 10. Non-goals

- No third production Graph, new agent role, vector database, or model router.
- No new Revision mutation path or bypass of PlanApproval/CandidateSelection/EditPreview.
- No professional mastering, VST, recording, collaboration, stem separation, or expanded piano-roll feature set.
- No multi-tenant permissions, cloud deployment, production alerting, long soak, disaster recovery, or broad P95 load certification.
- No generated hash inventory for source files, repository contents, docs, caches, or incidental outputs.
- No required paid API call.

## 11. Acceptance

S7 is complete when:

- Export and Inspector pages operate entirely from authoritative persisted facts and survive refresh;
- secure downloads cannot escape the Artifact root or cross Project/Revision lineage;
- Eval inventory is >=96, the public measured subset is >=50, and denominator semantics are truthful;
- the deterministic Compose and browser portfolio journeys finish with zero provider requests/tokens;
- current S1–S6 tests, Ruff, mypy, Web tests/build, OpenAPI regeneration, targeted PostgreSQL tests, and `git diff --check` pass;
- `PROJECT_GUIDE.md`, `IMPLEMENTATION_STATUS.md`, `NEXT_DEVELOPMENT_ROADMAP.md`, `TECH_EVOLUTION.md`, and `DECISION_LOG.md` accurately state that S7 is complete and distinguish deferred production hardening from delivered portfolio behavior.
