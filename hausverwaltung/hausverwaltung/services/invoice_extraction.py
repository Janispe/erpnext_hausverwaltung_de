"""PDF-Rechnungs-Extraktion via Mistral.

Pipeline:
1. File-Bytes via ``frappe.utils.file_manager.get_file`` laden.
2. Text mit ``pypdf`` extrahieren. Wenn leer und Vision-Fallback aktiv:
   erste Seite mit ``pypdfium2`` als PNG rendern und an Vision-Modell schicken.
3. Prompt mit Kostenarten-Liste und Few-Shot-Beispielen bauen.
4. Mistral-Aufruf, JSON-Schema-validierte Antwort parsen.
5. Post-Processing: Lieferant-Fuzzy-Match gegen Supplier-Liste, Kostenart
   gegen Stammdaten validieren, Kostenstelle aus PI-Historie ableiten.
"""

from __future__ import annotations

import io
import json
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

import frappe
from frappe.utils.file_manager import get_file

from hausverwaltung.hausverwaltung.services import mistral_client

MIN_TEXT_LENGTH_FOR_TEXT_MODEL = 80
SUPPLIER_FUZZY_THRESHOLD = 0.8
SUPPLIER_LIST_MAX = 500
MAX_RAW_TEXT_RETURN = 4000


def _load_kostenarten_for_prompt() -> list[dict]:
	"""Liefert die buchbaren Kostenarten als Liste mit Typ-Hinweis.

	Replik der Logik aus ``buchen_cockpit.list_eligible_kostenarten`` —
	nur ohne deren Suffix-Konflikt-Behandlung, die brauchen wir hier nicht.
	"""
	bks = frappe.get_all(
		"Betriebskostenart",
		filters={"konto": ["is", "set"], "artikel": ["is", "set"]},
		fields=["name", "konto"],
		order_by="name",
	)
	nuls = frappe.get_all(
		"Kostenart nicht umlagefaehig",
		filters={"konto": ["is", "set"], "artikel": ["is", "set"]},
		fields=["name", "konto"],
		order_by="name",
	)
	out: list[dict] = []
	for r in bks:
		out.append({"name": r["name"], "umlagefaehig": "Betriebskostenart"})
	for r in nuls:
		out.append({"name": r["name"], "umlagefaehig": "Kostenart nicht umlagefaehig"})
	return out


def _load_suppliers_for_prompt() -> list[str]:
	"""Aktive Supplier-Namen für den Prompt — supplier_name bevorzugt, Fallback name."""
	rows = frappe.get_all(
		"Supplier",
		filters={"disabled": 0},
		fields=["name", "supplier_name"],
		order_by="modified desc",
		limit_page_length=SUPPLIER_LIST_MAX,
	)
	out: list[str] = []
	seen: set[str] = set()
	for r in rows:
		display = (r.get("supplier_name") or r.get("name") or "").strip()
		if not display or display in seen:
			continue
		seen.add(display)
		out.append(display)
	return out


def _read_pdf_text(content: bytes) -> str:
	try:
		from pypdf import PdfReader
	except Exception as exc:
		raise mistral_client.MistralPermanentError(
			"pypdf ist nicht installiert."
		) from exc
	reader = PdfReader(io.BytesIO(content))
	parts: list[str] = []
	for page in reader.pages:
		try:
			text = page.extract_text() or ""
		except Exception:
			text = ""
		if text.strip():
			parts.append(text)
	return "\n".join(parts).strip()


def _render_pdf_first_page_png(content: bytes) -> bytes:
	"""Erste PDF-Seite als PNG rendern (für Vision-Fallback)."""
	try:
		import pypdfium2 as pdfium
	except Exception as exc:
		raise mistral_client.MistralPermanentError(
			"pypdfium2 ist nicht installiert. Vision-Fallback nicht möglich."
		) from exc
	pdf = pdfium.PdfDocument(content)
	if len(pdf) == 0:
		raise mistral_client.MistralPermanentError("PDF enthält keine Seiten.")
	page = pdf[0]
	# 200 DPI ist guter Kompromiss zwischen Lesbarkeit und Größe.
	bitmap = page.render(scale=200 / 72)
	pil = bitmap.to_pil()
	buf = io.BytesIO()
	pil.save(buf, format="PNG")
	return buf.getvalue()


