# S5 Dual Candidate, Evidence Critic, and Bounded Repair Design

**Status:** Approved in conversation on 2026-08-20  
**Product stage:** G0-S4 complete; S5 is the only active gate  
**Requirements:** MF-P04, MF-P13, MF-P14, MF-P18  

## 1. Goal

S5 turns the existing single-candidate Generate path into an observable Agent loop:

```text
approved CompositionPlan
→ two deterministic candidate branches
→ durable CandidateSnapshots and candidate previews
→ evidence-grounded Critic
→ at most one bounded local Repair
→ A/B human selection
→ one immutable Revision
→ existing seven-step canonical export
```

The result must make LangGraph fan-out/fan-in, bounded model judgment, deterministic tools, persistent recovery, and a second human approval visible without weakening the working S2-S4 contracts.

## 2. Scope and non-goals

S5 delivers:

- exactly two candidates for an approved new-composition Plan;
- stable candidate identities, distinct deterministic seeds, and order-independent aggregation;
- a small Section/Track Segment DAG projected from each candidate ArrangementIR;
- durable candidate-aware preview jobs and `candidate-preview.v1` MP3 Artifacts;
- one structured Evidence Critic call that compares both candidates, with a no-Key deterministic fallback;
- at most one deterministic, evidence-targeted Repair across the candidate pair;
- a durable A/B selection interrupt and atomic materialization of only the selected candidate;
- REST/SSE Read Model fields and a responsive Web Compare experience;
- representative Eval and one real PostgreSQL/Compose/browser path.

S5 does not add a third production Graph, free-form executable Graph generation, model-authored Revision writes, general multi-agent chat, a generic DAG scheduler, full DAW editing, AI selection editing, concurrent render-worker scheduling, multi-tenant hardening, load/P95 testing, or an exhaustive failure matrix. Those boundaries remain assigned to S6-S7.

## 3. Chosen architecture

### 3.1 One Parent Graph

The existing `motif-forge-parent.v2` Generate branch is extended after `PlanApproval`:

```text
PlanApproval
→ BuildCandidateBranches
→ PersistCandidateSnapshots
→ EnqueueCandidatePreview
→ WaitForCandidatePreview
→ ValidateCandidateEvidence
→ EvidenceCritic
→ QualityBudgetGate
   ├─ repairable + improving budget → ApplyBoundedRepair
   │  → PersistChildSnapshot → re-render repaired preview → ValidateCandidateEvidence
   └─ ready / non-improving / budget exhausted → CandidateSelection
→ MaterializeSelectedCandidate
→ existing CompleteExport loop
```

Candidate compilation fans out inside the existing Generate subgraph and returns branch-local `CandidateBranchResult` values. Fan-in uses a reducer keyed by stable `candidate_id` and sorts by ID before persistence. Candidate preview media jobs run sequentially through the existing interrupt/resume mechanism; S5 does not add render concurrency merely for demonstration value.

### 3.2 Stable candidate identity

Candidate A uses the approved request seed. Candidate B uses a deterministic derived seed that remains within the accepted integer range. Both IDs derive from the authoritative Run, Plan identity, Plan content identity, label, and seed using the repository's existing identity protocol. Replay must resolve to the same IDs and must not create a third candidate.

Content hashes remain only where the existing Candidate/Artifact integrity and idempotency protocols require them. S5 adds no repository, document, cache, or incidental verification hashing.

## 4. Candidate and Segment contracts

`CandidateBranchResult v1` contains only bounded control data:

- `candidate_id`, label A/B, seed, style/strategy/compiler versions;
- immutable `candidate_snapshot_id` after persistence;
- latest snapshot ID when a repair child exists;
- Theory report summary and stable evidence refs;
- preview job/artifact IDs and compact audio metrics;
- critique, score, repair status, and warnings.

Full ArrangementIR remains in PostgreSQL `candidate_snapshots`, not in Graph checkpoints.

`CandidateSegment v1` is a deterministic projection, not a new database table. A segment is identified by candidate ID, section ID, track ID, and tick range. Dependencies are derived from musical roles:

- harmony/foundation precedes melody or texture in the same section;
- rhythm and bass may provide evidence to each other without forming a cycle;
- adjacent-section continuity adds a read-only predecessor evidence edge.

The projection must reject cycles and overlapping/out-of-range targets. Repair operates on one target segment and can modify only events intersecting its tick range on its track. Successful segments are reused; no whole-candidate recompilation is allowed during Repair.

