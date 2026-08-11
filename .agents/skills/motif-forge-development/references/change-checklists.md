# Motif Forge Change Checklists

Load the checklist matching the current task. Do not apply every checklist mechanically.

## Vertical slice

- Record and recheck the source-of-truth guide revision/hash.
- If doc-only, confirm explicit authorization before scaffolding product code.
- Define user action and visible result.
- Name the deterministic baseline and why an LLM is or is not needed.
- Identify input/output schema versions and persisted data impact.
- Define normal, partial, cancelled, retryable, human-required, and terminal outcomes.
- Identify budget, timeout, idempotency, checkpoint, Trace, Metric, Log, and Eval impact.
- Cover API plus empty/loading/progress/error/resume UI states when user-facing.
- Verify no unrelated behavior or files changed.

## Greenfield or doc-only repository

- Stay in contract/plan mode when the guide forbids product code or the user has not started implementation.
- List decisions needed for package layout, dependency manager, queue/Worker, persistence, migrations, test runner, policy thresholds, and CI.
- Recommend the smallest reversible defaults and identify which decisions can wait.
- When implementation is authorized, create only the first vertical-slice scaffold and its tests; do not prebuild empty layers.

## Graph node, edge, or subgraph

- Confirm the operation has a finite task-level run/thread and records graph/state schema versions; do not reuse a permanent project thread.
- Unique responsibility; no duplicate hidden orchestration.
- Compact serializable input and state update.
- Allowed tools and forbidden actions.
- Deterministic preconditions and postconditions.
- Explicit success, retry, repair, fallback, human, cancel, and terminal edges.
- Checkpoint before HITL or expensive fan-out; idempotent side effects before resume.
- Loop improvement metric and hard termination conditions.
- Span name, state/artifact references, latency, cost, attempts, and error code.
- Unit test for routing plus integration test for checkpoint/resume.

## DeepSeek V4 Flash call

- Use exact `deepseek-v4-flash` model and official endpoint through the Provider Adapter.
- Select thinking/non-thinking explicitly; do not rely on defaults.
- Keep context scoped to project/section/track; keep stable prefix before dynamic content.
- Use JSON Output plus explicit JSON instruction and Pydantic validation.
- Bound `max_tokens`; handle empty content and every `finish_reason`.
- Preserve assistant `reasoning_content` across thinking tool-call turns.
- Restrict tools and validate arguments locally; do not rely solely on Beta strict mode.
- Define connect/read timeout, retryable status codes, backoff, budget, and fallback.
- Record usage/cache figures without raw reasoning or secrets.
- Contract-test native SDK versus LangChain adapter for JSON, tools, stream, usage, and errors.

## Rule policy

- State authoritative input facts; do not pass prose for model interpretation.
- Use stable ordered rule IDs and an explicit priority/conflict policy.
- Define decision, explanation code, next route, and no-match default.
- Version the policy and include it in traces/revisions when behavior changes.
- Test each boundary, conflict, missing fact, and conservative escalation.
- Require human review for a change that weakens safety, license, or HITL requirements.

## Worker Job or audio operator

- Define Job request/result/event schemas and resource limits.
- Write Job + Outbox transactionally; treat PostgreSQL as authoritative and Redis/Celery as at-least-once delivery.
- Validate Artifact IDs; never accept arbitrary server paths.
- Add idempotency key, attempt, deadline, heartbeat, progress, cancel, and cleanup semantics.
- Keep inputs immutable; outputs are content-addressed Derived Artifacts.
- Emit persistent completion/failure events safe for duplicate delivery.
- Distinguish retry owner: HTTP client, Worker queue, Graph, or human—only one owns each retry.
- For canonical audio rendering, pin the shared AudioGraph/audio-engine version and Chromium resource profile; never silently fall back to a different-sounding renderer.
- Test crash after side effect, duplicate event, timeout, cancellation, missing asset, and checksum mismatch.

## Audio import and time-stretch

- Validate magic bytes, size, duration, codec, channels, rights declaration, and quota in quarantine.
- Normalize without overwriting original; create waveform and analysis Artifacts.
- Store BPM/key/beat/section confidence and require confirmation when below threshold.
- For time-stretch, store source/target BPM, ratio, preserve-pitch, engine/version, and before/after analysis.
- Verify duration/BPM tolerance, pitch deviation, loudness, silence, click/pop, and cache reproducibility.
- Preserve Undo and return original Clip when processing fails.

## Timbre, preset, sample, or melody

- Determine whether the request means EQ, pitch, voicing, synthesis patch, sample search, or melodic content.
- Search local catalog first; external results must pass license Allowlist before import.
- Keep oscillator, ADSR, filter, LFO, effects, polyphony, gain, and pitch within supported bounds.
- Require Asset/Preset provenance, version, checksum, license, and preview.
- Validate melody key/chord fit, range, rhythm, motif continuity, locked material, and edit scope.
- Apply ChangeImpact after the real diff: bounded patch may auto-commit; main timbre/melody replacement requires preview.

## Frontend/API

- Use revision/idempotency tokens for writes and handle conflict responses.
- Keep immutable server Revision, local Draft, PreviewCandidate/Candidate Snapshot, and AudioEngine runtime as distinct states; approval creates a new Revision rather than mutating a Preview into one.
- Generate frontend DTOs from Pydantic/OpenAPI; do not hand-maintain a conflicting TypeScript contract.
- Use persistent SSE event IDs and replay after disconnect; Redis notification alone is insufficient.
- Show upload/generation/render progress from persistent events, not optimistic fake completion.
- Support cancel, retry, resume, partial success, low-confidence analysis, and license errors.
- Keep desktop editing usable with timeline overflow; mobile supports review/playback/approval.
- Do not place secrets or unrestricted paths in browser state.

## Eval and release

- Add a realistic case and failure tag; update baseline only with reviewed evidence.
- Measure task success, schema/tool correctness, edit locality, render success, continuity, latency, cost, and recovery.
- For audio quality, keep deterministic feature checks separate from human A/B judgment.
- Run focused unit tests, contract tests, integration path, failure injection, and document validation.
- Record known gaps and do not call the slice complete when only the happy-path demo works.
