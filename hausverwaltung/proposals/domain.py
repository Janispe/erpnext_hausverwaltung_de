"""Pure, typed label-operation contracts shared by the Frappe service/tests."""
import hashlib
import json

ACTION = "hv.synthetic_note.set_label/v1"
POLICY = "hv.synthetic-review/v1"


def encode(value):
	return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
	return hashlib.sha256(encode(value).encode()).hexdigest()


def payload(value):
	if not isinstance(value, dict) or set(value) != {"target", "label"}:
		raise ValueError("Only target and label are accepted")
	if not isinstance(value["target"], str) or not value["target"].startswith("SYN-") or len(value["target"]) > 140:
		raise ValueError("Synthetic identifier required")
	if not isinstance(value["label"], str) or not 1 <= len(value["label"]) <= 120 or value["label"] != value["label"].strip():
		raise ValueError("Label must contain 1..120 characters without outer whitespace")
	return json.loads(encode(value))


def binding(value):
	if (not isinstance(value, dict) or set(value) != {"id", "revision", "hash"}
		or not isinstance(value["id"], str) or not 1 <= len(value["id"]) <= 140
		or type(value["revision"]) is not int or value["revision"] < 1
		or not isinstance(value["hash"], str) or len(value["hash"]) != 64
		or any(c not in "0123456789abcdef" for c in value["hash"])):
		raise ValueError("Exact ID/revision/hash required")
	return value


def ordered_graph(dependencies, resolve, own_id=None):
	"""Return each bound node once, with explicit ancestry for writer ordering."""
	if not isinstance(dependencies, list) or len(dependencies) > 64:
		raise ValueError("At most 64 dependencies")
	seen, visiting, tokens, result, ancestry = set(), set(), {}, [], {}

	def visit(ref):
		binding(ref)
		pid = ref["id"]
		if pid == own_id or pid in visiting:
			raise ValueError("Dependency cycle")
		if pid in tokens and tokens[pid] != ref:
			raise ValueError("Conflicting dependency revision")
		tokens[pid] = ref
		if len(tokens) > 64:
			raise ValueError("At most 64 transitive dependencies")
		if pid in seen:
			return
		node = resolve(ref)
		visiting.add(pid)
		parents = set()
		for dep in node["body"]["dependencies"]:
			visit(dep)
			parents.add(dep["id"])
			parents.update(ancestry[dep["id"]])
		visiting.remove(pid)
		seen.add(pid)
		ancestry[pid] = parents
		result.append(node | {"ancestors": parents})

	for dep in dependencies:
		visit(dep)
	return result


def project(real, nodes, operation):
	"""No IO: only this registered label transformation can be composed."""
	states = json.loads(encode(real))
	writers, latest_real, modes = {}, {}, []
	for node in nodes:
		body, status = node["body"], node["status"]
		if body["action"] != ACTION or body["policy"] != POLICY:
			raise ValueError("Projection policy changed")
		pid, target = node["id"], body["payload"]["target"]
		if target in writers and writers[target] not in node["ancestors"]:
			raise ValueError("Unordered overlapping projections")
		writers[target] = pid
		if status == "Succeeded":
			result = node["result"]
			if result != {"doctype": "HV Synthetic Note", "id": target, "state": body["preview"]["after"]}:
				raise ValueError("Real result mapping differs")
			latest_real[target] = result["state"]
			mode = "real"
		else:
			if status not in {"Pending", "Approved"} or states[target] != body["preview"]["before"]:
				raise ValueError("Predecessor stale or unavailable")
			states[target] = body["preview"]["after"].copy()
			mode = "projected"
		modes.append({"id": pid, "revision": node["revision"], "hash": node["hash"], "mode": mode})
	for target, expected in latest_real.items():
		if real[target] != expected:
			raise ValueError("Real predecessor data differs")
	target = operation["target"]
	return {"doctype": "HV Synthetic Note", "target": target, "real": real[target],
		"before": states[target], "after": {"label": operation["label"], "generation": states[target]["generation"] + 1},
		"changes": [{"field": "label", "label": "Bezeichnung", "before": states[target]["label"], "after": operation["label"], "kind": "value"}],
		"dependencies": modes, "effects": ["Normal save updates modified/modified_by and generation"],
		"limits": ["Synthetic local label only", "No financial, mail, jobs or external actions",
			"Normal validation/hooks run only at execute; unknown hook effects are not simulated"],
		"projection_version": ACTION, "complete": True}


def text(value, name, minimum, maximum):
	if not isinstance(value, str) or not minimum <= len(value) <= maximum or (minimum and not value.strip()):
		raise ValueError(f"{name} must contain {minimum}..{maximum} characters")
	return value


def metadata(value):
	if not isinstance(value, dict) or set(value) - {"title", "summary", "lane", "rationale", "sources"}:
		raise ValueError("Invalid revision metadata")
	result = {"title": text(value.get("title"), "title", 1, 80),
		"summary": text(value.get("summary"), "summary", 1, 140),
		"rationale": text(value.get("rationale", ""), "rationale", 0, 2000), "lane": None, "sources": []}
	lane = value.get("lane")
	if lane is not None:
		if not isinstance(lane, dict) or set(lane) != {"key", "label"}:
			raise ValueError("Invalid lane")
		result["lane"] = {"key": text(lane["key"], "lane.key", 1, 80), "label": text(lane["label"], "lane.label", 1, 140)}
	sources = value.get("sources", [])
	if not isinstance(sources, list) or len(sources) > 10:
		raise ValueError("At most 10 sources")
	for source in sources:
		if not isinstance(source, dict) or set(source) - {"label", "doctype", "name"}:
			raise ValueError("Invalid source")
		item = {"label": text(source.get("label"), "source.label", 1, 200)}
		for key in ("doctype", "name"):
			if key in source: item[key] = text(source[key], key, 1, 140)
		if ("doctype" in item) != ("name" in item):
			raise ValueError("Source reference requires doctype and name")
		result["sources"].append(item)
	return result


def package_metadata(value):
	if not isinstance(value, dict) or set(value) - {"title", "reason", "reference_doctype", "reference_name", "lane_label"}:
		raise ValueError("Invalid package metadata")
	result = {"title": text(value.get("title"), "title", 1, 140)}
	for key, maximum in (("reason", 2000), ("reference_doctype", 140), ("reference_name", 140), ("lane_label", 140)):
		result[key] = text(value.get(key, ""), key, 0, maximum)
	if bool(result["reference_doctype"]) != bool(result["reference_name"]):
		raise ValueError("Package reference requires doctype and name")
	return result
