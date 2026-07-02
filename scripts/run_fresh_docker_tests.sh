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
# - runs targeted critical backend/report tests by default
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
RUN_UI_TESTS="${RUN_UI_TESTS:-1}"
RUN_ALL_TESTS="${RUN_ALL_TESTS:-0}"
KEEP_STACK="${KEEP_STACK:-0}"
KEEP_ON_FAIL="${KEEP_ON_FAIL:-0}"
CYPRESS_SPECS="${CYPRESS_SPECS:-cypress/integration/mieterwechsel_complex_ui.js}"

TEST_MODULES_DEFAULT=(
	"hausverwaltung.hausverwaltung.doctype.bankauszug_import.test_bankauszug_import"
	"hausverwaltung.hausverwaltung.page.bankimport_v2.test_bankimport_v2"
	"hausverwaltung.hausverwaltung.doctype.mietvertrag.test_mietvertrag"
	"hausverwaltung.hausverwaltung.page.buchen_cockpit.test_buchen_cockpit"
	"hausverwaltung.hausverwaltung.report.mieterkonto.test_mieterkonto_aggregation"
	"hausverwaltung.hausverwaltung.report.noch_offene_rechnungen_und_forderungen.test_noch_offene_rechnungen_und_forderungen_aggregation"
	"hausverwaltung.hausverwaltung.report.hauptbuch_hv.test_hauptbuch_hv_aggregation"
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
  configurator:
    command:
      - >
        bench set-config -g db_host \$\$DB_HOST;
        bench set-config -gp db_port \$\$DB_PORT;
        bench set-config -g redis_cache "redis://\$\$REDIS_CACHE";
        bench set-config -g redis_queue "redis://\$\$REDIS_QUEUE";
        bench set-config -g redis_socketio "redis://\$\$REDIS_QUEUE";
        bench set-config -gp socketio_port \$\$SOCKETIO_PORT;
        bench set-config -g host_name "http://frontend:8080";
        bench set-config -gp webserver_port 8080;
        bench set-config -g developer_mode 1;
        ( echo n; echo y ) | bench get-app file:///home/frappe/frappe-bench/apps/process_engine;
        ( echo n; echo y ) | bench get-app file:///home/frappe/frappe-bench/apps/mail_merge;
        ( echo n; echo y ) | bench get-app file:///home/frappe/frappe-bench/apps/hausverwaltung;
        ( echo n; echo y ) | bench get-app file:///home/frappe/frappe-bench/apps/hausverwaltung_peters;
        bench setup requirements --python process_engine;
        bench setup requirements --python mail_merge;
        bench setup requirements --python hausverwaltung;
        bench setup requirements --python hausverwaltung_peters;
        ls -1 apps > sites/apps.txt;

  create-site:
    command:
      - >
        SITE_NAME=\${SITE_NAME:-frontend};
        if [ -d "sites/\$\$SITE_NAME" ]; then echo "Site '\$\$SITE_NAME' already exists, skipping creation"; exit 0; fi;
        wait-for-it -t 120 db:3306;
        wait-for-it -t 120 redis-cache:6379;
        wait-for-it -t 120 redis-queue:6379;
        export start=\`date +%s\`;
        until [[ -n \`grep -hs ^ sites/common_site_config.json | jq -r ".db_host // empty"\` ]] && \
          [[ -n \`grep -hs ^ sites/common_site_config.json | jq -r ".redis_cache // empty"\` ]] && \
          [[ -n \`grep -hs ^ sites/common_site_config.json | jq -r ".redis_queue // empty"\` ]];
        do
          echo "Waiting for sites/common_site_config.json to be created";
          sleep 5;
          if (( \`date +%s\`-start > 120 )); then
            echo "could not find sites/common_site_config.json with required keys";
            exit 1
          fi
        done;
        echo "sites/common_site_config.json found";
        ( echo n; echo y ) | bench get-app file:///home/frappe/frappe-bench/apps/process_engine;
        ( echo n; echo y ) | bench get-app file:///home/frappe/frappe-bench/apps/mail_merge;
        ( echo n; echo y ) | bench get-app file:///home/frappe/frappe-bench/apps/hausverwaltung;
        ( echo n; echo y ) | bench get-app file:///home/frappe/frappe-bench/apps/hausverwaltung_peters;
        bench setup requirements --python process_engine;
        bench setup requirements --python mail_merge;
        bench setup requirements --python hausverwaltung;
        bench setup requirements --python hausverwaltung_peters;
        ls -1 apps > sites/apps.txt;
        echo "Creating site '\$\$SITE_NAME'";
        bench new-site --mariadb-user-host-login-scope='%' --admin-password=admin --db-root-username=root --db-root-password=admin --install-app erpnext --install-app process_engine --install-app mail_merge --install-app hausverwaltung --install-app hausverwaltung_peters --set-default "\$\$SITE_NAME";
        bench use "\$\$SITE_NAME";
        if [ -n "\$\$PAPERLESS_NGX_URL" ]; then bench --site "\$\$SITE_NAME" set-config paperless_ngx_url "\$\$PAPERLESS_NGX_URL"; fi;
        if [ -n "\$\$PAPERLESS_NGX_PUBLIC_URL" ]; then bench --site "\$\$SITE_NAME" set-config paperless_ngx_public_url "\$\$PAPERLESS_NGX_PUBLIC_URL"; fi;
        if [ -n "\$\$PAPERLESS_NGX_TOKEN" ]; then bench --site "\$\$SITE_NAME" set-config paperless_ngx_token "\$\$PAPERLESS_NGX_TOKEN"; fi;
        if [ -n "\$\$PAPERLESS_NGX_TAG_IDS" ]; then bench --site "\$\$SITE_NAME" set-config paperless_ngx_tag_ids "\$\$PAPERLESS_NGX_TAG_IDS"; fi;
        if [ -n "\$\$PAPERLESS_NGX_CORRESPONDENT_ID" ]; then bench --site "\$\$SITE_NAME" set-config paperless_ngx_correspondent_id "\$\$PAPERLESS_NGX_CORRESPONDENT_ID"; fi;
        if [ -n "\$\$PAPERLESS_NGX_DOCUMENT_TYPE_ID" ]; then bench --site "\$\$SITE_NAME" set-config paperless_ngx_document_type_id "\$\$PAPERLESS_NGX_DOCUMENT_TYPE_ID"; fi;
        if [ -n "\$\$PAPERLESS_NGX_VERIFY_SSL" ]; then bench --site "\$\$SITE_NAME" set-config paperless_ngx_verify_ssl "\$\$PAPERLESS_NGX_VERIFY_SSL"; fi;
        if [ -n "\$\$PAPERLESS_NGX_TIMEOUT" ]; then bench --site "\$\$SITE_NAME" set-config paperless_ngx_timeout "\$\$PAPERLESS_NGX_TIMEOUT"; fi;
        bench --site "\$\$SITE_NAME" migrate;
        bench --site "\$\$SITE_NAME" enable-scheduler;
        bench --site "\$\$SITE_NAME" execute hausverwaltung.hausverwaltung.scripts.bootstrap_site.run;
        bench --site "\$\$SITE_NAME" clear-cache;

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

log "Enabling tests on fresh site..."
compose exec -T backend bash -lc "cd /home/frappe/frappe-bench && bench --site '${SITE_NAME}' set-config allow_tests true"

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

	log "Running Cypress UI tests against isolated stack..."
	(
		cd "${APP_DIR}"
		CYPRESS_BASE_URL="http://127.0.0.1:${HTTP_PORT}" \
			npx cypress run \
				--spec "${CYPRESS_SPECS}" \
				--env "hv_user=Administrator,hv_password=${ADMIN_PASSWORD}"
	)
fi

log "Fresh Docker test run passed."
