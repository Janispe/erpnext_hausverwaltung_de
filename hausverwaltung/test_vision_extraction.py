"""End-to-end mit Vision-First: PDF → PNG → qwen2.5vl:7b → strukturiertes JSON."""

import json
import time

import frappe
from frappe.utils.file_manager import save_file


PDF_PATH = "/home/frappe/frappe-bench/sites/test_invoice.pdf"


def run():
	with open(PDF_PATH, "rb") as f:
		pdf_bytes = f.read()

	# Cleanup
	for vname in frappe.get_all(
		"Buchungs Vorschlag",
		filters={"original_filename": ["like", "%Rechnung_00750%"]},
		pluck="name",
	):
		try:
			frappe.delete_doc("Buchungs Vorschlag", vname, force=1, ignore_permissions=True)
		except Exception:
			pass
	for fname in frappe.get_all(
		"File",
		filters={"file_name": ["like", "%Rechnung_00750%"]},
		pluck="name",
	):
		try:
			frappe.db.delete("File", {"name": fname})
		except Exception:
			pass
	frappe.db.commit()

	# Upload
	saved = save_file("Rechnung_00750_24.pdf", pdf_bytes, "", "", is_private=1)
	print(f"Uploaded: {saved.file_url}")

	# Direkter Aufruf — synchron, damit ich die Latenz live sehe
	from hausverwaltung.hausverwaltung.services.invoice_extraction import (
		extract_from_file_url,
	)

	print(f"Starte Vision-Extraktion mit qwen2.5vl:7b...")
	start = time.monotonic()
	try:
		result = extract_from_file_url(saved.file_url)
	except Exception as exc:
		dt = time.monotonic() - start
		print(f"FAIL nach {dt:.1f}s: {type(exc).__name__}: {exc}")
		raise
	dt = time.monotonic() - start
	print(f"\n=== Ergebnis nach {dt:.1f} Sekunden ===")
	print(f"Vision genutzt: {result.get('used_vision')}")

	fields = result.get("fields", {})
	conf = result.get("confidence", {})
	print(f"\nLieferant (gemappt):     {fields.get('lieferant') or '(leer)'}")
	print(f"LLM-Lieferant-Name:      {result.get('llm_lieferant') or '(leer)'}")
	print(f"  → Confidence:          {conf.get('lieferant', 0):.2f}")
	print(f"Rechnungsdatum:          {fields.get('rechnungsdatum') or '(leer)'}  (conf {conf.get('rechnungsdatum', 0):.2f})")
	print(f"Wertstellungsdatum:      {fields.get('wertstellungsdatum') or '(leer)'}  (conf {conf.get('wertstellungsdatum', 0):.2f})")
	print(f"Bill-No:                 {fields.get('rechnungsname') or '(leer)'}  (conf {conf.get('bill_no', 0):.2f})")

	positionen = result.get("positionen", [])
	print(f"\nPositionen ({len(positionen)}):")
	for i, p in enumerate(positionen, 1):
		print(f"  {i}. {(p.get('beschreibung') or '?')[:70]}")
		print(f"     Betrag: {p.get('betrag')} EUR")
		print(f"     Kostenart: {p.get('kostenart') or '(leer)'} ({p.get('umlagefaehig') or '?'})")
		print(f"     Kostenstelle: {p.get('kostenstelle') or '(leer)'}")
		print(f"     Confidence: {p.get('_confidence')}")

	warnings = result.get("warnings", [])
	if warnings:
		print(f"\nWarnings ({len(warnings)}):")
		for w in warnings:
			print(f"  - {w}")

	lieferant_neu = result.get("lieferant_neu")
	if lieferant_neu:
		print(f"\nLieferant-Anlage-Vorschlag:")
		for k, v in lieferant_neu.items():
			if v:
				print(f"  {k}: {v}")
