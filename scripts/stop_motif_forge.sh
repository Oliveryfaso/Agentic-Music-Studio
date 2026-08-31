#!/usr/bin/env bash
set -uo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$project_root"

runtime_dir="${MOTIF_FORGE_RUNTIME_DIR:-/private/tmp/motif-forge-$(id -u)}"
web_pid_file="$runtime_dir/web.pid"
result=0

usage() {
  cat <<'EOF'
Usage: scripts/stop_motif_forge.sh

Stop the complete local Motif Forge stack:
  - the Vite Web Studio started by the launcher;
  - all services in this repository's Docker Compose project;
  - the default Colima VM, when it is running.

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

run_quiet_with_timeout() {
  local timeout_seconds="$1"
  shift
  "$@" >/dev/null 2>&1 &
  local command_pid=$!
  local deadline=$((SECONDS + timeout_seconds))

  while kill -0 "$command_pid" >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      kill "$command_pid" >/dev/null 2>&1 || true
      wait "$command_pid" >/dev/null 2>&1 || true
      return 124
    fi
    sleep 0.2
  done
  wait "$command_pid" >/dev/null 2>&1
}

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

  if [[ ! -f "$web_pid_file" || -L "$web_pid_file" ]]; then
    echo "Web Studio is already stopped."
    return
  fi

  web_pid="$(sed -n '1p' "$web_pid_file")"
  recorded_root="$(sed -n '2p' "$web_pid_file")"

  if [[ ! "$web_pid" =~ ^[0-9]+$ || "$recorded_root" != "$project_root" ]]; then
    echo "Discarding an invalid Motif Forge Web PID record."
    rm -f "$web_pid_file"
    return
  fi

  if ! process_is_running "$web_pid"; then
    echo "Web Studio is already stopped."
    rm -f "$web_pid_file"
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

colima_is_running() {
  if colima status >/dev/null 2>&1; then
    return 0
  fi
  colima list 2>/dev/null | awk 'NR > 1 && $1 == "default" && $2 == "Running" { found = 1 } END { exit !found }'
}

stop_owned_web

if command -v docker >/dev/null 2>&1 && run_quiet_with_timeout 3 docker info; then
  echo "Stopping Motif Forge Compose services…"
  if ! docker compose down; then
    echo "Docker Compose could not stop every Motif Forge service." >&2
    result=1
  fi
else
  echo "Docker is already unavailable; Compose services are not running."
fi

if command -v colima >/dev/null 2>&1 && colima_is_running; then
  echo "Stopping Colima…"
  if ! colima stop; then
    echo "Colima could not be stopped." >&2
    result=1
  fi
else
  echo "Colima is already stopped or is not installed."
fi

if (( result == 0 )); then
  echo "Motif Forge is fully stopped. Project data and Docker volumes were preserved."
fi
exit "$result"
