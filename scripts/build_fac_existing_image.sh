#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAC_BUILD_CONTEXT="$(mktemp -d /tmp/hv-fac-existing-build.XXXXXX)"
trap 'rm -rf "$FAC_BUILD_CONTEXT"' EXIT
cd "$APP_DIR"
FILES=(
  hausverwaltung/hausverwaltung/agent_tools/fac_contract.py
  hausverwaltung/hausverwaltung/agent_tools/fac_tools.py
  hausverwaltung/hausverwaltung/services/fac_native_assistant.py
  hausverwaltung/hausverwaltung/services/fac_assistant.py
  hausverwaltung/hausverwaltung/services/fac_setup.py
  hausverwaltung/hausverwaltung/services/assistant.py
  hausverwaltung/hausverwaltung/doctype/hausverwaltung_assistant_conversation/hausverwaltung_assistant_conversation.json
  hausverwaltung/hausverwaltung/page/hausverwaltung_assistant/hausverwaltung_assistant.js
)
for file in "${FILES[@]}"; do
  mkdir -p "$FAC_BUILD_CONTEXT/$(dirname "$file")"
  cp "$file" "$FAC_BUILD_CONTEXT/$file"
done
docker build --build-arg "BASE_IMAGE=${FAC_BASE_IMAGE:-hvp:8090-backend-before-fac-20260916}" \
  -f "$APP_DIR/docker/fac-existing/Dockerfile" \
  -t "${FAC_IMAGE:-hvp:16-helpdesk-suite-fac}" "$FAC_BUILD_CONTEXT"
