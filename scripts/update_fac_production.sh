#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER_ROOT=""
COMPOSE_FILE="compose.custom.yaml"
PROJECT="hvp"
SITE="frontend"
FAC_USER="Administrator"
BASE_IMAGE=""
BUILD_ONLY=0

usage() {
  cat <<'EOF'
Usage: update_fac_production.sh --docker-root PATH [options]

Build FAC 2.5.1 and the checked-out Hausverwaltung app on top of the existing
ERP image. With --build-only, do not change containers or site data.

Options:
  --compose-file NAME   Base Compose file in PATH (default: compose.custom.yaml)
  --project NAME        Compose project (default: hvp)
  --site NAME           Frappe site (default: frontend)
  --fac-user USER       ERPNext user of LibreChat API key (default: Administrator)
  --base-image IMAGE    Base image; default: image of backend in base Compose
  --build-only          Build and inspect candidate image without deployment
EOF
}

while (($#)); do
  case "$1" in
    --docker-root) DOCKER_ROOT="${2:?Missing path}"; shift 2 ;;
    --compose-file) COMPOSE_FILE="${2:?Missing file}"; shift 2 ;;
    --project) PROJECT="${2:?Missing project}"; shift 2 ;;
    --site) SITE="${2:?Missing site}"; shift 2 ;;
    --fac-user) FAC_USER="${2:?Missing user}"; shift 2 ;;
    --base-image) BASE_IMAGE="${2:?Missing image}"; shift 2 ;;
    --build-only) BUILD_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$DOCKER_ROOT" || ! -f "$DOCKER_ROOT/$COMPOSE_FILE" ]]; then
  echo "--docker-root must contain $COMPOSE_FILE" >&2
  exit 2
fi
DOCKER_ROOT="$(cd "$DOCKER_ROOT" && pwd)"
cd "$DOCKER_ROOT"

if [[ "$BUILD_ONLY" -eq 0 && -n "$(git -C "$APP_ROOT" status --porcelain)" ]]; then
  echo "Hausverwaltung checkout is not clean. Commit/push and git pull before production deployment." >&2
  exit 2
fi

compose_base() { docker compose -p "$PROJECT" -f "$DOCKER_ROOT/$COMPOSE_FILE" "$@"; }
compose_fac() { docker compose -p "$PROJECT" -f "$DOCKER_ROOT/$COMPOSE_FILE" -f "$DOCKER_ROOT/compose.fac.generated.json" "$@"; }

TEMP_DIR="$(mktemp -d /tmp/hv-fac-update.XXXXXX)"
trap 'rm -rf "$TEMP_DIR"' EXIT
compose_base config --format json > "$TEMP_DIR/base.json"
if [[ -z "$BASE_IMAGE" ]]; then
  BASE_IMAGE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["services"]["backend"]["image"])' "$TEMP_DIR/base.json")"
fi
docker image inspect "$BASE_IMAGE" >/dev/null

COMMIT="$(git -C "$APP_ROOT" rev-parse --short=12 HEAD)"
IMAGE="hvp:fac-${COMMIT}-$(date -u +%Y%m%d%H%M%S)"
echo "Building $IMAGE from $BASE_IMAGE and Hausverwaltung $COMMIT..."
docker build \
  --build-arg "BASE_IMAGE=$BASE_IMAGE" \
  --tag "$IMAGE" \
  --file "$APP_ROOT/docker/production-fac/Containerfile" \
  "$APP_ROOT"

docker run --rm --entrypoint /home/frappe/frappe-bench/env/bin/python "$IMAGE" -c '
from pathlib import Path
from hausverwaltung.hausverwaltung.agent_tools.fac_contract import FAC_TOOL_HOOKS
names = {item.rsplit(".", 1)[-1] for item in FAC_TOOL_HOOKS}
required = {"Fac_hv_export_view", "Fac_agent_mail_merge_list_templates", "Fac_agent_mail_merge_prepare", "Fac_agent_mail_merge_execute", "Fac_agent_mail_merge_get_pdf"}
assert required <= names, sorted(required - names)
assert Path("apps/frappe_assistant_core/frappe_assistant_core/api/fac_endpoint.py").is_file()
print(f"FAC image ready: {len(names)} Hausverwaltung tools")
'

if [[ "$BUILD_ONLY" -eq 1 ]]; then
  echo "Build-only complete: $IMAGE"
  exit 0
fi

# Back up the live site before changing any application container or migrating.
echo "Backing up site $SITE with files..."
compose_base exec -T backend bench --site "$SITE" backup --with-files

python3 "$APP_ROOT/docker/production-fac/make_override.py" "$TEMP_DIR/base.json" "$IMAGE" \
  > "$TEMP_DIR/compose.fac.generated.json"
docker compose -p "$PROJECT" -f "$DOCKER_ROOT/$COMPOSE_FILE" \
  -f "$TEMP_DIR/compose.fac.generated.json" config --quiet
if [[ -f compose.fac.generated.json ]]; then
  cp compose.fac.generated.json "compose.fac.generated.json.bak.$(date -u +%Y%m%d%H%M%S)"
fi
mv "$TEMP_DIR/compose.fac.generated.json" compose.fac.generated.json

echo "Starting application services with $IMAGE..."
compose_fac up -d
for attempt in $(seq 1 40); do
  if compose_fac exec -T backend bench version >/dev/null 2>&1; then break; fi
  if [[ "$attempt" -eq 40 ]]; then echo "Backend did not become ready" >&2; exit 1; fi
  sleep 3
done

if ! compose_fac exec -T backend bench --site "$SITE" list-apps | awk '{print $1}' | grep -qx frappe_assistant_core; then
  compose_fac exec -T backend bench --site "$SITE" install-app frappe_assistant_core
fi
compose_fac exec -T backend bench --site "$SITE" migrate
FAC_KWARGS="$(python3 -c 'import sys; print(repr({"user":sys.argv[1],"include_focused_tools":True}))' "$FAC_USER")"
compose_fac exec -T backend bench --site "$SITE" execute \
  hausverwaltung.hausverwaltung.services.fac_setup.enable_external_tools \
  --kwargs "$FAC_KWARGS"
compose_fac exec -T backend bench --site "$SITE" clear-cache

if [[ -n "${FAC_AUTH_HEADER:-}" ]]; then
  export FAC_MCP_URL="${FAC_MCP_URL:-http://frontend:8080/api/method/frappe_assistant_core.api.fac_endpoint.handle_mcp}"
  compose_fac exec -T -e FAC_MCP_URL -e FAC_AUTH_HEADER backend \
    ./env/bin/python apps/hausverwaltung/scripts/verify_fac_mcp.py
else
  echo "Set FAC_AUTH_HEADER and run the MCP check from docs/fac-librechat-build.md."
fi

echo "FAC update complete. Use compose.fac.generated.json with future Compose commands."
