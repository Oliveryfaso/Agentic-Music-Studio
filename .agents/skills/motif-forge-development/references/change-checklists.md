# Motif Forge Change Checklists

Load the checklist matching the current task. Do not apply every checklist mechanically.

## Vertical slice

- Record and recheck the source-of-truth guide revision/hash.
- Name the current roadmap gate and every covered `MF-Pxx`; do not change unlisted product requirements.
- If doc-only, confirm explicit authorization before scaffolding product code.
- Define user action and visible result.
- Name the deterministic baseline and why an LLM is or is not needed.
- Identify input/output schema versions and persisted data impact.
- Define normal, partial, cancelled, retryable, human-required, and terminal outcomes.
- Identify budget, timeout, idempotency, checkpoint, Trace, Metric, Log, and Eval impact.
- Cover API plus empty/loading/progress/error/resume UI states when user-facing.
- Verify no unrelated behavior or files changed.
- Update `IMPLEMENTATION_STATUS.md` only after runtime evidence exists; append actual evidence to `TECH_EVOLUTION.md` and do not mark a target contract complete from a Schema, unit test, or Spike alone.

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

## Artifact lifecycle or storage pressure

- Use only configured Artifact/temp roots; never accept a client path or silently fall back from the external Lean root to internal storage.
- Record retention class (`durable|protected|rebuildable|ephemeral`) and availability (`available|evicted|missing|rehydrating`) separately.
- Protect imported originals, current-Revision dependencies, selected final outputs, active jobs, and unresolved HITL candidates from cleanup.
- Give rebuildable outputs a version-pinned `RebuildRecipe`, source references, checksum, expected size, and deterministic idempotency key.
- Estimate required bytes before producing an Artifact and route through `StoragePressureGate` with project/global/temp quotas.
- Define exactly one cleanup pass and one retry; never loop GC, rehydration, or generation without a hard bound.
- Emit persistent pressure, eviction, rehydration, wait, resume, and failure events; expose the same state through API and UI.
- Test quota boundaries, external-root disconnect/reconnect, protected-file survival, evicted rehydration, missing source, duplicate resume, and cleanup race behavior.
- Treat full candidate IR as durable project state while compressed previews may expire; create lossless Masters/Stems on demand according to the approved retention policy.

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
- Represent `available`, `evicted`, `missing`, and `rehydrating` explicitly; offer rehydrate/retry only when the server contract permits it.
- Show storage pressure and external-root unavailability without claiming an edit was lost; simple state-only edits may continue when they produce no Artifact.

## Eval and release

- Add a realistic case and failure tag; update baseline only with reviewed evidence.
- Measure task success, schema/tool correctness, edit locality, render success, continuity, latency, cost, and recovery.
- For audio quality, keep deterministic feature checks separate from human A/B judgment.
- Run focused unit tests, contract tests, integration path, failure injection, and document validation.
- Record known gaps and do not call the slice complete when only the happy-path demo works.
- Include external-root disconnect, quota exhaustion, cleanup eligibility, protected Artifact survival, checkpoint resume, and rebuild reproducibility in the recovery suite.

## Stage-end storage hygiene

Run after a small stage has passed its acceptance tests, not after every edit or while a build/test is active.

- Freeze and print the keep set first: current tagged project images, running service images, PostgreSQL/Redis volumes, active external Artifact root, approved final/benchmark outputs, lockfiles, and the one current test environment needed for the next slice.
- Inventory before mutation: `docker image ls`, `docker ps -a`, `docker system df -v`, `docker buildx du`, exact cache/output directories, symlinks, sizes, and free space. Resolve every deletion target to a specific project-owned path.
- Remove obsolete project outputs by exact path: failed/older Spike runs, `.partial` files with no active Job lease, mistaken repository-local environments, and superseded generated fixtures. Keep the latest accepted evidence and its checksums.
- Clear unused BuildKit cache only after confirming no build is active. Preserve tagged current images and required base/service images; do not use `docker system prune --volumes`, `docker image prune -a`, or remove a named image merely because no container is currently running from it.
- Default to host-side Vite/TypeScript/Python checks for frontend, pure domain/application changes and unit tests. A source edit alone is not a Docker rebuild trigger. Rebuild only the affected target for Dockerfile/system dependency changes, container-relevant lockfile changes, migration/runtime wiring, or an accepted cross-service/stage gate; record why the rebuild was required.
- Use an explicit hot-target allowlist during development. Warm only targets needed by the next accepted slice, then keep shared BuildKit near 1.5 GiB and never above 2 GiB merely for speculative reuse; if the hot set cannot fit, retain current runnable images and accept a later cold build.
- At feature-complete, release-seal, or long-pause boundaries, clear all project-owned BuildKit cache after the final runtime evidence is captured. Lockfiles, current released images and build instructions are durable; build cache is not. Never apply this full cleanup to an unproven shared builder.
- Prefer a project-owned builder only after its network path, persistent overhead, and cache isolation are verified on the current host. When the available builder is shared, use single-target builds and stop before global pruning if ownership cannot be proven; never retain a failing dedicated builder merely for architectural uniformity.
- Do not mechanically create one image or one cache policy per future module. Record why the module needs process/image isolation, what layer is stable, whether data is durable or rebuildable, where it may live, and the measured storage/quality/cold-build tradeoff before choosing reuse, split, external cache, or on-demand installation.
- Prune tool caches with their native scoped command where possible (`uv cache prune`, an explicit npm cache root). Keep dependency lockfiles; caches must remain reproducible rather than durable.
- Never delete database volumes, imported originals, current-Revision dependencies, selected Masters, manifests/licenses, unresolved HITL candidates, or another project's named images/caches. If Docker cache ownership is mixed or unclear, stop and ask before global pruning.
- On Colima, run filesystem trim only after successful deletion when reclaiming sparse host space is useful; trim is not a substitute for deletion and must not restart or resize the VM.
- Re-inventory after cleanup and record bytes before/after, retained images/artifacts, and anything intentionally kept. Re-run readiness plus the smallest no-rebuild runtime smoke; a cleanup that forces an immediate full rebuild or breaks resume is not accepted.
