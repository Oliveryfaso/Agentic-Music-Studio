# S2 Unified Generate Graph Design

Status: approved in conversation; written specification pending user review

Date: 2026-08-13

Target stage: S2 — Unified Generate Graph

Parent topology version: `motif-forge-parent.v2`

Primary operation: `generate`

## 1. Decision summary

S2 integrates the existing CompositionPlan workflow into the single production Parent Graph. It does not copy planning nodes, chain two Graph APIs, or introduce an unbounded autonomous agent.

The production path is:

```text
Create AI Run
  -> Validate Generate Request
  -> Adapt Parent State to Planning State
  -> CompositionPlan Planning Subgraph
  -> Validate Plan Against Synth Ambient Strategy
  -> Human Plan Approval
  -> Deterministic Synth Ambient Compiler
  -> Candidate + Audited Commands + Immutable Revision
  -> Storage Pressure Gate
  -> Canonical Master Render
  -> Four Canonical Stem Renders
  -> MP3 Transcode
  -> Logical Export Bundle
  -> Complete AI Run
```

DeepSeek produces only a structured `CompositionPlan`. Deterministic code converts that plan into executable musical commands and `ArrangementIR`. The S1 renderer and export chain remain the only audio production path.

For this S2 increment:

- `synth_ambient` is the only implemented style strategy.
- `minimal_electronic`, `classical_chamber`, and `jazz_harmony` fail with `STYLE_NOT_IMPLEMENTED` before any paid model call.
- A from-zero composition is always L3 and requires explicit human approval before any Revision or render job is created.
- DeepSeek failure or irreparable structured output routes to the deterministic fallback plan, then still waits for the same human approval.
- The live paid acceptance uses at most three DeepSeek calls and 12,000 total tokens, and stops after the first successful end-to-end result.

## 2. Goals

S2 must prove the following engineering properties:

1. One durable Parent Graph owns planning, approval, materialization, worker waits, recovery, and completion.
2. The LLM is constrained to an auditable planning role and cannot write files, emit PCM, or mutate project state.
3. All model outputs cross strict schemas and deterministic domain validators.
4. Human approval is a real persisted interrupt, not an actor string inserted by a smoke script.
5. The approved plan creates an immutable Revision only through the existing command and preview transaction boundary.
6. The final output reuses S1's canonical Master, four Stem, MP3, and logical Bundle contracts.
7. Restarts, duplicate delivery, retry, and cancellation do not duplicate model calls, Revisions, jobs, or artifacts.
8. Every user-visible run can be inspected through persistent status and event APIs.
9. One real DeepSeek call is validated without exposing the API key or model reasoning.

This slice covers `MF-P02`, `MF-P04`, the complete-song part of `MF-P05`, `MF-P07`, `MF-P13`, `MF-P15`, `MF-P16`, `MF-P17`, `MF-P18`, and the secrets/audit portion of `MF-P21`. It deliberately does not claim completion of `MF-P09`; the four Style Packs remain a final-release contract, while S2 implements only the first strategy.

## 3. Non-goals

S2 does not include:

- a new web composition page;
- direct text-to-audio generation;
- LLM-generated note arrays, raw MIDI bytes, sample paths, PCM, or DSP graphs;
- multiple arrangement candidates or fan-out generation;
- the other three style strategies;
- audio upload-to-generation fusion;
- autonomous tool loops;
- a new renderer, new synthesis engine, or new export format;
- online music-history research during a run;
- storing hidden model reasoning;
- changing the behavior of the S1 deterministic baseline.

## 4. Alternatives considered

### 4.1 Selected: planning subgraph inside Parent Graph

The existing Plan v3 nodes are refactored into a reusable planning-only subgraph. The Parent Graph invokes that subgraph through explicit state adapters and owns the single production approval node and every downstream side effect.

Benefits:

- one checkpoint lineage and one thread;
- no copied planning logic;
- one place for budgets, cancellation, retry, and terminal routing;
- durable interrupt/resume across the complete user task;
- the standalone Plan graph can remain a regression harness built from the same node factory.

