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

`G0` closed with implementation checkpoint `6bf21f5` pushed to `origin/main`. The current gate is `S1` in `docs/NEXT_DEVELOPMENT_ROADMAP.md`: deterministic complete-song Walking Skeleton. Do not start S2 or a later product feature until S1 complete export, Eval, failure and recovery gates pass. Follow S1 → S7 in dependency order unless the user approves a documented route change.

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
