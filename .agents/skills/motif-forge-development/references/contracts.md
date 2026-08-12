# Motif Forge Contract Templates

Use these field sets as checklists. Adapt names to the repository conventions; do not copy fields that have no consumer.

## Node Contract

- name/version/responsibility
- input state keys and Artifact references
- output state update schema
- allowed tools and forbidden actions
- model mode/schema/context/budget, or `model: none`
- preconditions and deterministic validators
- success criteria and improvement metric
- normal/partial/retry/repair/fallback/human/cancel/terminal edges
- checkpoint and idempotency boundary
- Span/Metric/Log fields
- unit/integration/eval cases

## Tool Contract

- name/version/owner/read-or-write classification
- strict parameter and result schemas
- identity/revision/selection/Artifact inputs
- bounds/enums/license/permission validation
- idempotency and optimistic concurrency
- timeout/resource budget/cancellation
- `{status, data_ref, warnings, error_code, retryable}` result
- audit, trace, tests, and forbidden input forms such as arbitrary paths
- side-effect classification: Agent-visible tools must be read-only/pure; Revision commit, render enqueue, download, and queue scheduling remain Application/Graph commands

## Rule Policy

- policy name/version/owner
- authoritative input facts
- ordered stable rule IDs
- precedence and conflict behavior
- decision and explanation codes
- conservative no-match route
- effective date/migration/rollback
- boundary/conflict/regression tests

## Job Contract

- job/run/thread/revision/segment IDs
- request/result schema versions
- input/output Artifact references
- idempotency key/attempt/deadline/heartbeat
- progress and persistent event types
- resource limits and isolation
- retry owner and retryable codes
- cancel/cleanup/orphan behavior
- duplicate completion handling
- PostgreSQL Job/Outbox transaction and Redis/Celery at-least-once delivery semantics
- pinned audio-engine/Chromium resource profile for render jobs
- trace metrics and failure injection tests

## Artifact Contract

- artifact/project/revision/source IDs and immutable checksum
- media/schema/engine versions, size, duration, and provenance
- retention class: `durable|protected|rebuildable|ephemeral`
- availability: `available|evicted|missing|rehydrating`
- protection reason and reference owners
- configured storage-root identity, never a browser-visible or model-visible server path
- created/accessed/expires/evicted/rehydration timestamps
- version-pinned `RebuildRecipe` and source Artifact references when rebuildable
- atomic promotion, duplicate-write, checksum, cleanup, and orphan semantics
- API/event/UI mapping plus disconnect, quota, eviction, rehydrate, and missing-source tests

## StoragePressureGate Contract

- required/project/global/temp byte estimates and current usage snapshot
- configured-root mounted/writable/same-filesystem facts
- protected, rebuildable, and ephemeral cleanup candidates
- versioned deterministic policy and explanation code
- route: proceed/gc-then-retry/rehydrate-then-resume/wait-for-storage/fail
- hard bounds for cleanup and retry; no model call
- persistent event, trace span, metrics, and audit record
- idempotent resume/checkpoint behavior and recovery Eval cases

For Chromium render jobs, also define the Python `ChromiumRenderAdapter` ↔ page `RenderBridgeRequest/Receipt`, loopback output sink token/limits, pinned Chromium/Tone/audio-engine versions, cancellation, and semantic-parity tolerance.

## ErrorEnvelope

- error ID and occurred-at time
- node/job/run/segment IDs
- category/code/safe summary
- retryable/attempt/retry-after
- provider/model/engine/schema/policy versions
- last checkpoint and partial Artifact references
- idempotency key and side-effect status
- suggested route: retry/repair/fallback/human/terminal
- root cause details restricted to protected logs

## Eval Case

- id/version/tags/difficulty
- user input and project/Artifact fixtures
- style/strategy/change-impact category
- deterministic expected constraints
- acceptable musical range and human rubric
- expected tool/node route and forbidden behavior
- fault injection when applicable
- baseline outputs and comparison metric
- latency/cost budget
- known failure label and trace assertions

## Trace Span

- run/thread/revision/candidate/segment
- parent span and node/job/tool name
- model/provider/thinking/prompt/schema or rule policy version
- input/output summaries and Artifact refs
- attempt/idempotency/checkpoint
- start/end/queue wait/latency
- token/cache/cost/render seconds
- status/error/change-impact/HITL decision
- never raw secrets, full binary audio, or raw model reasoning
