#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
context_root="$(mktemp -d /private/tmp/motif-forge-docker-context.XXXXXX)"
requested_target="${1:-all}"

case "$requested_target" in
  all|api|media-worker|render-worker) ;;
  *)
    echo "usage: $0 [all|api|media-worker|render-worker]" >&2
    exit 64
    ;;
esac

cleanup() {
  if [[ "$context_root" != /private/tmp/motif-forge-docker-context.* ]]; then
    echo "refusing to clean unexpected build context: $context_root" >&2
    return 1
  fi
  if [[ -d "$context_root" && ! -L "$context_root" ]]; then
    rm -rf "$context_root"
  fi
}
trap cleanup EXIT

for command_name in docker rsync; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is unavailable: $command_name" >&2
    exit 69
  fi
done

if ! docker buildx version >/dev/null 2>&1; then
  echo "Docker Buildx is required." >&2
  exit 69
fi

mkdir -p \
  "$context_root/services/api" \
  "$context_root/services/render-worker" \
  "$context_root/packages/audio-engine" \
  "$context_root/scripts" \
  "$context_root/infra"
COPYFILE_DISABLE=1 rsync -rlpt --exclude='._*' \
  "$project_root/pyproject.toml" \
  "$project_root/uv.lock" \
  "$project_root/README.md" \
  "$project_root/alembic.ini" \
  "$project_root/.dockerignore" \
  "$context_root/"
COPYFILE_DISABLE=1 rsync -rlpt --exclude='._*' \
  "$project_root/package.json" \
  "$project_root/package-lock.json" \
  "$project_root/tsconfig.json" \
  "$context_root/"
COPYFILE_DISABLE=1 rsync -rlpt --exclude='._*' \
  "$project_root/services/api/Dockerfile" \
  "$context_root/services/api/"
COPYFILE_DISABLE=1 rsync -rlpt --exclude='._*' \
  "$project_root/services/api/src/" \
  "$context_root/services/api/src/"
COPYFILE_DISABLE=1 rsync -rlpt --exclude='._*' \
  "$project_root/infra/migrations/" \
  "$context_root/infra/migrations/"
COPYFILE_DISABLE=1 rsync -rlpt --exclude='._*' \
  "$project_root/services/render-worker/" \
  "$context_root/services/render-worker/"
COPYFILE_DISABLE=1 rsync -rlpt --exclude='._*' \
  "$project_root/packages/audio-engine/" \
  "$context_root/packages/audio-engine/"
COPYFILE_DISABLE=1 rsync -rlpt --exclude='._*' \
  "$project_root/scripts/build-render-worker.mjs" \
  "$context_root/scripts/"

if find "$context_root" -name '._*' -print -quit | grep -q .; then
  echo "clean build context unexpectedly contains AppleDouble files" >&2
  exit 73
fi

if [[ "$requested_target" == all || "$requested_target" == api ]]; then
  docker buildx build \
    --load \
    --build-arg BUILDKIT_INLINE_CACHE=1 \
    --tag motif-forge-api:local \
    --target api \
    --file "$context_root/services/api/Dockerfile" \
    "$context_root"
fi

if [[ "$requested_target" == all || "$requested_target" == media-worker ]]; then
  docker buildx build \
    --load \
    --build-arg BUILDKIT_INLINE_CACHE=1 \
    --tag motif-forge-media-worker:local \
    --target media-worker \
    --file "$context_root/services/api/Dockerfile" \
    "$context_root"
fi

if [[ "$requested_target" == all || "$requested_target" == render-worker ]]; then
  docker buildx build \
    --load \
    --build-arg BUILDKIT_INLINE_CACHE=1 \
    --tag motif-forge-render-worker:spike \
    --file "$context_root/services/render-worker/Dockerfile" \
    "$context_root"
fi
