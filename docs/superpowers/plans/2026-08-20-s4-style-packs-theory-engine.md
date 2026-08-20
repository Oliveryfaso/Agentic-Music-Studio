# S4 Style Packs and Theory Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing approved Generate flow produce four distinct complete works with versioned knowledge, deterministic theory evidence, and Web explanations.

**Architecture:** Keep Parent Graph v2 and PlanApproval unchanged. Resolve an allowlisted immutable Style Pack, route approved Plans through one deterministic strategy interface, validate the resulting ArrangementIR with one Theory Engine, then reuse existing Revision and seven-step export orchestration.

**Tech Stack:** Python 3.12, Pydantic v2, LangGraph, PostgreSQL/SQLAlchemy, FastAPI/OpenAPI, React/TypeScript, Vitest, Pytest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-08-20-s4-style-packs-theory-engine-design.md`

## Global Constraints

- Never create a third production Graph or bypass the existing PlanApproval interrupt.
- The model may produce only a strict CompositionPlan; deterministic code owns notes, validation and Revision writes.
- Four packs ship together; Classical and Jazz cannot be placeholders or Synth aliases.
- Only reviewed built-in/public-domain/CC0 symbolic knowledge is executable; citations never decide note legality.
- Keep exactly the existing four export roles and seven-step complete export.
- Prefer targeted portfolio-grade tests; do not add S7 load/P95/multi-tenant/fault matrices.
- Do not call DeepSeek unless deterministic provider-boundary evidence is insufficient; at most one attested paid call.
- Do not compute hashes except where existing Plan/Revision/idempotency/protocol contracts require them.

---

### Task 0: Test Configuration Isolation

**Files:**
- Modify: `services/api/src/motif_forge/config.py`
- Test: `services/api/tests/unit/test_config.py`

**Interfaces:**
- Produces: `Settings.for_test(**overrides) -> Settings`, which never reads `.env`.

- [x] **Step 1: Write RED tests** proving `Settings.for_test()` ignores a container DSN in `.env` while ordinary `Settings()` remains unchanged.
- [x] **Step 2: Run** `.venv/bin/pytest services/api/tests/unit/test_config.py -q`; expect failure because `for_test` is missing.
- [x] **Step 3: Implement** a classmethod using `_env_file=None`, and replace only S4/new tests that need explicit isolation.
- [x] **Step 4: Run** the focused test and the API unit suite; expect pass without renaming `.env`.
- [x] **Step 5: Commit** `test: isolate explicit API test settings`.

### Task 1: Strict Style Pack Registry

**Files:**
- Create: `services/api/src/motif_forge/domain/style_packs.py`
- Create: `services/api/src/motif_forge/knowledge/__init__.py`
- Create: `services/api/src/motif_forge/knowledge/style_packs.json`
- Test: `services/api/tests/unit/domain/test_style_packs.py`

**Interfaces:**
- Produces: `StylePack`, `SourceCitation`, `LicenseSnapshot`, `PresetEntry`, `StylePackRegistry`, `builtin_style_pack_registry()`.
- `StylePackRegistry.resolve(style: StyleId) -> StylePack` fails closed for missing, incompatible or unreviewed data.

- [x] **Step 1: Write RED tests** for exactly four unique v1 packs, strict schema rejection, reviewed license allowlist, compatible engine/schema versions, citations, exemplars and preset ranges.
- [x] **Step 2: Run** `.venv/bin/pytest services/api/tests/unit/domain/test_style_packs.py -q`; expect import failure.
- [x] **Step 3: Implement** immutable Pydantic contracts and load the single curated JSON resource with `importlib.resources`.
- [x] **Step 4: Add** four concise project-authored pack records with distinct form, role, harmony, rhythm, timbre and palette facts.
- [x] **Step 5: Run** focused tests and Ruff/Mypy; expect pass.
- [x] **Step 6: Commit** `feat: add four versioned style packs`.

### Task 2: Deterministic Theory Engine

**Files:**
- Create: `services/api/src/motif_forge/domain/theory.py`
- Test: `services/api/tests/unit/domain/test_theory.py`

**Interfaces:**
- Produces: `TheorySeverity`, `TheoryEvidence`, `TheoryIssue`, `TheoryReport`, `TheoryEngine.evaluate(arrangement: ArrangementIR, pack: StylePack) -> TheoryReport`.
- `TheoryReport.blocking` contains only `error`; warning/advice remain explanatory.

- [x] **Step 1: Write RED tests** for stable ordering, role/range blocking errors, non-blocking Classical parallel-motion warning, Jazz guide-tone/avoid-note evidence, and bounded suggested operations.
- [x] **Step 2: Run** the focused file; expect missing module.
- [x] **Step 3: Implement** small pure rule functions over authoritative NoteEvent/Track/Section facts; no RAG text or model calls.
- [x] **Step 4: Run** focused domain tests plus existing IR/composition tests; expect pass.
- [x] **Step 5: Commit** `feat: add deterministic theory evidence engine`.

### Task 3: Four Strategy Compilers and Router

**Files:**
- Create: `services/api/src/motif_forge/domain/music_strategies.py`
- Modify: `services/api/src/motif_forge/domain/composition.py`
- Modify: `services/api/src/motif_forge/agent/fallback.py`
- Test: `services/api/tests/unit/domain/test_music_strategies.py`
- Test: `services/api/tests/unit/agent/test_fallback.py`

**Interfaces:**
- Produces: `StrategyInput`, `StrategyResult`, `MusicStrategyRouter.compile(project_id, brief, plan, seed) -> StrategyResult`.
- `StrategyResult.build` is the existing `CompositionBuild`; `pack`, `theory_report`, `compiler_version` carry lineage.

- [x] **Step 1: Write RED tests** compiling the same bounded Brief shape through all four styles; assert deterministic replay, four export roles, valid duration, and distinct track/instrument/rhythm/register/form facts.
- [x] **Step 2: Write RED fallback tests** requiring canonical role coverage and Pack knowledge reference for every style.
- [x] **Step 3: Run** the focused files; expect missing router and incompatible non-Synth fallback roles.
- [x] **Step 4: Extract** shared pattern/Arrangement construction from the current Synth compiler without changing its output.
- [x] **Step 5: Implement** four data-driven strategy profiles and style-specific note/rhythm/voicing transforms; run Theory Engine and fail on blocking issues.
- [x] **Step 6: Run** focused tests plus the existing Synth Ambient regression suite; expect pass.
- [x] **Step 7: Commit** `feat: compile four deterministic music strategies`.

### Task 4: Parent Graph and Durable Lineage Integration

**Files:**
- Modify: `services/api/src/motif_forge/agent/generate.py`
- Modify: `services/api/src/motif_forge/application/generation.py`
- Modify: `services/api/src/motif_forge/api/ai_runs.py`
- Test: `services/api/tests/unit/agent/test_generate_graph.py`
- Test: `services/api/tests/unit/application/test_generation.py`
- Test: `services/api/tests/integration/test_postgres_generate_materialization.py`

**Interfaces:**
- `PersistPlanningResultRequest.style_pack_version` is derived from Brief style, never supplied by the model.
- `MaterializeApprovedComposition` consumes `MusicStrategyRouter` and persists exact pack/compiler/theory summary in existing receipt/version/event facts.

- [x] **Step 1: Write RED Graph tests** accepting all four allowlisted styles while rejecting unknown style/meter before planner/model work.
- [x] **Step 2: Write RED application tests** for exact pack selection, blocking theory rollback, warning continuation and replay stability.
- [x] **Step 3: Implement** pack resolution in Generate validation/persistence and router-based materialization; preserve PlanApproval and Preview transaction boundaries.
- [x] **Step 4: Add one real PostgreSQL test** proving each style persists one Revision/receipt with exact lineage and seven export jobs are still produced by shared orchestration.
- [x] **Step 5: Run** focused unit/integration commands, Ruff and Mypy; expect pass.
- [x] **Step 6: Commit** `feat: route approved plans through four style strategies`.

### Task 5: Web Style and Evidence Experience

**Files:**
- Modify: `apps/web/src/features/generate/BriefForm.tsx`
- Modify: `apps/web/src/features/generate/PlanReview.tsx`
- Modify: `apps/web/src/features/generate/RunPage.tsx`
- Modify: `apps/web/src/styles.css`
- Modify generated OpenAPI files through the existing generator only if the API schema changes.
- Test: `apps/web/src/features/generate/BriefPage.test.tsx`
- Test: `apps/web/src/features/generate/RunPage.test.tsx`

**Interfaces:**
- Brief submits one of the four existing OpenAPI `StyleId` literals.
- Read UI renders bounded `style_pack`, `sources`, `license`, and severity-separated `theory_issues` fields when present.

- [x] **Step 1: Write RED component tests** for four style options, submitted style, loading/error preservation, citations/license text, warning/advice separation and narrow mobile overflow.
- [x] **Step 2: Run** `npm run test:web -- --runInBand` or the repository-equivalent focused Vitest command; expect failure.
- [x] **Step 3: Implement** accessible selector and compact evidence panels using current visual language and flexible layouts.
- [x] **Step 4: Run** Web tests, TypeScript build and deterministic OpenAPI generation if applicable.
- [x] **Step 5: Commit** `feat: expose style strategy evidence in studio`.

### Task 6: Representative S4 Eval and End-to-End Gate

**Files:**
- Create: `evals/s4-four-style-packs-v1.json`
- Create: `services/api/tests/eval/test_s4_style_pack_eval.py`
- Create or modify: `scripts/run_s4_deterministic_smoke.py`
- Create: `tests/test_s4_script_contract.py`
- Modify: `scripts/check_s1.sh`
- Modify: `docs/IMPLEMENTATION_STATUS.md`
- Modify: `docs/NEXT_DEVELOPMENT_ROADMAP.md`
- Modify: `docs/PROJECT_GUIDE.md`
- Modify: `AGENTS.md`

**Interfaces:**
- Eval has at least two representative cases per style plus license/injection rejection cases.
- Smoke reports style, pack/compiler versions, theory error/warning counts, Revision, seven Jobs, six Audio artifacts, one Bundle and provider request/token counts.

- [x] **Step 1: Write RED Eval/script-contract tests** that require four distinct style results, exact lineage fields, fail-closed unreviewed knowledge and zero paid requests in deterministic mode.
- [x] **Step 2: Run** focused host tests; expect missing fixture/runner/smoke.
- [x] **Step 3: Implement** the smallest deterministic runner and Compose/browser journey through public API/action paths; never invoke media execution directly.
- [x] **Step 4: Run** focused host gates, one real PostgreSQL boundary and one Compose/browser four-style smoke.
- [x] **Step 5: Run final proportional gate:** Python unit/eval, Audio 13+, Web 41+, OpenAPI generation/build, Ruff, Mypy and `git diff --check`. Do not rerun S1 fault matrices unless shared worker contracts changed.
- [x] **Step 6: Update docs** to close S4 and open only S5 if all four styles genuinely complete full export.
- [x] **Step 7: Commit** `feat: complete S4 four-style composition workflow`.
