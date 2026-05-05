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
# Rechnungs-PDFs mit vielen Seiten (z.B. Wartung/Reparaturen mit langer
# Positions-Liste) können mehrere zehntausend Zeichen produzieren — der Mistral-
# Call läuft dann in den Timeout. Die wirklich relevanten Daten (Header +
# erste Positionen + Summe) stehen normalerweise auf den ersten 1-2 Seiten,
# daher harte Kappung.
MAX_PROMPT_INVOICE_TEXT_CHARS = 14000


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
	"""Extrahiert Text aus PDF mit Layout-Berücksichtigung.

	PyMuPDF im 'blocks'-Modus liefert Text-Blöcke mit ihren BBox-Koordinaten —
	wir sortieren räumlich (oben→unten, links→rechts) und gruppieren Blöcke,
	die in derselben horizontalen Zeile liegen, mit Tab-Trennern. Das macht
	Tabellen ('Position\\tMenge\\tBezeichnung\\t...\\t1\\t2,00 Stk.\\tJunkers...')
	für das LLM lesbar.

	pypdf bleibt als Fallback für PDFs, die fitz nicht parsen kann.
	"""
	# 1) PyMuPDF blocks-mode — primär.
	try:
		import fitz

		try:
			doc = fitz.open(stream=content, filetype="pdf")
		except Exception:
			doc = None
		if doc is not None:
			page_texts: list[str] = []
			for page in doc:
				try:
					blocks = page.get_text("blocks") or []
				except Exception:
					blocks = []
				# blocks: (x0, y0, x1, y1, "text", block_no, block_type)
				text_blocks = [b for b in blocks if len(b) >= 5 and (b[6] if len(b) > 6 else 0) == 0]
				# Sortieren oben→unten, dann links→rechts (mit Toleranz für gleiche Zeile).
				text_blocks.sort(key=lambda b: (round(float(b[1]) / 6) * 6, float(b[0])))
				lines: list[str] = []
				current_y = None
				current_row: list[str] = []
				for b in text_blocks:
					y0 = float(b[1])
					text = (b[4] or "").strip()
					if not text:
						continue
					if current_y is None or abs(y0 - current_y) <= 6:
						current_row.append(text)
						current_y = y0 if current_y is None else current_y
					else:
						if current_row:
							lines.append("\t".join(current_row))
						current_row = [text]
						current_y = y0
				if current_row:
					lines.append("\t".join(current_row))
				if lines:
					page_texts.append("\n".join(lines))
			doc.close()
			joined = "\n\n".join(page_texts).strip()
			if joined:
				return joined
	except Exception:
		pass

	# 2) pypdf als Fallback.
	try:
		from pypdf import PdfReader
	except Exception as exc:
		raise mistral_client.MistralPermanentError(
			"Weder pymupdf noch pypdf sind installiert."
		) from exc
	reader = PdfReader(io.BytesIO(content))
	parts2: list[str] = []
	for page in reader.pages:
		try:
			text = page.extract_text() or ""
		except Exception:
			text = ""
		if text.strip():
			parts2.append(text)
	return "\n".join(parts2).strip()


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
	"Du extrahierst aus einer deutschen Eingangsrechnung strukturierte Daten und "
	"antwortest ausschliesslich als JSON nach folgendem Schema (keine Listen, "
	"keine Beispiele, kein zusaetzlicher Text):\n"
	"{\n"
	'  "lieferant_name": "Firma im Briefkopf des Rechnungsstellers (NICHT die Empfaenger-Adresse)",\n'
	'  "lieferant_confidence": 0.0,\n'
	'  "lieferant_iban": "IBAN des Lieferanten oder null",\n'
	'  "lieferant_steuer_id": "USt-IdNr (DE...) oder Steuernummer oder null",\n'
	'  "lieferant_strasse": "Strasse + Hausnummer (Briefkopf) oder null",\n'
	'  "lieferant_plz": "5-stellige PLZ oder null",\n'
	'  "lieferant_ort": "Ort oder null",\n'
	'  "lieferant_land": "Land oder Deutschland",\n'
	'  "rechnungsdatum": "YYYY-MM-DD oder null",\n'
	'  "rechnungsdatum_confidence": 0.0,\n'
	'  "wertstellungsdatum": "YYYY-MM-DD oder null (Leistungszeitraum-Beginn / Verbrauchszeitraum / Abrechnungsperiode)",\n'
	'  "wertstellungsdatum_confidence": 0.0,\n'
	'  "bill_no": "Rechnungsnummer oder null",\n'
	'  "bill_no_confidence": 0.0,\n'
	'  "immobilie_hinweis": "Strassenname oder Adresse der gemieteten/verwalteten Immobilie aus dem Rechnungstext oder null (z.B. \\"Wilhelmshavener Str. 31\\", \\"Gropiusstr. 12\\"). NICHT die Adresse des Lieferanten oder die Empfaenger-Adresse der Hausverwaltung.",\n'
	'  "remarks_vorschlag": "kurze Anmerkung (1-3 Saetze) mit Verwendungszweck/Auftragskontext fuer die Buchung — was wurde gemacht, fuer welche Wohnungen/Mieter, ggf. Verbrauchszeitraum",\n'
	'  "positionen": [\n'
	'    {"betrag": 123.45, "beschreibung": "kurze Beschreibung der Leistung"}\n'
	"  ]\n"
	"}\n"
	"Regeln:\n"
	"- DE-Datum (12.04.2026, 12. April 2026, 12.4.2026) zu YYYY-MM-DD umwandeln.\n"
	"- Beträge als Float in EUR (Brutto bevorzugen). Beschreibung kurz.\n"
	"- confidence: Float 0.0-1.0 (1.0 = sicher).\n"
	"- Auch bei einer einzigen Position: positionen muss eine Liste sein.\n"
	"- 'immobilie_hinweis': suche im Beschreibungstext / Verwendungszweck nach einer "
	"  Strassenadresse, die nicht Lieferant und nicht Empfaenger (Hausverwaltung) ist. "
	"  Bei Versorger-Rechnungen ist es oft die 'Lieferadresse' / 'Verbrauchsstelle'. "
	"  Format wie auf der Rechnung uebernehmen, null wenn nicht erkennbar.\n"
	"- 'remarks_vorschlag': fasse den Verwendungszweck zusammen (Beispiele: "
	"  'Wartung Heizung VH+HH, Brennerdichtungen erneuert', 'Allgemeinstrom Verbrauchszeitraum 01-03/2026', "
	"  'Reparatur Wasserrohrbruch Wohnung 2.OG'). 1-3 Saetze, max. 250 Zeichen, "
	"  null wenn keine sinnvolle Zusammenfassung moeglich.\n"
)


