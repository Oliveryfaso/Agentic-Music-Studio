# G0 Development Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert the already-validated Import/Analysis/Alignment/Web Preview worktree into a documented, reproducible and recoverable Git baseline before any S1 product code begins.

**Architecture:** This gate changes no product behavior and adds no dependencies. It verifies that current documentation describes the running system, inventories every dirty path, excludes local/secret/generated content, reruns the accepted host and Compose baselines, then creates and pushes a reviewable checkpoint. If safe logical splitting would break cross-file dependencies, prefer one truthful milestone commit over artificial history surgery.

**Tech Stack:** Git, uv/pytest/Ruff/Mypy, npm/Vitest/TypeScript/Vite, Docker Compose, PostgreSQL, Redis, FFmpeg Media Worker.

## Global Constraints

- Covered requirements: `MF-P13`, `MF-P16`, `MF-P17`, `MF-P18`; no product behavior changes are authorized.
- Read repository `AGENTS.md` and the required document order before execution.
- Preserve every existing user change until its ownership and role are understood.
- Never stage `.env`, API keys, Artifact bytes, user audio, caches, build output, AppleDouble sidecars or new machine-specific paths in product code/config. Existing explicitly labeled local-development commands are allowed only when a portable variable-based alternative is documented.
- Do not rewrite history, reset the worktree, delete files to make status clean, or use broad Docker prune commands.
- Do not start S1 until the checkpoint is pushed and G0 acceptance passes.

---

### Task 1: Freeze the source-of-truth snapshot

**Files:**
- Verify: `docs/DECISION_LOG.md`
- Verify: `docs/PROJECT_GUIDE.md`
- Verify: `docs/IMPLEMENTATION_STATUS.md`
- Verify: `docs/NEXT_DEVELOPMENT_ROADMAP.md`
- Verify: `README.md`
- Verify: `AGENTS.md`

**Interfaces:**
- Consumes: current worktree and documentation hierarchy.
- Produces: recorded guide hash and a confirmed G0-only scope.

- [ ] **Step 1: Record the guide and repository identity**

Run:

```bash
openssl dgst -sha256 docs/PROJECT_GUIDE.md
git branch --show-current
git rev-parse HEAD
git status --short
```

Expected: branch `main`; the guide hash is recorded in the task report; no command mutates the worktree.

- [ ] **Step 2: Verify documentation roles and links**

Run:

```bash
rg -n "IMPLEMENTATION_STATUS|NEXT_DEVELOPMENT_ROADMAP" README.md docs/PROJECT_GUIDE.md AGENTS.md .agents/skills/motif-forge-development/SKILL.md
rg -n "MF-P01|MF-P21|G0|S1|S7" docs/NEXT_DEVELOPMENT_ROADMAP.md
```

Expected: all four entry points link current status and roadmap; all 21 requirement IDs exist; G0 is the active gate.

- [ ] **Step 3: Scan for ambiguous placeholders and stale capability claims**

Run:

```bash
rg -n "TBD|TODO|PLACEHOLDER|frontend is not yet|does not yet implement the Upload UI|Upload orchestration.*next" README.md docs .agents AGENTS.md
```

Expected: no placeholder or stale Upload/Web claim in current-state documents. Historical statements in dated `TECH_EVOLUTION.md` are allowed only inside their original dated snapshot.

### Task 2: Classify every worktree path before staging

**Files:**
- Inspect: all paths reported by `git status --short`
- Verify: `.gitignore`
- Verify: `.dockerignore`
- Verify: `.env.example`

**Interfaces:**
- Consumes: dirty worktree inventory.
- Produces: an explicit include/exclude manifest for the checkpoint.

- [ ] **Step 1: Save a non-mutating inventory**

Run:

```bash
git status --porcelain=v1
git diff --stat
git diff --name-only
git ls-files --others --exclude-standard
```

Expected: every modified and untracked path appears in one of the lists; no staging occurs.

