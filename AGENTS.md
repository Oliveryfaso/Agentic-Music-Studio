# Motif Forge Agent Instructions

These instructions apply to the entire repository.

## Required reading before work

Read in this order before planning, coding, reviewing, testing, or editing documentation:

1. `docs/DECISION_LOG.md`
2. `docs/PROJECT_GUIDE.md`
3. `docs/IMPLEMENTATION_STATUS.md`
4. `docs/NEXT_DEVELOPMENT_ROADMAP.md`
5. `.agents/skills/motif-forge-development/SKILL.md`
6. Only the specialized contract/checklist relevant to the active slice

Record the SHA-256 of `docs/PROJECT_GUIDE.md` at task start and recheck it before handoff. Stop and reconcile evidence if the guide, implementation status, roadmap, code, migrations, or tests disagree.

## Active gate

`G0` and `S1` are complete. `S2` is the only active gate. S2 Tasks 1–5 are implemented and independently approved through atomic approved-Plan materialization; Task 6 has not started. Resume at reusable complete-song Render/Export orchestration, then Parent Graph/API/recovery/Eval/live acceptance. Do not start S3 or later product work, and do not claim DeepSeek is live, until all S2 gates pass.

## Scope and traceability

- Every implementation plan and completion report must name the current stage and all covered `MF-Pxx` requirements.
- Do not change an unlisted product requirement as incidental cleanup.
- A target written in `PROJECT_GUIDE.md` is not an implemented feature. Only runtime evidence can move a capability in `IMPLEMENTATION_STATUS.md`.
- Preserve the final contracts for complete-song output, four Style Packs, DeepSeek, one Parent Graph, HITL, complete export, DAW editing, the approved visual language, security/copyright, Eval and recovery even when an internal walking skeleton is smaller.
- Use “short pre-development closure + optimization within vertical slices.” Do not start a repository-wide refactor or add infrastructure without a current user-value consumer.

## Implementation discipline

- Write a slice-specific plan under `docs/superpowers/plans/` before product code.
- Use tests first, then the smallest implementation; run narrow checks before integration checks.
- Keep ArrangementIR/Revision as project truth, PPQ ticks as persistent music time, and large media in the Artifact Store.
- Keep model output structured and bounded. Deterministic code owns timing, theory validation, rendering, storage, transactions, retries and hard budgets.
- Add at least one Eval success case and one failure label with every creative slice.
- Use host-first development. Build only a changed Docker target at a documented integration/stage gate.
- Never commit secrets, `.env`, user audio, external Artifact contents or caches. Do not hardcode machine-specific paths in product code/config; an explicitly labeled, already validated local-development command in documentation may name the current external root but must have a portable variable-based alternative.
- After an accepted slice, update `IMPLEMENTATION_STATUS.md`, append evidence to `TECH_EVOLUTION.md`, create a Git checkpoint, and run the scoped storage hygiene gate.
