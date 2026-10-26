#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$project_root"

check_only=0
open_browser=1
personal_beta=0
enable_deepseek=0
web_port=5173
web_url="http://127.0.0.1:5173"
api_ready_url="http://127.0.0.1:8000/health/ready"
render_ready_url="http://127.0.0.1:8090/health"
runtime_tag="$(printf '%s' "$project_root" | cksum | awk '{print $1}')"
runtime_dir="${MOTIF_FORGE_RUNTIME_DIR:-/private/tmp/motif-forge-$(id -u)-$runtime_tag}"
web_pid_file="$runtime_dir/web.pid"

usage() {
  cat <<'EOF'
Usage: scripts/start_motif_forge.sh [--personal-beta] [--enable-deepseek] [--check] [--no-open]

Start the complete local Motif Forge portfolio:
  - initialize the external development storage root;
  - require an already available Docker daemon; no VM is started or stopped;
  - start the existing Docker Compose backend and workers;
  - wait for API and Render Worker readiness;
  - start the Vite Web Studio and open it in the browser.

Options:
  --personal-beta  Isolated reviewed-catalog profile; models disabled by default.
  --enable-deepseek  Explicitly load the private Key configured by configure_deepseek.py.
  --check     Validate local prerequisites without starting or changing anything.
  --no-open   Do not open the browser after the Web Studio becomes ready.
  -h, --help  Show this help.

Ctrl+C stops the Vite frontend. Stop the complete local stack with:
  scripts/stop_motif_forge.sh
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --personal-beta)
      personal_beta=1
      ;;
    --enable-deepseek)
      enable_deepseek=1
      ;;
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

