#!/usr/bin/env bash
# Einmaliges Setup im Devcontainer (postCreateCommand).
#
# Idempotent: bereits vorhandene Apps und eine bereits angelegte Site werden
# übersprungen, das Skript darf jederzeit erneut laufen.
set -euo pipefail

BENCH=/home/frappe/frappe-bench
SITE="${HV_SITE:-dev}"
cd "$BENCH"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

log "Warte auf MariaDB"
for _ in $(seq 1 60); do
	(echo >/dev/tcp/mariadb/3306) >/dev/null 2>&1 && break
	sleep 2
done
(echo >/dev/tcp/mariadb/3306) >/dev/null 2>&1 || { echo "MariaDB nicht erreichbar"; exit 1; }

log "Bench konfigurieren"
bench set-config -g db_host mariadb
bench set-config -gp db_port 3306
bench set-config -g redis_cache "redis://redis-cache:6379"
bench set-config -g redis_queue "redis://redis-queue:6379"
bench set-config -g redis_socketio "redis://redis-queue:6379"
bench set-config -gp socketio_port 9000
bench set-config -g developer_mode 1
# 3 Sekunden Default reichen für den Chromium-Start nicht aus.
bench set-config -gp chromium_start_timeout 30

# required_apps aus hausverwaltung/hooks.py.
log "required_apps holen"
get_app() { # $1=app-name $2=repo-url $3=branch
	if [ -d "apps/$1" ]; then
		echo "  $1 bereits vorhanden"
		return
	fi
	bench get-app --branch "$3" "$1" "$2"
}
# Beide Repos sind öffentlich, HTTPS kommt also ohne Credentials aus. Der
# Container braucht damit weder SSH-Key noch Agent-Forwarding.
# Achtung: unterschiedliche Default-Branches, und das mail-merge-Repo heißt
# anders als die App.
get_app process_engine https://github.com/Janispe/process_engine.git master
get_app mail_merge https://github.com/Janispe/erp_next_mail_merge.git main

log "hausverwaltung (gemountet) im Bench registrieren"
( echo n; echo y ) | bench get-app "file://$BENCH/apps/hausverwaltung"

if [ -d "sites/$SITE" ]; then
	log "Site '$SITE' existiert bereits — überspringe Anlage"
else
	log "Site '$SITE' anlegen (dauert ein paar Minuten)"
	bench new-site \
		--mariadb-user-host-login-scope='%' \
		--db-root-username root --db-root-password admin \
		--admin-password admin \
		--install-app erpnext \
		--install-app process_engine \
		--install-app mail_merge \
		--install-app hausverwaltung \
		--set-default "$SITE"

	log "PDF-Engine auf Chrome stellen"
	bench --site "$SITE" execute frappe.client.set_value --kwargs \
		"{'doctype': 'Print Settings', 'name': 'Print Settings', 'fieldname': 'pdf_generator', 'value': 'chrome'}"

	log "Grundkonfiguration (Company, Kontenrahmen, Rollen)"
	bench --site "$SITE" execute hausverwaltung.hausverwaltung.scripts.bootstrap_site.run
	bench --site "$SITE" clear-cache
fi

bench use "$SITE"

cat <<INFO

  Fertig.

  Starten:   bench start
  Site:      http://localhost:8200   (Administrator / admin)

  Danach im Container z.B.:
    bench --site $SITE migrate
    bench --site $SITE clear-cache
    bench --site $SITE run-tests --app hausverwaltung
    bench build --app hausverwaltung

INFO
