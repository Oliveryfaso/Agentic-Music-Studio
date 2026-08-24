# S6 Lightweight DAW and AI Selection Editing Design

> **Stage:** S6 — the only active product gate after accepted G0–S5
> **Mode:** Portfolio Engineering Mode
> **Status:** Approved design, ready for implementation planning
> **Date:** 2026-08-24

## 1. Goal

Turn the existing read-only Arrangement Studio into a lightweight, desktop-first editing workspace and add bounded AI selection editing without weakening the single Parent Graph, immutable Revision, Preview/HITL, deterministic rendering, recovery, or cost contracts.

S6 completes these first-version requirements:

- `MF-P05`: generate or edit content in a selected range or new track without silently rewriting the whole song.
- `MF-P06`: auto-commit validated L0/L1 AI edits with Undo; route L2/L3 edits through Preview/HITL.
- `MF-P10`: use the reviewed local sound and preset catalog for AI timbre and melody work.
- `MF-P11`: provide the promised lightweight Timeline, Piano Roll, Mixer, and core clip operations.
- `MF-P13`: mount AI editing under the existing versioned Parent Graph as one finite edit Run/thread.
- `MF-P18`: add representative edit locality, impact-routing, recovery, and no-cost evaluation evidence.
- `MF-P20`: extend the restrained dark DAW visual language without sacrificing timeline readability.
- `MF-P21`: preserve pure/read-only model tools, locked regions, license boundaries, secret isolation, audit, and HITL.

## 2. Product stage and bottleneck

Motif Forge is an MVP moving from generation into editing. G0–S5 already provide Project creation, four Style Packs, Brief and Plan approval, two candidates, Critic and one bounded Repair, A/B selection, immutable Revision materialization, complete export, persistent recovery, and a read-only Studio.

The current bottleneck is not another generation strategy or more infrastructure. Users can create and hear a complete song but cannot shape it after generation. The existing domain already contains most `EditorCommand` types, command application, L0/L1 Revision commits, high-impact Preview persistence, and Parent Graph infrastructure. S6 must connect these facts into one user-facing editing loop instead of creating a parallel editor model.

## 3. Approved scope

### 3.1 Manual editing

The desktop Studio supports:

- Timeline selection, move, trim, split, duplicate, delete, loop, snap, zoom, and horizontal scrolling.
- Piano Roll note selection, add, move, resize, pitch, velocity, and delete.
- Track mute, solo, gain, pan, and three-band EQ.
- Clip gain, pan, fade-in, fade-out, and loop parameters.
- A local Sample Library / Preset Catalog browser using reviewed built-in Style Pack entries.
- Browser Draft undo/redo, save, unsaved state, conflict preservation, and committed Revision Undo.
- Branch and Revision identity visible throughout editing.

### 3.2 AI selection editing

The AI panel supports bounded requests to:

- change explicit track or clip parameters;
- add one melody, harmony, bass, rhythm, or texture track in the selected range;
- rewrite selected melody or accompaniment notes;
- extend a selected NoteClip while preserving adjacent continuity;
- generate or adjust a bounded `SynthPatchSpec`;
- select a reviewed local preset or sample from the built-in catalog.

The model receives only the target selection, adjacent 1–2 bar summaries, key/chord/rhythm facts, relevant track summaries, locked material, reviewed catalog summaries, and the user intent. It returns a local delta, never a replacement project.

### 3.3 Explicit non-goals

S6 does not add:

- external network sound search, download, or quarantine import;
- a new production Graph or permanent project thread;
- WebGL, professional automation editing, recording, VST hosting, or a complex tempo map;
- real-time pitch-preserving stretch while dragging;
- fine-grained mobile editing;
- repository-wide refactors, exhaustive concurrency permutations, load/P95 matrices, multi-tenancy, or full production observability.

External allowlist search and its license/import workflow remain an S7 or later decision. S6 can show the external-search capability as unavailable; it must not silently perform network search.

## 4. Chosen architecture

S6 uses one deterministic edit kernel with two entry paths.

```text
Manual entry
Timeline / Piano Roll / Mixer / Inspector
  -> Browser Draft of EditorCommand[]
  -> existing command-batch application service
  -> immutable Revision + Branch head advance

AI entry
Selection + bounded context + intent
  -> existing Parent Graph v2 / edit branch
  -> EditPatchProposal v1
  -> pure simulate_edit_patch
  -> actual diff + ChangeImpact policy
     -> L0/L1: atomic Revision + Undo
     -> L2/L3: CandidateSnapshot + Preview render
                -> HITL approve/reject
                -> approved immutable Revision
```

