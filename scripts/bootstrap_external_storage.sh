#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: $0 absolute-storage-root" >&2
  exit 64
fi

storage_root="$1"

if [[ "$storage_root" != /* || "$storage_root" == "/" || "$storage_root" == "/Volumes" ]]; then
  echo "storage root must be a specific absolute directory below a mounted volume" >&2
  exit 64
fi

if [[ -L "$storage_root" ]]; then
  echo "storage root must not be a symbolic link" >&2
  exit 64
fi

mkdir -p \
  "$storage_root/artifacts" \
  "$storage_root/artifacts/tmp/jobs" \
  "$storage_root/artifacts/quarantine/source-original" \
  "$storage_root/artifacts/protected/working-pcm" \
  "$storage_root/artifacts/derived/time-stretch" \
  "$storage_root/tmp" \
  "$storage_root/cache/npm" \
  "$storage_root/cache/pnpm" \
  "$storage_root/cache/playwright"

# Bind mounts appear root-owned inside the Linux VM. Keep the Worker non-root by
# granting write access only to the controlled Artifact namespaces it owns.
chmod 1777 "$storage_root/artifacts/tmp" "$storage_root/artifacts/tmp/jobs"
chmod 1777 \
  "$storage_root/artifacts/quarantine" \
  "$storage_root/artifacts/quarantine/source-original" \
  "$storage_root/artifacts/protected" \
  "$storage_root/artifacts/protected/working-pcm" \
  "$storage_root/artifacts/derived" \
  "$storage_root/artifacts/derived/time-stretch"

for required_dir in \
  "$storage_root/artifacts" \
  "$storage_root/tmp" \
  "$storage_root/cache/npm" \
  "$storage_root/cache/pnpm" \
  "$storage_root/cache/playwright"; do
  if [[ ! -d "$required_dir" || -L "$required_dir" || ! -w "$required_dir" ]]; then
    echo "storage check failed: expected a writable, non-symlink directory: $required_dir" >&2
    exit 73
  fi
done

if [[ "$(uname -s)" == "Darwin" ]]; then
  artifact_device="$(stat -f '%d' "$storage_root/artifacts")"
  temp_device="$(stat -f '%d' "$storage_root/tmp")"
else
  artifact_device="$(stat -c '%d' "$storage_root/artifacts")"
  temp_device="$(stat -c '%d' "$storage_root/tmp")"
fi

if [[ "$artifact_device" != "$temp_device" ]]; then
  echo "storage check failed: artifact and temporary roots are on different filesystems" >&2
  exit 73
fi

probe_source="$(mktemp -d "$storage_root/tmp/.rename-probe.pending.XXXXXX")"
probe_target="${probe_source/.rename-probe.pending./.rename-probe.ok.}"
mv "$probe_source" "$probe_target"
rmdir "$probe_target"

echo "External storage is writable and same-volume rename succeeded."
echo "Root: $storage_root"
echo
echo "Export these values in your shell (the script does not edit .env):"
printf 'export MOTIF_FORGE_ARTIFACT_ROOT=%q\n' "$storage_root/artifacts"
printf 'export MOTIF_FORGE_TEMP_ROOT=%q\n' "$storage_root/tmp"
printf 'export PLAYWRIGHT_BROWSERS_PATH=%q\n' "$storage_root/cache/playwright"
printf 'export npm_config_cache=%q\n' "$storage_root/cache/npm"
printf 'export MOTIF_FORGE_PNPM_STORE_DIR=%q\n' "$storage_root/cache/pnpm"
