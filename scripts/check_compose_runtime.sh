#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$project_root"

for command_name in docker curl uv; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is unavailable: $command_name" >&2
    exit 69
  fi
done

if find . -path './.git' -prune -o -name '._*' -print -quit | grep -q .; then
  echo "warning: AppleDouble ._* files exist; use scripts/build_compose_images.sh for BuildKit." >&2
fi

docker compose config --quiet

running_services="$(docker compose ps --services --status running)"
for service_name in api dispatcher resume-dispatcher media-worker postgres redis; do
  if ! grep -Fxq "$service_name" <<<"$running_services"; then
    echo "Compose service is not running: $service_name" >&2
    exit 70
  fi
done

migrate_container="$(docker compose ps -aq migrate)"
if [[ -z "$migrate_container" ]]; then
  echo "Compose migrate container is unavailable." >&2
  exit 70
fi
if [[ "$(docker inspect --format '{{.State.ExitCode}}' "$migrate_container")" != "0" ]]; then
  echo "Compose migrate service did not exit successfully." >&2
  exit 70
fi

live_response=""
for _attempt in {1..20}; do
  if live_response="$(curl -fsS http://127.0.0.1:8000/health/live 2>/dev/null)"; then
    break
  fi
  sleep 0.5
done
if [[ -z "$live_response" ]]; then
  echo "API live endpoint did not become ready within 10 seconds." >&2
  exit 70
fi

ready_response="$(curl -fsS http://127.0.0.1:8000/health/ready)"
grep -Fq '"status":"live"' <<<"$live_response"
grep -Fq '"status":"ready"' <<<"$ready_response"
grep -Fq '"postgres":{"configured":true,"connectivity":"connected"}' <<<"$ready_response"
grep -Fq '"redis":{"configured":true,"connectivity":"connected"}' <<<"$ready_response"

if [[ "$(docker compose exec -T redis redis-cli ping)" != "PONG" ]]; then
  echo "Redis PING failed." >&2
  exit 70
fi

migration_version="$(
  docker compose exec -T postgres \
    psql -U motif_forge -d motif_forge -Atc \
    'select version_num from public.alembic_version;'
)"
if [[ "$migration_version" != "20260812_0009" ]]; then
  echo "unexpected Alembic version: $migration_version" >&2
  exit 70
fi

docker compose run --rm --no-deps api sh -c \
  'test ! -e /usr/local/bin/uv && test ! -e /opt/venv/bin/uv && python -c "from motif_forge.agent.graph import GRAPH_TOPOLOGY_VERSION, STATE_SCHEMA_VERSION; from motif_forge.agent.parent_graph import PARENT_GRAPH_TOPOLOGY_VERSION; from motif_forge.audio.time_stretch import TIME_STRETCH_RECIPE_VERSION; from motif_forge.domain.media_jobs import FeatureProfile; assert GRAPH_TOPOLOGY_VERSION == \"motif-forge-plan.v3\"; assert STATE_SCHEMA_VERSION == \"motif-forge-plan-state.v3\"; assert PARENT_GRAPH_TOPOLOGY_VERSION == \"motif-forge-parent.v1\"; assert TIME_STRETCH_RECIPE_VERSION == \"time-stretch-recipe.v1\"; assert FeatureProfile.WAVEFORM_PEAKS_V1.value == \"waveform-peaks.v1\"" && alembic heads >/dev/null'

docker compose exec -T media-worker sh -c \
  'test "$(id -u)" != "0" && test ! -e /usr/local/bin/uv && test ! -e /opt/venv/bin/uv && command -v ffmpeg >/dev/null && celery --version >/dev/null'

test_dsn="${MOTIF_FORGE_TEST_POSTGRES_DSN:-postgresql://motif_forge:motif_forge@127.0.0.1:5432/motif_forge}"
MOTIF_FORGE_TEST_POSTGRES_DSN="$test_dsn" scripts/check_postgres_integration.sh

echo "Compose runtime contract passed: API, migration, PostgreSQL, Redis, Job Dispatcher, Resume Dispatcher, Media Worker, runtime images, and PostgreSQL integration tests."