Manual edits do not create AI Runs. AI edits always create a finite Run/thread and return to the same Parent Graph after model work, Worker wait, HITL, retry, or failure. PostgreSQL remains the project fact source; the browser Draft and audio runtime remain discardable projections.

## 5. State separation

The frontend keeps four distinct layers:

1. **Server Revision** — immutable PostgreSQL `ArrangementIR` and authoritative Branch head.
2. **Browser Draft** — `base_revision_id`, `branch_id`, ordered `EditorCommand[]`, local history cursor, and conflict state.
3. **PreviewCandidate** — immutable candidate content plus mutable approval lifecycle for L2/L3 edits.
4. **Audio Runtime** — playback projection derived from a Revision plus Draft or Preview; it is never persisted as project truth.

The Draft stores commands, not a second arbitrary mutable IR. A pure reducer rebuilds the editable projection from Base IR plus commands. Ephemeral drag state, viewport, selection, dock state, and playback position are local UI state and do not enter `ArrangementIR`.

After a successful command-batch commit, the client:

1. reads the committed Revision as the new Base;
2. removes exactly the committed Draft commands;
3. preserves viewport and selection where their IDs remain valid;
4. reloads the authoritative server projection;
5. invalidates stale playback projections.

On `REVISION_CONFLICT`, the client freezes save, retains the local commands, displays the new server Base, and offers discard or manual replay. S6 does not automatically rebase creative commands.

## 6. Domain contracts

### 6.1 EditorCommand reuse and completion

All manual and AI changes use the existing `editor-command.v1` discriminated union. S6 completes only the command support needed by its user flows, following existing conventions:

- `duplicate_clip`
- three-band EQ through an allowlisted `set_track_param` representation
- any missing NoteClip operation required for Piano Roll interaction
- inverse-command generation for committed Undo

Existing commands such as `move_clip`, `trim_clip`, `split_clip`, `set_clip_param`, `set_track_param`, `add_notes`, `update_notes`, and `delete_notes` remain the canonical names. S6 must not add a whole-IR replacement command.

Continuous gestures collapse into one command at interaction end. Multi-selection operations expand into a stable ordered command batch. Browser-generated IDs are UUIDs carried in the command payload so local replay and server replay refer to the same objects.

### 6.2 EditPatchProposal v1

The public domain proposal contains:

- `schema_version = edit-patch-proposal.v1`
- `proposal_id`
- `project_id`
- `branch_id`
- `base_revision_id`
- `selection`
- `locked_ranges`
- ordered `commands`
- `rationale`
- `evidence_refs`
- `expected_effect`
- `predicted_change_impact`
- `confidence`
- prompt, provider/model, schema, policy, and graph version references

An agent proposal accepts only `actor_kind=agent` commands and all commands must remain inside the declared selection unless an allowlisted command explicitly creates a new target track scoped to that selection.

### 6.3 Pure simulation result

`simulate_edit_patch` has no database, queue, filesystem, Artifact, or render side effect. Given the authoritative Base IR and a validated proposal, it returns:

- candidate IR and its protocol-required content identity;
- structural diff entries;
- validation issues;
- actual affected track IDs and tick ranges;
- non-target preservation evidence;
- actual `ChangeImpact`;
- render recommendation for no render, affected-range audition, or full candidate preview.

Content hashing remains limited to existing Revision, Candidate, idempotency, Artifact, and non-target-preservation protocols. S6 adds no repository, source-file, document, cache, or generic generated-output hashing.

### 6.4 ChangeImpact v1 behavior

The final impact is `max(predicted, actual, policy_escalation)`.

- L0: explicit move, trim, split, gain, pan, fade, mute, solo, loop, or bounded EQ parameter change.
- L1: bounded note edits, quantization-like adjustment, or small selection-local additions that do not alter principal structure.
- L2: a new creative track, melody/harmony rewrite, clear timbre-role replacement, or musical extension.
- L3: form, Style Pack, principal theme, global tempo, or large-proportion replacement.

Locked-range contact fails with `LOCKED_RANGE_VIOLATION`; it is not converted into a Preview. Any changed non-target track/range fails with `EDIT_SCOPE_VIOLATION`. The model cannot lower either policy result.

## 7. Application and persistence boundaries

### 7.1 Manual commit