- [ ] **Step 2: Scan candidate text files for secret-shaped values and personal paths**

Run:

```bash
rg -n --hidden --glob '!node_modules/**' --glob '!apps/web/dist/**' --glob '!.git/**' "(DEEPSEEK_API_KEY|sk-[A-Za-z0-9_-]{16,}|postgresql://[^[:space:]]+:[^[:space:]]+@|/Users/oliver|/Volumes/KINGSTON)" .
```

Expected: `.env.example`, docs and controlled development scripts may contain variable names or documented development paths, but no real API key or undisclosed credential. Review every match; do not stage a secret.

- [ ] **Step 3: Verify generated/local exclusions**

Run:

```bash
git status --short --ignored | rg "(\.env$|node_modules|dist/|\.venv|__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\._|var/artifacts)"
```

Expected: local environments, build output, caches, sidecars and Artifact roots are ignored rather than checkpoint candidates.

- [ ] **Step 4: Produce the staging manifest**

In the execution report, group included paths as:

```text
domain-agent-persistence
media-storage-import
web-audio
docs-ops-lockfiles
```

If a file participates in more than one group or splitting would make any commit fail tests/migrations, record the coupling and use one milestone commit.

### Task 3: Reproduce the accepted host baseline

**Files:**
- Verify: `pyproject.toml`
- Verify: `package.json`
- Verify: `uv.lock`
- Verify: `package-lock.json`

**Interfaces:**
- Consumes: existing external caches and `/private/tmp/motif-forge-venv`.
- Produces: current unit, type, lint and build evidence without Docker rebuilds.

