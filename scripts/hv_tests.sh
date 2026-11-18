#!/usr/bin/env bash
# Gemeinsamer Testlauf der Hausverwaltung, gegliedert in Stufen.
#
# Läuft gegen eine bereits gestartete Test-Site. Nicht direkt aufrufen, sondern über
# ./scripts/agent_ci.sh --<stufe>. Das baut jedes Mal eine frische, isolierte Site auf
# und entfernt sie danach wieder.
#
#   quick   Smoke-Test Mietvertrag (Standard, auch vor jedem Agenten-Push)
#   python  alle Python-Tests der App und unter tests/
#   e2e     JavaScript- und Browsertests: KI-Vorschläge, Node, Vitest, Playwright
#   all     python und e2e
#
# Erwartete Umgebung (setzt agent_preview.sh):
#   HV_TEST_SITE, HV_TEST_BACKEND (Container), HV_TEST_DOCKER_CONTEXT, HV_TEST_BASE_URL,
#   HV_TEST_REPORT (Ordner für Protokolle), HV_TEST_ADMIN_PASSWORD
set -euo pipefail

fail() {
  printf 'Tests: %s\n' "$*" >&2
  exit 2
}

stage=${1:-quick}
case "$stage" in
  quick|python|e2e|all) ;;
  *) fail "Unbekannte Stufe $stage. Erlaubt: quick, python, e2e, all." ;;
esac

repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
site=${HV_TEST_SITE:?HV_TEST_SITE fehlt}
backend=${HV_TEST_BACKEND:?HV_TEST_BACKEND fehlt}
context=${HV_TEST_DOCKER_CONTEXT:?HV_TEST_DOCKER_CONTEXT fehlt}
base_url=${HV_TEST_BASE_URL:?HV_TEST_BASE_URL fehlt}
report=${HV_TEST_REPORT:?HV_TEST_REPORT fehlt}
admin_password=${HV_TEST_ADMIN_PASSWORD:-admin}
[[ "$base_url" =~ ^http://127\.0\.0\.1:[0-9]+$ ]] || fail 'Nur eine Loopback-Site wird getestet.'
mkdir -p -- "$report"

bench_dir=/home/frappe/frappe-bench
docker_cli=(docker --context "$context")
in_backend() {
  "${docker_cli[@]}" exec -i -w "$bench_dir" "$backend" "$@"
}
bench() {
  in_backend bench --site "$site" "$@"
}

failed=()
skipped=()
# Exit 77 eines Schritts bedeutet „übersprungen“ (Automake-Konvention).
step() {
  local name=$1 log=$report/$1.log start=$SECONDS rc=0
  shift
  printf '\n== %s\n' "$name"
  # Eigene Subshell: ein Fehler beendet nur diesen Schritt, nicht den ganzen Lauf.
  ( "$@" ) >"$log" 2>&1 || rc=$?
  if (( rc == 0 )); then
    printf '%-28s bestanden      %4ss\n' "$name" "$((SECONDS - start))" | tee -a "$report/summary.txt"
  elif (( rc == 77 )); then
    skipped+=("$name")
    printf '%-28s übersprungen   %4ss (%s)\n' "$name" "$((SECONDS - start))" "$(tail -n 1 -- "$log")" |
      tee -a "$report/summary.txt"
  else
    failed+=("$name")
    tail -n 40 -- "$log"
    printf '%-28s FEHLGESCHLAGEN %4ss (Exit %s, %s)\n' "$name" "$((SECONDS - start))" "$rc" "$log" |
      tee -a "$report/summary.txt"
  fi
}

# ---------------------------------------------------------------------------- Python

python_module() {
  bench run-tests --module "$1"
}

python_app() {
  local rc=0
  bench run-tests --app hausverwaltung --junit-xml-output /tmp/hv-python-app.xml || rc=$?
  # JUnit-Bericht für die Auswertung einzelner Fehler sichern.
  in_backend cat /tmp/hv-python-app.xml >"$report/python-app.junit.xml" 2>/dev/null || true
  return "$rc"
}

python_repo_tests() {
  # DB-freie Verträge unter tests/; sie importieren die App direkt aus dem Checkout.
  in_backend bash -c 'cd apps/hausverwaltung && ../../env/bin/python -m unittest discover -v -s tests -p "test_*.py"'
}

error_log() {
  # Abgefangene Fehler (z. B. aus der PDF-Erzeugung) landen nur im Error Log der Site.
  bench execute frappe.get_all --kwargs \
    '{"doctype": "Error Log", "fields": ["creation", "method", "error"], "order_by": "creation desc", "limit": 40}' \
    >"$report/error-log.json" 2>/dev/null || true
}

# ---------------------------------------------------------------------------- KI-Vorschläge

# Wegwerf-Zugangsdaten nur für diesen Lauf; die Datei wird am Ende gelöscht.
auth_file=$report/.proposals-auth.json
container_auth=/tmp/hv-proposals-auth.json
tools=$report/.tools
trap 'rm -f -- "$auth_file"' EXIT

proposals_deps() {
  # Playwright für Python in derselben Version wie das Node-Playwright des Bankimports.
  local version target
  version=$(cd "$repo/HV_Bankimport/src_react" && npx playwright --version | awk '{print $2}') || return
  target=${XDG_CACHE_HOME:-$HOME/.cache}/hv-tests/pw-py-$version
  if [[ ! -d "$target/playwright" ]]; then
    uv pip install --quiet --target "$target" "playwright==$version" || return
  fi
  PYTHONPATH=$target python3 -m playwright install chromium || return
  mkdir -p -- "$tools"
  printf '%s\n' "$target" >"$tools/pw-py"
  PYTHONPATH=$target python3 -c \
    'from playwright.sync_api import sync_playwright
with sync_playwright() as p: print(p.chromium.executable_path)' >"$tools/chromium"
  cat -- "$tools/pw-py" "$tools/chromium"
}

proposals_bootstrap() {
  HV_ADMIN=$admin_password python3 - "$auth_file" <<'PY' || return
import json, os, secrets, sys
auth = {"purpose": "hv-proposals-disposable-testauth", "admin": os.environ["HV_ADMIN"]}
auth.update({account: secrets.token_urlsafe(24) for account in ("agent", "reviewer")})
with open(sys.argv[1], "w") as handle:
    json.dump(auth, handle)
PY
  in_backend sh -c 'umask 077 && cat >"$1"' _ "$container_auth" <"$auth_file" || return
  in_backend bash -c 'cd sites && ../env/bin/python ../apps/hausverwaltung/tests/proposals_bootstrap.py --site "$1"' \
    _ "$site" <"$auth_file"
}

proposals_http() {
  python3 "$repo/tests/proposals_http_contracts.py" --synthetic --base-url "$base_url" --auth-file "$auth_file"
}

proposals_readonly() {
  in_backend bash -c \
    'cd sites && ../env/bin/python ../apps/hausverwaltung/tests/proposals_readonly_site.py --synthetic --site "$1" --auth-file "$2"' \
    _ "$site" "$container_auth"
}

bank_proposals_site() {
  in_backend bash -c 'cd sites && ../env/bin/python ../apps/hausverwaltung/tests/bank_proposals_bootstrap.py --site "$1"' \
    _ "$site" | tail -1 >"$tools/bank-proposals-fixture.json" || return
  in_backend sh -c 'umask 077 && cat >"$1"' _ "$container_auth.bank" <"$tools/bank-proposals-fixture.json" || return
  in_backend bash -c \
    'cd sites && ../env/bin/python ../apps/hausverwaltung/tests/bank_proposals_site.py --site "$1" --auth-file "$2" --fixture-file "$2.bank"' \
    _ "$site" "$container_auth"
}

bank_proposals_playwright() {
  python3 "$repo/tests/bank_proposals_playwright.py" "$base_url" "$auth_file" "$tools/bank-proposals-fixture.json" \
    "$(<"$tools/pw-py")" "$(<"$tools/chromium")"
}

proposals_playwright() {
  # Der Test wechselt das Theme wie ein Nutzer über den Einstellungsdialog, den erst neuere
  # Frappe-Versionen haben (Produktion 16.55). Ältere Dev-/CI-Images überspringen ihn sichtbar.
  if ! in_backend grep -rqs settings-dialog-wrapper apps/frappe/frappe/public/js; then
    echo 'Frappe dieser Bench hat den Einstellungsdialog nicht, den der Theme-Wechsel braucht.'
    return 77
  fi
  [[ -s "$tools/pw-py" && -s "$tools/chromium" ]] || { echo 'Playwright für Python fehlt (Schritt proposals-deps).'; return 3; }
  python3 "$repo/tests/proposals_playwright_e2e.py" --synthetic --base-url "$base_url" --auth-file "$auth_file" \
    --dependencies "$(<"$tools/pw-py")" --chromium "$(<"$tools/chromium")" --output-dir "$report/proposals-playwright"
}

# ---------------------------------------------------------------------------- JavaScript

use_node() {
  if [[ -x "${HV_TEST_NODE_DIR:-$HOME/.local/node/current/bin}/node" ]]; then
    PATH=${HV_TEST_NODE_DIR:-$HOME/.local/node/current/bin}:$PATH
  fi
  local major
  major=$(node --version 2>/dev/null | sed -E 's/^v([0-9]+).*/\1/') || major=0
  (( major >= 20 )) || fail 'Node 20 oder neuer fehlt (HV_TEST_NODE_DIR setzen).'
}

node_unit_tests() {
  local files=()
  mapfile -t files < <(cd "$repo" && git ls-files -- 'tests/*.test.cjs' 'tests/*.test.mjs' \
    'hausverwaltung/public/**/*.test.cjs' 'hausverwaltung/public/**/*.test.mjs' 'hausverwaltung/public/**/*.test.js')
  (( ${#files[@]} )) || { echo 'Keine Node-Tests gefunden.'; return 0; }
  (cd "$repo" && node --test "${files[@]}")
}

bankimport_deps() {
  (cd "$repo/HV_Bankimport/src_react" && npm ci --no-audit --no-fund --loglevel=error)
}

bankimport_vitest() {
  (cd "$repo/HV_Bankimport/src_react" && npx vitest run)
}

bankimport_playwright_mock() {
  (cd "$repo/HV_Bankimport/src_react" && CI=1 npx playwright test --output "$report/playwright-mock")
}

e2e_site() {
  # Die Vorschlagsfunktion ist nur auf ausdrücklich freigeschalteten synthetischen Sites aktiv.
  bench set-config --parse hv_proposals_synthetic_enabled True || return
  bench set-config --parse hv_receipt_pilot 1 || return
  # Web-Worker halten site_config.json bis zu 60 s im Speicher (frappe.config, site_cache).
  # Gunicorn (PID 1 im Backend) lädt seine Worker neu, damit alle Requests die Schalter sehen.
  in_backend sh -c 'kill -HUP 1' || return
  local attempt
  for ((attempt = 1; attempt <= 30; attempt++)); do
    sleep 2
    curl --disable --noproxy '*' --fail --silent --max-time 2 "$base_url/api/method/ping" | grep -q pong && break
  done
  (( attempt <= 30 )) || { echo 'Frappe antwortet nach dem Neuladen der Worker nicht.'; return 1; }
  # Geschäftsjahre und aktive Company-Kostenstelle, die eine frische Site nicht mitbringt.
  bench execute hausverwaltung.cypress_fixtures.prepare_e2e_site
}

frappe_playwright() {
  (cd "$repo/HV_Bankimport/src_react" &&
    CI=1 DOCKER_CONTEXT=$context FRAPPE_BASE_URL=$base_url FRAPPE_SITE=$site \
    FRAPPE_BACKEND_CONTAINER=$backend FRAPPE_USER=Administrator FRAPPE_PASSWORD=$admin_password \
    npx playwright test -c playwright.frappe.config.js --output "$report/playwright-frappe")
}

# ---------------------------------------------------------------------------- Ablauf

printf 'Stufe %s gegen %s (Site %s, Backend %s)\n' "$stage" "$base_url" "$site" "$backend"
bench set-config --parse allow_tests 1 >/dev/null
# Markiert die frische Site als Wegwerf-Testsite; die Vorschlags-Tests verlangen das.
bench set-config --parse hv_disposable_test_site 1 >/dev/null

case "$stage" in
  quick)
    # HV_TEST_MODULE wählt für Fehlersuche ein anderes einzelnes Testmodul.
    step python-module python_module "${HV_TEST_MODULE:-hausverwaltung.hausverwaltung.doctype.mietvertrag.test_mietvertrag}"
    error_log
    ;;
  python|all)
    step python-app python_app
    step python-repo python_repo_tests
    error_log
    ;;&
  e2e|all)
    use_node
    step e2e-site e2e_site
    step bankimport-deps bankimport_deps
    step proposals-deps proposals_deps
    step proposals-bootstrap proposals_bootstrap
    step proposals-http proposals_http
    step proposals-readonly proposals_readonly
    step bank-proposals-site bank_proposals_site
    step bank-proposals-playwright bank_proposals_playwright
    step proposals-playwright proposals_playwright
    step node-unit node_unit_tests
    step bankimport-vitest bankimport_vitest
    step bankimport-playwright bankimport_playwright_mock
    step frappe-playwright frappe_playwright
    error_log
    ;;
esac

printf '\nBericht: %s/summary.txt\n' "$report"
(( ${#skipped[@]} )) && printf 'Übersprungen: %s\n' "${skipped[*]}"
if (( ${#failed[@]} )); then
  printf 'Fehlgeschlagen: %s\n' "${failed[*]}"
  exit 1
fi
printf 'Alle Schritte der Stufe %s bestanden.\n' "$stage"
