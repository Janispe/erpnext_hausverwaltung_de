#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'Lokale CI: %s\n' "$*" >&2
  exit 1
}

repo=$(git rev-parse --show-toplevel)
head=$(git rev-parse --verify HEAD^{commit})
stage=quick
build_image=0
case "${1:-}" in
  --quick|--python|--e2e|--all)
    stage=${1#--}
    ;;
  --build-image)
    build_image=1
    ;;
  --pre-push)
    run=0
    while read -r local_ref local_sha remote_ref _; do
      [[ "$remote_ref" == refs/heads/* && "$local_ref" != '(delete)' ]] || continue
      [[ "$local_sha" == "$head" ]] || fail 'Den zu pushenden Commit zuerst auschecken.'
      run=1
    done
    (( run )) || exit 0
    ;;
  '') ;;
  *) fail 'Aufruf aus dem Hausverwaltungs-Checkout: ./scripts/agent_ci.sh [--quick|--python|--e2e|--all|--build-image]' ;;
esac

# Git hooks export repository-specific variables. Child Git commands use their own checkouts.
while IFS= read -r name; do
  unset "$name"
done < <(git rev-parse --local-env-vars)

# CI-Image: Basisimage aus compose.dev.yml plus Chrome-Bibliotheken für die PDF-Erzeugung.
ci_image=hausverwaltung/frappe-chrome:ci
if (( build_image )); then
  ci_base=${HV_CI_BASE_IMAGE:-frappe/erpnext:v16.14.0}
  context=hv-preview
  [[ ${HV_PREVIEW_LOCAL_DOCKER:-1} == 1 ]] && context=default
  printf 'Baue %s aus %s (Kontext %s)\n' "$ci_image" "$ci_base" "$context"
  exec docker --context "$context" build --build-arg "FRAPPE_BASE_IMAGE=$ci_base" -t "$ci_image" \
    -f "$repo/docker/frappe-chrome.Dockerfile" "$repo/docker"
fi
export HV_PREVIEW_CI_IMAGE=$ci_image

workspace=$(dirname -- "$repo")
git_dir=$(git -C "$repo" rev-parse --path-format=absolute --git-common-dir)
ci_dir=$git_dir/agent-ci
local_docker=${HV_PREVIEW_LOCAL_DOCKER:-1}
cleanup_command=(rm)
cache=$ci_dir/uv
if [[ "$local_docker" == 0 ]]; then
  command -v rootlesskit >/dev/null || fail 'RootlessKit fehlt für die Bereinigung des CI-Checkouts.'
  cleanup_command=(rootlesskit rm)
  cache=$ci_dir/uv-rootless
fi
umask 077
mkdir -p -- "$cache"
exec 9>"$ci_dir/run.lock"
flock 9
sandbox=$(mktemp -d "$ci_dir/run.XXXXXXXX")

cleanup_checkout() {
  local result=$?
  if ! "${cleanup_command[@]}" -r -- "$sandbox"; then
    printf 'CI-Checkout konnte nicht entfernt werden: %s\n' "$sandbox" >&2
    exit 125
  fi
  exit "$result"
}

trap cleanup_checkout EXIT

for app in hausverwaltung process_engine mail_merge thunderbird_hausverwaltung; do
  source_repo=$workspace/$app
  [[ "$(git -C "$source_repo" rev-parse --show-toplevel)" == "$source_repo" ]] ||
    fail "Git-Checkout für $app fehlt."
  revision=$head
  if [[ "$app" != hausverwaltung ]]; then
    revision=$(git -C "$source_repo" rev-parse --verify HEAD^{commit})
  fi
  if git -C "$source_repo" ls-tree -r -z --name-only "$revision" | grep -zE '(^|/)\.env($|\.)' >/dev/null; then
    fail "$app enthält eine versionierte .env-Datei."
  fi
  printf '%s: %s\n' "$app" "$revision"
  git clone --quiet --shared --no-checkout -- "$source_repo" "$sandbox/$app"
  git -C "$sandbox/$app" -c core.hooksPath=/dev/null checkout --quiet --detach "$revision"
done

# Eigener Port je Arbeitsordner möglich, damit parallele Läufe aus verschiedenen Checkouts nicht kollidieren.
export HV_PREVIEW_LOCAL_DOCKER=$local_docker HV_PREVIEW_USE_BASE_IMAGE=1 HV_PREVIEW_HTTP_PORT=${HV_PREVIEW_HTTP_PORT:-8182}
export HV_PREVIEW_CI_CACHE=$cache
run_id=${sandbox##*.}
# Protokolle, Screenshots und Bericht bleiben nach dem Aufräumen erhalten.
export HV_TEST_REPORT=$ci_dir/reports/$(date +%Y%m%d-%H%M%S)-$stage-${head:0:8}
mkdir -p -- "$HV_TEST_REPORT"
printf 'Stufe: %s\nBericht: %s\n' "$stage" "$HV_TEST_REPORT"
# --all läuft als python und e2e auf je einer frischen Site, damit Testdaten sich nicht beeinflussen.
stages=("$stage")
[[ "$stage" == all ]] && stages=(python e2e)
result=0
for current in "${stages[@]}"; do
  export HV_TEST_STAGE=$current
  ticket=ci-${run_id,,}
  (( ${#stages[@]} > 1 )) && ticket+=-$current
  "$sandbox/hausverwaltung/scripts/agent_preview.sh" ci "$ticket" || {
    rc=$?
    if (( rc == 125 )); then
      trap - EXIT
      printf 'CI-Aufräumen fehlgeschlagen. Checkout erhalten: %s\n' "$sandbox" >&2
      exit 125
    fi
    result=$rc
  }
done
printf '\nGesamtbericht: %s/summary.txt\n' "$HV_TEST_REPORT"
exit "$result"
