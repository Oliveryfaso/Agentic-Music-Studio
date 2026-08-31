# Motif Forge

Motif Forge is a local-first, agent-assisted instrumental composition workbench. S1–S7 are complete at the personal-portfolio level: the browser supports four-style Briefs, Plan/HITL, two bounded candidates, Critic/Repair, A/B selection, a lightweight Studio with AI selection edits, complete export, Run inspection, Eval evidence, controlled multi-Stem import, and recoverable execution through one LangGraph Parent Graph.

## One-command quick start

From the repository root:

```bash
scripts/start_motif_forge.sh
```

The launcher initializes the existing external storage layout, starts Colima when Docker is not ready, starts the Compose API/database/queue/audio services, waits for readiness, starts Vite, and opens [http://127.0.0.1:5173](http://127.0.0.1:5173). The first launch may build missing images or install missing Web dependencies; later launches reuse them.

Useful variants:

```bash
scripts/start_motif_forge.sh --check
scripts/start_motif_forge.sh --no-open
```

When finished, stop the Web Studio, all Motif Forge Compose services, and the
Colima VM with the matching command:

```bash
scripts/stop_motif_forge.sh
```

The stop command is idempotent and preserves PostgreSQL volumes, Docker images,
imported media, generated works, and exports. It does not run `prune` or
`docker compose down -v`. If you only press `Ctrl+C` in the startup terminal,
Vite stops while the backend remains warm until the stop command is run.

The standard Compose profile deliberately keeps the DeepSeek key out of runtime containers and uses the deterministic no-key fallback, so the one-command launcher cannot create an accidental paid model call.

## 查看 Agent / LangGraph 执行路径

正式 Generate 流程中，Run 页面会显示一条紧凑的“执行路径”，用于快速判断当前处于规划、人工审批、候选生成、Critic、提交还是导出阶段。点击“查看完整 Graph”进入只读 Run Inspector，可以查看 `motif-forge-parent.v2` 的完整阶段、候选 A/B 并行分支、Worker 边界与重复导出循环。

Graph 只点亮已有持久证据的节点：`checkpoint_confirmed` 表示 LangGraph checkpoint task path 已确认，`event_confirmed` 表示安全应用事件已确认，`grouped_parallel` 表示两个匿名并行候选分支已按持久顺序归组。选择节点可查看受限证据和精确技术节点名，例如 `ValidateRequest`、`PlanApproval` 与 `CreateCandidateBranch`；页面不会读取或显示 checkpoint payload、Prompt、模型推理、审批断言、存储路径或密钥。

无需 DeepSeek Key 也可以走完演示：创建 Project → 新建编曲 → 填写 Brief → 审批 Plan → 比较并选择候选 → 等待 Revision/导出完成 → 在 Run Inspector 查看 Graph → 打开 Studio。Graph 读取异常不会阻断审批、候选选择、取消、结果或 Studio 操作，原有持久事件时间线仍可展开检查。

If Colima reports that it is already running but `--check` still says Docker is not ready, the existing Colima VM is stale. Recover it once without deleting its data, then launch normally:

```bash
colima stop
scripts/start_motif_forge.sh
```

Read documentation in this order:

1. [docs/DECISION_LOG.md](docs/DECISION_LOG.md) for approved invariants.
2. [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md) for final product and architecture contracts.
3. [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) for current code facts.
4. [docs/NEXT_DEVELOPMENT_ROADMAP.md](docs/NEXT_DEVELOPMENT_ROADMAP.md) for the active development route.

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker Compose for PostgreSQL/Redis integration work
- A DeepSeek API key only for explicit live-provider tests; unit tests never require one

## Manual setup and development

The commands below are the expanded development setup and troubleshooting path. Normal portfolio use should start with `scripts/start_motif_forge.sh` above.

This checkout is already on an external volume. Keep future audio artifacts and movable package/
browser caches on that volume, while retaining only the Python virtual environment on an internal
APFS temporary directory. On exFAT, an installed Python environment containing directory metadata
can acquire AppleDouble `._*` entries and fail wheel `RECORD` validation; uv's download cache has
been verified on the external root and remains movable. The first command
derives a sibling storage root from the current checkout, so the repository does not hardcode a
machine-specific volume name.

```bash
export MOTIF_FORGE_DEV_STORAGE_ROOT="$(cd .. && pwd -P)/.motif-forge-data"
scripts/bootstrap_external_storage.sh "$MOTIF_FORGE_DEV_STORAGE_ROOT"
export MOTIF_FORGE_STORAGE_PROFILE=lean
export PLAYWRIGHT_BROWSERS_PATH="$MOTIF_FORGE_DEV_STORAGE_ROOT/cache/playwright"
export npm_config_cache="$MOTIF_FORGE_DEV_STORAGE_ROOT/cache/npm"
export MOTIF_FORGE_ARTIFACT_ROOT="$MOTIF_FORGE_DEV_STORAGE_ROOT/artifacts"
export MOTIF_FORGE_TEMP_ROOT="$MOTIF_FORGE_DEV_STORAGE_ROOT/tmp"
export UV_PROJECT_ENVIRONMENT=/private/tmp/motif-forge-venv
export UV_CACHE_DIR="$MOTIF_FORGE_DEV_STORAGE_ROOT/cache/uv"
export UV_LINK_MODE=copy
uv sync --dev
uv run pytest
uv run ruff check .
uv run mypy
uv run uvicorn motif_forge.api.app:create_app --factory --reload
```

For the containerized PostgreSQL/Redis services, create a local environment file first:

```bash
cp .env.example .env
scripts/build_compose_images.sh api
scripts/build_compose_images.sh media-worker
docker compose up -d
```

On an Apple Silicon Mac without Docker Desktop, the validated low-storage runtime is Docker CLI +
Compose + Buildx on Colima. The VM profile used for this project is 4 CPU, 4 GiB RAM, a 15 GiB
sparse Docker data disk and an 8 GiB sparse root disk. These values are upper bounds, not immediate
allocations. Verify that both plugins are visible with `docker compose version` and
`docker buildx version`; Colima does not need Kubernetes, Rosetta or QEMU for this arm64 stack.

```bash
colima start --cpus 4 --memory 4 --disk 15 --root-disk 8 \
  --vm-type vz --mount-type virtiofs --runtime docker \
  --binfmt=false --ssh-config=false
colima ssh -- sudo sysctl -w vm.overcommit_memory=1
scripts/build_compose_images.sh api
scripts/build_compose_images.sh media-worker
docker compose up -d
scripts/check_compose_runtime.sh
```

If the host uses a localhost HTTP proxy, configure the Docker daemon proxy as described in the
[Docker daemon proxy documentation](https://docs.docker.com/engine/daemon/proxy/). A host shell
proxy alone does not configure the daemon inside Colima. Do not commit proxy addresses or
credentials to this repository.

The default local bootstrap keeps `MOTIF_FORGE_ARTIFACT_ROOT` and `MOTIF_FORGE_TEMP_ROOT` under one
external storage root for simpler capacity accounting. S1 Render and MP3 promotion is also safe
when the two roots become distinct container mounts: the Worker streams into a unique partial file
inside the final Artifact directory, verifies size/checksum, then atomically renames on that final
filesystem. The bootstrap script creates only the requested directories, verifies write access and
a same-volume rename, removes its empty probe directory, and never edits `.env` or deletes existing
content. The API now includes a deterministic root/quota
gate, exact-ID safe eviction, pinned time-stretch Audio Artifact rehydration, and independent
waveform/analysis Feature Artifacts with same-ID deterministic rehydration. It does not yet claim
generic render/transcode rehydration or a complete temporary-file ledger.

The default Lean Storage limits are 10 GiB globally, 2 GiB per project and 2 GiB for temporary
work. Candidate previews expire after 24 hours; rebuildable derived cache and terminal checkpoints
default to seven days. Imported originals, current-Revision dependencies and selected final Masters
are not cleanup targets. These limits are active inputs to Upload and Parent Graph storage gates;
cleanup is bounded to one database-selected pass and only evicts unprotected rebuildable Artifacts
with complete recipes.

At each accepted small-stage boundary, follow the project Skill's stage-end storage hygiene gate:
inventory first, preserve current tagged images/database volumes/final Artifacts, remove only exact
obsolete project outputs and unused build caches, then recheck disk usage and `/health/ready`.
Never use a broad volume prune or delete another project's named cache/image as routine cleanup.
During active development, explicitly warm only the targets that the next slice will use (selected
from API, Media Worker and Chromium Render Worker), then keep BuildKit near a 1.5 GiB target with a 2 GiB hard
ceiling. The tagged runnable images are the keep set; old source snapshots, failed builds and
superseded dependency/application layers are not. Run the guarded cleanup only after inspecting the
shared builder and opting in:

```bash
MOTIF_FORGE_ALLOW_SHARED_BUILDER_PRUNE=1 scripts/prune_development_build_cache.sh
```

When the project is feature-complete or a release is sealed, do not retain gigabytes of speculative
build cache. Keep lockfiles, current tagged/released images and reproducible build instructions; clear
all project-owned BuildKit cache. A shared builder must first have project ownership proven or be
replaced by a working project-owned builder, so release cleanup cannot erase another project's cache.
Build only the target changed in the current slice. The Media Worker keeps FFmpeg in a stable base
stage and copies the changing Python environment afterwards, so application-source changes do not
recreate the large FFmpeg installation layer. A dedicated Buildx builder is optional rather than a
project invariant: use one only after its proxy/network path and persistent overhead work on the
current host; otherwise keep the shared builder and stop before an ownership-ambiguous prune.

Use the host-first loop for Web Studio, TypeScript/audio packages, pure Python domain/application
changes and unit tests. Source changes alone do not trigger a Docker build. Rebuild only the affected
target for Dockerfile/system dependency changes, container-relevant lockfile changes, migrations or
runtime wiring, or an explicit cross-service/stage acceptance gate.

The current frontend workspace follows the existing npm lockfile. Keep npm's cache on the external
development volume per command instead of repairing or expanding the internal user cache:

```bash
npm_config_cache="$MOTIF_FORGE_DEV_STORAGE_ROOT/cache/npm" npm install
npm run dev:web
npm run test:web
npm run build:web
```

Playwright browsers may also use the external path above. If Chromium cannot execute from the exFAT
volume on a particular macOS release, move only `PLAYWRIGHT_BROWSERS_PATH` back to an internal cache;
the canonical Render Worker image, Docker engine data, PostgreSQL volume and Docker BuildKit cache
remain inside the Docker VM. Do not bind-mount PostgreSQL onto exFAT.

## Canonical Chromium Render Worker

The pinned Render Worker image uses Playwright Chromium and the shared TypeScript audio engine to
render canonical Master or isolated Stem Jobs. S1 validates a 72-second four-track composition at
48 kHz stereo PCM24. WAV bytes go through a one-time loopback
sink directly to the explicit Artifact root; they never pass through Redis, Graph state, base64, or
the repository. Build and run it with:

```bash
scripts/build_compose_images.sh render-worker
export MOTIF_FORGE_ARTIFACT_ROOT="$MOTIF_FORGE_DEV_STORAGE_ROOT/artifacts"
scripts/run_audio_spike.sh
```

The low-cost regression remains constrained to 2 CPU, 1 GiB RAM, 256 processes and no external
network. It validates
48 kHz stereo duration, non-silence, Stem isolation and repeat stability. Chromium floating DSP to
PCM16 can differ at the one-LSB quantization boundary, so the report exposes both SHA-256 values and
the bounded sample-difference metric instead of falsely claiming byte-identical output.
The Worker uses a pinned Node slim base plus Playwright's Chromium headless shell rather than the
full multi-browser Playwright image; the accepted local image is 1.48 GB instead of 4.04 GB. FFmpeg
time-stretch/transcode belongs to the controlled Python media-task boundary and is not duplicated in
this Chromium-only image.

With Compose running and migration head applied, the complete internal S1 acceptance path is:

```bash
export MOTIF_FORGE_POSTGRES_DSN='postgresql://motif_forge:motif_forge@127.0.0.1:5432/motif_forge'
export MOTIF_FORGE_ARTIFACT_ROOT="$MOTIF_FORGE_DEV_STORAGE_ROOT/artifacts"
export MOTIF_FORGE_RENDER_SERVICE_URL='http://127.0.0.1:8090'
export MOTIF_FORGE_S1_APPROVAL_ACTOR='local-user:your-name'
export MOTIF_FORGE_S1_APPROVAL_ASSERTION='I reviewed the generated composition and approve this export.'
scripts/check_s1.sh
```

It creates an L3 Preview, records the caller-supplied human approval assertion, materializes an
immutable Revision, and queues Master, four Stem, MP3 and Export Bundle Jobs. The Bundle is logical:
it stores MIDI, Project/manifests and immutable references to the six Audio Artifacts instead of
copying their bytes. The smoke verifies every checksum and Revision lineage. No DeepSeek key is
required.

Compose runs Alembic in a one-shot `migrate` service before starting the API. To execute the real
PostgreSQL checkpoint and transaction tests from the host:

```bash
export MOTIF_FORGE_TEST_POSTGRES_DSN='postgresql://motif_forge:motif_forge@localhost:5432/motif_forge'
scripts/check_postgres_integration.sh
```

On macOS external volumes that create `._*` AppleDouble files, keep the installed Python environment
off the volume; the uv download cache may stay under the external development storage root. The repository ignores these sidecars, but BuildKit may reject them
before ignore rules are applied. `scripts/build_compose_images.sh` copies only the required build
inputs without xattrs into a unique `/private/tmp` context, loads the image, then validates and
removes that temporary context. It does not delete sidecars or source files from the checkout.
The audio-test command also excludes `**/._*`, so metadata sidecars cannot be collected as test
modules.

```bash
export UV_PROJECT_ENVIRONMENT=/private/tmp/motif-forge-venv
export UV_CACHE_DIR="$MOTIF_FORGE_DEV_STORAGE_ROOT/cache/uv"
export UV_LINK_MODE=copy
uv sync --dev --frozen
```

The health endpoints are:

- `GET /health/live`
- `GET /health/ready`

The first write endpoints are:

- `POST /api/v1/projects`
- `POST /api/v1/projects/{project_id}/command-batches`

Both require an `Idempotency-Key` header. The command endpoint is restricted to human editor
commands. AI L2/L3 changes use the implemented internal Candidate Snapshot/Preview/Approval
transaction path; its public endpoints stay closed until the audio Worker can attach a real
listenable Preview and resume the originating Graph safely.

`/health/ready` performs bounded PostgreSQL `SELECT 1` and Redis `PING` probes. It returns `200`
only when both configured dependencies are connected; otherwise it fails closed with `503` and
does not expose DSNs or secrets.

## Current implementation boundaries

- The shared Tone.js/Chromium audio engine, three built-in synth presets, deterministic four-track
  composer and canonical PCM24 Master/Stem render service are implemented.
  PostgreSQL Run/Job/Outbox/Inbox/Artifact metadata and the deterministic Graph Worker-event gate
  are implemented. The PostgreSQL Outbox dispatcher, Redis/Celery media task and non-root FFmpeg
  Worker execute persisted import, pitch-preserving time-stretch, canonical render, MP3 transcode
  and Export Bundle Jobs end to end.
- Candidate Preview/Approval persistence is implemented but intentionally has no public HTTP route
  before preview rendering and Graph resume exist.
- No API key is stored in source control or emitted through health responses.
- Agent tests use deterministic fake planners.
- The planning Graph v3 adds a deterministic Error Router, bounded schema repair, approval-required
  fallback, DeepSeek thinking tool-call continuation, and idempotent PostgreSQL Trace/Span/Usage
  writes keyed by provider operation ID.
- The pitch-preserving FFmpeg `atempo` operator is implemented and quality-tested against duration,
  pitch, silence and transient bounds. Its persisted Job is now dispatched through Redis/Celery and
  writes an idempotent Artifact completion transaction. The first `motif-forge-parent.v1`
  Import/Arrangement branch now mounts `WaitForJobEvent`; a dedicated Resume Dispatcher restores the
  same PostgreSQL checkpoint and deduplicates repeated `resume_event_id` deliveries. Upload/API and
  controlled Upload, import validation, independent waveform/analysis Feature Artifacts and
  deterministic recovery are implemented.
- Web Import Review implements local upload, rights confirmation, Import Run URL recovery,
  low-confidence confirmation/override/skip/cancel, original/aligned Range playback, Canvas
  waveform/analysis review, Artifact rehydration, and narrow-screen review.
- S2 Tasks 1–12 mount Generate in the single `motif-forge-parent.v2` Graph, dispatch durable
  start/resume/cancel actions, expose replayable REST/SSE Run APIs, atomically materialize an
  approved Synth Ambient Plan, and reuse the seven-step complete export chain. Representative
  restart/cancel/idempotency integration and the 16-case Generate Eval are checkpointed.
- Complete-song Pattern compilation and full export are implemented for the fixed S1 baseline and
  the API-level DeepSeek Generate path. The accepted live run used one provider request and 4,911
  tokens, produced no fallback, and completed one immutable Revision, seven Jobs, six audio
  Artifacts and one Bundle under one `complete_song_export.v1` Media Run. Four Style Packs,
  Brief/Plan UI, DAW editing, A/B candidates, AI selection editing, and the final 96-case Eval remain.
- S2 Tasks 6–12 follow Portfolio Engineering Mode: the single Parent Graph, structured DeepSeek plus
  deterministic fallback, real HITL, immutable Revision, restart-safe export and one paid acceptance
  remain mandatory. Exhaustive fault/concurrency matrices, all historical populated downgrades,
  load/P95 and multi-tenant hardening are tracked for the later release-hardening gate instead of
  blocking every intermediate Task.
- LangGraph owns workflow state; project truth remains in immutable revisions.
- DeepSeek V4 Flash live calls remain opt-in; the default test suite uses HTTP fakes and incurs no cost.
- Real PostgreSQL tests are explicitly skipped unless `MOTIF_FORGE_TEST_POSTGRES_DSN` is supplied;
  SQLite is not used as a substitute.