SYSTEM_PROMPT_BASE = (
	"Du bist ein Buchhaltungs-Assistent für eine deutsche Hausverwaltung. "
	"Du extrahierst aus einer Eingangsrechnung strukturierte Daten und ordnest jede "
	"Position einer Kostenart aus der angegebenen Liste zu. Antworte ausschließlich "
	"als gültiges JSON nach folgendem Schema und ohne zusätzlichen Text:\n\n"
	"{\n"
	'  "lieferant_name": "string (Firmenname des Rechnungsstellers, exakt aus Lieferanten-Liste wenn möglich)",\n'
	'  "lieferant_confidence": 0.0,\n'
	'  "rechnungsdatum": "YYYY-MM-DD oder null",\n'
	'  "rechnungsdatum_confidence": 0.0,\n'
	'  "wertstellungsdatum": "YYYY-MM-DD oder null (= Leistungszeitraum-Beginn '
	'oder Hauptdatum bei Versorger-Abrechnungen)",\n'
	'  "wertstellungsdatum_confidence": 0.0,\n'
	'  "bill_no": "Rechnungsnummer oder null",\n'
	'  "bill_no_confidence": 0.0,\n'
	'  "positionen": [\n'
	"    {\n"
	'      "betrag": 123.45,\n'
	'      "beschreibung": "kurze Beschreibung der Leistung",\n'
	'      "kostenart_vorschlag": "Name aus der Kostenart-Liste oder null wenn unsicher",\n'
	'      "umlagefaehig": "Betriebskostenart oder Kostenart nicht umlagefaehig oder null",\n'
	'      "kostenart_confidence": 0.0\n'
	"    }\n"
	"  ]\n"
	"}\n\n"
	"Regeln:\n"
	"- confidence-Werte sind Floats zwischen 0.0 und 1.0. 0.95+ = sicher, 0.7-0.9 = "
	"plausibel, <0.7 = unsicher.\n"
	"- Wenn ein Feld nicht eindeutig bestimmt werden kann, setze null + niedrige Confidence.\n"
	"- Beträge immer als Float in EUR ohne Währungssymbol. Brutto bevorzugen wenn USt ausgewiesen.\n"
	"- Bei wenigen kleinen Positionen (< 5): jede einzeln. Bei langer Liste oder "
	"  einer Sammelrechnung: zu max. 3-5 Positionen aggregieren mit zusammenfassender Beschreibung.\n"
	"- Datumsangaben in ISO-Format YYYY-MM-DD. Eingaben können in DE-Format vorliegen "
	"  (z.B. '12.04.2026', '12. April 2026', '12.4.2026') — immer in YYYY-MM-DD umwandeln.\n"
	"- 'wertstellungsdatum' = Leistungszeitraum-Beginn (Felder: 'Leistungszeitraum', "
	"  'Verbrauchszeitraum', 'Abrechnungszeitraum'). Wenn nicht vorhanden, null.\n"
	"- 'lieferant_name': Wenn ein Eintrag aus der Lieferanten-Liste plausibel passt, gib "
	"  diesen Eintrag EXAKT zurück. Sonst gib den Namen wie auf der Rechnung an.\n"
	"- 'kostenart_vorschlag' MUSS exakt einem Namen aus der Kostenart-Liste entsprechen "
	"  (Groß-/Kleinschreibung beachten) oder null sein.\n"
	"- 'umlagefaehig' muss zur gewählten Kostenart passen (Liste sagt 'Betriebskostenart' "
	"  oder 'Kostenart nicht umlagefaehig').\n"
	"\n"
	"Beispiel 1 — Stromabrechnung von Vattenfall, einfacher Allgemeinstrom-Posten:\n"
	"Eingabe: 'Vattenfall Europe Sales GmbH ... Rechnungs-Nr. VS-2026-998877 ... "
	"Rechnungsdatum 14.03.2026 ... Verbrauchszeitraum 01.01.2026 - 31.01.2026 ... "
	"Allgemeinstrom Treppenhaus 156,40 EUR brutto'\n"
	"Ausgabe: {\"lieferant_name\": \"Vattenfall Europe Sales GmbH\", \"lieferant_confidence\": 0.95, "
	"\"rechnungsdatum\": \"2026-03-14\", \"rechnungsdatum_confidence\": 1.0, "
	"\"wertstellungsdatum\": \"2026-01-01\", \"wertstellungsdatum_confidence\": 0.9, "
	"\"bill_no\": \"VS-2026-998877\", \"bill_no_confidence\": 0.95, "
	"\"positionen\": [{\"betrag\": 156.40, \"beschreibung\": \"Allgemeinstrom Treppenhaus\", "
	"\"kostenart_vorschlag\": \"Allgemeinstrom\", \"umlagefaehig\": \"Betriebskostenart\", "
	"\"kostenart_confidence\": 0.92}]}\n"
	"\n"
	"Beispiel 2 — Handwerker-Rechnung mit zwei Positionen, eine nicht umlegbar:\n"
	"Eingabe: 'Maler Schmidt GmbH ... Rg.-Nr. 2026-117 ... 22. April 2026 ... "
	"Pos 1: Renovierung Treppenhaus EG 1.250,00 ... Pos 2: Streichen Wohnung 4.OG li 850,00'\n"
	"Ausgabe: {\"lieferant_name\": \"Maler Schmidt GmbH\", \"lieferant_confidence\": 0.9, "
	"\"rechnungsdatum\": \"2026-04-22\", \"rechnungsdatum_confidence\": 1.0, "
	"\"wertstellungsdatum\": null, \"wertstellungsdatum_confidence\": 0.0, "
	"\"bill_no\": \"2026-117\", \"bill_no_confidence\": 0.9, "
	"\"positionen\": [{\"betrag\": 1250.00, \"beschreibung\": \"Renovierung Treppenhaus EG\", "
	"\"kostenart_vorschlag\": \"Schönheitsreparaturen\", \"umlagefaehig\": \"Betriebskostenart\", "
	"\"kostenart_confidence\": 0.7}, "
	"{\"betrag\": 850.00, \"beschreibung\": \"Streichen Wohnung 4.OG li\", "
	"\"kostenart_vorschlag\": \"Instandhaltung Wohnungen\", \"umlagefaehig\": \"Kostenart nicht umlagefaehig\", "
	"\"kostenart_confidence\": 0.65}]}\n"
)