- [ ] **Step 1: Run Python tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/motif-forge-venv UV_CACHE_DIR=/Volumes/KINGSTON/idea/.motif-forge-data/cache/uv UV_LINK_MODE=copy uv run pytest -q
```

Expected: at least the recorded `152 passed`; PostgreSQL/Redis-dependent cases may only skip with explicit reasons.

- [ ] **Step 2: Run Python static checks**

Run:

```bash
UV_PROJECT_ENVIRONMENT=/private/tmp/motif-forge-venv UV_CACHE_DIR=/Volumes/KINGSTON/idea/.motif-forge-data/cache/uv UV_LINK_MODE=copy uv run ruff check .
UV_PROJECT_ENVIRONMENT=/private/tmp/motif-forge-venv UV_CACHE_DIR=/Volumes/KINGSTON/idea/.motif-forge-data/cache/uv UV_LINK_MODE=copy uv run mypy
```

Expected: Ruff passes and Mypy strict reports no issues.

- [ ] **Step 3: Run Audio and Web checks**

Run:

```bash
npm_config_cache=/Volumes/KINGSTON/idea/.motif-forge-data/cache/npm npm run test:audio
npm_config_cache=/Volumes/KINGSTON/idea/.motif-forge-data/cache/npm npm run test:web
npm_config_cache=/Volumes/KINGSTON/idea/.motif-forge-data/cache/npm npm run build:web
```

Expected: Audio `6 passed`, Web `15 passed`, TypeScript strict and Vite build pass.

### Task 4: Reproduce the accepted service baseline without rebuilding

**Files:**
- Verify: `compose.yaml`
- Verify: `scripts/check_postgres_integration.sh`
- Verify: `scripts/check_compose_runtime.sh`

**Interfaces:**
- Consumes: current tagged images, running PostgreSQL/Redis and external Artifact root.
- Produces: PostgreSQL, migration, Worker and readiness evidence.

- [ ] **Step 1: Confirm current runtime before tests**

Run:

```bash
docker compose ps
curl -fsS http://localhost:8000/health/ready
```

Expected: PostgreSQL, Redis, API, Dispatcher, Resume Dispatcher and Media Worker are running; readiness reports PostgreSQL, Redis and Artifact Root connected.

- [ ] **Step 2: Run real PostgreSQL integration tests**

Run:

```bash
MOTIF_FORGE_TEST_POSTGRES_DSN='postgresql://motif_forge:motif_forge@localhost:5432/motif_forge' UV_PROJECT_ENVIRONMENT=/private/tmp/motif-forge-venv UV_CACHE_DIR=/Volumes/KINGSTON/idea/.motif-forge-data/cache/uv UV_LINK_MODE=copy scripts/check_postgres_integration.sh
```

Expected: at least `13 passed`; the Celery E2E case may skip only because its dedicated Redis/Artifact test variables are absent.

- [ ] **Step 3: Run the full Compose runtime contract**

Run:

```bash
scripts/check_compose_runtime.sh
```

Expected: the existing runtime contract passes without rebuilding an image. If it requests opt-in destructive cleanup or a new build, stop and report instead of expanding G0.

### Task 5: Review and create the Git checkpoint

**Files:**
- Stage: only paths approved by Task 2
- Exclude: all local/generated/secret paths listed in Global Constraints

**Interfaces:**
- Consumes: green G0 evidence and staging manifest.
- Produces: a local reviewable commit, then a pushed `main` checkpoint after explicit diff review.

- [ ] **Step 1: Stage only the manifest**

Run `git add` with explicit approved paths or coherent directories. Do not use `git add -A` until the porcelain inventory has been matched line-by-line to the manifest.

- [ ] **Step 2: Review the staged snapshot**

Run:

```bash
git diff --cached --stat
git diff --cached --check
git diff --cached --name-status
```

Expected: no secret/local/generated path, no whitespace error, and all required migrations, tests, lockfiles and docs are staged together.

- [ ] **Step 3: Commit the milestone**

Run:

```bash
git commit -m "feat: complete durable audio import web slice"
```

Expected: commit succeeds; hooks do not modify unreviewed files.

- [ ] **Step 4: Verify and push**

Run:

```bash
git status --short
git log -2 --oneline --decorate
git push origin main
```

Expected: all intended business changes are committed and pushed; any remaining dirty paths are listed with a reason. Never force-push.

### Task 6: Close G0 and expose S1 as the only next gate

**Files:**
- Modify after evidence: `docs/IMPLEMENTATION_STATUS.md`
- Append after evidence: `docs/TECH_EVOLUTION.md`
- Verify: `docs/NEXT_DEVELOPMENT_ROADMAP.md`

**Interfaces:**
- Consumes: pushed checkpoint ID and final verification evidence.
- Produces: G0-complete status and an unambiguous S1 entry point.

- [ ] **Step 1: Record the checkpoint and evidence**

Update the version-governance section with the pushed commit ID, remaining explained dirty paths, and final test counts. Append the actual G0 result to `TECH_EVOLUTION.md`; do not rewrite previous dated evidence.

- [ ] **Step 2: Change the active gate**

Only after the push succeeds, update repository `AGENTS.md` and `IMPLEMENTATION_STATUS.md` from `G0` to `S1`. Do not mark any S1 product capability complete.

- [ ] **Step 3: Recheck the guide hash and documentation diff**

Run:

```bash
openssl dgst -sha256 docs/PROJECT_GUIDE.md
git diff --check
rg -n "active gate|当前开发断点|S1" AGENTS.md docs/IMPLEMENTATION_STATUS.md docs/NEXT_DEVELOPMENT_ROADMAP.md
```

Expected: the guide hash matches the start value unless a reviewed contract change was necessary; S1 is the only next product gate.

- [ ] **Step 4: Commit and push the G0 closure record**

Run:

```bash
git add AGENTS.md docs/IMPLEMENTATION_STATUS.md docs/TECH_EVOLUTION.md docs/NEXT_DEVELOPMENT_ROADMAP.md
git diff --cached --check
git commit -m "docs: close development baseline gate"
git push origin main
```

Expected: documentation points at the exact pushed implementation checkpoint; the next session can begin by writing the S1 slice-specific plan.
