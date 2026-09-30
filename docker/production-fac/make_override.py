"""Create a Compose override for application services from resolved base config."""

import json
import sys

config_path, image = sys.argv[1:3]
with open(config_path, encoding="utf-8") as source:
    services = json.load(source)["services"]
if "backend" not in services:
    raise SystemExit("Compose service 'backend' fehlt.")
backend_image = services["backend"].get("image")
known = {"backend", "frontend", "configurator", "scheduler", "websocket"}
selected = {
    name: {"image": image, "pull_policy": "never"}
    for name, service in services.items()
    if service.get("image")
    and (
        name in known
        or name.startswith("queue-")
        or (service["image"] == backend_image and name != "dataset-interpreter")
    )
}
if "frontend" not in selected or "backend" not in selected:
    raise SystemExit("Backend oder Frontend fehlen im Compose-Stack.")
print(json.dumps({"services": selected}, indent=2))
