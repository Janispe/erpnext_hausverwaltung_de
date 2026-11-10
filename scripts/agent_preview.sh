#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Aufruf: ./scripts/agent_preview.sh <up|status|seed|test|restart|migrate|build|stop> <ticket> [test-modul]
Docker-Kontext: hv-preview
HTTP-Port: HV_PREVIEW_HTTP_PORT (Standard 8180, nur Loopback)
USAGE
}

fail() {
  printf 'Preview: %s\n' "$*" >&2
  exit 1
}

if [[ ${1:-} == --help || ${1:-} == -h ]]; then
  usage
  exit 0
fi

action=${1:-}
ticket=${2:-}
test_module=${3:-hausverwaltung.hausverwaltung.doctype.mietvertrag.test_mietvertrag}
case "$action" in
  up|status|seed|test|restart|migrate|build|stop) ;;
  *) usage >&2; exit 2 ;;
esac
[[ "$ticket" =~ ^[a-z0-9]([a-z0-9-]{0,38}[a-z0-9])?$ ]] ||
  fail 'Ticket-ID aus Kleinbuchstaben, Ziffern und Bindestrichen angeben.'
[[ $# -le 2 || ( $# == 3 && "$action" == test ) ]] || fail 'Zu viele Argumente.'
[[ "$test_module" =~ ^[a-zA-Z_][a-zA-Z0-9_.]*$ ]] || fail 'Ungültiges Testmodul.'

port=${HV_PREVIEW_HTTP_PORT:-8180}
[[ "$port" =~ ^[1-9][0-9]{3,4}$ ]] &&
  (( port >= 1024 && port <= 65535 && port != 8080 && port != 8090 )) ||
  fail 'HTTP-Port zwischen 1024 und 65535 wählen. 8080 und 8090 sind reserviert.'

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
workspace=$(dirname -- "$repo")
project=hv-qa-$ticket
context=hv-preview
site=frontend
apps=(process_engine mail_merge hausverwaltung thunderbird_hausverwaltung)

# Resolve the dedicated context before any request to its daemon.
unset DOCKER_HOST DOCKER_CONTEXT DOCKER_TLS_VERIFY DOCKER_CERT_PATH
endpoint=$(docker context inspect --format '{{(index .Endpoints "docker").Host}}' "$context") ||
  fail 'Docker-Kontext hv-preview ist nicht verfügbar.'
rootless_socket=/run/user/$(id -u)/docker.sock
docker_cli=(docker --context "$context")
case "$endpoint" in
  "unix://$rootless_socket")
    [[ -S "$rootless_socket" && -O "$rootless_socket" &&
       "$(realpath -e -- "$rootless_socket")" == "$rootless_socket" ]] ||
      fail 'Rootless-Socket fehlt oder gehört einem anderen Benutzer.'
    options=$("${docker_cli[@]}" info --format '{{range .SecurityOptions}}{{println .}}{{end}}') ||
      fail 'Der Rootless-Daemon ist nicht erreichbar.'
    grep -Eq '^name=rootless(,|$)' <<< "$options" ||
      fail 'Der gewählte Docker-Daemon läuft ohne Rootless-Modus.'
    ;;
  unix:///var/run/docker.sock|unix:///run/docker.sock)
    if ! systemd-detect-virt --vm --quiet || systemd-detect-virt --container --quiet; then
      fail 'Der systemweite Docker-Socket ist nur direkt in einer erkannten VM zulässig.'
    fi
    [[ -S /run/docker.sock && "$(realpath -e -- "${endpoint#unix://}")" == /run/docker.sock ]] ||
      fail 'Der VM-Docker-Socket fehlt oder verweist auf einen anderen Pfad.'
    ;;
  *) fail 'hv-preview muss auf den lokalen VM- oder eigenen Rootless-Socket zeigen.' ;;
esac

containers=$("${docker_cli[@]}" ps --all --format '{{.Names}}') ||
  fail 'Container im Preview-Kontext konnten nicht geprüft werden.'
if grep -Eq '^(hvp|frappe)(-|$)' <<< "$containers"; then
  fail 'Produktionscontainer im gewählten Docker-Kontext erkannt.'
fi

if [[ "$action" != stop && "$action" != status ]]; then
  for app in "${apps[@]}"; do
    checkout=$workspace/$app
    [[ -f "$checkout/pyproject.toml" &&
       "$(git -C "$checkout" rev-parse --show-toplevel)" == "$checkout" ]] ||
      fail "Eigener Checkout für $app fehlt unter $workspace."
  done
fi
[[ "$repo" == "$workspace/hausverwaltung" ]] ||
  fail 'Das Skript muss aus dem hausverwaltung-Checkout des Ticket-Workspaces laufen.'

# Compose should use only the preview files and their explicit settings.
unset FRAPPE_BASE_IMAGE COMPOSE_ENV_FILES COMPOSE_PROFILES
unset HV_LANGUAGE HV_TIME_ZONE HV_COUNTRY HV_CURRENCY HV_COA_TEMPLATE
unset HV_BOOTSTRAP_CREATE_COA HV_BOOTSTRAP_RUN_SETUP_WIZARD HV_BOOTSTRAP_MARK_SETUP_COMPLETE HV_BOOTSTRAP_FORCE
export SITE_NAME=$site
export HV_APPS="${apps[*]}"
export HV_COMPANY='Demo Hausverwaltung'
export HV_PREVIEW_PROJECT=$project
export HV_PREVIEW_WORKSPACE=$repo
export HV_PREVIEW_HTTP_PORT=$port
compose=("${docker_cli[@]}" compose --project-name "$project" --project-directory "$repo"
  --env-file /dev/null -f "$repo/compose.dev.yml" -f "$repo/compose.agent-preview.yml")
bench=("${compose[@]}" exec -T backend bench --site "$site")

# A ticket can be restarted from the same checkout only.
project_containers=$("${docker_cli[@]}" ps --all --filter "label=com.docker.compose.project=$project" \
  --format '{{.Names}}{{"\t"}}{{.Label "com.docker.compose.project.working_dir"}}') ||
  fail 'Das vorhandene Preview-Projekt konnte nicht geprüft werden.'
while IFS=$'\t' read -r name owner; do
  if [[ -n "$name" && "$owner" != "$repo" ]]; then
    fail 'Das Projekt hat bereits Container aus einem anderen Checkout.'
  fi
done <<< "$project_containers"

volume=${project}_db-data
volumes=$("${docker_cli[@]}" volume ls --quiet --filter "name=$volume") ||
  fail 'Preview-Volumes konnten nicht geprüft werden.'
if grep -Fxq "$volume" <<< "$volumes"; then
  owner=$("${docker_cli[@]}" volume inspect --format '{{index .Labels "de.hausverwaltung.preview.checkout"}}' "$volume")
  [[ "$owner" == "$repo" ]] ||
    fail 'Das Projekt hat bereits ein Datenbank-Volume aus einem anderen Checkout.'
fi

preview_url() {
  local address
  address=$("${compose[@]}" port frontend 8080) || fail 'Das Preview-Frontend läuft noch nicht.'
  [[ "$address" =~ ^127\.0\.0\.1:[0-9]+$ ]] ||
    fail 'Das Preview-Frontend meldet keine Loopback-Adresse.'
  printf 'http://%s\n' "$address"
}

wait_for_site() {
  local url=$1 response attempt
  for ((attempt=1; attempt<=60; attempt++)); do
    if response=$(curl --disable --noproxy '*' --fail --silent --max-time 2 "$url/api/method/ping") &&
      grep -Eq '"message"[[:space:]]*:[[:space:]]*"pong"' <<< "$response"; then
      return
    fi
    sleep 2
  done
  "${compose[@]}" ps --all >&2
  fail "Frappe antwortet nicht unter $url."
}

check_apps() {
  local installed app
  installed=$("${bench[@]}" list-apps)
  for app in frappe erpnext "${apps[@]}"; do
    grep -Eq "^[[:space:]]*$app([[:space:]]|$)" <<< "$installed" ||
      fail "Auf der Preview-Site fehlt $app. Für den erweiterten App-Satz eine neue Vorschau starten."
  done
  printf '%s\n' "$installed"
}

report_revisions() {
  local app sha changes state
  for app in "${apps[@]}"; do
    if ! sha=$(git -C "$workspace/$app" rev-parse HEAD 2>/dev/null); then
      printf '%s: kein Commit verfügbar\n' "$app"
      continue
    fi
    changes=$(git -C "$workspace/$app" status --porcelain)
    state=unverändert
    [[ -z "$changes" ]] || state='lokale Änderungen'
    printf '%s: %s (%s)\n' "$app" "$sha" "$state"
  done
}

case "$action" in
  up)
    "${compose[@]}" config --quiet
    "${compose[@]}" build configurator
    "${compose[@]}" up --detach --no-build
    url=$(preview_url)
    wait_for_site "$url"
    check_apps
    report_revisions
    printf 'Preview %s ist erreichbar: %s\n' "$project" "$url"
    ;;
  status)
    "${compose[@]}" ps --all
    report_revisions
    ;;
  seed)
    "${compose[@]}" exec -T backend bash -s -- "$site" <<'SEED'
