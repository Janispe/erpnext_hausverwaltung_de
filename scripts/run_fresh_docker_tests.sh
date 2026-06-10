#!/usr/bin/env bash
set -euo pipefail

# Stage-2 fresh-install test runner.
#
# Starts an isolated Docker Compose stack with fresh volumes, installs a fresh
# Frappe/ERPNext/Hausverwaltung site, runs targeted tests, then removes the
# stack and its volumes again.
#
# Defaults are intentionally conservative:
# - uses separate ports so it can run next to the local 8080 dev stack
# - runs targeted Bankimport backend tests by default
# - runs real browser UI tests only when RUN_UI_TESTS=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
FRAPPE_DOCKER_DIR="$(cd "${APP_DIR}/../.." && pwd)"
PETERS_DIR="${PETERS_DIR:-${FRAPPE_DOCKER_DIR}/apps/hausverwaltung_peters}"
REACT_DIR="${APP_DIR}/HV_Bankimport/src_react"

PROJECT_NAME="${PROJECT_NAME:-hv_fresh_tests_$(date +%Y%m%d%H%M%S)}"
SITE_NAME="${SITE_NAME:-frontend}"
HTTP_PORT="${HTTP_PORT:-18080}"
DB_PORT="${DB_PORT:-13306}"
TEMPORAL_UI_PORT="${TEMPORAL_UI_PORT:-18081}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
RUN_UI_TESTS="${RUN_UI_TESTS:-0}"
RUN_ALL_TESTS="${RUN_ALL_TESTS:-0}"
KEEP_STACK="${KEEP_STACK:-0}"
KEEP_ON_FAIL="${KEEP_ON_FAIL:-0}"

TEST_MODULES_DEFAULT=(
	"hausverwaltung.hausverwaltung.doctype.bankauszug_import.test_bankauszug_import"
	"hausverwaltung.hausverwaltung.page.bankimport_v2.test_bankimport_v2"
)

cleanup_done=0
tmp_override=""

log() {
	printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"
}

fail() {
	printf '\nERROR: %s\n' "$*" >&2
	exit 1
}

require_file() {
	[[ -f "$1" ]] || fail "Required file not found: $1"
}

compose() {
	docker compose -p "${PROJECT_NAME}" -f "${PETERS_DIR}/compose.yml" -f "${tmp_override}" "$@"
}

cleanup() {
	local status=$?
	if [[ "${cleanup_done}" == "1" ]]; then
		exit "${status}"
	fi
	cleanup_done=1

	if [[ "${KEEP_STACK}" == "1" || ( "${status}" != "0" && "${KEEP_ON_FAIL}" == "1" ) ]]; then
		log "Keeping stack '${PROJECT_NAME}' for inspection."
		log "Stop later with: docker compose -p ${PROJECT_NAME} -f ${PETERS_DIR}/compose.yml -f ${tmp_override} down -v --remove-orphans"
		exit "${status}"
	fi

	log "Removing isolated Docker stack '${PROJECT_NAME}' and volumes..."
	if [[ -n "${tmp_override}" && -f "${tmp_override}" ]]; then
		compose down -v --remove-orphans || true
		rm -f "${tmp_override}"
	fi
	exit "${status}"
}

trap cleanup EXIT

require_file "${PETERS_DIR}/compose.yml"
require_file "${REACT_DIR}/package.json"
command -v docker >/dev/null 2>&1 || fail "docker is not installed or not on PATH."
docker compose version >/dev/null 2>&1 || fail "docker compose is not available."

if ! docker network ls --format '{{.Name}}' | grep -qx "shared_net"; then
	log "Creating external Docker network shared_net..."
	docker network create shared_net >/dev/null
fi

tmp_override="$(mktemp "${TMPDIR:-/tmp}/hv-fresh-compose.XXXXXX.yml")"
cat >"${tmp_override}" <<YAML
services:
  db:
    ports: !override
      - "127.0.0.1:${DB_PORT}:3306"

  frontend:
    ports: !override
      - "127.0.0.1:${HTTP_PORT}:8080"
    environment:
      FRAPPE_SITE_NAME_HEADER: "${SITE_NAME}"

  caddy:
    profiles: ["disabled"]

  temporal-postgresql:
    profiles: ["disabled"]

  temporal:
    profiles: ["disabled"]

  temporal-ui:
    profiles: ["disabled"]
    ports: !override
      - "127.0.0.1:${TEMPORAL_UI_PORT}:8080"

  temporal-worker:
    profiles: ["disabled"]
YAML

log "Starting isolated fresh-install stack '${PROJECT_NAME}'..."
log "Frappe URL will be http://127.0.0.1:${HTTP_PORT} (site: ${SITE_NAME})"

(
	cd "${PETERS_DIR}"
	export SITE_NAME
	export HV_BOOTSTRAP_FORCE=1
	export HV_BOOTSTRAP_CREATE_COA=1
	export HV_BOOTSTRAP_RUN_SETUP_WIZARD=1
	export HV_BOOTSTRAP_MARK_SETUP_COMPLETE=1
	compose up -d --wait
)

log "Waiting for site '${SITE_NAME}' to answer..."
for _ in $(seq 1 120); do
	if curl -fsS "http://127.0.0.1:${HTTP_PORT}/api/method/ping" >/dev/null 2>&1; then
		break
	fi
	sleep 2
done
curl -fsS "http://127.0.0.1:${HTTP_PORT}/api/method/ping" >/dev/null \
	|| fail "Fresh stack did not become reachable on port ${HTTP_PORT}."

log "Running backend tests on fresh site..."
if [[ "${RUN_ALL_TESTS}" == "1" ]]; then
	compose exec -T backend bash -lc "cd /home/frappe/frappe-bench && bench --site '${SITE_NAME}' run-tests --app hausverwaltung"
else
	if [[ -n "${TEST_MODULES:-}" ]]; then
		IFS=',' read -r -a modules <<<"${TEST_MODULES}"
	else
		modules=("${TEST_MODULES_DEFAULT[@]}")
	fi
	for module in "${modules[@]}"; do
		log "bench run-tests --module ${module}"
		compose exec -T backend bash -lc "cd /home/frappe/frappe-bench && bench --site '${SITE_NAME}' run-tests --module '${module}'"
	done
fi

if [[ "${RUN_UI_TESTS}" == "1" ]]; then
	log "Running real Frappe Playwright UI tests against isolated stack..."
	(
		cd "${REACT_DIR}"
		FRAPPE_BASE_URL="http://127.0.0.1:${HTTP_PORT}" \
		FRAPPE_SITE="${SITE_NAME}" \
		FRAPPE_BACKEND_CONTAINER="${PROJECT_NAME}-backend-1" \
		FRAPPE_USER="Administrator" \
		FRAPPE_PASSWORD="${ADMIN_PASSWORD}" \
			npm run test:e2e:frappe
	)
fi

log "Fresh Docker test run passed."