The existing command-batch endpoint remains the only public manual commit path. It requires `project_id`, `branch_id`, `base_revision_id`, ordered commands, a public idempotency key, and the local actor. The application service locks the Branch, checks its head, applies commands, computes actual impact, inserts the immutable Revision and command records, advances the Branch, and writes audit/idempotency facts in one transaction.

Public human command batches may commit only L0/L1. A browser request that deterministically evaluates to L2/L3 fails closed instead of bypassing Preview/HITL.

### 7.2 Committed Undo

`POST /api/v1/projects/{project_id}/undo` accepts the target `branch_id`, current `base_revision_id`, the committed command batch or Revision being undone, and an idempotency key. The application service derives inverse commands from authoritative before/after facts, revalidates them against the current Branch head, and creates a new Revision. It never moves the Branch pointer backward or deletes history.

Undo fails with a conflict if the target command cannot be safely inverted against the current head. Browser Draft undo/redo remains entirely local and does not call this endpoint.

### 7.3 AI edit application

The edit branch consumes the same Revision and project repositories as manual editing. L0/L1 proposals call the transactional command-batch commit internally with `author_kind=agent`. L2/L3 proposals create an immutable `CandidateSnapshot` and `PreviewCandidate` without advancing the Branch. Approval materializes a new Revision only after rechecking Preview status, Branch head, Base Revision, candidate identity, and approval assertion.

Any edit Run that reaches a model call uses the existing persistent Usage Ledger and BudgetGate. No-key fallback records zero provider requests and zero provider tokens.

## 8. Parent Graph edit branch

The edit branch is mounted under `motif-forge-parent.v2` and uses the current Parent State schema through bounded edit fields or a focused state extension. It does not introduce a third Graph.

```text
LoadEditContext
-> ValidateEditSelection
-> PredictChangeImpact
-> BuildBoundedEditContext
-> EditPlanner
-> ValidateEditPatchProposal
-> SimulateEditPatch
-> RouteActualChangeImpact
   -> L0/L1 CommitEditRevision
      -> RequestAffectedRangeRender when needed
      -> FinalizeRun
   -> L2/L3 PersistEditCandidate
      -> RequestEditPreviewRender
      -> WaitForEditPreview
      -> EditPreviewApprovalInterrupt
         -> approve: MaterializeEditCandidate -> FinalizeRun
         -> reject: RejectEditPreview -> FinalizeRun
         -> cancel: FinalizeRun
```

Node contracts:

- `LoadEditContext`: model none; loads the exact Project/Branch/Base Revision and safe summaries.
- `ValidateEditSelection`: model none; checks IDs, tick bounds, selection size, locked material, and supported target types.
- `PredictChangeImpact`: deterministic policy; the model cannot lower the result.
- `BuildBoundedEditContext`: pure projection; includes only selected and adjacent summaries plus reviewed local catalog facts.
- `EditPlanner`: DeepSeek non-thinking for explicit parameter edits; thinking mode only for bounded musical creation/rewrite. Output is strict `EditPatchProposal v1`.
- `ValidateEditPatchProposal`: deterministic schema, tool, permission, catalog/license, and budget validation.
- `SimulateEditPatch`: pure domain execution and actual diff calculation.
- persistence, render, approval, and finalization nodes are Application/Graph commands and are never model tools.

The edit branch checkpoints before any provider call whose replay could spend again, before Preview render fan-out, and before the approval interrupt. Stable operation IDs, outbox delivery dedupe, and the Usage Ledger prevent duplicate spend and duplicate Revision/Preview creation.

## 9. Deterministic fallback

S6 must remain demonstrable without a paid key. The no-key edit planner supports a bounded set of explicit intents:

- set track mute/solo/gain/pan;
- set clip gain/pan/fade/loop;
- choose a reviewed local preset by structured role/timbre tags;
- generate one stable, seed-based local motif or accompaniment pattern within the selected range.

Unsupported semantic rewrites return `EDIT_FALLBACK_UNSUPPORTED` and leave the project unchanged. Fallback does not pretend to understand unrestricted prose. The UI explains which deterministic edit forms are available.

At stage end, one optional paid DeepSeek edit acceptance may validate the structured proposal boundary and persistent usage facts. It is not required for every Task and must remain within a predeclared one-request budget.

## 10. Local sound catalog

S6 exposes reviewed built-in Style Pack preset/sample summaries through a read-only application/API projection. Each entry includes stable ID, Style Pack, instrument family, role, brightness/attack/texture tags, supported pitch range, preview availability when present, license summary, and provenance reference.