## 5. Candidate persistence and materialization

The current combined `compile → Preview → approve → Revision` service is split without duplicating semantics:

1. `CreateCompositionCandidates` compiles and persists two immutable CandidateSnapshots against the same Branch head.
2. A Repair creates a child CandidateSnapshot with `parent_candidate_snapshot_id`; it never overwrites its parent.
3. `CreateCandidateSelectionPreviews` exposes only the latest snapshot in each candidate family for A/B.
4. `MaterializeSelectedCompositionCandidate` reuses the established Preview decision transaction to create exactly one Revision and advance the Branch once.

The initial PlanApproval authorizes candidate generation. A separate CandidateSelection assertion authorizes the final Revision. Reject/cancel creates no Revision. A changed Branch head fails closed with the existing revision-conflict behavior.

Duplicate start, worker completion, Critic resume, selection resume, or outbox delivery must return the already persisted facts. Idempotency is backed by PostgreSQL facts and deterministic identities, not process-local memory.

## 6. Candidate-aware preview rendering

The media contract gains one bounded source variant for `candidate_preview` jobs:

- source identity: `candidate_snapshot_id` and candidate content identity;
- output profile: exactly `candidate-preview.v1`;
- output role: candidate preview MP3;
- lineage: Project, source Run, source Job, CandidateSnapshot, engine/profile versions;
- no `revision_id`, canonical Master, Stem, MIDI, or Bundle output.

The Media Worker loads the authoritative CandidateSnapshot, recompiles the AudioGraph from its ArrangementIR, and rejects mismatched project, content identity, output profile, job lineage, or duration. The audio Artifact row records its source CandidateSnapshot; after Critic/Repair settles, the final PreviewCandidate references that Artifact ID. Repaired candidates receive a new preview Artifact; the obsolete Artifact remains reconstructible evidence but is not attached to the final A/B PreviewCandidate.

This is a first-class candidate render path. S5 must not create hidden temporary Revisions or depend on browser-only audio as the authoritative A/B result.

## 7. Evidence Critic

### 7.1 Inputs

One Critic request compares both final candidate evidence bundles. It receives only:

- Brief and approved Plan summaries;
- Style Pack and compiler versions;
- deterministic Theory findings;
- Section/Track Segment summaries;
- bounded audio metrics from preview render output;
- structural differences between candidates;
- remaining request/token/deadline budget.

It never receives secrets, raw audio bytes, unrestricted file paths, arbitrary tools, or mutation permissions.

### 7.2 Output

`CandidateCritique v1` is strict structured output containing:

- one assessment for candidate A and one for B;
- normalized evidence-backed score components;
- stable evidence references for every negative finding;
- at most one Top-1 repair proposal for the pair;
- a recommended candidate and concise comparison rationale;
- provider/prompt/schema identity and usage facts.

A finding without a valid evidence reference is rejected. The model may express aesthetic preference only as advice; deterministic Theory errors and measured audio faults retain rule ownership.

### 7.3 Provider and fallback

When the configured DeepSeek boundary is explicitly enabled, one request evaluates both candidates. The full paid path therefore needs at most two provider requests: one Composition Planner request and one Critic request. S5 acceptance configures one transport attempt per node; invalid Critic transport or schema output falls back deterministically instead of spending a repair request. The persistent ledger rejects every request beyond the two-request Run budget before HTTP.

Without a Key, `DeterministicEvidenceCritic` emits the same schema from Theory severity, continuity facts, note density, dynamic range, clipping/silence indicators, and strategy-specific evidence. The fallback is a supported product path, not test-only behavior.

## 8. Quality budget and bounded Repair

S5 permits at most one Repair across the candidate pair. A Repair is eligible only when:

- the Top-1 finding has a valid candidate/segment/evidence reference;
- its operation belongs to the repair allowlist;
- the target range and track are valid and unlocked;
- request, token, render, revision, and deadline budgets remain;
- the proposal is expected to affect the measured issue.

The deterministic Repair service emits existing `EditorCommand` values and applies them to the candidate snapshot in memory before persisting a child snapshot. It cannot write a Revision, expand the target segment, or modify the other candidate.

After re-rendering, the same deterministic evidence calculation runs again. The repaired child replaces its parent in A/B only if the targeted score improves and no new blocking Theory error appears. Otherwise the original candidate remains selectable and the Run records `non_improving`. Budget exhaustion returns the best two playable candidates with a warning; it is not an infinite reflection loop. LangGraph recursion limits remain a last-resort guard, not the business budget.