# Only the checked private file may supply this Secret to Compose.
unset DEEPSEEK_API_KEY
compose_command=(docker compose)
if (( personal_beta )); then
  # Explicit public configuration at both Compose layers; never load/copy .env.
  unset COMPOSE_FILE COMPOSE_ENV_FILES COMPOSE_PROFILES
  export MOTIF_FORGE_CONTAINER_ENV_FILE="$project_root/.env.example"
  compose_command+=(--env-file "$project_root/.env.example"
    -f "$project_root/compose.yaml" -f "$project_root/compose.personal-beta.yaml")
  export MOTIF_FORGE_DEV_STORAGE_ROOT="${MOTIF_FORGE_BETA_STORAGE_ROOT:-$project_root/artifacts/personal-beta}"
  export MOTIF_FORGE_REVIEWED_PIANO_ROOT="${MOTIF_FORGE_REVIEWED_PIANO_ROOT:-$project_root/artifacts/instrument-packs/kw-small-20190703}"
  export MOTIF_FORGE_COMPOSE_PROJECT_NAME="${MOTIF_FORGE_COMPOSE_PROJECT_NAME:-motif-forge-beta-$(id -u)-$runtime_tag}"
  runtime_dir="$runtime_dir-personal-beta"
  web_pid_file="$runtime_dir/web.pid"
  export MOTIF_FORGE_API_HOST_PORT="${MOTIF_FORGE_BETA_API_PORT:-18000}"
  export MOTIF_FORGE_RENDER_HOST_PORT="${MOTIF_FORGE_BETA_RENDER_PORT:-18090}"
  export MOTIF_FORGE_POSTGRES_HOST_PORT="${MOTIF_FORGE_BETA_POSTGRES_PORT:-15432}"
  export MOTIF_FORGE_REDIS_HOST_PORT="${MOTIF_FORGE_BETA_REDIS_PORT:-16379}"
  web_port="${MOTIF_FORGE_BETA_WEB_PORT:-15173}"
  for port in "$MOTIF_FORGE_API_HOST_PORT" "$MOTIF_FORGE_RENDER_HOST_PORT"       "$MOTIF_FORGE_POSTGRES_HOST_PORT" "$MOTIF_FORGE_REDIS_HOST_PORT" "$web_port"; do
    if [[ ! "$port" =~ ^[1-9][0-9]{0,4}$ ]] || (( 10#$port < 1 || 10#$port > 65535 )); then
      echo "Invalid personal Beta port; use a number from 1 to 65535." >&2
      exit 64
    fi
  done
  web_url="http://127.0.0.1:$web_port"
  api_ready_url="http://127.0.0.1:$MOTIF_FORGE_API_HOST_PORT/health/ready"
  render_ready_url="http://127.0.0.1:$MOTIF_FORGE_RENDER_HOST_PORT/health"
  export MOTIF_FORGE_API_PROXY_TARGET="http://127.0.0.1:$MOTIF_FORGE_API_HOST_PORT"
  export MOTIF_FORGE_ARTIFACT_HOST_ROOT="$MOTIF_FORGE_DEV_STORAGE_ROOT/artifacts"
  export MOTIF_FORGE_ARTIFACT_ROOT="$MOTIF_FORGE_DEV_STORAGE_ROOT/artifacts"
  export MOTIF_FORGE_TEMP_ROOT="$MOTIF_FORGE_DEV_STORAGE_ROOT/tmp"
fi

if (( enable_deepseek )); then
  if ! python3 scripts/configure_deepseek.py --check; then
    echo "DeepSeek is not enabled. Run: python3 scripts/configure_deepseek.py" >&2
    exit 78
  fi
  deepseek_env_file="$(python3 scripts/configure_deepseek.py --path)"
  if (( ! personal_beta )); then
    base_env="$project_root/.env.example"
    if [[ -f "$project_root/.env" ]]; then base_env="$project_root/.env"; fi
    compose_command+=(--env-file "$base_env" -f "$project_root/compose.yaml")
  fi
  compose_command+=(--env-file "$deepseek_env_file" -f "$project_root/compose.deepseek.yaml")
fi

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is unavailable: $command_name" >&2
    exit 69
  fi
}

docker_is_ready() {
  node scripts/motif_runtime_owner.mjs probe "$project_root" "$runtime_dir" >/dev/null 2>&1
}

wait_for_http() {
  local url="$1"
  local label="$2"
  local attempts="${3:-60}"

  for ((attempt = 1; attempt <= attempts; attempt += 1)); do
    if curl --noproxy "*" -fsS --max-time 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done

  echo "$label did not become ready: $url" >&2
  return 1
}

for command_name in docker curl npm node python3; do
  require_command "$command_name"
done

if (( personal_beta )); then
  if [[ ! -x node_modules/.bin/vite ]]; then
    echo "Web dependencies are missing; install the existing lockfile dependencies explicitly." >&2
    exit 69
  fi
  if ! PYTHONDONTWRITEBYTECODE=1 python3 scripts/personal_beta_preflight.py --repo "$project_root"       --piano-root "$MOTIF_FORGE_REVIEWED_PIANO_ROOT"; then
    echo "Personal Beta resource preflight failed; no services were started." >&2
    exit 78
  fi
  if ! docker_is_ready; then
    echo "Docker is not ready; start your Docker environment explicitly, then retry." >&2
    exit 70
  fi
  if ! release="$(PYTHONDONTWRITEBYTECODE=1 python3 scripts/personal_beta_release.py --repo "$project_root")"; then
    echo "Personal Beta release/local schema check failed; no services were started." >&2
    exit 78
  fi
  IFS=$'\t' read -r beta_api_image beta_api_image_id beta_schema <<< "$release"
  # Bind creation to the immutable ID, even if the tag moves after inspection.
  export MOTIF_FORGE_BETA_RELEASE_IMAGE_ID="$beta_api_image_id"
  if ! selected_images="$("${compose_command[@]}" config --format json | python3 -c 'import json,sys; s=json.load(sys.stdin)["services"]; print(s["api"]["image"], s["migrate"]["image"], sep="\t")' 2>/dev/null)"; then
    echo "Personal Beta release configuration could not be read; no services were started." >&2
    exit 78
  fi
  IFS=$'\t' read -r selected_api_image selected_migration_image <<< "$selected_images"
  if [[ "$selected_api_image" != "$beta_api_image_id" || "$selected_migration_image" != "$beta_api_image_id" ]]; then
    echo "Personal Beta API/migrator images differ from the reviewed release; no services were started." >&2
    exit 78
  fi
  for target in api shared-python media-worker render-worker; do
    image="motif-forge-beta-$target:${MOTIF_FORGE_BETA_IMAGE_TAG:-local}"
    if [[ "$target" == api ]]; then image="$beta_api_image"; fi
    if [[ "$target" == shared-python ]]; then image="motif-forge-beta-api:${MOTIF_FORGE_BETA_IMAGE_TAG:-local}"; fi
    if ! actual_image_id="$(docker image inspect --format '{{.Id}}' "$image" 2>/dev/null)"; then
      echo "Missing personal Beta image: $image. Restore the reviewed API release; workers can use scripts/build_compose_images.sh --personal-beta TARGET. Launch never builds, pulls or learns a new pin." >&2
      exit 78
    fi
    if [[ "$target" == api && "$actual_image_id" != "$beta_api_image_id" ]]; then
      echo "Personal Beta API image identity differs from the reviewed release; no services were started." >&2
      exit 78
    fi
  done
fi

if (( ! check_only )); then
node scripts/motif_runtime_owner.mjs init "$project_root" "$runtime_dir" || exit "$?"
if ! exec 9<> "$runtime_dir/operation.lock"; then exit 1; fi
python3 scripts/motif_runtime_lock.py acquire "$runtime_dir/operation.lock" || exit "$?"
fi

if ! "${compose_command[@]}" version >/dev/null 2>&1; then
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
  if (( ! personal_beta )) && [[ ! -f .env ]]; then
    echo "missing .env; a normal launch will create it from .env.example" >&2
    exit 78
  fi
  if [[ ! -d "$MOTIF_FORGE_DEV_STORAGE_ROOT" ]]; then
    echo "missing storage root; a normal launch will create: $MOTIF_FORGE_DEV_STORAGE_ROOT" >&2
    exit 78
  fi
  if ! docker_is_ready; then
    echo "Docker is not ready; start your Docker environment explicitly, then retry" >&2
    exit 70
  fi
  "${compose_command[@]}" config --quiet
  echo "Motif Forge launch prerequisites are ready."
  exit 0
fi

if (( ! personal_beta )) && [[ ! -f .env ]]; then
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
  echo "Docker is not ready. Start your Docker environment explicitly; no VM was changed." >&2
  exit 70
fi
ownership="$(node scripts/motif_runtime_owner.mjs prepare "$project_root" "$runtime_dir" "${MOTIF_FORGE_COMPOSE_PROJECT_NAME:-}")"
read -r compose_project runtime_owner <<< "$ownership"
export MOTIF_FORGE_RUNTIME_OWNER="$runtime_owner"

# A killed launcher may leave a dead PID receipt; never replace a live owner.
if [[ -e "$web_pid_file" || -L "$web_pid_file" ]]; then
  if [[ -L "$web_pid_file" || ! -f "$web_pid_file" ]]; then
    echo "Web ownership record is invalid; no existing server was adopted." >&2
    exit 78
  fi
  previous_pid="$(sed -n '1p' "$web_pid_file")"
  previous_root="$(sed -n '2p' "$web_pid_file")"
  if [[ ! "$previous_pid" =~ ^[1-9][0-9]*$ || "$previous_root" != "$project_root" ]] || kill -0 "$previous_pid" 2>/dev/null; then
    echo "Web ownership is still recorded; stop it using its original launcher first." >&2
    exit 78
  fi
  rm -f "$web_pid_file"
fi

if [[ ! -x node_modules/.bin/vite ]]; then
  echo "Installing Web dependencies…"
  npm install
fi

echo "Starting Motif Forge services…"
if (( personal_beta )); then
  "${compose_command[@]}" --project-name "$compose_project" up -d --no-build --pull never
else
  "${compose_command[@]}" --project-name "$compose_project" up -d
fi

if ! wait_for_http "$api_ready_url" "Motif Forge API" 90; then
  "${compose_command[@]}" --project-name "$compose_project" ps >&2 || true
  exit 70
fi
if ! wait_for_http "$render_ready_url" "Motif Forge Render Worker" 90; then
  "${compose_command[@]}" --project-name "$compose_project" ps >&2 || true
  exit 70
fi

if (( personal_beta )); then
  if ! PYTHONDONTWRITEBYTECODE=1 python3 scripts/personal_beta_preflight.py --repo "$project_root"       --piano-root "$MOTIF_FORGE_REVIEWED_PIANO_ROOT"       --api-url "http://127.0.0.1:$MOTIF_FORGE_API_HOST_PORT"       --render-url "http://127.0.0.1:$MOTIF_FORGE_RENDER_HOST_PORT"; then
    echo "Personal Beta live resource checks failed; inspect the reported code before retrying." >&2
    exit 70
  fi
fi

if curl --noproxy "*" -fsS --max-time 2 "$web_url" >/dev/null 2>&1; then
  echo "Web port is occupied; no existing server was adopted: $web_url" >&2
  exit 78
fi

web_pid=""
web_started=""
stop_process_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    stop_process_tree "$child"
  done
  kill -TERM "$pid" >/dev/null 2>&1 || true
}
stop_web() {
  if [[ -n "$web_pid" && -n "$web_started" ]] &&
      [[ "$(ps -p "$web_pid" -o lstart= 2>/dev/null | sed 's/^[[:space:]]*//')" == "$web_started" ]]; then
    stop_process_tree "$web_pid"
    for ((attempt = 1; attempt <= 50; attempt += 1)); do
      kill -0 "$web_pid" >/dev/null 2>&1 || break
      sleep 0.1
    done
    kill -KILL "$web_pid" >/dev/null 2>&1 || true
    wait "$web_pid" >/dev/null 2>&1 || true
  fi
  if [[ -f "$web_pid_file" && ! -L "$web_pid_file" &&
        "$(sed -n '1p' "$web_pid_file")" == "$web_pid" &&
        "$(sed -n '3p' "$web_pid_file")" == "$web_started" ]]; then
    rm -f "$web_pid_file"
  fi
}
trap stop_web EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ -L "$runtime_dir" || -L "$web_pid_file" ]]; then
  echo "Motif Forge runtime path must not be a symbolic link: $runtime_dir" >&2
  exit 64