### 4.2 Rejected: API chaining between two graphs

Calling a standalone planning API and then a Parent API creates two run identities, two checkpoint lineages, ambiguous cancellation, and fragile recovery at the handoff.

### 4.3 Rejected: copy Plan nodes into Parent Graph

Copying nodes makes prompt, validation, retry, and fallback behavior drift between standalone and production paths.

### 4.4 Rejected: one large agent node

A single agent node hides deterministic boundaries, makes restart behavior difficult to prove, and encourages the model to make decisions that belong in rules and domain services.

## 5. Component boundaries

### 5.1 LangChain

LangChain remains the model abstraction layer for:

- DeepSeek message construction;
- provider-independent structured generation;
- structured output and tool schema support where required;
- model metadata and token usage extraction.

LangChain does not own project state, retries for business validation, rendering, or persistence.

### 5.2 LangGraph

LangGraph owns:

- the single durable Parent topology;
- the planning subgraph;
- conditional routes;
- interrupts and resume;
- worker wait and resume;
- bounded repair and fallback;
- terminal state selection.

### 5.3 Deterministic domain and application services

Deterministic services own:

- request and style gating;
- plan-to-brief compatibility validation;
- plan-to-command compilation;
- command validation and audit;
- Candidate, Preview, Revision, and Branch transactions;
- storage estimates and pressure gating;
- media job creation and idempotency;
- rendering, transcoding, probing, and bundling.

### 5.4 PostgreSQL, Redis, and workers

- PostgreSQL is the source of truth for AI Run projections, events, approvals, usage, Revisions, jobs, and artifacts.
- The LangGraph PostgreSQL checkpointer stores compact orchestration state.
- Redis is delivery infrastructure, never the source of truth.
- The existing Graph/Resume dispatcher runs start and resume requests outside FastAPI requests.
- The existing Media Worker and Chromium Render Worker execute the S1 media chain.

No new Docker image is required. Existing service images may receive new process entry points or configuration only where necessary.

## 6. Parent Graph topology

The Parent Graph is versioned as `motif-forge-parent.v2`. Existing import, time-stretch, and rehydrate operations remain supported and unchanged except for shared infrastructure extracted safely for reuse.

The generate branch contains these conceptual nodes:

1. `ValidateGenerateRequest`
2. `CheckCancellation`
3. `PlanInputAdapter`
4. `CompositionPlanningSubgraph`
5. `ValidateStrategyCompatibility`
6. `PlanApproval`
7. `CompileSynthAmbientArrangement`
8. `MaterializeApprovedRevision`
9. `EstimateCompleteExport`
10. `StoragePressureGate`
11. `EnsureMediaRun`
12. `EnqueueNextRenderJob`
13. `WaitForMediaJob`
14. `CollectMediaArtifact`
15. `EnqueueMp3Job`
16. `EnqueueBundleJob`
17. `FinalizeGenerateRun`
18. `GenerateErrorRouter`
19. `GenerateCancelled`
20. `GenerateFailed`

The render scopes are intentionally sequential in S2:

```text
master -> pad stem -> melody stem -> bass stem -> rhythm stem -> mp3 -> bundle
```

The current worker concurrency is one, so graph fan-out would add queue and aggregation complexity without reducing local completion time. Parallel render fan-out can be introduced later only after worker capacity and artifact aggregation contracts justify it.

### 6.1 Explicit termination conditions

The generate branch terminates when one of these is true:

- logical Bundle succeeded;
- the user rejected the plan;
- the user cancelled the AI Run;
- an unrecoverable domain, storage, media, or persistence error occurred;
- the model call or token budget was exhausted and fallback could not produce a valid plan;
- the Graph recursion limit is reached as a final safety net.

There is no open-ended reflection loop.

## 7. State contracts and adapters

### 7.1 Parent state

`ParentGraphState v2` stores only JSON-serializable control state and IDs:

- identity: `run_id`, `thread_id`, `project_id`, `branch_id`, `base_revision_id`;
- operation: `generate` plus existing operation variants;
- input refs: normalized brief and brief hash;
- planning refs: persisted Plan Artifact/row ID, Plan summary/hash, provider result category, validation issues;
- approval: interrupt reference, decision, actor ID, assertion hash, timestamp;
- materialization refs: candidate, preview, revision, command batch;
- media refs: media run, current job, render scope cursor, artifact IDs;
- budget: model calls, total tokens, maximum calls, maximum tokens;
- control: phase, retry counters, cancellation flag, pending action;
- outcome: Bundle ID, status, terminal error code.

It never stores audio bytes, waveform arrays, model reasoning, full trace payloads, or file-system paths supplied by the model.

### 7.2 Planning state adapter

`PlanInputAdapter` maps the approved Parent fields into the planning subgraph state. `PlanOutputAdapter` accepts only:

- a schema-valid `CompositionPlan` or deterministic fallback plan;
- the Plan persistence reference, hash, and short summary;
- provider/model identifiers;
- call, token, and latency measurements;
- fallback reason or structured validation issues.

The adapter rejects unknown fields. Reducers are defined only for fields that genuinely aggregate; sequential fields use overwrite semantics.

The complete validated Plan is persisted in PostgreSQL before the planning subgraph returns. The Parent checkpoint stores its immutable reference, hash, and bounded summary rather than relying on a truncated summary for later compilation. The compiler reloads the Plan by ID and verifies the hash after resume.

### 7.3 Planning subgraph extraction

The Plan v3 implementation is reorganized around a reusable planning node factory:

```text
Validate Brief
  -> Composition Planner
  -> Validate Generic Plan
  -> optional one-time Repair Plan
  -> Deterministic Fallback when required
  -> Return Validated Planning Result
```

The production subgraph has no side effects and no approval interrupt. The Parent Graph owns the single approval node. The standalone Plan regression graph is rebuilt from the same factory and may append its existing approval/finalization nodes.

No planning node implementation is copied into `parent_graph.py`.

## 8. Generate request and style gate

The create request accepts:

- target project and branch;
- expected base Revision;
- instrumental composition brief;
- duration target;
- `style_pack`;
- mood and energy description;
- optional key, BPM, and instrument preferences;
- negative constraints;
- request idempotency key.

S2 applies these deterministic checks before Graph dispatch and again at the first node:

- project, branch, and base Revision exist and match;
- the request is instrumental;
- duration and text fields are bounded;
- the style is exactly `synth_ambient`;
- meter is 4/4 for this increment;
- no exact living-artist imitation request;
- the run budget is within server limits.

Unsupported style returns `STYLE_NOT_IMPLEMENTED`. Unsupported meter returns `METER_NOT_IMPLEMENTED`. Both occur before any DeepSeek call and do not create a model-usage row.

## 9. DeepSeek provider contract

### 9.1 Configuration

The Graph dispatcher reads:

```text
DEEPSEEK_API_KEY
DEEPSEEK_MODEL=deepseek-v4-flash
```

The key is never written to Graph state, logs, traces, event payloads, database rows, artifacts, `.env.example`, or Git. Readiness reports only whether the provider is configured.

### 9.2 Model role

DeepSeek receives:

- the normalized brief;
- the `synth_ambient` Style Pack summary;
- strict plan constraints;
- the required JSON schema;
- structured issues during the single repair attempt.

DeepSeek returns only a JSON `CompositionPlan`. It cannot invoke project mutation, shell, renderer, storage, or arbitrary retrieval tools.

The adapter uses DeepSeek JSON Output with a prompt that explicitly requests JSON. Thinking mode may be enabled, but `reasoning_content` is never persisted or returned to clients.

Official provider references:

