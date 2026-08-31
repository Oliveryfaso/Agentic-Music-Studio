# Motif Forge One-command Local Lifecycle Plan

> Stage: post-S7 portfolio usability slice
> Mode: portfolio engineering; focused proof, no release-platform expansion

## Scope

Cover `MF-P01`, `MF-P16`, and `MF-P17` by making the existing Web, API,
PostgreSQL, Redis, Media Worker, Render Worker, and external Artifact Store
launchable from one repository command. This slice does not change the Parent
Graph, model provider, persistence schema, audio contracts, or paid-model
configuration.

User-visible result: from the repository root, running
`scripts/start_motif_forge.sh` prepares the existing local storage layout,
starts the existing Compose services, waits for lightweight readiness, starts
Vite, and opens the browser. The default Compose runtime remains no-key and
therefore cannot trigger a paid DeepSeek call.

The symmetric `scripts/stop_motif_forge.sh` command stops the launcher-owned
Web process, this repository's Compose services, and a running default Colima
VM. It preserves database volumes, images, imported media, generated works,
and exports, and is safe to repeat after the stack is already stopped.

## Task 1: RED launcher contract

Create `tests/test_local_launcher_contract.py` before the launcher. Cover:

- the documented no-argument command and supported `--check`/`--no-open` flags;
- explicit dependency and `.env` handling without overwriting an existing file;
- bounded Docker readiness and safe Colima start;
- existing external-storage bootstrap reuse;
- Compose start, API/Render readiness, Vite start, and macOS browser open;
- absence of volume deletion, global prune, secret output, or paid-provider enablement.

RED command:

```bash
.venv/bin/pytest tests/test_local_launcher_contract.py -q
```

Expected RED: the production launcher does not exist.

## Task 2: Minimal launcher implementation

Add executable `scripts/start_motif_forge.sh` using Bash strict mode. Resolve
the repository from the script location, derive the portable sibling
`.motif-forge-data` root unless explicitly overridden, create `.env` only when
missing, and reuse `bootstrap_external_storage.sh`. Use the existing Docker
Compose topology and Vite command; do not add a Web container or dependency.

If Docker is unavailable, start Colima only when installed. Never restart an
already running Docker runtime. Readiness waits are bounded and report
the failing service without printing secrets. `--check` validates prerequisites
without mutating or starting services. `--no-open` suppresses browser opening.

GREEN commands:

```bash
.venv/bin/pytest tests/test_local_launcher_contract.py -q
bash -n scripts/start_motif_forge.sh
scripts/start_motif_forge.sh --help
```

## Task 3: Symmetric complete stop

Write the stopping behavior contract before adding
`scripts/stop_motif_forge.sh`. The launcher records its Web PID and project
root in a user-scoped runtime directory. The stop command validates both the
record and live process command before terminating the Web process, then runs
`docker compose down` and stops a running default Colima VM. Stale PID records
must never kill an unrelated process. Repeated stopping succeeds without
deleting volumes, images, imported media, generated works, or exports.

GREEN commands:

```bash
.venv/bin/pytest tests/test_local_launcher_contract.py -q
bash -n scripts/start_motif_forge.sh scripts/stop_motif_forge.sh
scripts/stop_motif_forge.sh --help
```

## Task 4: Documentation synchronization

Update `README.md` so the one-command path is the primary Quick Start and the
opening status matches the completed S7 product. Keep the detailed manual and
Colima setup as troubleshooting/reference material. Update
`IMPLEMENTATION_STATUS.md` to remove its stale S7-active tail and record the
launcher only after test evidence exists. Append the actual change and evidence
to `TECH_EVOLUTION.md`.

## Acceptance

Run the focused tests and shell syntax/help checks, then:

```bash
git diff --check
git status --short
git diff -- docs/PROJECT_GUIDE.md
```

The guide must remain unchanged. No Docker build or paid DeepSeek call is
required for this host-orchestration slice; the local Docker daemon is currently
unresponsive, so runtime startup is not claimed without later live evidence.
