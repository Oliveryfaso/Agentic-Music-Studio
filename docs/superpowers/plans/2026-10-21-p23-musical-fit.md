# P2.3 Musical Fit Implementation Plan

> Native execution: use executing-plans; one fresh review at end. User already requested diagnosis then implementation.

Goal: improve accompaniment fit using verified musical context, not stronger effects. MF-P04/P05/P06/P10/P11/P13/P15/P16/P18/P20/P21.
Architecture: existing Provider gets compact deterministic advisory context; existing compiler/Plan/IR/Parent/PG/HITL/Worker unchanged. Prompt v5; only new records get fit policy version. Old records/bytes never rewritten. No new dependencies/model/genre/schema; main/Guide untouched.
Spec: research diagnosis in current workspace; bounded design already reported in chat.
Base2485e639 / Guide d68b900 clean. Prior cumulative peak-price upper0.046616CNY is not a bill. Existing batches remain paused.

Review focus: unresolved nonchord tones vs passing notes; source half-cadence vs naive final tonic; legacy/v2/read replay; fixed harmony/register takes precedence; max8000B at full16bar; false “better” claims from empty/trivial output; frozen media/cumulative money.

### Task1: music context in existing planner
- [x] TDD Provider request must expose source C02 F/cadence G/rest and3/4 phrase facts; valid mocked response preserved exactly, one call, original track untouched.
- [x] Domain helper tests weight structural durations/accents, allow short resolved passing/neighbor notes, return multiple candidates and bounded output; no quality hard rejection, no automatic rewrite.
- [x] Create domain/piano_fit.py (piano_fit_context), edit providers/piano.py (Prompt v5, only v2 fit_context and fit_policy version), tests unit/domain/test_piano_fit.py, unit/providers/test_piano_fit.py. Keep existing fixed constraints higher priority.
- [x] Narrow→required fullPython/Eval/type/lint once at checkpoint; old semantic/register/fixtures preserved.

### Task2: causal verification and delivery
- [x] Frozen saved source/old/newQ4 recompile audit; offline H=chords only, R=grid only, V=octave only controls with no arbitrary winner selection; fixed instrument/gain/velocity/gate unless named variable.
- [x] Real API/ownedPG/Parent/Worker boundary and saved-plan replay; seed/reuse existing inputs labeled. Focused render set only; no old full batch rerun, userdb/sharedVM/game unaffected.
- [x] One fresh review of code+budget+data scope, maxone repair review. Only then one C02 real call/new distinct batch (max1, reserve0.096 cap0.10), priorledger seals, official confirmed model mapping rechecked same day before/after; no retries.
- [x] Original/old/improved same-location equalLUFS constant-gain clips and added-track solo, separate fit/clarity/phrase/preference human rubric. Check measured encoded LUFS/truepeak; no compressor/EQ-loudness trick. Small Library upload via current skill once and report actualID/failure.
- [x] Close exact owned resources, scoped storage gate/keep-set, update status/roadmap/technical evidence, normal dev commit/push+remote readback. Report actual calls/usage/estimated fees and limitations, no claim of human taste pass.

Execution evidence: docs/evidence/2026-10-21-p23-musical-fit.md and .json. Final Git commit/push readback is recorded in task workspace delivery-handoff; music acceptance remains pending.
