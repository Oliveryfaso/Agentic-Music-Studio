#!/usr/bin/env bash
set -euo pipefail

builder="${MOTIF_FORGE_BUILDX_BUILDER:-colima}"
cold_after="${MOTIF_FORGE_CACHE_COLD_AFTER:-45m}"
target_size="${MOTIF_FORGE_CACHE_TARGET_SIZE:-1500mb}"
hard_limit="${MOTIF_FORGE_CACHE_HARD_LIMIT:-2gb}"
reserved_size="${MOTIF_FORGE_CACHE_RESERVED_SIZE:-768mb}"

if [[ "${MOTIF_FORGE_ALLOW_SHARED_BUILDER_PRUNE:-}" != "1" ]]; then
  echo "refusing shared-builder cleanup without MOTIF_FORGE_ALLOW_SHARED_BUILDER_PRUNE=1" >&2
  exit 64
fi

for command_name in docker awk; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is unavailable: $command_name" >&2
    exit 69
  fi
done

if ! docker buildx inspect "$builder" >/dev/null 2>&1; then
  echo "Buildx builder is unavailable: $builder" >&2
  exit 69
fi

if docker ps --format '{{.Image}} {{.Command}}' | awk 'BEGIN { active = 0 } /buildkit|buildx build/ { active = 1 } END { exit active ? 0 : 1 }'; then
  echo "refusing cleanup while a visible BuildKit build container is active" >&2
  exit 75
fi

echo "builder=$builder cold_after=$cold_after target=$target_size hard_limit=$hard_limit"
docker buildx du --builder "$builder"

docker buildx prune \
  --builder "$builder" \
  --filter "until=$cold_after" \
  --force

docker buildx prune \
  --builder "$builder" \
  --max-used-space "$target_size" \
  --reserved-space "$reserved_size" \
  --force

echo "cleanup complete; configured hard limit is $hard_limit"
docker buildx du --builder "$builder"
