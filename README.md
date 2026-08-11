# Motif Forge

Motif Forge is a local-first, agent-assisted instrumental composition workbench. The current vertical slice contains an immutable music-domain revision spine, transactional Project writes, and a resumable `CompositionPlan` approval graph.

The architecture and product contracts live in [docs/PROJECT_GUIDE.md](docs/PROJECT_GUIDE.md).

## Prerequisites

- Python 3.12
- [uv](https://docs.astral.sh/uv/)
- Docker Compose for PostgreSQL/Redis integration work
- A DeepSeek API key only for explicit live-provider tests; unit tests never require one

## Local setup

```bash
export UV_CACHE_DIR=/private/tmp/motif-forge-uv-cache
uv sync --dev
uv run pytest
uv run ruff check .
uv run mypy
uv run uvicorn motif_forge.api.app:create_app --factory --reload
```

For the containerized PostgreSQL/Redis services, create a local environment file first:

```bash
cp .env.example .env
docker compose up --build
```

Compose runs Alembic in a one-shot `migrate` service before starting the API. To execute the real
PostgreSQL checkpoint and transaction tests from the host:

```bash
export MOTIF_FORGE_TEST_POSTGRES_DSN='postgresql://motif_forge:motif_forge@localhost:5432/motif_forge'
scripts/check_postgres_integration.sh
```

On macOS external volumes that create `._*` AppleDouble files inside virtual environments, keep the environment off the volume:

```bash
export UV_PROJECT_ENVIRONMENT=/private/tmp/motif-forge-venv
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
commands; AI L2/L3 changes must use the Candidate Preview and approval flow implemented in the next
slice.

`/health/ready` reports PostgreSQL and Redis as `not_checked` until service lifespan probes are
wired; it does not claim a successful connection.

## First-slice boundaries

- No audio rendering, Celery Worker, or frontend is scaffolded yet.
- No API key is stored in source control or emitted through health responses.
- Agent tests use deterministic fake planners.
- LangGraph owns workflow state; project truth remains in immutable revisions.
- DeepSeek V4 Flash live calls are opt-in; the default test suite uses HTTP fakes and incurs no cost.
- Real PostgreSQL tests are explicitly skipped unless `MOTIF_FORGE_TEST_POSTGRES_DSN` is supplied;
  SQLite is not used as a substitute.