def _format_kostenarten_block(kostenarten: list[dict]) -> str:
	lines = [f"- {k['name']} ({k['umlagefaehig']})" for k in kostenarten]
	return "\n".join(lines)


def _format_suppliers_block(suppliers: list[str]) -> str:
	if not suppliers:
		return "(keine Lieferanten-Stammdaten verfügbar)"
	return "\n".join(f"- {name}" for name in suppliers)


def _build_user_prompt(invoice_text: str, kostenarten: list[dict], suppliers: list[str]) -> str:
	return (
		"Verfügbare Lieferanten (Stammdaten — bevorzugt einen Eintrag aus dieser Liste "
		"als 'lieferant_name' verwenden, wenn er zur Rechnung passt):\n"
		f"{_format_suppliers_block(suppliers)}\n\n"
		"Verfügbare Kostenarten:\n"
		f"{_format_kostenarten_block(kostenarten)}\n\n"
		"Rechnungstext:\n"
		f"{invoice_text}\n"
	)


def _build_vision_user_prompt(kostenarten: list[dict], suppliers: list[str]) -> str:
	return (
		"Analysiere das Bild der Eingangsrechnung und extrahiere die Daten.\n\n"
		"Verfügbare Lieferanten (bevorzugt einen Eintrag aus dieser Liste als "
		"'lieferant_name' verwenden, wenn er passt):\n"
		f"{_format_suppliers_block(suppliers)}\n\n"
		"Verfügbare Kostenarten:\n"
		f"{_format_kostenarten_block(kostenarten)}\n"
	)


