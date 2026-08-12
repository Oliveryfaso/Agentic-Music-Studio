# S1 Deterministic Complete-Song Walking Skeleton Plan

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:executing-plans` and `superpowers:test-driven-development`. Complete tasks in order; do not begin S2 work.

**Goal:** Produce, render and export one deterministic 60–90 second four-track Synth Ambient composition without an API key, while proving the Revision → Job/Outbox → Chromium Worker → Artifact → Export Bundle fact chain.

**Architecture:** A pure deterministic Composer turns versioned `PatternSpec v1` values into audited System/Editor Commands and one immutable `ArrangementIR` Revision. A single Python projection converts tick truth to the existing versioned `AudioGraphSpec`; the existing TypeScript/Tone compiler remains the only audio renderer. PostgreSQL owns Job state, Redis/Celery provides at-least-once delivery, a resource-bounded internal Chromium service renders PCM24 files to a shared external Artifact root, and Python validates/promotes every result. Master, four Stem and MP3 outputs remain separate Audio Artifacts; one protected Export Bundle manifest binds them to MIDI, canonical Project JSON, credits/license/provenance and trace manifests without duplicating audio bytes.

**Tech Stack:** Python 3.12, Pydantic v2, SQLAlchemy/PostgreSQL/Alembic, Celery/Redis, TypeScript, Tone.js/Web Audio, Playwright Chromium, FFmpeg, Docker Compose.

## Scope and invariants

- Covered requirements: `MF-P02`, `MF-P10`, `MF-P15`, `MF-P16`, `MF-P17`, `MF-P18`, `MF-P21`.
- Fixed baseline: 24 bars, 4/4, 80 BPM, C major, four tracks (`pad`, `melody`, `bass`, `rhythm`), one candidate, fixed seed, 72 seconds.
- No DeepSeek/API key, Timeline editor, second candidate, RAG/vector database, external sound search, large sound pack or generic storage-platform expansion.
- PPQ ticks remain Project truth. Seconds appear only in `AudioGraphSpec` render projection.
- Canonical Master/Stem are 48 kHz stereo PCM24. MP3 is a delivery derivative; it never replaces the canonical Master.
- From-zero generation is high-impact. The internal S1 command must carry an explicit approval assertion and emit a Revision/audit record; S2 will replace this internal assertion with Graph HITL.
- The external Artifact root is mandatory in the Lean profile. Render output never falls back to the internal disk and bytes never enter Redis, PostgreSQL JSON, Graph state or Playwright return values.
- Guide SHA-256 at plan start: `6ccfc0c8941b88efcff5e9a4f6de57bb7f659590188330d63a7435f7637fe7b2`; final independently reviewed contract hash after the deliberate stage-status update: `21345f64304338777a9dd2603d34ad54448b6c4b82902bc743204ba1026c9f58`.

---

### Task 1: Freeze PatternSpec v1 and deterministic composition commands

**Files:**
- Create: `services/api/src/motif_forge/domain/composition.py`
- Modify: `services/api/src/motif_forge/domain/commands.py`
- Modify: `services/api/src/motif_forge/domain/policies.py`
- Create: `services/api/src/motif_forge/application/composition.py`
- Create: `services/api/tests/unit/domain/test_composition.py`
- Create: `services/api/tests/unit/application/test_composition.py`
- Create: `evals/s1_deterministic_cases.jsonl`
- Create: `services/api/tests/eval/test_s1_deterministic_eval.py`

**Contracts:**
- `PatternSpec v1` contains `pattern_id`, `section_id`, `track_role`, `bar_range`, `chord_degrees`, `rhythm_grid`, `register`, `density`, `syncopation`, `variation_seed`, and `locked_constraints`.
- `InitializeCompositionCommand` is a generated-candidate command, sets tempo/meter/key/sections/provenance before ordinary `AddTrackCommand` values add material, and is always classified L3 when Agent-authored.
- `build_s1_composition(project_id, seed) -> CompositionBuild` returns frozen PatternSpecs, ordered commands and the validated ArrangementIR.
- `PrepareDeterministicCompositionPreview` sends those Agent-authored commands through the existing immutable Candidate/Preview path; the existing `DecidePreview(APPROVE)` is the sole operation that materializes the L3 Revision, advances the Branch with optimistic concurrency and records approval/audit events.

- [x] **Step 1: Write failing schema, range, reproducibility and command-audit tests.**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/motif-forge-venv UV_CACHE_DIR=/Volumes/KINGSTON/idea/.motif-forge-data/cache/uv UV_LINK_MODE=copy uv run pytest -q services/api/tests/unit/domain/test_composition.py services/api/tests/unit/application/test_composition.py
```

