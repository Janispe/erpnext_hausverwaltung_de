#!/usr/bin/env bash
# Läuft als postCreateCommand im Devcontainer.
#
# Holt die beiden required_apps als Geschwisterordner, damit ../compose.dev.yml
# sie mounten kann. Beide Repos sind öffentlich — der Clone braucht keine
# Credentials, und es liegen folglich auch keine im Container.
#
# Der Frappe-Stack selbst wird hier NICHT gestartet. Das macht `./dev.sh up`
# in einem Terminal, wo du den Build mitverfolgen kannst.
set -euo pipefail

WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PARENT="$(dirname "$WORKSPACE")"

log() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

clone_app() { # $1=zielordner $2=repo-url $3=branch
	local dest="$PARENT/$1"
	if [ -d "$dest/.git" ]; then
		echo "  $1 bereits vorhanden"
		return
	fi
	git clone --branch "$3" --quiet "$2" "$dest"
	echo "  $1 ← $2 ($3)"
}

log "required_apps holen (öffentliche Repos, anonym über HTTPS)"
# Achtung: unterschiedliche Default-Branches, und das mail-merge-Repo heißt
# anders als die App. Der Ordnername muss dem app_name entsprechen.
clone_app process_engine https://github.com/Janispe/process_engine.git master
clone_app mail_merge https://github.com/Janispe/erp_next_mail_merge.git main

log "Prüfen, dass kein Host-Docker durchgereicht wurde"
if [ -S /var/run/docker.sock ] && docker info 2>/dev/null | grep -q "Docker Root Dir: /var/lib/docker"; then
	if [ -e /.dockerenv ] && ! pgrep -x dockerd >/dev/null 2>&1; then
		echo "  WARNUNG: Es scheint der Docker-Daemon des HOSTS erreichbar zu sein."
		echo "  Damit wäre die Isolation aufgehoben. Prüfe das docker-in-docker-Feature."
	fi
fi
docker version --format '  Docker-Daemon: {{.Server.Version}} (im Container)' 2>/dev/null \
	|| echo "  Docker-Daemon noch nicht bereit — beim ersten Start normal."

cat <<INFO

  Vorbereitet. Es liegen jetzt nebeneinander:

    $PARENT/hausverwaltung      (dieses Repo)
    $PARENT/process_engine
    $PARENT/mail_merge

  Stack starten (dauert beim ersten Mal 10-20 Minuten):

    ./dev.sh up

  Danach: http://localhost:8180   (Administrator / admin)

INFO
