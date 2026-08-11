---
name: motif-forge-development
description: Use when implementing, reviewing, testing, or documenting Motif Forge work involving LangGraph/LangChain orchestration, DeepSeek V4 Flash, music IR, audio or Stem import, pitch-preserving time-stretch, segmented synthesis/rendering, timbre or melody generation/search, rule policies, Worker jobs, error recovery, evals, traces, FastAPI, or the Web Studio.
---

# Motif Forge Development

Build one verifiable vertical slice at a time while preserving the project's music, Agent, safety, and recovery contracts.

## Required context

Read `../../../docs/PROJECT_GUIDE.md` before planning or editing. Treat it as the product and architecture source of truth. Record its git blob ID or SHA-256 at task start and verify it again before handoff when work spans multiple edits or agents. If code and the guide disagree or the guide changes mid-task, report the mismatch and re-evaluate the plan; do not silently rewrite either side.

Read only the reference needed for the task:

- Read [references/change-checklists.md](references/change-checklists.md) before implementation or review.
- Read [references/contracts.md](references/contracts.md) when adding or changing a Graph node, tool, Provider, Job, policy, error, trace, or Eval case.

## Core workflow

1. Inspect the relevant code, tests, schemas, prompts, policies, migrations, and current git diff. Preserve unrelated user changes. If the repository is still doc-only or the guide says product code is not yet authorized, restrict work to contracts/plans/skills until the user explicitly starts implementation.
2. Classify the slice: domain/IR, rule policy, Graph, DeepSeek Provider, audio Worker, timbre/melody, API, UI, observability, or eval.
3. State the user-visible behavior, deterministic baseline, inputs, outputs, error routes, budget, and acceptance check before coding.
   - For a greenfield slice, also identify unresolved package layout, queue/Worker framework, persistence, migration, and policy-threshold decisions. Recommend defaults, but do not invent irreversible conventions when they are not approved.
4. Update the smallest contract or schema first. Add a migration/version only when persisted data changes.
5. Add focused tests and at least one relevant Eval or failure case before or with implementation.
6. Implement deterministic logic outside LLM nodes. Keep model calls limited to semantic music decisions.
7. Emit structured events and metrics; do not add an invisible retry, fallback, auto-commit, or background job.
8. Run the narrow tests first, then the relevant integration/smoke path. Check formatting and migrations.
9. Update `docs/PROJECT_GUIDE.md` only when the approved product or architecture contract changes. Record later decision/evolution docs once they exist.
10. Report changed files, behavior, tests, trace/eval impact, known limitations, and the next smallest slice.

## Architecture invariants

- Keep one versioned `MotifForgeGraph` topology, but create one finite parent run/thread per import, generation, edit, or export task. Within that run, strategy subgraphs, Worker waits, HITL, and recovery always return state to the same parent thread; project state persists across runs through Revision/Artifact contracts.
- Keep `ArrangementIR` and immutable Revision history as the source of truth. Never serialize Web Audio objects into project state.
- Keep PreviewCandidate separate from Revision: candidate content is immutable, approval creates a new Revision, and Branch head is the only authoritative current pointer for that branch.
- Store immutable full `ArrangementIR` snapshots in PostgreSQL Revision JSONB. Store large audio/MIDI/waveform data in the Artifact Store; checkpoints contain references and compact task control state.
- Let DeepSeek generate `CompositionPlan`, `SectionGenerationPlan`, `PatternSpec`, `SynthPatchSpec`, `SampleTriggerSpec`, or bounded `EditPatchProposal`; never raw PCM arrays or arbitrary DSP/shell code.
- Compile and render with deterministic tools. Validate every model output and tool argument locally.
- Use non-thinking DeepSeek calls for bounded simple tasks and thinking mode for macro planning/critique. Preserve `reasoning_content` across thinking tool turns, but never expose it in UI or normal traces.
- Route L0/L1 changes to validated atomic Revision + Undo. Route L2/L3 changes to Preview/HITL. Actual diff can raise but never lower ChangeImpact.
- Use versioned rules for retry, budget, import, license, continuity, render quality, and completion decisions. Do not ask the model to interpret infrastructure errors.
- Make Jobs and side effects idempotent. Preserve partial Segment and Artifact success across retries.
- Keep imported originals immutable. Pitch-preserving time-stretch creates a Derived Artifact and must be reversible.
- Search the approved local catalog by default. External Allowlist search requires an explicit user action, and every result must pass license review and quarantine import before use. Generated synth patches must stay within the supported schema and parameter bounds.
- Keep Agent tools side-effect free or read-only: use `simulate_edit_patch` and `search_sound_catalog`; never expose `commit_revision`, `request_preview_render`, external download, queue scheduling, or arbitrary persistence to the model.
- Keep browser and canonical Worker rendering on the shared TypeScript `AudioGraphCompiler`/Tone semantics. Chromium render jobs are resource-bounded and default to concurrency 1; FFmpeg owns time-stretch/transcode, not synth semantics.
- Use PostgreSQL as the only business database and Celery + Redis for delivery with PostgreSQL Job/Event/Outbox as the source of truth. Do not add a SQLite behavior fork.
- Never put API keys, raw secrets, private paths, or unnecessary audio content into prompts, logs, traces, fixtures, or commits.

## Change routing

Use these defaults:

- Graph/Node/Edge/Loop: define Node Contract, state update, normal edge, every error edge, checkpoint boundary, trace span, and eval.
- DeepSeek call: define mode, schema, max output, tool set, `finish_reason` handling, timeout, retry, context slice, usage capture, and native-SDK contract test.
- Rule node: define facts, ordered rule IDs, decision, explanation code, version, boundary tests, and no-match behavior.
- Worker/audio operator: define Job contract, heartbeat, idempotency, cancellation, Artifact lineage, resource limit, failure event, and retry ownership.
- Import/time-stretch: preserve original, validate format/license, record analysis confidence, generate Derived Artifact, verify duration/BPM/pitch/clicks, and support Undo.
- Timbre/melody: separate semantic request, catalog search or patch generation, theory/parameter validation, preview, license, and ChangeImpact.
- API/UI: cover loading, progress, partial success, waiting approval, retry, cancel, resume, empty, conflict, and error states.
- Eval/observability: compare against the simplest non-Agent baseline and attach every regression to a traceable failure category.

## Stop conditions

Stop and surface the issue instead of guessing when:

- A requested change contradicts an approved invariant or materially expands scope.
- A Provider capability or license cannot be verified.
- A destructive/mutating action lacks the required ChangeImpact approval.
- The same Job or model step would retry beyond policy or budget.
- Persisted schema changes lack a migration or rollback path.
- The guide revision changed after planning, or the repository has no approved implementation scaffold and the request did not authorize creating one.
- Tests cannot isolate user data, secrets, external cost, or nondeterministic audio behavior.

## Completion standard

A slice is complete only when its success path, failure path, cancellation/recovery behavior, structured trace, focused test, relevant eval fixture, and user-facing state are either implemented or explicitly documented as out of scope.
