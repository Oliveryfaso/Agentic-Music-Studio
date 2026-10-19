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

Record the Git revision and working-tree state of `docs/PROJECT_GUIDE.md` at task start and recheck its diff before handoff. Do not compute a content hash unless an integrity/idempotency protocol or explicit acceptance requirement needs one. Stop and reconcile evidence if the guide, implementation status, roadmap, code, migrations, or tests disagree.

## Active gate

`G0` and `S1`–`S7` are historical completed portfolio gates. The user authorized P1 A2/B work (ADR-019). P0, P1-A1, pack contracts, A2.1 internal export files, and C1 internal real-piano boundary are accepted. User approval explicitly covered normal detach/readwrite reattach of the same UnityWorkspace image and task-local official 7-Zip; both succeeded. WAV/CC0/SFZ checks and real 30s piano A/B/legacy rollback are verified. Production IR/Job/API/UI remains v1; no persistent new-piano Undo or pedal is admitted. Isolated PostgreSQL is now available from cached image: two real baseline tests passed, migration head 20260824_0021; own disposable container/credentials were removed at closure. Colima/shared historical services remain running and untouched. Next production Task is A2.2 then B, after the requested minimal test audit. Use `docs/evidence/2026-10-19-p1-c1-real-piano.md` and existing P1 plans. Preserve manual model settings and legacy IDs/projects/sounds. No paid API, large packs, new implicit installations, shared-VM shutdown, public push or release.

## Scope and traceability

- Every implementation plan and completion report must name the current stage and all covered `MF-Pxx` requirements.
- Do not change an unlisted product requirement as incidental cleanup.
- A target written in `PROJECT_GUIDE.md` is not an implemented feature. Only runtime evidence can move a capability in `IMPLEMENTATION_STATUS.md`.
- Preserve the final contracts for complete-song output, legacy four-Style-Pack compatibility and the approved classical/jazz focus, DeepSeek, one Parent Graph, HITL, complete export, DAW editing, the approved visual language, security/copyright, Eval and recovery even when an internal walking skeleton is smaller.
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

## Portfolio Engineering Mode

- Protect the complete Agent architecture and the current user journey before adding production-platform breadth. Never trade away the single Parent Graph, bounded structured model output, deterministic compiler/Fallback, hash-bound HITL, immutable Revision, persistent recovery, complete export, truthful usage, or secret isolation.
- A Task normally proves its new behavior with focused RED/GREEN tests plus one real boundary integration. Run combined/full regression at a cross-service checkpoint, every 2–3 Tasks, and at each stage final gate—not after every local edit.
- A Task normally receives one independent review and at most one repair re-review. Critical issues always block. Important issues block when they affect the current user path, irreversible data, secrets/permissions, duplicate model spend, HITL, idempotent side effects, or restart recovery. Record other Important/Minor findings under the roadmap's deferred hardening register.
- Execute one implementation Task per fresh Codex session when practical. Start from the latest clean Git checkpoint and a compact `session-handoff`; do not carry full historical review transcripts into the next Task. Give any necessary subagent only the active Task, required contracts and current diff.
- If a blocking Critical/current-path Important remains after the one repair re-review, stop the Task, record the exact blocker and ask for direction. Do not hide it, lower its severity, or start an unbounded review loop.
- Do not require exhaustive crash/cancel/concurrency permutations, every historical populated downgrade, load/P95 testing, multi-tenant isolation, or full observability infrastructure before the creative workflow exists. Add one representative case now; promote further cases only when a real failure, repeated defect, public-release boundary, or measured bottleneck triggers them.
- Do not use this mode to waive TDD, schema validation, migrations for persisted changes, one real PostgreSQL boundary, or stage-end Compose/live evidence. It reduces repeated proof, not architecture or music-product quality.