Expected: fail because the schemas/use case do not exist.

- [x] **Step 2: Implement the smallest deterministic Composer.**

Use UUID5 identities derived from project/seed/section/role; compile pad chord realization, motif, bass and pulse/drum NoteEvents. Validate section closure, per-role ranges, polyphony, event bounds, 72-second duration and exactly four tracks.

- [x] **Step 3: Add at least 20 Eval cases and a parameterized runner.**

Cases cover valid deterministic seeds, Pattern field/range boundaries, structure closure, note bounds, role range, polyphony, stable hashes and forbidden unapproved materialization.

- [x] **Step 4: Run focused tests, Ruff and Mypy.**

---

### Task 2: Establish the one-way ArrangementIR → AudioGraphSpec projection

**Files:**
- Create: `services/api/src/motif_forge/domain/rendering.py`
- Create: `services/api/src/motif_forge/application/rendering.py`
- Create: `services/api/tests/unit/application/test_rendering.py`
- Modify: `packages/audio-engine/src/contracts.ts`
- Modify: `packages/audio-engine/src/presets.ts`
- Modify: `packages/audio-engine/src/validation.ts`
- Modify: `packages/audio-engine/src/wav.ts`
- Modify: `services/render-worker/src/page-entry.ts`
- Modify: `packages/audio-engine/tests/audio-engine.test.ts`

**Contracts:**
- `compile_audio_graph(arrangement, render_track_ids=None)` maps tick/tempo to seconds, maps reviewed `builtin:*` instrument refs to pinned synth/sampler presets, rejects audio tracks and unknown presets, and returns a canonical hash.
- `AudioGraphSpec` remains the sole TypeScript render contract. Canonical requests explicitly select PCM24; preview compatibility may retain PCM16.
- Add small synthesized presets only; no binary sound pack is introduced in S1.

- [x] **Step 1: Write failing Python projection and TypeScript PCM24/preset tests.**
- [x] **Step 2: Implement tick projection, stable hashing, PCM24 encoding and bounded preset additions.**
- [x] **Step 3: Run Python rendering tests plus `npm run test:audio` and `npm run build:audio`.**

---

### Task 3: Generalize the Chromium Spike into a controlled internal render service

**Files:**
- Create: `services/render-worker/src/server.ts`
- Modify: `services/render-worker/src/runtime.ts`
- Modify: `scripts/build-render-worker.mjs`
- Modify: `services/render-worker/Dockerfile`
- Modify: `services/render-worker/tests/runtime.test.ts`
- Create: `services/render-worker/tests/server.test.ts`
- Modify: `compose.yaml`
- Modify: `.env.example`

**Contracts:**
- Internal `POST /v1/render` accepts a versioned render-service request containing a `RenderBridgeRequest`, a repository-relative temp storage key, maximum bytes and deadline.
- The service rejects absolute/traversal paths, unsupported schemas, concurrent over-capacity work and oversized output; it reuses one Chromium process/page at concurrency 1.
- It returns metadata/checksum only. Audio is written through an atomic loopback sink under the mounted external root.
- Disconnect/timeout closes the active page and returns a stable error code; partial files are removed.

- [x] **Step 1: Write failing path, capacity, request-version, timeout and health tests.**
- [x] **Step 2: Implement the persistent service and pinned health endpoint.**
- [x] **Step 3: Run TypeScript tests/build and the existing 30-second Spike regression without rebuilding Docker.**

---

### Task 4: Add formal Render/MP3/Export Bundle Jobs and persisted Artifact lineage