def _build_user_prompt(invoice_text: str) -> str:
	# Schutz gegen Timeout bei langen mehrseitigen PDFs — Header + erste
	# Positionen reichen normalerweise. Wenn der Cut greift, hängen wir einen
	# Hinweis dran, damit das Modell weiß dass die Liste evtl. unvollständig ist.
	if len(invoice_text) > MAX_PROMPT_INVOICE_TEXT_CHARS:
		invoice_text = (
			invoice_text[:MAX_PROMPT_INVOICE_TEXT_CHARS]
			+ "\n[...Text abgeschnitten — restliche Seiten ausgelassen.]"
		)
	return f"Rechnungstext:\n{invoice_text}\n"


def _build_vision_user_prompt() -> str:
	return "Analysiere das Bild der Eingangsrechnung und extrahiere die Daten."


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


def _normalize_supplier_token(s: str) -> str:
	"""Lowercase, Punctuation entfernt, Whitespace collapsed — fürs Token-Matching."""
	import re

	s = (s or "").lower().strip()
	s = re.sub(r"[.,;:!?\(\)\"']", " ", s)
	s = re.sub(r"\s+", " ", s)
	return s


def _prefix_supplier_lookup(name: str) -> str | None:
	"""Mappt LLM-Output auf einen Supplier, wenn die kürzere Variante als
	Token-Präfix oder -Suffix in der längeren enthalten ist.

	Beispiele:
	- LLM='Rida Facility Service Hohenzollerndamm 182', DB='Rida Facility Service' → Match.
	- LLM='Rida Facility Service', DB='Rida Facility Service Hohenzollerndamm 182' → Match.
	- LLM='Manfred Stobbe GmbH', DB='Manfred Stobbe' → Match.

	Längster gemeinsamer Token-Anker gewinnt — vermeidet z.B. dass 'Berlin GmbH'
	fälschlich einem Supplier 'Berlin' zugeordnet wird, wenn auch 'Berlin GmbH'
	existiert. Anker unter 6 Zeichen werden ignoriert (zu fehleranfällig: 'AG').
	"""
	if not name:
		return None
	norm = _normalize_supplier_token(name)
	if not norm:
		return None
	candidates = frappe.get_all(
		"Supplier",
		filters={"disabled": 0},
		fields=["name", "supplier_name"],
		limit_page_length=2000,
	)
	best_name = None
	best_len = 0
	for c in candidates:
		for field in (c.get("supplier_name"), c.get("name")):
			db_norm = _normalize_supplier_token(field)
			if not db_norm or len(db_norm) < 6:
				continue
			if norm == db_norm:
				return c["name"]
			# Kürzeren als Token-Anker im längeren suchen — egal in welche
			# Richtung. Kein Match mitten im String (zu fehleranfällig: 'Bau'
			# in 'Hausbau').
			short_norm, long_norm = (norm, db_norm) if len(norm) <= len(db_norm) else (db_norm, norm)
			if len(short_norm) < 6:
				continue
			if long_norm.startswith(short_norm + " ") or long_norm.endswith(" " + short_norm):
				if len(short_norm) > best_len:
					best_name = c["name"]
					best_len = len(short_norm)
	return best_name


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


