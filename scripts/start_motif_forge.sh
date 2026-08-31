#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$project_root"

check_only=0
open_browser=1
web_url="http://127.0.0.1:5173"
api_ready_url="http://127.0.0.1:8000/health/ready"
render_ready_url="http://127.0.0.1:8090/health"
runtime_dir="${MOTIF_FORGE_RUNTIME_DIR:-/private/tmp/motif-forge-$(id -u)}"
web_pid_file="$runtime_dir/web.pid"

usage() {
  cat <<'EOF'
Usage: scripts/start_motif_forge.sh [--check] [--no-open]

Start the complete local Motif Forge portfolio:
  - initialize the external development storage root;
  - start Colima when Docker is unavailable and Colima is installed;
  - start the existing Docker Compose backend and workers;
  - wait for API and Render Worker readiness;
  - start the Vite Web Studio and open it in the browser.

Options:
  --check     Validate local prerequisites without starting or changing anything.
  --no-open   Do not open the browser after the Web Studio becomes ready.
  -h, --help  Show this help.

Ctrl+C stops the Vite frontend. Stop the complete local stack with:
  scripts/stop_motif_forge.sh
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --check)
      check_only=1
      ;;
    --no-open)
      open_browser=0
      ;;
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
  shift
done

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is unavailable: $command_name" >&2
    exit 69
  fi
}

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

docker_is_ready() {
  run_quiet_with_timeout 3 docker info
}

wait_for_docker() {
  local deadline=$((SECONDS + 60))
  while (( SECONDS < deadline )); do
    if docker_is_ready; then
      return 0
    fi
    sleep 1
  done
  return 1
}

wait_for_http() {
  local url="$1"
  local label="$2"
  local attempts="${3:-60}"

  for ((attempt = 1; attempt <= attempts; attempt += 1)); do
    if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  echo "$label did not become ready: $url" >&2
  return 1
}

for command_name in docker curl npm; do
  require_command "$command_name"
done

if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose is unavailable; install the Docker Compose plugin." >&2
  exit 69
fi

storage_parent="$(cd "$project_root/.." && pwd -P)"
export MOTIF_FORGE_DEV_STORAGE_ROOT="${MOTIF_FORGE_DEV_STORAGE_ROOT:-$storage_parent/.motif-forge-data}"

if [[ "$MOTIF_FORGE_DEV_STORAGE_ROOT" != /* || "$MOTIF_FORGE_DEV_STORAGE_ROOT" == "/" ]]; then
  echo "MOTIF_FORGE_DEV_STORAGE_ROOT must be a specific absolute directory." >&2
  exit 64
fi
if [[ -L "$MOTIF_FORGE_DEV_STORAGE_ROOT" ]]; then
  echo "MOTIF_FORGE_DEV_STORAGE_ROOT must not be a symbolic link." >&2
  exit 64
fi

if (( check_only )); then
  if [[ ! -f .env ]]; then
    echo "missing .env; a normal launch will create it from .env.example" >&2
    exit 78
  fi
  if [[ ! -d "$MOTIF_FORGE_DEV_STORAGE_ROOT" ]]; then
    echo "missing storage root; a normal launch will create: $MOTIF_FORGE_DEV_STORAGE_ROOT" >&2
    exit 78
  fi
  if ! docker_is_ready; then
    echo "Docker is not ready; a normal launch will try: colima start" >&2
    exit 70
  fi
  docker compose config --quiet
  echo "Motif Forge launch prerequisites are ready."
  exit 0
fi

if [[ ! -f .env ]]; then
  if [[ ! -f .env.example ]]; then
    echo "cannot create .env because .env.example is missing" >&2
    exit 78
  fi
  cp .env.example .env
  echo "Created .env from .env.example."
fi

scripts/bootstrap_external_storage.sh "$MOTIF_FORGE_DEV_STORAGE_ROOT" >/dev/null
export MOTIF_FORGE_STORAGE_PROFILE=lean
export MOTIF_FORGE_ARTIFACT_HOST_ROOT="${MOTIF_FORGE_ARTIFACT_HOST_ROOT:-$MOTIF_FORGE_DEV_STORAGE_ROOT/artifacts}"
export MOTIF_FORGE_ARTIFACT_ROOT="${MOTIF_FORGE_ARTIFACT_ROOT:-$MOTIF_FORGE_DEV_STORAGE_ROOT/artifacts}"
export MOTIF_FORGE_TEMP_ROOT="${MOTIF_FORGE_TEMP_ROOT:-$MOTIF_FORGE_DEV_STORAGE_ROOT/tmp}"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-$MOTIF_FORGE_DEV_STORAGE_ROOT/cache/playwright}"
export npm_config_cache="${npm_config_cache:-$MOTIF_FORGE_DEV_STORAGE_ROOT/cache/npm}"

if ! docker_is_ready; then
  if ! command -v colima >/dev/null 2>&1; then
    echo "Docker is not ready and Colima is unavailable." >&2
    echo "Start Docker Desktop, then run this command again." >&2
    exit 70
  fi
  echo "Docker is not ready; starting Colima…"
  colima start --cpus 4 --memory 4 --disk 15 --root-disk 8 \
    --vm-type vz --mount-type virtiofs --runtime docker \
    --binfmt=false --ssh-config=false
  if ! wait_for_docker; then
    echo "Docker did not become ready after colima start." >&2
    exit 70
  fi
fi

if [[ ! -x node_modules/.bin/vite ]]; then
  echo "Installing Web dependencies…"
  npm install
fi

echo "Starting Motif Forge services…"
docker compose up -d

if ! wait_for_http "$api_ready_url" "Motif Forge API" 90; then
  docker compose ps >&2 || true
  exit 70
fi
if ! wait_for_http "$render_ready_url" "Motif Forge Render Worker" 90; then
  docker compose ps >&2 || true
  exit 70
fi

if curl -fsS --max-time 2 "$web_url" >/dev/null 2>&1; then
  echo "Motif Forge Web Studio is already running: $web_url"
  if (( open_browser )) && [[ "$(uname -s)" == "Darwin" ]] && command -v open >/dev/null 2>&1; then
    open "$web_url"
  fi
  exit 0
fi

web_pid=""
stop_web() {
  if [[ -n "$web_pid" ]] && kill -0 "$web_pid" >/dev/null 2>&1; then
    kill "$web_pid" >/dev/null 2>&1 || true
    wait "$web_pid" >/dev/null 2>&1 || true
  fi
  rm -f "$web_pid_file"
}
trap stop_web EXIT INT TERM

if [[ -L "$runtime_dir" || -L "$web_pid_file" ]]; then
  echo "Motif Forge runtime path must not be a symbolic link: $runtime_dir" >&2
  exit 64
fi
mkdir -p "$runtime_dir"
chmod 700 "$runtime_dir"

npm run dev:web -- --host 127.0.0.1 --strictPort &
web_pid=$!
printf '%s\n%s\n' "$web_pid" "$project_root" > "$web_pid_file"

if ! wait_for_http "$web_url" "Motif Forge Web Studio" 45; then
  exit 70
fi

echo
echo "Motif Forge is ready: $web_url"
echo "Stop everything with: scripts/stop_motif_forge.sh"

if (( open_browser )) && [[ "$(uname -s)" == "Darwin" ]] && command -v open >/dev/null 2>&1; then
  open "$web_url"
fi

wait "$web_pid"