**Files:**
- Modify: `services/api/src/motif_forge/domain/media_jobs.py`
- Create: `services/api/src/motif_forge/domain/exporting.py`
- Modify: `services/api/src/motif_forge/application/media_jobs.py`
- Create: `services/api/src/motif_forge/application/exporting.py`
- Modify: `services/api/src/motif_forge/application/ports.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/tables.py`
- Modify: `services/api/src/motif_forge/infrastructure/persistence/media_jobs.py`
- Create: `services/api/src/motif_forge/audio/chromium_render.py`
- Create: `services/api/src/motif_forge/audio/midi.py`
- Create: `services/api/src/motif_forge/audio/transcode.py`
- Modify: `services/api/src/motif_forge/worker/execution.py`
- Modify: `services/api/src/motif_forge/worker/outbox.py`
- Modify: `services/api/src/motif_forge/config.py`
- Create: `infra/migrations/versions/20260812_0010_render_export_bundle.py`
- Add focused unit/integration tests under `services/api/tests/`.

**Contracts:**
- `RenderJobPayload v1`: revision ID, `master|stem` scope, optional track IDs, engine version, seed, expected AudioGraph hash and timeout.
- `ExportMp3JobPayload v1`: canonical Master Artifact ref, revision ID, 256 kbps delivery profile and timeout.
- `ExportBundleJobPayload v1`: revision ID plus Master/MP3/four Stem Artifact refs and pinned schema/engine/seed/trace refs.
- `ExportBundleArtifact v1`: protected logical bundle manifest with immutable file entries, checksum, byte total, revision lineage and availability.
- Each Job keeps PostgreSQL/Outbox/Celery idempotency, lease, attempt, deadline, heartbeat and duplicate completion semantics. Worker validates root availability, graph hash, WAV receipt, checksum, sample rate, channels, bit depth, duration, non-silence and lineage before completion.

- [x] **Step 1: Write failing domain/job/worker/persistence tests, including timeout, checksum mismatch, missing root and duplicate completion.**
- [x] **Step 2: Add migration and strict schemas; verify upgrade/downgrade SQL.**
- [x] **Step 3: Implement Chromium client, PCM validation/promotion, MP3 transcode, standard-library MIDI and deterministic bundle writer.**
- [x] **Step 4: Wire job execution and persistence with no raw path accepted from API/model payloads.**
- [x] **Step 5: Run focused tests, real PostgreSQL integration, Ruff and Mypy.**

---

### Task 5: Provide the internal S1 smoke path and close the stage gate

**Files:**
- Create: `scripts/run_s1_deterministic_smoke.py`
- Create: `scripts/check_s1.sh`
- Modify: `README.md`
- Modify after evidence: `docs/IMPLEMENTATION_STATUS.md`
- Append after evidence: `docs/TECH_EVOLUTION.md`
- Modify after evidence: `AGENTS.md`

**Flow:**

```text
Create Project
→ build PatternSpecs/commands
→ explicit internal approval
→ immutable Revision
→ enqueue/poll Master Render
→ enqueue/poll four Stem Renders
→ enqueue/poll MP3 Transcode
→ enqueue/poll Export Bundle
→ verify every manifest entry and checksum
```

- [x] **Step 1: Write the smoke script and fail it on incomplete/mismatched artifacts.**
- [x] **Step 2: Run the full host baseline before Docker changes.**
- [x] **Step 3: Build only changed API/Media/Render targets, migrate, and run the Compose S1 smoke.**
- [x] **Step 4: Inject one Worker retry, duplicate dispatch/completion and external-root disconnect case; verify explicit terminal/recovery results.**
- [x] **Step 5: Re-run full Python, PostgreSQL, Audio, Web, migration and readiness checks.**
- [x] **Step 6: Execute the stage-end Storage Hygiene Gate.**

Inventory first. Keep current tagged runtime images, PostgreSQL/Redis volumes, the accepted S1 bundle, lockfiles and the next-stage environment. Remove only exact obsolete project Spike outputs, abandoned `.partial` files and proven project-owned cold cache. Do not run broad system/image/volume prune commands.

- [x] **Step 7: Close independent review findings, recheck the guide hash, document evidence, create a Git checkpoint and push.**

S1 may be marked complete only when the fixed composition produces readable Master WAV/MP3, four Stems, MIDI, canonical Project JSON and all manifests with verified checksums and lineage, and the documented failure cases pass. The accepted implementation additionally requires `audio-artifact.v2` structured Revision lineage, duration/non-silence MP3 probes, persisted running cancellation, real temp/lease storage facts, and a logical Bundle that does not duplicate audio bytes. Otherwise leave S1 active and record the exact incomplete subgate.
