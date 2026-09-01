# Optional LangSmith Observability Implementation Plan

> **For agentic workers:** Execute inline with `superpowers:test-driven-development`; do not dispatch subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add opt-in, secret-safe LangSmith tracing for Motif Forge's existing LangGraph Parent Graph and native DeepSeek boundary without making the SaaS an application dependency.

**Architecture:** Keep PostgreSQL checkpoints, persistent Run events, usage ledgers, and the built-in Graph view authoritative. A small observability module configures LangSmith only when both tracing and an API key are present, builds safe `RunnableConfig` metadata for related invocations, and shields manual provider spans so tracing failures cannot change product outcomes. Compose passes the optional secret only to Graph-owning services and forces input/output hiding.

**Tech Stack:** Python 3.12, LangGraph 1.x, LangChain Core, LangSmith Python SDK, Pydantic Settings, Docker Compose, pytest.

**Spec:** Approved in-chat design from 2026-09-01: optional tracing, API/Dispatcher/Resume Dispatcher wiring, safe correlation metadata, no sensitive payloads, fail-open behavior, Base retention guidance, and README setup.

## Global Constraints

- Current stage is post-S7 portfolio maintenance under ADR-016/ADR-017.
- Covers `MF-P13`, `MF-P18`, and `MF-P21`; no other product requirement changes.
- Keep exactly one production Parent Graph (`motif-forge-parent.v2`).
- PostgreSQL remains the source of truth; LangSmith is disposable developer telemetry.
- No database migration, public API, frontend, Revision, Artifact, approval, or Worker contract change.
- Tracing defaults off and sends nothing without explicit `LANGSMITH_TRACING=true` plus `LANGSMITH_API_KEY`.
- Never send prompts, raw model reasoning, Graph state/checkpoint payloads, approval assertions, local paths, Authorization headers, secrets, or audio bytes.
- Trace backend failure must not fail, retry, or duplicate a model/Graph operation.
- Tests use fake keys and local fakes only; no DeepSeek or LangSmith paid/network call.

---

### Task 1: Safe runtime configuration boundary

**Files:**
- Create: `services/api/src/motif_forge/observability.py`
- Modify: `services/api/src/motif_forge/config.py`
- Test: `services/api/tests/unit/test_langsmith_observability.py`
- Test: `services/api/tests/unit/test_config.py`

**Interfaces:**
- Produces `configure_langsmith(settings: Settings, *, service: str) -> bool`.
- Produces `graph_trace_config(...) -> RunnableConfig` with safe IDs/tags only.
- Produces `safe_trace(...)` for manual provider spans; it never suppresses application exceptions and swallows only tracing setup/finalization failures.

- [x] Write RED tests proving tracing is off by default, a missing key disables it, secrets are absent from representations, safe graph metadata contains only approved IDs, and trace setup/finalization failures do not change application results/errors.
- [x] Run the narrow tests and confirm failures are due to missing configuration/module behavior.
- [x] Add the minimal Settings fields and observability module.
- [x] Re-run the narrow tests to GREEN.

Acceptance:

```bash
PYTHONPATH=services/api/src /Volumes/KINGSTON/idea/agentic-music-workbench/.venv/bin/pytest \
  services/api/tests/unit/test_config.py \
  services/api/tests/unit/test_langsmith_observability.py -q
```

### Task 2: Correlate Parent Graph invocations safely

**Files:**
- Modify: `services/api/src/motif_forge/worker/outbox.py`
- Modify: `services/api/src/motif_forge/api/app.py`
- Modify: `services/api/src/motif_forge/worker/dispatcher.py`
- Modify: `services/api/src/motif_forge/worker/resume_dispatcher.py`
- Test: `services/api/tests/unit/worker/test_outbox.py`
- Test: `services/api/tests/unit/api/test_health.py`

**Interfaces:**
- Generate/Edit configs carry `run_id`, `thread_id`, `project_id`, `run_type`, `graph_version`, and service tags.
- Import/Rehydrate configs carry only stable operation IDs already present in the product boundary.
- `configurable.thread_id` remains byte-for-byte compatible with checkpoint lookup.

- [x] Update existing outbox assertions first so they require safe tags/metadata while preserving `thread_id`.
- [x] Run RED and confirm the old bare config is the only mismatch.
- [x] Replace production bare configs with `graph_trace_config` and call `configure_langsmith` at service startup.
- [x] Run focused API/Outbox tests to GREEN.

