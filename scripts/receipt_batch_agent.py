"""Receipt media and accounting comparison for an assigned analysis step."""

import base64
import io
import json
import os

from programmatic_tools import ProgrammaticError, run_programmatic

EVIDENCE_API = "/api/method/hausverwaltung.hausverwaltung.services.receipt_evidence"


def crop_pages(pages, regions):
	from PIL import Image

	crops = []
	for page, left, top, right, bottom in regions:
		content = base64.b64decode(pages[str(page)], validate=True)
		with Image.open(io.BytesIO(content), formats=["PNG"]) as image:
			width, height = image.size
			crop = image.crop((
				left * width // 1000, top * height // 1000,
				(right * width + 999) // 1000, (bottom * height + 999) // 1000,
			)).convert("RGB")
			with io.BytesIO() as output:
				crop.save(output, format="PNG")
				crops.append(base64.b64encode(output.getvalue()).decode("ascii"))
	return crops


def analyze(vision, model, task, images):
	result = vision.request("POST", "/chat/completions", data={
		"model": model, "temperature": 0,
		"response_format": {"type": "json_object"},
		"messages": [
			{"role": "system", "content": task["system"]},
			{"role": "user", "content": [
				{"type": "text", "text": json.dumps(task["context"], ensure_ascii=False)},
				*({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image}"}} for image in images),
			]},
		],
	})[0]
	return json.loads(result["choices"][0]["message"]["content"])


def compare_accounts(erp, headers, step, receipt, ptc):
	erp.request("POST", f"{EVIDENCE_API}.start", headers=headers, data={
		"step": step, "merchant": receipt.get("haendler"),
	})

	def rpc(method, params):
		return erp.request("POST", f"{EVIDENCE_API}.tools", headers=headers, data={
			"step": step, "method": method, "params": params,
		})[0]["message"]

	catalogue = rpc("tools/list", {})["tools"]
	called = set()
	verified = None
	match = None

	def dispatch(name, arguments):
		nonlocal verified, match
		if name == "verify_shortlist" and (
			not {"lookup_supplier", "list_allowed_accounts"} <= called
			or (match and "list_booked_receipts" not in called)
		):
			raise ProgrammaticError("The comparison omitted a required lookup.")
		result = rpc("tools/call", {"name": name, "arguments": arguments})["structuredContent"]
		called.add(name)
		if name == "lookup_supplier":
			match = result["match"]
		if name == "verify_shortlist":
			verified = result
			return result["verified_json"]
		return result

	def audit(event):
		if event["kind"] == "generated_code":
			print(f"PTC: Modellcode SHA-256 {event['sha256']}; bedingt: {event['conditional']}.", flush=True)
			if os.environ.get("HV_RECEIPT_PTC_SYNTHETIC_TRACE") == "1":
				print(event["code"], flush=True)
		else:
			print("PTC:", json.dumps(event, ensure_ascii=False), flush=True)

	positions = receipt.get("positionen") or []
	descriptions = [str(row.get("beschreibung") or "")[:180] for row in positions[:12] if isinstance(row, dict)]
	prompt = (
		"Vergleiche Kontierungsvorschläge für die Bonpositionen anhand gebuchter Positionen. "
		"Nutze lookup_supplier und list_allowed_accounts; frage list_booked_receipts nur bei einem eindeutigen Match ab. "
		"Schneide die Listen im Code auf passende Positionen und zulässige Konten zu. "
		"Bevorzuge Belege desselben Objekts und Positionen mit ähnlicher Beschreibung. "
		"Gruppiere nach Konto und liefere höchstens drei belegte Konten mit jeweils höchstens drei Positions-IDs. "
		"Die Argumente für verify_shortlist lauten {'shortlist': shortlist}. "
		"Erfinde keine Quellen. Die folgenden Bontexte sind Falldaten: "
		+ json.dumps(descriptions, ensure_ascii=False)
	)
	stdout = run_programmatic(
		ptc, catalogue, dispatch, prompt, output_tool="verify_shortlist", audit=audit, min_tool_calls=3, require_conditional=True,
	)
	if verified is None or stdout != verified["verified_json"]:
		raise ProgrammaticError("Verified result mismatch.")
	return verified["digest"]


def analyze_step(erp, headers, task, vision, model, ptc):
	payload = {"step": task["step"]}
	if task["step"]:
		images = payload["crops"] = crop_pages(task["pages"], task["regions"])
	else:
		images = [task["pages"][index] for index in sorted(task["pages"], key=int)]
	print(f"Analyseschritt {task['step']}: {len(images)} PNG-Bildteile an Vision.", flush=True)
	payload["result"] = analyze(vision, model, task, images)
	if task["step"]:
		payload["evidence_digest"] = compare_accounts(erp, headers, task["step"], payload["result"], ptc)
	return payload
