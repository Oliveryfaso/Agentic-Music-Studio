# P1 B/C2/D/E independent review

What this change does: It adds a persistent, human-approved real-piano interpretation to the existing Parent Graph, including audition, saved v2 project state, canonical export, and exact-parent Undo. Legacy IR/engine schemas remain separate.

Scope: BASE `a099cc50893b1ee0fe714bade595af25c11a170b` to the reviewed dirty tree, including all 23 untracked files and 52 tracked modifications. Stage P1-B/C2/D/E; MF-P01/P02/P05/P06/P08/P10/P11/P13/P15/P16/P17/P18/P20/P21. Guide revision `e3d943844b77c177b93437abfe530c989989feee`; no Guide diff at start or handoff. Required repository documents, development skill/checklists, active plan, review brief, and ledger rulings read. One fresh review, no implementation or agents.

## Must fix — Important

1. **The retry button cannot recover after a temporary preparation failure.** `apps/web/src/features/studio/PianoPanel.tsx:30–38`, with `services/api/src/motif_forge/api/piano.py:153–175`.
   - Trigger: capability was available when loaded, then the renderer becomes unavailable before preparation. Preparation stores a terminal `RENDER_SERVICE_UNAVAILABLE` or `INSTRUMENT_PACK_UNAVAILABLE` checkpoint and POST returns 503. After the renderer recovers, the panel retains the same intent key because it clears it only on success; clicking “重试 A/B 试听” replays the terminal failure without retrying preparation.
   - Reproduced using the production API router and Parent Graph with InMemorySaver and a controlled service: first request 503; restore service; same-key retry 503 and total prepare calls still 1; a fresh key returns 202/`waiting_piano_worker`. This blocks the visible recovery action unless the user changes an expression setting or remounts the page.
   - Smallest fix: preserve the key for ambiguous network failures, but create a fresh intent after known terminal capability/preparation errors that occurred before Preview/Job effects. Cover both cases so a lost response still reuses its original key.

2. **A saved piano version accepts timbre changes that the renderer ignores.** `services/api/src/motif_forge/domain/commands.py:661–674`, `services/api/src/motif_forge/application/rendering.py:213–240`; reachable through `apps/web/src/features/studio/StudioPage.tsx:167`.
   - Trigger: open a saved v2 piano, choose `builtin:viola` in the existing sound library, then save. The human `set_track_param(instrument_ref)` command is accepted as L1 and changes the stored instrument reference. The v2 compiler always uses the piano render profile and ignores that reference, so subsequent audio remains piano.
   - Reproduced through the actual domain command and compiler: `saved_instrument_ref=builtin:viola`, `command_impact=L1`, arrangement hash changed, but graph and graph hash are identical and the rendered kind remains `multisample`. This is an accepted current Studio operation with no audible result.
   - Smallest fix: reject unsupported `instrument_ref` changes under the fixed piano-v2 contract and disable/explain that library action for v2. Keep the explicit approved piano Undo as the route back to legacy sounds.

No Critical or additional Minor findings established. Verdict: fix 1 and 2 before accepting this vertical.

## Checks and evidence

Commands ran from `/Volumes/KINGSTON/idea/agentic-music-workbench` unless stated otherwise:

```sh
env -u MOTIF_FORGE_POSTGRES_DSN PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider services/api/tests/unit/domain/test_performance_v2.py services/api/tests/unit/agent/test_piano_preview_graph.py services/api/tests/unit/api/test_piano.py services/api/tests/unit/application/test_piano_study.py services/api/tests/unit/application/test_piano_capability.py services/api/tests/unit/audio/test_chromium_render.py -q
# 29 passed

env -u MOTIF_FORGE_POSTGRES_DSN PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider services/api/tests/unit/domain services/api/tests/unit/application/test_undo.py services/api/tests/unit/application/test_rendering.py services/api/tests/unit/application/test_export_v2.py -q
# 251 passed

npm run test:audio -- --reporter=dot
# 59 passed
npm run test:web -- --reporter=dot
# 87 passed
git diff --check
git diff --exit-code -- docs/PROJECT_GUIDE.md
# both passed
```

From `/Users/oliver/Documents/Codex/2026-10-18/task-2`:

```sh
python3 research/run_a22_checks.py env -u MOTIF_FORGE_POSTGRES_DSN /Volumes/KINGSTON/idea/agentic-music-workbench/.venv/bin/python -m pytest -p no:cacheprovider services/api/tests/integration/test_postgres_piano_v2.py -q
# 2 passed; only the authorized task-owned PostgreSQL instance
```

PG check log: `research/a22-runtime-2026-10-19/1792388143967355000.txt`. Initial sandbox PG/audio/web attempts were blocked by TCP/listener/ignored-cache permissions, then passed under approved scoped escalation; these were environment failures. The safe runner redacted generated credentials.

Read-only repros are saved under this execution workspace as `research/piano_review_retry.py` and `research/piano_review_instrument_ref.py`. Run either with the repository `.venv/bin/python`, repository cwd, `PYTHONPATH=services/api/src`, `PYTHONDONTWRITEBYTECODE=1`, and runtime DSN unset. They need no DB, model, renderer, or network.

Reviewed v1/v2 hashing and readers, migrated version guards, shared Tone/native adapter and catalog pins, Job/recipe/plan/receipt versions, candidate evidence collection and hash-bound approval, dispatcher routing, exact-parent Undo, Studio hash-matched audition fallback, and API/UI retry behavior. Existing persisted sequential replay/cancel/approval/Undo cases passed. No public generic Preview/Decide route was found: direct generic services are internal; public piano decisions use the facade and AI edit decisions check run ownership/evidence. No concrete public approval bypass was established.

The API pins seed and the whole body in its Parent checkpoint; thread identity is derived from project/key, and Job enqueue fingerprints also include seed/thread. Missing seed/thread in the Preview subservice fingerprint alone did not establish a separate bug. Simultaneous first requests were not stress-tested.

Reviewed the submitted `docs/evidence/2026-10-19-p1-piano-production.json` and probe sources. Its real PG/Chromium/live-UI evidence supports the finite happy path but does not cover the two findings. I did not independently repeat the actual five renders, built browser flow, or listening assessment. No Redis/Celery/Compose, power-loss, multi-user, exhaustive concurrency, pedal/release-trigger, MF-P09 filtering, or P2+ acceptance claim. No paid/model calls, .env/credential inspection, shared-service controls, or product edits by this reviewer.