AI receives only matching compact catalog summaries. It can propose a catalog ID but cannot write files, download URLs, invent an asset ID, or alter license metadata. The server rechecks catalog membership and compatibility before simulation.

An empty catalog is a supported UI state. External search is visibly unavailable in S6 and does not trigger hidden network activity.

## 11. Public API and read models

S6 preserves existing envelopes, Problem Details, idempotency headers, and SSE replay semantics.

Required public resources:

- existing `POST /api/v1/projects/{project_id}/command-batches` for human Draft commit;
- new `POST /api/v1/projects/{project_id}/undo` for committed inverse Revision;
- existing AI Run creation extended with strict `run_type=edit` input;
- existing `GET /api/v1/runs/{run_id}` and SSE event stream extended with edit projection;
- existing Preview read/approve/reject contracts used for edit Preview lifecycle;
- Revision Studio read model extended with target Branch/Base identity, editable IR, command capabilities, relevant catalog summary, and edit Preview references.

The browser cannot call `commit_revision`, enqueue a render Job, provide a server path, or submit a Candidate Snapshot directly. OpenAPI remains the TypeScript DTO source.

Edit Run events include stable, safe summaries for:

- selection validated or rejected;
- planner started/completed/fallback;
- proposal validated;
- patch simulated and impact classified;
- revision committed;
- preview render queued/ready;
- approval required/approved/rejected;
- conflict, cancellation, and terminal failure.

Events contain IDs, ranges, impact, issue codes, usage, and Artifact references but never raw model reasoning, secrets, server paths, or full audio.

## 12. Studio UX

The existing Studio becomes an editable workspace:

```text
Transport / Project / Branch / Revision / Draft / Run status
Track Headers | Timeline Canvas | Selection Inspector / AI Panel
Bottom Dock: Piano Roll | Mixer | Sample Library | Run / Versions
```

### 12.1 Timeline

The Canvas draws the grid, sections, clips, selection, drag preview, and playhead. DOM focus proxies expose selected objects and keyboard actions. Pointer movement updates ephemeral drag state; pointer release produces one snapped command. Timeline remains horizontally scrollable and avoids fixed page heights.

### 12.2 Piano Roll

The Canvas draws the note grid, notes, selection, and velocity overlay. DOM controls or keyboard commands support precise pitch, start, duration, and velocity changes. It edits only NoteClips and presents an explicit empty/non-note selection state.

### 12.3 Mixer and Inspector

DOM controls provide mute, solo, gain, pan, and three-band EQ with accessible labels and numeric values. Clip Inspector separates pitch, EQ, fade envelope, and reverb/delay concepts. Continuous adjustments commit one command when interaction ends.

### 12.4 AI panel and Preview

Before submission, the panel shows selected tracks, bar/tick range, locks, and predicted approval behavior. L0/L1 progress resolves only when the server emits or projects the committed Revision. L2/L3 displays actual changed ranges, structural diff, rationale/evidence, and the real Preview Artifact state. Approval waits for a new Revision; it never relabels the Preview ID as a Revision.

### 12.5 Responsive and state behavior

Desktop is the creation surface. Below the desktop target, Inspector and Bottom Dock become mutually exclusive while Timeline overflow remains horizontal. Mobile continues to support playback and Preview approval only.

The UI explicitly handles empty project/track/catalog/selection, loading, unsaved Draft, API unavailable, SSE reconnect, Worker wait/failure, conflict, Preview unavailable/evicted/rehydrating/missing, cancellation, retry, and external Artifact Root unavailability. State-only Draft edits may continue when the root is unavailable, but render-producing actions remain disabled.

## 13. Error and recovery behavior

Representative stable error routes:

- `REVISION_CONFLICT`: preserve Draft or pending edit request; do not overwrite or auto-rebase.
- `LOCKED_RANGE_VIOLATION`: terminal validation failure with exact safe target summary; no Preview or Revision.
- `EDIT_SCOPE_VIOLATION`: terminal failure when actual non-target changes are detected.
- `CHANGE_IMPACT_ESCALATED`: internal route from auto-commit intent to Preview, not a public success claim.
- `EDIT_FALLBACK_UNSUPPORTED`: no-key request is outside the deterministic fallback allowlist.
- `CATALOG_ENTRY_NOT_FOUND` or `CATALOG_ENTRY_NOT_ALLOWED`: fail before persistence or render.
- `PREVIEW_NOT_READY`: remain waiting; do not approve without its required Artifact.
- provider timeout/429/5xx: existing bounded provider retry ownership and budget policy.
- provider 401/402/403: stop paid calls and require configuration repair.
- Worker failure: preserve Base Revision and any safe completed Preview Artifact refs; route through the same Parent Graph error path.
- cancel: stop future work, preserve already committed Revisions, and never convert a pending Preview into a Revision.

