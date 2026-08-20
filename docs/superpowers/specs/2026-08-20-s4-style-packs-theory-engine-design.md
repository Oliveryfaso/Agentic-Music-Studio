# S4 Style Packs and Theory Engine Design

**Date:** 2026-08-20

**Status:** Approved for implementation
**Scope:** Portfolio-grade S4 only

## Outcome

The existing Brief → PlanApproval → Revision → seven-step export flow will generate four structurally distinct, fully renderable works: Synth Ambient, Minimal Electronic, Classical Chamber, and Jazz Harmony & Improvisation. Every result records a versioned Style Pack, deterministic compiler, structured theory evidence, curated source citations, and a license snapshot.

S4 demonstrates Agent/LangGraph skill through explicit strategy routing and observable deterministic tool boundaries. It does not add a third production Graph, direct model writes, dual candidates, Critic/Repair orchestration, full DAW editing, multi-tenant hardening, or broad load testing.

## Architecture

The single Parent Graph v2 remains authoritative. `ValidateGenerate` resolves an allowlisted Style Pack from the Brief; planning produces the existing strict `CompositionPlan`; PlanApproval remains the only write authorization. Materialization calls one `MusicStrategyRouter`, which selects one deterministic compiler and then runs the shared Theory Engine. Only a successful build may enter the existing Preview/Revision/export path.

```text
Brief
  -> Parent Graph v2 / ValidateGenerate
  -> StylePackRegistry.resolve(style)
  -> Composition Planner (DeepSeek or deterministic fallback)
  -> PlanApproval interrupt
  -> MusicStrategyRouter.compile(approved Plan)
       -> style-specific PatternSpec compiler
       -> TheoryEngine.evaluate(ArrangementIR, StylePack)
  -> immutable Revision
  -> existing seven-step export
  -> Web Studio + style/source/theory explanation
```

The four strategies are bounded code paths inside the existing Generate subgraph. They are not independent workers and do not chat with each other. Future S5 loops may reuse their common `StrategyInput`/`StrategyResult` contracts.

## Versioned Knowledge Contracts

`StylePack v1` is strict, immutable, and contains:

- `pack_id`, `version`, genre/era and compatible schema/engine versions;
- form templates, instrument roles and MIDI ranges;
- harmony, rhythm and timbre constraints plus avoidances;
- production recipes and reviewed preset palette entries;
- symbolic exemplar references containing derived structural facts only;
- source citations and a license snapshot.

Built-in packs are curated JSON package assets. S4 accepts only project-authored or public-domain/CC0 symbolic knowledge and project-authored built-in synth presets. No network retrieval, sampled commercial recording, NC asset, or unreviewed free text is executable. Citation text may explain a choice but cannot decide note legality.

## Theory Engine

The engine consumes authoritative `ArrangementIR` plus its Style Pack and emits ordered `TheoryIssue` values. Each issue includes stable rule ID, severity (`error`, `warning`, `advice`), bar/track evidence, explanation code, and one bounded suggested operation.

Errors block materialization. Warnings and advice are persisted in materialization/run evidence and shown to users but do not block. Initial deterministic rules cover common track/range/form facts and the style-specific evidence required by the roadmap:

- Synth Ambient: role coverage, sparse density and supported registers;
- Minimal Electronic: drum/bass lock, stable grid and section energy contrast;
- Classical Chamber: instrument ranges, voice crossing, and parallel fifth/octave warnings;
- Jazz: guide tones, bounded tensions/avoid notes, voicing span and swing-grid evidence.

S4 intentionally implements conservative symbolic checks over generated facts. It does not claim perceptual audio quality or complete conservatory-grade analysis.

## Deterministic Compilers

All compilers return the existing `CompositionBuild` and preserve the four shared export roles (`harmony`, `melody`, `bass`, `rhythm`) so the seven-step export contract remains unchanged. Track names, instruments, form, progression, rhythm grids, registers, articulation and density differ by style. The same project/Plan/seed remains deterministic.

Classical and Jazz are real playable strategies, not metadata aliases: their note/register/voicing/rhythm facts must differ from Synth Ambient in tests. Built-in synthesis limits acoustic realism; S4 evaluates structure and lineage, not orchestral sample realism.

## Persistence and Read Model

The existing `composition_plans.style_pack_version`, materialization receipt, `VersionRefs.knowledge/compiler`, Candidate/Revision lineage and run events remain authoritative. No migration is needed unless structured theory evidence cannot fit the existing event payload safely. The public Run/Project read model exposes a bounded explanation containing pack identity, citations, license label and issue summaries; it never exposes prompt internals or arbitrary retrieved text.

## Web State

Brief adds an explicit four-option style selector. Plan Review and Studio show the selected Pack version, a compact “why this strategy” summary, source/license badges, and theory findings separated into blocking rules and non-blocking suggestions. Existing loading, empty, error, replay, mobile overflow and PlanApproval behavior remain unchanged.

## Failure Policy

- Unknown style/pack/version: fail closed before planning or model spend.
- Invalid/unreviewed license metadata: fail closed during pack load.
- Theory `error`: terminal stable `PLAN_STRATEGY_INCOMPATIBLE`, no Revision or Job.
- Theory warning/advice: continue and expose evidence.
- Model/provider failure: existing no-key deterministic fallback, now style-safe for all four packs.
- Export/restart/cancel: unchanged S2/S3 contracts.

## Evaluation and Cost

Portfolio-grade acceptance uses targeted unit tests, one real PostgreSQL boundary, four representative deterministic Eval cases, and one Compose/browser journey that selects and completes each style. Assertions cover distinct IR facts, Pack/version/citation/license lineage, theory severity separation, Revision and seven-job export counts, and zero paid requests in deterministic mode.

A paid DeepSeek call is not required unless the changed prompt/provider schema cannot be validated deterministically. If required, allow one explicitly attested call and reuse the existing persistent budget/idempotency gate.

## Non-goals

- S5 dual candidates, Evidence Critic and Repair loops.
- S6 Piano Roll/Mixer editing and AI selection edits.
- External RAG/vector database or asset marketplace.
- High-quality orchestral/jazz sample library.
- S7 load, P95, multi-tenant and exhaustive fault matrices.