## 9. A/B selection and public state

The second interrupt payload contains:

- two stable candidate and preview IDs;
- preview Artifact references and availability;
- score/evidence summaries and recommendation;
- repair lineage and warnings;
- options `select_a`, `select_b`, `reject`, and `cancel`.

Resume requires actor, a fresh assertion of at least the existing minimum length, selected Preview ID, and the expected candidate content identity. Replay with the same public request returns the same result; changing the selected candidate under the same idempotency key conflicts.

The Run Read Model gains:

- `pending_action = select_candidate`;
- ordered candidate summaries;
- Critic comparison and recommendation;
- preview playback availability;
- selected candidate/preview IDs when decided;
- repair status and bounded warnings.

SSE emits durable candidate-created, preview-ready, critique-complete, repair-complete/non-improving, waiting-selection, and selected events. Refresh reconstructs state from PostgreSQL plus checkpoint facts.

## 10. Web Compare experience

After PlanApproval, the existing Run page transitions through candidate generation, preview rendering, Critic, optional Repair, and waiting selection. The Compare view provides:

- A and B cards with style, seed variation, structure, instruments, Theory/Critic facts, and repair badge;
- one active audio transport at a time using the authoritative preview URL;
- a transparent recommendation labelled as evidence, not an automatic decision;
- explicit select, reject, and cancel actions;
- loading, missing/rehydrating Artifact, failure, replay, and stale-Revision states.

Desktop uses a two-column comparison. At 390 px it becomes a vertical list with one transport and large approval controls. S5 does not add waveform editing or synchronized dual playback.

## 11. Failure and recovery rules

- One candidate compilation failure receives one deterministic strategy fallback under the same candidate identity and seed. If the pair still does not contain exactly two playable candidates, the Run fails with a stable code.
- A candidate preview render failure retries only through the existing media policy and never recompiles the other candidate.
- Invalid Critic output routes once to the deterministic Critic fallback if budget/policy allows.
- Invalid or non-improving Repair keeps the original candidate and records a warning.
- Missing or evicted preview Artifacts expose existing availability states and rehydrate from CandidateSnapshot recipe when requested.
- Reject/cancel, Branch conflict, storage pressure, wrong worker lineage, and duplicate completion remain fail-closed and do not create a Revision.
- Terminal success is reached only after the selected Revision completes the existing seven-step export.

## 12. Evaluation and verification

S5 follows portfolio engineering mode:

- each implementation Task starts with a narrow RED contract and ends with focused GREEN tests;
- persistence/HITL/replay uses one representative real PostgreSQL boundary per affected group;
- every two or three Tasks receives one combined regression run;
- stage completion runs Python unit/eval/contracts, Audio/Web tests and builds, Ruff, mypy, migration-head validation, OpenAPI generation, one Compose/browser flow, and one four-style representative Eval set;
- a paid DeepSeek acceptance is optional and, if used, limited to one explicit end-to-end Run with at most the persisted two-request budget;
- full checkpoint crash matrices, render concurrency permutations, P95/load, multi-tenancy, and broad historical migrations remain in S7.

Minimum behavioral acceptance:

1. exactly two stable CandidateSnapshots are produced and replay does not add a third;
2. fan-in ordering is independent of branch completion order;
3. each final candidate has one playable `candidate-preview.v1` Artifact with authoritative source Job/Snapshot lineage;
4. Critic findings all cite real deterministic evidence;
5. at most one bounded Repair occurs and non-improvement preserves the original;
6. selection/replay materializes exactly one Revision and reject/cancel materialize none;
7. restart at preview, Critic, Repair, or selection does not repeat provider calls or durable side effects;
8. the selected Revision alone enters the existing seven-step canonical export;
9. the public Web flow can compare, play, select, refresh, and reach the read-only Studio;
10. no-Key acceptance reports zero provider requests/tokens.

## 13. Documentation and stage close

When all acceptance evidence is green, update `IMPLEMENTATION_STATUS.md`, `NEXT_DEVELOPMENT_ROADMAP.md`, `PROJECT_GUIDE.md`, and `TECH_EVOLUTION.md` to close S5 and open only S6. Do not claim full DAW editing, AI selection editing, final 96-case Eval, production hardening, or release readiness.
