#!/usr/bin/env bash
# Kurzbefehle für den Dev-Stack (compose.dev.yml, Projekt hv-dev).
# Der Projektname steckt in compose.dev.yml (`name: hv-dev`) — dieses Skript
# kann den Produktiv-Stack also nicht versehentlich treffen.
set -euo pipefail

cd "$(dirname "$0")"
DC=(docker compose -f compose.dev.yml)
# Optionale Overlays: HV_EXTRA="thunderbird" ./dev.sh up
for extra in ${HV_EXTRA:-}; do DC+=(-f "compose.dev.$extra.yml"); done
SITE="${SITE_NAME:-frontend}"
BE=hv-dev-backend-1

usage() {
	cat <<'USAGE'
./dev.sh up          Stack starten (erster Lauf: baut das Image)
./dev.sh down        Stack stoppen (Volumes bleiben)
./dev.sh nuke        Stack + Volumes löschen — Site ist danach weg
./dev.sh migrate     bench migrate
./dev.sh cache       bench clear-cache
./dev.sh build       bench build --app hausverwaltung (mit NVM-Sourcing)
./dev.sh restart     Worker + frontend neu starten (Python-Code-Änderungen)
./dev.sh test [mod]  Tests der App, optional ein einzelnes Modul
./dev.sh console     bench console
./dev.sh shell       bash im Backend-Container
./dev.sh logs [svc]  Logs folgen

HV_EXTRA=thunderbird ./dev.sh up   Overlay compose.dev.thunderbird.yml dazu
USAGE
}

case "${1:-}" in
up)
	"${DC[@]}" up -d --build
	echo "→ http://localhost:8180  (Administrator / admin)"
	;;
down) "${DC[@]}" down ;;
nuke) "${DC[@]}" down -v ;;
migrate) docker exec "$BE" bench --site "$SITE" migrate ;;
cache) docker exec "$BE" bench --site "$SITE" clear-cache ;;
build)
	docker exec "$BE" bash -lc \
		'export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; \
		 cd /home/frappe/frappe-bench && bench build --app hausverwaltung'
	;;
restart)
	# frontend muss mit: ein Backend-Neustart ändert die Container-IP, der
	# nginx im frontend cacht die alte und antwortet sonst mit 502.
	"${DC[@]}" restart backend queue-short queue-long scheduler frontend
	;;
test)
	if [ -n "${2:-}" ]; then
		docker exec "$BE" bench --site "$SITE" run-tests --module "$2"
	else
		docker exec "$BE" bench --site "$SITE" run-tests --app hausverwaltung
	fi
	;;
console) docker exec -it "$BE" bench --site "$SITE" console ;;
shell) docker exec -it "$BE" bash ;;
logs) "${DC[@]}" logs -f ${2:-} ;;
*) usage; exit 1 ;;
esac