On process restart, canonical start/resume delivery reloads authoritative AI Run facts and the same Parent checkpoint. Repeated delivery cannot repeat provider spend, Preview creation, approval, or Revision commit.

## 14. Evaluation and verification

S6 follows Portfolio Engineering Mode. Each implementation Task gets focused RED/GREEN tests; persisted behavior gets one representative real PostgreSQL boundary. Combined regression runs every 2–3 Tasks and at the stage gate. S7 retains exhaustive crash, cancellation, concurrency, load, and release hardening.

The S6 representative Eval set covers at least:

- successful explicit L0 parameter edit;
- successful bounded L1 note edit;
- actual diff escalation from predicted L1 to L2;
- L2 melody rewrite requiring Preview/HITL;
- local catalog timbre selection;
- new bounded accompaniment track;
- locked-range rejection;
- non-target preservation rejection;
- Revision conflict and retained Draft;
- duplicate resume with no duplicate model spend or Revision;
- no-key supported fallback and unsupported fallback label;
- Preview reject/cancel leaving the Branch unchanged.

The deterministic baseline is direct human `EditorCommand` construction plus the no-key fallback parser. The Agent path must add value by translating bounded musical intent into a valid proposal and correct approval route; it is not considered better merely because it uses a model.

Measured outcomes:

- proposal schema validity;
- edit locality and locked-material preservation;
- actual ChangeImpact routing accuracy;
- L2/L3 unapproved commit count, target zero;
- idempotent provider request and Revision counts;
- render/Preview availability when required;
- user-visible conflict and recovery state;
- provider request/token facts and bounded latency.

One no-key browser journey is required at the stage gate. One paid DeepSeek edit call is optional and requires explicit runtime budget/secret attestation; keys and raw responses never enter logs, docs, fixtures, screenshots, or commits.

## 15. Implementation slicing guidance

The implementation plan should form independently reviewable vertical Tasks in this order:

1. edit domain proposal, simulation, locality, impact, and missing manual command semantics;
2. manual commit/Undo PostgreSQL boundary and public API;
3. browser Draft store and editable Timeline;
4. Piano Roll, Mixer, Inspector, and local Catalog UI/read model;
5. Parent Graph edit branch with deterministic fallback and persistent usage/recovery;
6. L0/L1 auto-Revision and L2/L3 Preview/HITL orchestration;
7. AI panel, Preview approval UX, SSE recovery, and conflicts;
8. representative Eval, no-key browser/Compose stage gate, documentation, and storage hygiene.

The implementation plan may split a Task when code inspection shows a real boundary, but it must not create separate manual and AI editing domain models or introduce infrastructure without a current S6 consumer.

## 16. Acceptance criteria

S6 is complete when runtime evidence demonstrates all of the following:

1. A user opens an existing generated Revision and edits it through Timeline, Piano Roll, Mixer, and Clip Inspector controls.
2. Browser Draft undo/redo works without mutating the server, and save creates one immutable Revision from ordered commands.
3. A committed Undo creates a new inverse Revision and does not move history backward.
4. A stale Base produces a visible conflict while preserving local Draft commands.
5. An AI explicit parameter edit is simulated, classified L0/L1, committed once, and can be undone.
6. An AI melody rewrite or creative new track is classified L2/L3, produces a real Preview, and cannot change Branch head before approval.
7. Approving the Preview creates exactly one new Revision; reject and cancel leave Branch head unchanged.
8. Locked material and non-target regions remain unchanged or the edit fails closed.
9. The local reviewed catalog can drive a bounded timbre or accompaniment edit without external network search.
10. Restart and duplicate delivery resume the same finite Parent thread without duplicate provider spend, Preview, or Revision.
11. The no-key end-to-end edit journey records zero provider requests and zero provider tokens.
12. Desktop editing, narrow layout overflow, empty/loading/error/conflict states, and mobile review/approval remain usable.
13. No third production Graph, direct model persistence, secret exposure, arbitrary path, or unapproved L2/L3 commit exists.

After acceptance, update `IMPLEMENTATION_STATUS.md` and `TECH_EVOLUTION.md`, run the scoped stage-end storage hygiene gate, create the S6 Git checkpoint, and leave S7 closed until S6 evidence is recorded.