KOSTENART_FUZZY_THRESHOLD = 0.55


def _fuzzy_kostenart_lookup(beschreibung: str, kostenarten: list[dict]) -> dict | None:
	"""Findet die best-passende Kostenart anhand der LLM-Beschreibung via fuzzy-Match.

	Liefert {name, umlagefaehig, score} oder None bei Score unter Threshold.
	Keine LLM-Anfrage nötig — die Kostenarten-Liste belastet den Prompt nicht mehr.
	"""
	if not beschreibung:
		return None
	target = beschreibung.lower().strip()
	best_score = 0.0
	best = None
	for k in kostenarten:
		score = SequenceMatcher(None, target, k["name"].lower().strip()).ratio()
		# Bonus wenn ein Wort der Kostenart im Description-Text vorkommt.
		first_word = k["name"].lower().split()[0] if k["name"] else ""
		if first_word and len(first_word) >= 4 and first_word in target:
			score = max(score, 0.7)
		if score > best_score:
			best_score = score
			best = k
	if best and best_score >= KOSTENART_FUZZY_THRESHOLD:
		return {
			"name": best["name"],
			"umlagefaehig": best["umlagefaehig"],
			"score": round(best_score, 2),
		}
	return None


IMMOBILIE_FUZZY_THRESHOLD = 0.55


