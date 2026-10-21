#!/usr/bin/env bash
set -uo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$project_root"

runtime_tag="$(printf '%s' "$project_root" | cksum | awk '{print $1}')"
runtime_dir="${MOTIF_FORGE_RUNTIME_DIR:-/private/tmp/motif-forge-$(id -u)-$runtime_tag}"
web_pid_file="$runtime_dir/web.pid"
result=0

usage() {
  cat <<'EOF'
Usage: scripts/stop_motif_forge.sh

Stop the complete local Motif Forge stack:
  - the Vite Web Studio started by the launcher;
  - exact containers carrying this launcher's recorded ownership label.

Shared services and Colima are never stopped. Unrecorded stacks are not adopted.

PostgreSQL volumes, images, imported media, and generated works are preserved.
The command is safe to repeat when Motif Forge is already stopped.
EOF
}

if [[ $# -gt 0 ]]; then
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown option: $1" >&2
      usage >&2
      exit 64
      ;;
  esac
fi

process_is_running() {
  local pid="$1"
  local state
  kill -0 "$pid" >/dev/null 2>&1 || return 1
  state="$(ps -p "$pid" -o stat= 2>/dev/null || true)"
  [[ "$state" != Z* ]]
}

stop_process_tree() {
  local pid="$1"
  local child

  if command -v pgrep >/dev/null 2>&1; then
    for child in $(pgrep -P "$pid" 2>/dev/null || true); do
      stop_process_tree "$child"
    done
  fi
  kill -TERM "$pid" >/dev/null 2>&1 || true
}

stop_owned_web() {
  local web_pid=""
  local recorded_root=""
  local command_line=""
  local recorded_start=""
  local actual_start=""

  if [[ ! -f "$web_pid_file" || -L "$web_pid_file" ]]; then
    echo "Web Studio is already stopped."
    return
  fi

  web_pid="$(sed -n '1p' "$web_pid_file")"
  recorded_root="$(sed -n '2p' "$web_pid_file")"
  recorded_start="$(sed -n '3p' "$web_pid_file")"

  if [[ ! "$web_pid" =~ ^[0-9]+$ || "$recorded_root" != "$project_root" ]]; then
    echo "Refusing an invalid Motif Forge Web PID record." >&2
    result=1
    return
  fi

  if ! process_is_running "$web_pid"; then
    echo "Web Studio is already stopped."
    rm -f "$web_pid_file"
    return
  fi

  actual_start="$(ps -p "$web_pid" -o lstart= 2>/dev/null | sed 's/^[[:space:]]*//')"
  if [[ -z "$recorded_start" || "$actual_start" != "$recorded_start" ]]; then
    echo "Web ownership cannot be verified; no process was stopped. Use its original terminal." >&2
    result=1
    return
  fi
  command_line="$(ps -p "$web_pid" -o command= 2>/dev/null || true)"
  if [[ "$command_line" != *"npm run dev:web"* && "$command_line" != *"vite --config apps/web/vite.config.ts"* ]]; then
    echo "Discarding a stale Web PID record without stopping PID $web_pid."
    rm -f "$web_pid_file"
    return
  fi

  echo "Stopping Motif Forge Web Studio…"
  stop_process_tree "$web_pid"
  for ((attempt = 1; attempt <= 50; attempt += 1)); do
    if ! process_is_running "$web_pid"; then
      break
    fi
    sleep 0.1
  done
  if process_is_running "$web_pid"; then
    kill -KILL "$web_pid" >/dev/null 2>&1 || true
  fi
  rm -f "$web_pid_file"
}

if [[ "$runtime_dir" != /* || -L "$runtime_dir" || -L "$web_pid_file" ]]; then
  echo "Runtime ownership path is invalid; no resources were stopped." >&2
  exit 64
fi
if ! command -v node >/dev/null 2>&1 || ! command -v python3 >/dev/null 2>&1; then
  echo "Node.js and Python 3 are required to verify runtime ownership; no resources were stopped." >&2
  exit 69
fi
node scripts/motif_runtime_owner.mjs init "$project_root" "$runtime_dir" || exit "$?"
if ! exec 9<> "$runtime_dir/operation.lock"; then exit 1; fi
python3 scripts/motif_runtime_lock.py acquire "$runtime_dir/operation.lock" || exit "$?"
# Verify private metadata and the entire container set before touching Web.
if ! node scripts/motif_runtime_owner.mjs stop "$project_root" "$runtime_dir"; then
  exit 1
fi
stop_owned_web
if (( result == 0 )); then
  echo "Recorded Motif Forge resources stopped; data volumes, shared services and VM preserved."
fi
exit "$result"
