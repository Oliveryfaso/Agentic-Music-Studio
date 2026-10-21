# P2.3 Daily Editing Stability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline. One fresh whole-slice review, maximum one narrow repair recheck.

**Goal:** Keep the human-approved v5 sound baseline while proving repeatable in-product local edits and truthful constraint/usage states.
**Architecture:** Existing Parent/API/PG/Plan/IR/Worker/HITL/Undo/A-B remain; extend focused offline Eval/PG evidence and bounded PianoPanel UI only.
**Tech Stack:** Existing Python3.12/FastAPI/PostgreSQL, React/TypeScript/Vitest, Chromium/Tone/FFmpeg. No new dependencies.
**Spec:** Task workspace gaps-and-design.md, direct user continue + three requested risk dimensions.

## Global Constraints

- Stage P2.3; MF-P04/P05/P06/P10/P11/P13/P15/P16/P18/P20/P21.
- Base36d2a3e; dev codex/motif-p0-piano-preparation; Guide d68b900 clean/main unchanged; no deploy.
- Preserve accepted package/9clips/plans/paused historical ledgers; no Prompt/DSP/mix changes.
- Old postapproval9calls/19161tokens/upper¥0.053748 not bill; same cumulative¥10. New live maximum1/reserve¥0.096/batch¥0.10, no retry, same official service/data.

## Review Focus

- Reopened accepted/undone revisions must prove register across mixed ancestry; no inferred octave or extra submission.
- Explicit helper text must not automatically submit or change restored unknown request identities.
- Partial usage may expose reported total but not invent reasoning/cache/cost or known0.
- Stale/head conflicts, invalid range and model lock violations must leave source/head intact and create no candidate/Job.
- Synthetic fixtures and stored-plan seeds must remain clearly offline; no musical-quality/generalization claim from proxy passes.

### Task1: applicability and multiround proof

**Files:** tests/eval/test_piano_fit_scope_eval.py (new); tests/integration/test_postgres_piano_multiround.py (new), existing helpers reused by import only when portable.
**Consumes:** reviewed_score, piano_fit_context(base,start_bar,end_bar,include_harmony), compile_piano_plan; existing workflow/approval/undo/repository APIs.
**Produces:** executable meter/range/density/rest success + named failure cases; PG append→edit1–4→edit3–6→Undo→tail-edit proof, saved replay and stale rejection.
- [x] Add small3score start/mid/end scope matrix with allowed chords/pulse, no competing harmony in modify, terminal rest only when scope ends at source end; originalIR unchanged.
- [x] Adversarial wrong meter/source, out-of-bar gate, missing coverage, range-spanning note and performance conflict fail before provider; no weakening to pass fixtures.
- [x] Add PG one representative overlapping-edit chain with actual Provider MockTransport and exact protected/outside notes, locked chords/octaves, repeated workflow preparation zeroextra calls, Undo exactIR/hash, re-edit through ancestor lineage, stale branch and wrong hash reject.
- [x] Run narrow offline Eval/tests then the new PG case on owned disposable database, alongside existing3scorePG case only as needed for untested source boundary.

### Task2: explicit daily user controls

**Files:** apps/web/src/features/studio/PianoPanel.tsx, PianoPanel.test.tsx; contract + evidence/docs.
**Consumes:** existing semantic DTO and stored body/key; source report bars/beats; existing error_code and usage_status/total_tokens.
**Produces:** explicit text-fill preset, range/source guidance, actionable known errors, partial-total display; no new DTO or automatic calls.
- [x] Write RED for explicit preset presence/action (no submission), partial2501tokens without confirmed fee, and known register/stale error explanation; verify intended failures.
- [x] Implement exact small UI additions. Preset `这几小节更稀疏、更轻，保留原和声与音区，其余保持不变。`; full request remains textarea-derived and retry storage unchanged.
- [x] Verify existing remount/retry/default-range/dirty/hash-approval tests, new preset/copy/partial tests; fullWeb TS and required Web suite/build once at cross-service gate.

### Task3: real day-to-day boundary and close

**Files:** task-only owned runtime/probe/browser/gates, sanitized docs/evidence/2026-10-21-p23-daily-stability.{md,json}; current status/roadmap/history, plan.
- [x] Build workspace-only current UI; actual UI/API/ownedPG/productionWorker append saved accepted plan(seed explicitly offline)→local edits→A/B/keep/reopen/Undo→stale/repeat checks, no model network while offline. Preserve baseline event/media identity.
- [x] One fresh independent review of product diff + live scope/money/identity; one limited repair recheck if needed, no paid until clear.
- [x] If offline evidence supports it, one live C02 tail edit on accepted-plan seed, same UI/API/Worker flow, exact melody/harmony/register/outside; official pre/post source receipts, durable new batch+prior seals, immediate first-result update. Fail once and pause; never paid seed/retry.
- [x] Deliver small new human A/B in product path plus offline fallback/Library, retain accepted full package unchanged. Do not call automatic invariants human acceptance.
- [x] Close exact owned processes/PG/DSN, persist keep-set/inventory before scoped cleanup and after-check; update evidence/status/roadmap/history and prepare normal dev checkpoint/push + remoteSHA readback. The Git action is performed after this plan is saved; its authoritative completion receipt is in the task final handoff, not a precomputed commit hash.


Execution close: concrete evidence is docs/evidence/2026-10-21-p23-daily-stability.{md,json}. All technical slice items above are complete; current commit/push is the final authorized delivery operation and is reported after remote readback. One actual call/2465tokens/upper¥0.006250, cumulative¥0.059998 not bill; no retry. Human local-edit listening remains pending.