def _fuzzy_immobilie_lookup(hinweis: str) -> dict | None:
	"""Mappt einen LLM-Adress-Hinweis auf eine Immobilie + deren Kostenstelle.

	Nutzt fuzzy-match auf Immobilie.name UND Immobilie.adresse_titel. Beide sind
	üblicherweise Straßennamen (z.B. "Wilhelmshavener", "Gropiusstr."). Bonus
	wenn der Immobilien-Name als Substring im Hinweis vorkommt — das ist sehr
	zuverlässig, weil die Hausverwaltung ihre Immobilien meist nach Straße
	benennt und Rechnungen die Straße irgendwo erwähnen.

	Liefert {name, kostenstelle, score} oder None bei zu schwachem Match.
	"""
	if not hinweis:
		return None
	target = hinweis.lower().strip()
	rows = frappe.get_all(
		"Immobilie",
		filters={"kostenstelle": ["is", "set"]},
		fields=["name", "adresse_titel", "kostenstelle"],
		limit_page_length=500,
	)
	best_score = 0.0
	best = None
	for r in rows:
		for candidate in (r.get("name"), r.get("adresse_titel")):
			if not candidate:
				continue
			cand_lower = candidate.lower().strip()
			score = SequenceMatcher(None, target, cand_lower).ratio()
			# Substring-Bonus: wenn der Immobilien-Name (oder ein Hauptwort davon)
			# direkt im Hinweis vorkommt, sind wir sehr sicher.
			first_word = cand_lower.split(".")[0].split()[0] if cand_lower else ""
			if first_word and len(first_word) >= 5 and first_word in target:
				score = max(score, 0.85)
			if score > best_score:
				best_score = score
				best = r
	if best and best_score >= IMMOBILIE_FUZZY_THRESHOLD:
		return {
			"name": best["name"],
			"kostenstelle": best["kostenstelle"],
			"score": round(best_score, 2),
		}
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

	# 2. Text extrahieren — bei force_vision skippen.
	force_vision = mistral_client.is_force_vision_enabled()
	pdf_text = "" if force_vision else _read_pdf_text(content)
	used_vision = False

	kostenarten = _load_kostenarten_for_prompt()
	suppliers = _load_suppliers_for_prompt()

	# 3. Vision-Strategie:
	#    - force_vision: immer Vision-Modell, kein pypdf-Pfad.
	#    - sonst: Text-Pfad bevorzugt; Vision-Fallback nur wenn Text leer/zu kurz UND erlaubt.
	use_vision = force_vision or (
		len(pdf_text) < MIN_TEXT_LENGTH_FOR_TEXT_MODEL
		and mistral_client.is_vision_fallback_enabled()
	)
	if use_vision:
		image_bytes = _render_pdf_first_page_png(content)
		extracted = mistral_client.complete_vision_json(
			system=SYSTEM_PROMPT_BASE,
			user_prompt=_build_vision_user_prompt(),
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
			user=_build_user_prompt(pdf_text),
		)

	# 4. Post-Processing — Lieferant.
	llm_lieferant = str(extracted.get("lieferant_name") or "").strip()
	# Wenn das Modell exakt einen Eintrag aus der Stammdaten-Liste zurückgegeben hat,
	# matchen wir direkt — sonst Fuzzy-Match als Fallback.
	matched_supplier = (
		_exact_supplier_lookup(llm_lieferant)
		or _prefix_supplier_lookup(llm_lieferant)
		or _fuzzy_supplier_lookup(llm_lieferant)
	)
	warnings: list[str] = []
	if llm_lieferant and not matched_supplier:
		warnings.append(
			f"Lieferant '{llm_lieferant}' nicht in den Stammdaten gefunden — bitte manuell wählen oder anlegen."
		)

	# 5. Kostenstelle: erst über die im PDF-Text genannte Immobilie versuchen
	#    (zuverlässiger), dann Fallback auf häufigste Kostenstelle der letzten
	#    PIs des Lieferanten.
	immobilie_hinweis = str(extracted.get("immobilie_hinweis") or "").strip()
	matched_immobilie = _fuzzy_immobilie_lookup(immobilie_hinweis) if immobilie_hinweis else None
	if matched_immobilie:
		default_kostenstelle = matched_immobilie["kostenstelle"]
	elif matched_supplier:
		default_kostenstelle = _most_common_cost_center_for_supplier(matched_supplier)
	else:
		default_kostenstelle = None
	if immobilie_hinweis and not matched_immobilie:
		warnings.append(
			f"Immobilie-Hinweis '{immobilie_hinweis[:50]}' konnte nicht auf eine Immobilie gemappt werden — "
			"bitte Kostenstelle manuell prüfen."
		)

	# 6. Positionen normalisieren — Kostenart wird backend-side via fuzzy-Match
	#    aus der Beschreibung abgeleitet, damit das LLM nicht mit Listen überfrachtet wird.
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

		beschreibung = str(raw_pos.get("beschreibung") or "").strip()

		# Kostenart NICHT automatisch zuordnen — Fuzzy-Match war zu unzuverlässig
		# (z.B. "Reparaturen Sammelwartung" → "Wartung Rauchabzugsanlage").
		# User wählt im Eingangsrechnungs-Dialog manuell aus dem Dropdown.
		pos = {
			"betrag": betrag_f,
			"beschreibung": beschreibung,
			"kostenart": "",
			"umlagefaehig": "",
			"kostenstelle": default_kostenstelle or "",
			"_confidence": 0.0,
		}
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

	# 8. Wenn kein Match: Block mit Vorschlagsdaten für Quick-Create-Dialog liefern.
	lieferant_neu: dict | None = None
	if llm_lieferant and not matched_supplier:
		lieferant_neu = {
			"supplier_name": llm_lieferant,
			"iban": str(extracted.get("lieferant_iban") or "").strip(),
			"tax_id": str(extracted.get("lieferant_steuer_id") or "").strip(),
			"strasse": str(extracted.get("lieferant_strasse") or "").strip(),
			"plz": str(extracted.get("lieferant_plz") or "").strip(),
			"ort": str(extracted.get("lieferant_ort") or "").strip(),
			"land": str(extracted.get("lieferant_land") or "").strip() or "Deutschland",
		}

	# 9. Result.
	llm_remarks = str(extracted.get("remarks_vorschlag") or "").strip()
	return {
		"fields": {
			"lieferant": matched_supplier or "",
			"rechnungsdatum": _coerce_iso_date(extracted.get("rechnungsdatum")) or "",
			"wertstellungsdatum": _coerce_iso_date(extracted.get("wertstellungsdatum")) or "",
			"rechnungsname": str(extracted.get("bill_no") or "").strip(),
			"remarks": llm_remarks[:250],
		},
		"positionen": positionen_out,
		"confidence": confidence_map,
		"warnings": warnings,
		"used_vision": used_vision,
		"raw_text": (pdf_text or "")[:MAX_RAW_TEXT_RETURN],
		"llm_lieferant": llm_lieferant,
		"lieferant_neu": lieferant_neu,
	}
