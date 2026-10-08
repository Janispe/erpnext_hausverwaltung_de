#!/usr/bin/env python3
"""Build a minimal candidate from effective authoring files; never deploy it.

Read-only access to running app containers, no site commands. Keep historical
bind mounts except the two fixed modules, which become part of the new image.
"""

import argparse
import ast
import hashlib
import json
import subprocess
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
BENCH = "/home/frappe/frappe-bench"
MODULE_DIR = "hausverwaltung/hausverwaltung/agent_tools"
MODULES = ("block_authoring_api.py", "template_authoring_api.py")
SERVICES = ("backend", "queue-short", "queue-long", "scheduler")


def run(*args, **kwargs):
	return subprocess.run(args, check=True, text=True, **kwargs)


def prepare(project, image, output):
	output.mkdir(parents=True, exist_ok=False)
	containers = json.loads(
		run(
			"docker", "inspect", *[f"{project}-{service}-1" for service in SERVICES], capture_output=True
		).stdout
	)
	active_tags = {container["Config"]["Image"] for container in containers}
	if image in active_tags or image + "-base" in active_tags:
		raise RuntimeError("Candidate tag must differ from every active app image tag.")
	for tag in (image, image + "-base"):
		if subprocess.run(["docker", "image", "inspect", tag], capture_output=True).returncode == 0:
			raise RuntimeError(f"Image tag already exists; choose a fresh tag: {tag}")
	images = {container["Image"] for container in containers}
	if len(images) != 1:
		raise RuntimeError("App services have different base images; review separately before building.")
	base_image = image + "-base"
	base_image_id = images.pop()
	run("docker", "tag", base_image_id, base_image)
	target_dir = output / MODULE_DIR
	target_dir.mkdir(parents=True)
	targets = set()
	manifest = {
		"project": project,
		"image": image,
		"base_image": base_image,
		"base_image_id": base_image_id,
		"modules": {},
	}
	for module in MODULES:
		target = f"{BENCH}/apps/hausverwaltung/{MODULE_DIR}/{module}"
		targets.add(target)
		path = target_dir / module
		run("docker", "cp", f"{project}-backend-1:{target}", str(path))
		manifest["modules"][module] = {"before": hashlib.sha256(path.read_bytes()).hexdigest()}
	patch = APP_ROOT / "deployment/authoring-doctype-permissions.patch"
	run("patch", "--batch", "--fuzz=0", "--no-backup-if-mismatch", "-p1", "-i", str(patch), cwd=output)
	for module in MODULES:
		path = target_dir / module
		compile(path.read_text(), str(path), "exec")
		manifest["modules"][module]["after"] = hashlib.sha256(path.read_bytes()).hexdigest()

	# The patch must stay synchronized with the canonical shared helper.
	def helper(path):
		source = path.read_text()
		for node in ast.parse(source).body:
			if isinstance(node, ast.FunctionDef) and node.name == "_require_doctype_read":
				return ast.get_source_segment(source, node)
		raise RuntimeError(f"Shared permission helper missing in {path}")

	if helper(target_dir / MODULES[1]) != helper(APP_ROOT / MODULE_DIR / MODULES[1]):
		raise RuntimeError("Deployment patch differs from the canonical permission helper.")
	(output / "Dockerfile").write_text(
		f"FROM {base_image}\nUSER frappe\nWORKDIR {BENCH}\n"
		"COPY --chown=frappe:frappe hausverwaltung/ apps/hausverwaltung/hausverwaltung/\n"
		# Old pyc files must never hide a patched source with a matching timestamp.
		"RUN rm -f apps/hausverwaltung/hausverwaltung/hausverwaltung/agent_tools/__pycache__/"
		"block_authoring_api.*.pyc apps/hausverwaltung/hausverwaltung/hausverwaltung/agent_tools/"
		"__pycache__/template_authoring_api.*.pyc\n"
	)
	lines = ["# Keep this override in every subsequent Compose invocation.", "services:"]
	volumes = {}
	for container in containers:
		service = container["Config"]["Labels"]["com.docker.compose.service"]
		lines += [f"  {service}:", f"    image: {json.dumps(image)}", "    volumes: !override"]
		for mount in container["Mounts"]:
			if mount["Destination"] in targets:
				continue
			if mount["Type"] not in {"bind", "volume"}:
				raise RuntimeError(f"Unsupported mount in {service}: {mount['Type']}")
			source = mount["Source"] if mount["Type"] == "bind" else mount["Name"]
			if mount["Type"] == "volume":
				volumes[source] = {"external": True, "name": source}
			lines.append(
				"      - "
				+ json.dumps(
					{
						"type": mount["Type"],
						"source": source,
						"target": mount["Destination"],
						"read_only": not mount["RW"],
					}
				)
			)
	lines.append("volumes: " + json.dumps(volumes))
	(output / "compose.authoring-permissions.yaml").write_text("\n".join(lines) + "\n")
	(output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
	run("docker", "build", "--network=none", "--tag", image, str(output))
	print(f"Candidate only; production unchanged. Review artifacts: {output}")


if __name__ == "__main__":
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--project", default="hvp")
	parser.add_argument("--image", required=True, help="New, unique candidate tag (never the active tag)")
	parser.add_argument(
		"--output", required=True, type=Path, help="New directory for build and Compose artifacts"
	)
	args = parser.parse_args()
	prepare(args.project, args.image, args.output.resolve())