set -euo pipefail
site=$1
exec 9>"/home/frappe/frappe-bench/sites/$site/.hv-preview-seed.lock"
flock -n 9 || { echo 'Ein anderer Seed-Lauf ist aktiv.' >&2; exit 1; }
for doctype in Immobilie Wohnung Mietvertrag; do
  count=$(bench --site "$site" execute "str(frappe.db.count('$doctype'))")
  if [[ "$count" != 0 ]]; then
    printf 'Seed abgebrochen: %s ist nicht leer.\n' "$doctype" >&2
    exit 1
  fi
done
bench --site "$site" execute hausverwaltung.hausverwaltung.data_import.sample.sample_data.create_sample_data \
  --kwargs "{'company': 'Demo Hausverwaltung', 'with_invoices': False, 'with_payments': False}"
count=$(bench --site "$site" execute "str(frappe.db.count('Mietvertrag'))")
[[ "$count" == 3 ]] || { echo 'Seed hat nicht drei Demo-Mietverträge angelegt.' >&2; exit 1; }
SEED
    ;;
  test)
    "${bench[@]}" set-config --parse allow_tests 1
    "${bench[@]}" run-tests --module "$test_module"
    ;;
  restart)
    "${compose[@]}" restart backend queue-short queue-long scheduler frontend
    wait_for_site "$(preview_url)"
    ;;
  migrate)
    "${bench[@]}" migrate
    ;;
  build)
    "${compose[@]}" exec -T backend bash -lc \
      'export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; bench build --apps "$1"' _ "${HV_APPS// /,}"
    ;;
  stop)
    "${compose[@]}" stop
    ;;
esac