def _exact_supplier_lookup(name: str) -> str | None:
	"""Liefert die Supplier-`name`-ID, wenn der LLM-Output exakt einem
	supplier_name oder name aus den Stammdaten entspricht.

	Wird vor dem Fuzzy-Match versucht, da das Modell jetzt eine Lieferantenliste
	im Prompt hat und idealerweise einen passenden Eintrag zurückgibt.
	"""
	if not name:
		return None
	# 1. Exakter Match auf supplier_name (häufigster Fall, weil das der Anzeige-Name ist).
	hit = frappe.db.get_value("Supplier", {"supplier_name": name, "disabled": 0}, "name")
	if hit:
		return hit
	# 2. Exakter Match auf den Frappe-Doc-Namen (= meistens identisch zu supplier_name).
	if frappe.db.exists("Supplier", {"name": name, "disabled": 0}):
		return name
	return None


def _fuzzy_supplier_lookup(name: str) -> str | None:
	"""Findet einen Supplier mit fuzzy-Match auf supplier_name oder name."""
	if not name:
		return None
	candidates = frappe.get_all(
		"Supplier",
		filters={"disabled": 0},
		fields=["name", "supplier_name"],
		limit_page_length=2000,
	)
	best_score = 0.0
	best_name = None
	target = name.lower().strip()
	for c in candidates:
		for field in (c.get("supplier_name"), c.get("name")):
			if not field:
				continue
			score = SequenceMatcher(None, target, field.lower().strip()).ratio()
			if score > best_score:
				best_score = score
				best_name = c["name"]
	if best_score >= SUPPLIER_FUZZY_THRESHOLD:
		return best_name
	return None


def _validate_kostenart(name: str, kostenarten: list[dict]) -> dict | None:
	"""Prüft, ob der LLM-Vorschlag in der Liste existiert. Liefert {name, umlagefaehig} oder None."""
	if not name:
		return None
	for k in kostenarten:
		if k["name"] == name:
			return {"name": k["name"], "umlagefaehig": k["umlagefaehig"]}
	# Case-insensitive Fallback.
	target = name.lower().strip()
	for k in kostenarten:
		if k["name"].lower().strip() == target:
			return {"name": k["name"], "umlagefaehig": k["umlagefaehig"]}
	return None


def _most_common_cost_center_for_supplier(supplier: str) -> str | None:
	"""Häufigste Kostenstelle der letzten 10 Purchase Invoices des Lieferanten."""
	if not supplier:
		return None
	pi_names = frappe.get_all(
		"Purchase Invoice",
		filters={"supplier": supplier, "docstatus": 1},
		fields=["name"],
		order_by="posting_date desc",
		limit_page_length=10,
	)
	if not pi_names:
		return None
	rows = frappe.get_all(
		"Purchase Invoice Item",
		filters={"parent": ["in", [p["name"] for p in pi_names]]},
		fields=["cost_center"],
	)
	counts = Counter([r["cost_center"] for r in rows if r.get("cost_center")])
	if not counts:
		return None
	return counts.most_common(1)[0][0]


def _coerce_confidence(value: Any) -> float:
	try:
		f = float(value)
	except (TypeError, ValueError):
		return 0.0
	return max(0.0, min(1.0, f))


def _coerce_iso_date(value: Any) -> str | None:
	if not value:
		return None
	s = str(value).strip()
	# Mistral hält sich meist ans Format; trotzdem defensiv.
	if len(s) == 10 and s[4] == "-" and s[7] == "-":
		return s
	return None


