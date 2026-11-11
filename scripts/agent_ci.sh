#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'Lokale CI: %s\n' "$*" >&2
  exit 1
}

repo=$(git rev-parse --show-toplevel)
head=$(git rev-parse --verify HEAD^{commit})
case "${1:-}" in
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
  *) fail 'Aufruf aus dem Hausverwaltungs-Checkout: ./scripts/agent_ci.sh' ;;
esac

# Git hooks export repository-specific variables. Child Git commands use their own checkouts.
while IFS= read -r name; do
  unset "$name"
done < <(git rev-parse --local-env-vars)

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

export HV_PREVIEW_LOCAL_DOCKER=$local_docker HV_PREVIEW_USE_BASE_IMAGE=1 HV_PREVIEW_HTTP_PORT=8182
export HV_PREVIEW_CI_CACHE=$cache
run_id=${sandbox##*.}
if "$sandbox/hausverwaltung/scripts/agent_preview.sh" ci "ci-${run_id,,}"; then
  exit 0
else
  result=$?
  if (( result == 125 )); then
    trap - EXIT
    printf 'CI-Aufräumen fehlgeschlagen. Checkout erhalten: %s\n' "$sandbox" >&2
  fi
  exit "$result"
fi