fi
mkdir -p "$runtime_dir"
chmod 700 "$runtime_dir"

npm run dev:web -- --host 127.0.0.1 --port "$web_port" --strictPort 9>&- &
web_pid=$!
web_started="$(ps -p "$web_pid" -o lstart= | sed 's/^[[:space:]]*//')"
web_record="$runtime_dir/web.pid.$$.tmp"
printf '%s\n%s\n%s\n' "$web_pid" "$project_root" "$web_started" > "$web_record"
if ! ln "$web_record" "$web_pid_file"; then
  rm -f "$web_record"
  echo "Web ownership is already recorded; no existing record was replaced." >&2
  exit 78
fi
rm -f "$web_record"

if ! wait_for_http "$web_url" "Motif Forge Web Studio" 45; then
  exit 70
fi

echo
python3 scripts/motif_runtime_lock.py release "$runtime_dir/operation.lock"
exec 9>&-
echo "Motif Forge is ready: $web_url"
if (( personal_beta )); then
  echo "Stop this profile with: scripts/stop_motif_forge.sh --personal-beta"
  if (( enable_deepseek )); then
    echo "DeepSeek Key loaded for backend services; connection and generation have not been tested. Open Settings."
  else
    echo "Models are disabled. Configure a Key from Settings and explicitly enable it when needed."
  fi
  echo "Runtime receipt supports normal close/reopen; OS temporary-directory cleanup requires explicit recovery."
else
  echo "Stop everything with: scripts/stop_motif_forge.sh"
fi

if (( open_browser )) && [[ "$(uname -s)" == "Darwin" ]] && command -v open >/dev/null 2>&1; then
  open "$web_url"
fi

wait "$web_pid"