- [DeepSeek models and pricing](https://api-docs.deepseek.com/quick_start/pricing)
- [DeepSeek JSON Output](https://api-docs.deepseek.com/guides/json_mode)

### 9.3 Retry and repair

- HTTP 429, timeout, and retryable 5xx failures are retried only inside the provider adapter with exponential backoff and jitter.
- The Graph does not stack another transport retry around the provider.
- Invalid structured output receives at most one schema or compatibility repair call.
- The live acceptance allows at most three upstream completion requests total and 12,000 input-plus-output tokens. Every request submitted to DeepSeek counts, including a transport retry and a repair request; the adapter cannot spend three attempts and then start a separate repair budget.
- When the budget is exhausted, the provider returns a typed result; it does not throw an unclassified exception into the Graph.

### 9.4 Fallback

Provider unavailability, retry exhaustion, malformed output after repair, or budget exhaustion routes to the deterministic fallback planner. The fallback result:

- must pass the same `CompositionPlan` schema;
- must pass the same brief and strategy compatibility validators;
- is clearly marked `fallback_used=true` with a reason code;
- still requires human approval;
- never silently impersonates a DeepSeek result.

## 10. Plan validation and synth ambient strategy

### 10.1 Generic validation

The planning subgraph validates:

- schema version;
- BPM and duration bounds;
- 4/4 meter;
- key and mode;
- contiguous, non-overlapping sections;
- section lengths summing to the declared duration;
- bounded energy values;
- valid instrumentation and roles;
- prohibited content and unsupported requests.

### 10.2 Brief compatibility

The Parent strategy validator additionally proves:

- planned duration matches the brief within the documented tolerance;
- explicit BPM and key requests are honored;
- negative constraints are represented;
- the plan exposes the four supported roles: pad, melody, bass, rhythm;
- each role can be mapped to a licensed built-in synth preset;
- every section can be compiled without inventing unsupported assets.

Compatibility issues may trigger the one allowed repair call. Remaining issues route to fallback or a typed terminal error.

### 10.3 Deterministic compiler

S2 adds a new plan-driven Synth Ambient compiler. It does not alter `build_s1_composition`, which remains the S1 baseline.

The compiler consumes the approved plan and produces:

- a normalized PatternSpec per supported role and section;
- deterministic, bounded editor commands;
- an `ArrangementIR` with PPQ time coordinates;
- provenance referencing the Plan hash, compiler version, Style Pack version, and deterministic seed.

The compiler uses plan BPM, key/mode, sections, and energy curve. It maps them through versioned deterministic rules for:

- scale degrees and chord functions;
- pad voicing and voice leading;
- bass root and approach patterns;
- melody register, density, and motif variation;
- rhythm density and section transitions;
- fades and supported synth parameters.

It supports the key/mode vocabulary admitted by the Plan schema through deterministic interval maps. It never asks the LLM to output thousands of `NoteEvent` objects.

The same Plan hash, compiler version, seed, and Style Pack version must produce the same command payload and Arrangement hash.

## 11. Human approval and materialization

`PlanApproval` is the only user interrupt in S2 generation.

Its resume payload requires:

- `decision`: `approve` or `reject`;
- authenticated `actor_id`;
- `approval_assertion` of at least 16 characters;
- the expected interrupt or Plan hash;
- optional bounded note.

The approval is persisted before materialization. The Graph must verify that the resumed Plan hash matches the waiting interrupt.

On rejection:

- the AI Run becomes `rejected`;
- no Candidate, Preview, Revision, media job, or artifact is created.

On approval:

1. the deterministic compiler creates bounded editor commands;
2. `CreateCommandPreview` persists the Candidate with `source_run_id` and complete command audit;
3. the previously persisted approval assertion authorizes `DecidePreview(APPROVE)`;
4. the existing transaction creates the immutable Revision and advances the Branch using optimistic concurrency;
5. a Revision conflict fails closed and requires an explicit retry based on the new head.

There is no hidden direct write to the project JSON and no second synthetic approval.

## 12. Complete render and export chain

S2 extracts the successful S1 orchestration from the smoke script into idempotent application services callable by the Parent Graph.

For the approved Revision, it creates or reuses:

- one canonical Master WAV;
- one canonical Stem WAV for each of pad, melody, bass, and rhythm;
- one validated MP3 derived from the Master;
- one logical Export Bundle containing immutable references and manifests without copying audio bytes.

Every render job recompiles or verifies the canonical AudioGraph from the referenced immutable Revision. Artifact lineage includes project, Revision, Arrangement hash, render scope, source job, profile, checksum, and storage location.

Job idempotency keys derive from:

```text
generate_run_id + revision_id + job_kind + render_scope + profile_version
```

The Parent state stores only job and artifact IDs. Existing Worker contracts continue to provide:

- storage pressure checks;
- cancellation polling;
- bounded retry for retryable infrastructure failures;
- cross-filesystem safe atomic promotion;
- media receipt validation;
- immutable content-addressed outputs;
- fail-closed divergent completion handling.

## 13. Persistence model

S2 introduces a first-class `ai_runs` projection instead of overloading `MediaRun`, whose invariant assumes a waiting media job.

The new migration, expected to be `0013`, adds at minimum:

### 13.1 `ai_runs`

- ID, project, branch, and base Revision;
- Parent thread ID and topology/state versions;
- operation and status;
- normalized brief JSON and hash;
- Plan JSON or Plan summary plus hash;
- provider/model and fallback category;
- budget limits and consumed calls/tokens;
- approval actor, assertion hash, decision, and timestamp;
- Candidate, Preview, Revision, Media Run, and Bundle refs;
- terminal error code and retryable flag;
- parent run ID for an explicit retry lineage;
- optimistic version and timestamps.

The raw approval assertion is stored only where the existing audit contract requires it; otherwise a salted hash and bounded audit summary are preferred.

### 13.2 `composition_plans`

The full validated Plan is an immutable auditable input to the compiler and is not reconstructed from event text. It stores:

- Plan ID, AI Run ID, schema version, and canonical hash;
- normalized Plan JSON;
- provider/model or deterministic fallback provenance;
- prompt/schema/Style Pack versions and deterministic validation result;
- usage reference and creation timestamp.

The compiler must load this row by ID and verify its canonical hash before generating commands. A Plan row is created at most once for each accepted planning result through an idempotency key derived from Run ID and Plan hash.

### 13.3 `ai_run_events`

Events use a monotonic database sequence suitable for SSE replay and contain:

- event sequence and event ID;
- AI Run ID;
- event type and phase;
- bounded JSON payload;
- timestamp.

Events never contain the API key, hidden reasoning, raw audio, or unbounded model responses.

### 13.4 Model usage and cost truthfulness

Usage records store provider-reported input, output, cache, and total tokens when available. Cost must not be recorded as zero merely because it is unknown.

The persistence contract distinguishes:

- `cost_status=known` with a computed microusd value and pricing version;
- `cost_status=unknown` with nullable cost;
- `cost_status=not_applicable` for deterministic fallback without a paid call.

If the current telemetry column cannot express this, migration `0013` must evolve it without falsifying historical records.

## 14. API and SSE contracts

S2 adds API-level orchestration without a new web page.

### 14.1 Create

`POST /api/v1/projects/{project_id}/ai-runs`

- requires `Idempotency-Key`;
- validates project/branch/base Revision and the pre-model style gate;
- atomically creates the AI Run, initial event, and graph-start outbox record;
- returns `202` with Run and thread IDs;
- never waits for DeepSeek or rendering inside the request.

The new public Pydantic DTOs are included in the OpenAPI document and drive generated TypeScript contracts. S2 does not build the consuming page, but it does not create a second hand-maintained browser schema for S3 to repair later.

### 14.2 Read

`GET /api/v1/runs/{run_id}` returns the persisted projection, pending action, usage summary, and final refs.

### 14.3 Events

`GET /api/v1/runs/{run_id}/events` returns persistent SSE:

- `id` is the monotonic event sequence;
- `Last-Event-ID` replays missed events;
- PostgreSQL is the replay source;
- Redis may wake delivery but cannot be the only event store;
- heartbeat comments keep the local connection observable;
- terminal events close the stream cleanly.

### 14.4 Resume

`POST /api/v1/runs/{run_id}/resume`

- accepts only a currently pending interrupt;
- requires the expected Plan hash/interrupt reference;
- persists the human decision and a graph-resume outbox record atomically;
- returns `202` without running the Graph in the request.

### 14.5 Cancel

`POST /api/v1/runs/{run_id}/cancel`

- persists authoritative cancellation;
- cancels the waiting media job when present;
- wakes the Graph to reach a terminal cancellation node;
- discards a late model result rather than materializing it.

### 14.6 Retry

`POST /api/v1/runs/{run_id}/retry` creates a child AI Run referencing the failed or cancelled parent. It does not rewind a terminal checkpoint in place. Compatible immutable artifacts may be reused through existing idempotency and checksum contracts.

## 15. Dispatcher and async execution

The API does not execute the model or Graph directly.

The existing Graph/Resume dispatcher is extended to consume persistent outbox actions for:

- `graph.start.requested`;
- `graph.resume.requested`;
- `graph.cancel.requested` when a wake-up is required.

It loads the AI Run, builds `motif-forge-parent.v2`, invokes or resumes the same thread, and updates the Run projection and events. Delivery is at least once; state transitions and side effects are idempotent.

The DeepSeek key is mounted only into the process that constructs the real provider. Tests and deterministic fallback paths use injected provider implementations.

## 16. Failure, retry, and recovery policy

Errors are classified before routing:

| Category | Owner | Action |
| --- | --- | --- |
| Unsupported style/meter | API/rule node | reject before model |
| DeepSeek 429/timeout/5xx | provider | bounded backoff retry |
| Invalid model JSON/schema | planning subgraph | one repair, then fallback |
| Plan incompatible with strategy | strategy validator | one repair, then fallback/error |
| Missing user approval | Parent Graph | durable interrupt |
| Revision conflict | application transaction | fail closed; explicit child retry |
| Storage pressure | storage gate | persistent waiting/error route; no render |
| Retryable render failure | worker | existing bounded retry |
| Nonretryable media failure | Parent Graph | terminal failed with partial refs |
| Cancellation | persistence + Graph/Worker | authoritative cancel and exact cleanup |
| Duplicate delivery | idempotency/replay | return authoritative persisted result |

Checkpoint boundaries include:

- before the planning subgraph;
- after a validated plan;
- at human approval interrupt;
- after Revision materialization;
- before each media job enqueue;
- on each worker wait;
- after each artifact collection;
- before final Bundle completion.

On process restart, the same Parent thread resumes from the persisted checkpoint. Completed model and side-effect nodes must be replay-safe.

## 17. Observability and audit

Trace hierarchy:

```text
ai_run
  -> parent_graph_node
    -> planning_subgraph_node
      -> model_call
    -> approval_wait
    -> compiler
    -> revision_transaction
    -> media_job
      -> render/transcode/bundle span
```

Required attributes include:

- run/thread/project/Revision/job/artifact IDs;
- graph, prompt, schema, provider, model, compiler, Style Pack, render-profile versions;
- attempt, latency, token counts, cache status, and truthful cost status;
- fallback reason;
- validation and terminal error codes;
- content hashes and lineage refs.

The system must not log:

- `DEEPSEEK_API_KEY`;
- authorization headers;
- hidden reasoning;
- unbounded prompts or responses;
- raw audio bytes.

## 18. Evaluation design

S2 adds a versioned Synth Ambient evaluation set covering:

- valid and invalid briefs;
- style/meter pre-model rejection;
- DeepSeek schema success;
- JSON repair;
- provider failure fallback;
- approval/rejection;
- restart at planning, approval, and media waits;
- duplicate start/resume/job delivery;
- cancellation before and during expensive work;
- Revision conflict;
- storage pressure;
- complete Master/Stem/MP3/Bundle lineage.

The offline comparison has three baselines:

1. S1 deterministic fixed template;
2. a single DeepSeek Plan followed by deterministic compilation;
3. the full Parent Graph with validation, approval, fallback, durable recovery, and complete export.

Metrics include:

- schema pass rate;
- hard-constraint satisfaction;
- first playable rate;
- deterministic fallback rate;
- approval and rejection correctness;
- duplicate side-effect count;
- resume success rate;
- render/export success rate;
- total latency and worker time;
- model calls, tokens, truthful known/unknown cost;
- artifact lineage and citation/provenance correctness.

## 19. Real paid DeepSeek acceptance

After unit, integration, migration, and deterministic end-to-end gates pass, one reviewed live acceptance is allowed.

The live brief is:

- style: Synth Ambient;
- instrumental only;
- 4/4;
- bounded duration suitable for local S2 validation;
- broad musical properties, with no exact artist imitation;
- four supported roles.

Hard budget:

- maximum three paid model calls;
- maximum 12,000 total input-plus-output tokens;
- stop after the first valid successful Plan and complete exported Bundle;
- no automatic repetition for aesthetic preference.

Evidence records:

- provider/model and version;
- request/response schema versions and Plan hash;
- call count and provider-reported tokens;
- latency and fallback status;
- approval event;
- Revision and complete artifact lineage;
- final Bundle ID and checksums.

Evidence excludes the API key, hidden reasoning, and raw provider payload. If DeepSeek is unavailable, the deterministic fallback path is validated separately, but the paid acceptance remains incomplete rather than being falsely reported as passed.

## 20. Compatibility and rollout

- S1 behavior and deterministic smoke remain a locked regression baseline.
- Existing Parent v1 threads continue to resume with their recorded topology; they are not migrated in place.
- New generate Runs use Parent v2 only.
- The Plan standalone regression graph and Parent production graph share planning node factories.
- Migration `0013` must support upgrade and downgrade SQL checks and a real PostgreSQL round trip.
- No new dependency is added unless an existing library cannot satisfy persistent SSE or provider behavior; standard FastAPI streaming and current database primitives are preferred.
- No Docker rebuild occurs for documentation-only work. Implementation rebuilds only affected services and performs the established post-stage cache hygiene.

## 21. Acceptance gates

S2 is complete only when all of the following are true:

1. Unsupported styles and meters are rejected before model invocation.
2. Parent v2 contains the planning subgraph through explicit adapters with no copied nodes.
3. DeepSeek structured output, one-time repair, budgets, and deterministic fallback are tested.
4. Plan approval is a persisted, hash-bound interrupt with an authenticated actor and assertion.
5. Rejection creates no Candidate, Revision, job, or artifact.
6. Approval creates a fully audited command Candidate and immutable Revision.
7. The plan-driven compiler is deterministic and leaves the S1 template unchanged.
8. The full Master, four Stem, MP3, and logical Bundle chain succeeds through existing workers.
9. Restart and duplicate-delivery tests prove no duplicate model call, Revision, job, or artifact.
10. Cancellation and retry preserve authoritative state and clean new unregistered outputs.
11. AI Run status and persistent SSE replay work across API restart.
12. Model usage and cost never use a false zero for unknown values.
13. Unit, integration, migration, API contract, real PostgreSQL, and deterministic end-to-end tests pass.
14. One live paid DeepSeek acceptance succeeds within the approved budget.
15. Documentation, implementation status, trace/eval evidence, and cache hygiene are updated from fresh runtime evidence.

## 22. Implementation sequencing constraint

The implementation plan must preserve this dependency order:

1. contracts and migration;
2. planning subgraph extraction and state adapters;
3. DeepSeek/fallback provider integration;
4. plan-driven Synth Ambient compiler;
5. approval and Revision materialization;
6. complete render/export orchestration;
7. async API, dispatcher, and SSE;
8. recovery, cancellation, and idempotency tests;
9. deterministic full-stack acceptance;
10. one budgeted live DeepSeek acceptance;
11. documentation/status update and cache hygiene.

Each implementation slice begins with a failing contract test and ends with targeted verification. Full Docker rebuilds are reserved for the final affected-service gate rather than routine inner-loop development.