def extract_from_file_url(file_url: str) -> dict:
	"""Hauptfunktion: file_url → strukturiertes Vorschlags-Dict für den Cockpit-Dialog."""
	if not file_url:
		raise mistral_client.MistralPermanentError("file_url fehlt.")

	mistral_client.ensure_configured()

	# 1. File laden.
	try:
		_filename, content = get_file(file_url)
	except Exception as exc:
		raise mistral_client.MistralPermanentError(
			f"Datei konnte nicht geladen werden: {exc}"
		) from exc
	if isinstance(content, str):
		content = content.encode("utf-8", errors="replace")

	# 2. Text extrahieren.
	pdf_text = _read_pdf_text(content)
	used_vision = False

	kostenarten = _load_kostenarten_for_prompt()
	suppliers = _load_suppliers_for_prompt()

	# 3. Vision-Fallback wenn Text leer/zu kurz.
	if (
		len(pdf_text) < MIN_TEXT_LENGTH_FOR_TEXT_MODEL
		and mistral_client.is_vision_fallback_enabled()
	):
		image_bytes = _render_pdf_first_page_png(content)
		extracted = mistral_client.complete_vision_json(
			system=SYSTEM_PROMPT_BASE,
			user_prompt=_build_vision_user_prompt(kostenarten, suppliers),
			image_bytes=image_bytes,
		)
		used_vision = True
	elif len(pdf_text) < MIN_TEXT_LENGTH_FOR_TEXT_MODEL:
		raise mistral_client.MistralPermanentError(
			"Aus dem PDF konnte kein Text extrahiert werden und der Vision-Fallback ist deaktiviert."
		)
	else:
		extracted = mistral_client.complete_json(
			system=SYSTEM_PROMPT_BASE,
			user=_build_user_prompt(pdf_text, kostenarten, suppliers),
		)

	# 4. Post-Processing — Lieferant.
	llm_lieferant = str(extracted.get("lieferant_name") or "").strip()
	# Wenn das Modell exakt einen Eintrag aus der Stammdaten-Liste zurückgegeben hat,
	# matchen wir direkt — sonst Fuzzy-Match als Fallback.
	matched_supplier = _exact_supplier_lookup(llm_lieferant) or _fuzzy_supplier_lookup(llm_lieferant)
	warnings: list[str] = []
	if llm_lieferant and not matched_supplier:
		warnings.append(
			f"Lieferant '{llm_lieferant}' nicht in den Stammdaten gefunden — bitte manuell wählen oder anlegen."
		)

	# 5. Kostenstelle aus History.
	default_kostenstelle = _most_common_cost_center_for_supplier(matched_supplier or "") if matched_supplier else None

	# 6. Positionen normalisieren.
	positionen_out: list[dict] = []
	for raw_pos in extracted.get("positionen") or []:
		if not isinstance(raw_pos, dict):
			continue
		betrag = raw_pos.get("betrag")
		try:
			betrag_f = float(betrag) if betrag not in (None, "") else None
		except (TypeError, ValueError):
			betrag_f = None
		if betrag_f is None:
			continue

		llm_kostenart = str(raw_pos.get("kostenart_vorschlag") or "").strip()
		validated = _validate_kostenart(llm_kostenart, kostenarten)

		pos = {
			"betrag": betrag_f,
			"beschreibung": str(raw_pos.get("beschreibung") or "").strip(),
			"kostenart": validated["name"] if validated else "",
			"umlagefaehig": validated["umlagefaehig"] if validated else "",
			"kostenstelle": default_kostenstelle or "",
			"_confidence": _coerce_confidence(raw_pos.get("kostenart_confidence")),
		}
		# Beschreibung hilfreich als 'kostenart' für UI, falls keine Validierung griff:
		if llm_kostenart and not validated:
			warnings.append(
				f"Kostenart-Vorschlag '{llm_kostenart}' ist nicht in den Stammdaten — bitte manuell wählen."
			)
		positionen_out.append(pos)

	# 7. Confidence-Sammlung für Header-Felder.
	confidence_map = {
		"lieferant": _coerce_confidence(extracted.get("lieferant_confidence")),
		"rechnungsdatum": _coerce_confidence(extracted.get("rechnungsdatum_confidence")),
		"wertstellungsdatum": _coerce_confidence(extracted.get("wertstellungsdatum_confidence")),
		"bill_no": _coerce_confidence(extracted.get("bill_no_confidence")),
	}
	for fname, conf in confidence_map.items():
		if conf and conf < 0.7:
			warnings.append(f"{fname}: niedrige Confidence ({conf:.2f}) — bitte prüfen.")

	# 8. Result.
	return {
		"fields": {
			"lieferant": matched_supplier or "",
			"rechnungsdatum": _coerce_iso_date(extracted.get("rechnungsdatum")) or "",
			"wertstellungsdatum": _coerce_iso_date(extracted.get("wertstellungsdatum")) or "",
			"rechnungsname": str(extracted.get("bill_no") or "").strip(),
		},
		"positionen": positionen_out,
		"confidence": confidence_map,
		"warnings": warnings,
		"used_vision": used_vision,
		"raw_text": (pdf_text or "")[:MAX_RAW_TEXT_RETURN],
		"llm_lieferant": llm_lieferant,
	}
