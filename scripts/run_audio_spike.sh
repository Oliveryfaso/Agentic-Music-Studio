#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${MOTIF_FORGE_ARTIFACT_ROOT:-}" ]]; then
  echo "MOTIF_FORGE_ARTIFACT_ROOT must be an explicit absolute external artifact root" >&2
  exit 64
fi

artifact_root="$MOTIF_FORGE_ARTIFACT_ROOT"
if [[ "$artifact_root" != /* || "$artifact_root" == "/" || -L "$artifact_root" ]]; then
  echo "artifact root must be a specific absolute non-symlink directory" >&2
  exit 64
fi
if [[ ! -d "$artifact_root" || ! -w "$artifact_root" ]]; then
  echo "artifact root must already exist and be writable; run bootstrap_external_storage.sh" >&2
  exit 73
fi

output_root="$artifact_root/render-spike"
mkdir -p "$output_root"
if [[ -L "$output_root" || ! -w "$output_root" ]]; then
  echo "render spike output directory is unsafe or not writable" >&2
  exit 73
fi

exec docker run --rm --init --ipc=host \
  --cpus 2 --memory 1g --pids-limit 256 --network none \
  --mount "type=bind,src=$output_root,dst=/outputs" \
  -e MOTIF_FORGE_SPIKE_OUTPUT_ROOT=/outputs \
  motif-forge-render-worker:spike