Acceptance:

```bash
PYTHONPATH=services/api/src /Volumes/KINGSTON/idea/agentic-music-workbench/.venv/bin/pytest \
  services/api/tests/unit/worker/test_outbox.py \
  services/api/tests/unit/api/test_health.py -q
```

### Task 3: Trace the native DeepSeek transport without payload leakage

**Files:**
- Modify: `services/api/src/motif_forge/providers/deepseek.py`
- Test: `services/api/tests/unit/providers/test_deepseek.py`

**Interfaces:**
- Each provider HTTP attempt emits an optional `llm` span named `DeepSeekV4Flash`.
- Span inputs contain only model, request kind, attempt, thinking mode, and token ceiling.
- Span outputs contain only finish reason, token/cache counters already admitted to the persistent usage ledger, and sanitized error codes.
- Headers, messages, content, reasoning, response body, and API key never enter the span API.

- [x] Add RED tests with a fake trace recorder for safe success metadata and a trace backend that fails on enter/exit.
- [x] Run RED and confirm provider behavior is otherwise unchanged.
- [x] Add the smallest `safe_trace` integration around each transport attempt.
- [x] Re-run provider tests to GREEN, including retry and sanitized-error cases.

Acceptance:

```bash
PYTHONPATH=services/api/src /Volumes/KINGSTON/idea/agentic-music-workbench/.venv/bin/pytest \
  services/api/tests/unit/providers/test_deepseek.py -q
```

### Task 4: Compose secret isolation and operator documentation

**Files:**
- Modify: `compose.yaml`
- Modify: `.env.example`
- Modify: `README.md`
- Test: `tests/test_langsmith_observability_contract.py`
- Test: `tests/test_local_launcher_contract.py`

**Interfaces:**
- API, Dispatcher, and Resume Dispatcher receive optional LangSmith configuration.
- Migrate/Media/Render/Storage services receive no LangSmith secret and tracing remains disabled.
- Compose forces `LANGSMITH_HIDE_INPUTS=true` and `LANGSMITH_HIDE_OUTPUTS=true` for traced services.

- [x] Add RED contract tests for default-off behavior, exact service secret boundaries, redaction, README setup, cost controls, and stop/disable instructions.
- [x] Run RED and confirm missing configuration/docs are the failures.
- [x] Add Compose/environment/docs wiring without changing the one-command launch interface.
- [x] Run contract tests and `docker compose config --quiet` to GREEN using a secret-free local environment.

Acceptance:

```bash
PYTHONDONTWRITEBYTECODE=1 /Volumes/KINGSTON/idea/agentic-music-workbench/.venv/bin/pytest \
  tests/test_langsmith_observability_contract.py \
  tests/test_local_launcher_contract.py -q
bash -n scripts/start_motif_forge.sh scripts/stop_motif_forge.sh
```

### Task 5: Combined verification and evidence update

**Files:**
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/TECH_EVOLUTION.md`
- Recheck only: `docs/PROJECT_GUIDE.md`

**Interfaces:**
- Status calls LangSmith “optional developer telemetry,” never a persisted product fact or complete OTel platform.
- Evidence records no paid/network provider call and explicitly retains distributed Celery/FFmpeg tracing as out of scope.

- [x] Run the combined focused suite, Ruff, Mypy, Compose config validation, and diff check.
- [x] Recheck the recorded `PROJECT_GUIDE.md` Git blob ID and confirm no diff.
- [x] Update status/evolution with only evidence actually observed.
- [x] Inspect the final diff and working tree; do not merge, push, or expose a real key.

Acceptance:

```bash
PYTHONPATH=services/api/src /Volumes/KINGSTON/idea/agentic-music-workbench/.venv/bin/pytest \
  services/api/tests/unit/test_config.py \
  services/api/tests/unit/test_langsmith_observability.py \
  services/api/tests/unit/worker/test_outbox.py \
  services/api/tests/unit/providers/test_deepseek.py \
  tests/test_langsmith_observability_contract.py \
  tests/test_local_launcher_contract.py -q
/Volumes/KINGSTON/idea/agentic-music-workbench/.venv/bin/ruff check \
  services/api/src/motif_forge services/api/tests/unit tests/test_langsmith_observability_contract.py
PYTHONPATH=services/api/src /Volumes/KINGSTON/idea/agentic-music-workbench/.venv/bin/mypy \
  services/api/src/motif_forge
git diff --check
```
