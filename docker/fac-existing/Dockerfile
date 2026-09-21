ARG BASE_IMAGE=hvp:8090-backend-before-fac-20260916
FROM ${BASE_IMAGE}
USER frappe
WORKDIR /home/frappe/frappe-bench
RUN git clone https://github.com/buildswithpaul/Frappe_Assistant_Core.git apps/frappe_assistant_core \
    && cd apps/frappe_assistant_core \
    && git checkout 7ddc433772f4ade794d9f5ee30b7d9ea0af2a487 \
    && cd ../.. \
    && ./env/bin/pip install -e apps/frappe_assistant_core
# Copy only FAC integration files, preserving all other apps and image customizations.
COPY --chown=frappe:frappe hausverwaltung/ apps/hausverwaltung/hausverwaltung/
RUN ./env/bin/python - <<'PY'
from pathlib import Path
path = Path('apps/hausverwaltung/hausverwaltung/hooks.py')
source = path.read_text()
if '\nassistant_tools =' in source:
    raise RuntimeError('Existing assistant_tools hook must be merged explicitly')
path.write_text(source + '\n# Optional FAC integration.\nfrom hausverwaltung.hausverwaltung.agent_tools.fac_contract import FAC_TOOL_HOOKS\nassistant_tools = FAC_TOOL_HOOKS\n')
PY
RUN ls -1 apps > sites/apps.txt && bench build --app frappe_assistant_core
