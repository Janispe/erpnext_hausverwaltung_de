from __future__ import annotations

import re

import frappe
from frappe.utils import cstr


# Reihenfolge ist relevant: längere/spezifischere Tokens VOR kürzeren stehen,
# damit z.B. ``mieter_strasse`` ersetzt wird bevor ``mieter`` greift.
FIELD_REPLACEMENTS = {
	# Mieter (zuerst die spezifischen Composite-Tokens, dann der bare-Token)
	"mieter_strasse": "objekt.kunde.briefanschrift.address_line1",
	"mieter_plz_ort": "objekt.kunde.briefanschrift.plz_ort",
	"mieter_plz": "objekt.kunde.briefanschrift.pincode",
	"mieter_ort": "objekt.kunde.briefanschrift.city",
	"mieter_adresse": "objekt.kunde.briefanschrift.adresse",
	"mieter_name": "objekt.kunde.customer_name",
	"mieter_doc": "objekt.kunde",
	"mieter": "objekt.kunde",
	# Wohnung
	"wohnung_groesse": "objekt.wohnung.zustand_aktuell.größe",
	"wohnung_anzahl_zimmer": "objekt.wohnung.zustand_aktuell.anzahl_zimmer",
	"wohnung_bezeichnung": "objekt.wohnung.name__lage_in_der_immobilie",
	"wohnung_doc": "objekt.wohnung",
	"wohnung": "objekt.wohnung",
	# Immobilie — Adresse + composite via Address-Properties (plz_ort/adresse)
	"immobilie_strasse": "objekt.wohnung.immobilie.address.address_line1",
	"immobilie_plz_ort": "objekt.wohnung.immobilie.address.plz_ort",
	"immobilie_plz": "objekt.wohnung.immobilie.address.pincode",
	"immobilie_ort": "objekt.wohnung.immobilie.address.city",
	"immobilie_adresse": "objekt.wohnung.immobilie.address.adresse",
	"immobilie_doc": "objekt.wohnung.immobilie",
	"immobilie": "objekt.wohnung.immobilie",
	# Eigentümer (= Contact-Doc auf Immobilie)
	"eigentuemer_strasse": "objekt.wohnung.immobilie.eigentuemer.address.address_line1",
	"eigentuemer_plz_ort": "objekt.wohnung.immobilie.eigentuemer.address.plz_ort",
	"eigentuemer_plz": "objekt.wohnung.immobilie.eigentuemer.address.pincode",
	"eigentuemer_ort": "objekt.wohnung.immobilie.eigentuemer.address.city",
	"eigentuemer_adresse": "objekt.wohnung.immobilie.eigentuemer.address.adresse",
	"eigentuemer_doc": "objekt.wohnung.immobilie.eigentuemer",
	"eigentuemer": "objekt.wohnung.immobilie.eigentuemer",
	# Bank-Daten (Hauptkonto der Immobilie via Bank Account-Doc)
	"bank_iban": "objekt.wohnung.immobilie.bank_konto.iban",
	"bank_bic": "objekt.wohnung.immobilie.bank_konto.bic",
	"bank_blz": "objekt.wohnung.immobilie.bank_konto.branch_code",
	"bank_kto_inhaber": "objekt.wohnung.immobilie.bank_konto.account_name",
	"bank_konto": "objekt.wohnung.immobilie.bank_konto.account_name",
	"bank_name": "objekt.wohnung.immobilie.bank_konto.bank",
	# Vorauszahlungen — 1-basierter Slot-Index via Property-Liste
	"vorauszahlung_1_netto": "objekt.vorauszahlung_slots[1]",
	"vorauszahlung_2_netto": "objekt.vorauszahlung_slots[2]",
	"vorauszahlung_3_netto": "objekt.vorauszahlung_slots[3]",
	"vorauszahlung_4_netto": "objekt.vorauszahlung_slots[4]",
	"vorauszahlung_1": "objekt.vorauszahlung_slots[1]",
	"vorauszahlung_2": "objekt.vorauszahlung_slots[2]",
	"vorauszahlung_3": "objekt.vorauszahlung_slots[3]",
	"vorauszahlung_4": "objekt.vorauszahlung_slots[4]",
	# Mietvertrag-Aliase
	"mietvertrag_doc": "objekt",
	"mietvertrag": "objekt",
	# Run-Metadaten
	"empfaenger_anzeigename": "objekt.name",
	"empfaenger_index": "serienbrief.index",
	"empfaenger_count": "serienbrief.count",
	"serienbrief_titel": "serienbrief.titel",
	# Generic ``doc`` / ``iteration_doc`` zuletzt — andere Replacements könnten
	# Token enthalten, die ``doc`` als Substring haben (haben sie aktuell nicht,
	# aber Reihenfolge ist verteidigbar).
	"iteration_objekt": "objekt",
	"iteration_doc": "objekt",
	"doc": "objekt",
}

# Tokens, deren Verbleiben nach der Migration verdächtig ist und ge-loggt
# werden soll — typischerweise weil der Vorlagen-Schreiber sie in
# nicht-Standard-Konstruktionen verwendet hat (z.B. ``mieter|some_filter``).
LEGACY_ROOTS = {
	"empfaenger_data",
	"wohnung_bezeichnung",
	"immobilie_bezeichnung",
	"eigentuemer_saldo",
}


def execute():
	_backfill_baustein_keys()
	_migrate_template_sources()
	_migrate_block_sources()
	_drop_legacy_reference_doctype()


def _replace_known_roots(source: str | None) -> tuple[str | None, bool]:
	if not source:
		return source, False
	updated = source
	for old, new in FIELD_REPLACEMENTS.items():
		# (?<![\w.]): vor dem Token darf weder ein Wort-Char noch ein Punkt
		# stehen — verhindert dass z.B. ``objekt.mieter[0]`` zu
		# ``objekt.objekt.kunde[0]`` umgeschrieben wird, wenn der Replacer
		# ``mieter`` als Root-Token ersetzt.
		# \b nach dem Token: matched nur ganze Wörter, also greift
		# ``mieter`` nicht in ``mieter_strasse``.
		updated = re.sub(rf"(?<![\w.]){re.escape(old)}\b", new, updated)
	return updated, updated != source


def _log_legacy_roots(owner: str, fieldname: str, source: str | None) -> None:
	if not source:
		return
	found = sorted(root for root in LEGACY_ROOTS if re.search(rf"\b{re.escape(root)}\b", source))
	if not found:
		return
	frappe.log_error(
		title="Serienbrief Legacy-Kontext Migration",
		message=(
			f"{owner}.{fieldname} enthält nach der Best-effort-Migration noch "
			f"Legacy-Root-Variablen: {', '.join(found)}"
		),
	)


def _backfill_baustein_keys() -> None:
	rows = frappe.get_all(
		"Serienbrief Vorlagenbaustein",
		fields=["name", "parent", "baustein", "baustein_key", "idx"],
		order_by="parent asc, idx asc",
	)
	seen_by_parent: dict[str, dict[str, int]] = {}
	for row in rows:
		if cstr(row.baustein_key).strip() or not cstr(row.baustein).strip():
			continue
		seen = seen_by_parent.setdefault(row.parent, {})
		base = frappe.scrub(row.baustein) or "baustein"
		seen[base] = seen.get(base, 0) + 1
		key = base if seen[base] == 1 else f"{base}_{seen[base]}"
		frappe.db.set_value("Serienbrief Vorlagenbaustein", row.name, "baustein_key", key, update_modified=False)


def _migrate_template_sources() -> None:
	for row in frappe.get_all(
		"Serienbrief Vorlage",
		fields=["name", "content", "html_content", "jinja_content"],
	):
		updates = {}
		for fieldname in ("content", "html_content", "jinja_content"):
			updated, changed = _replace_known_roots(row.get(fieldname))
			if changed:
				updates[fieldname] = updated
			_log_legacy_roots(f"Serienbrief Vorlage {row.name}", fieldname, updated)
		if updates:
			frappe.db.set_value("Serienbrief Vorlage", row.name, updates, update_modified=False)


def _migrate_block_sources() -> None:
	for row in frappe.get_all(
		"Serienbrief Textbaustein",
		fields=["name", "text_content", "html_content", "jinja_content"],
	):
		updates = {}
		for fieldname in ("text_content", "html_content", "jinja_content"):
			updated, changed = _replace_known_roots(row.get(fieldname))
			if changed:
				updates[fieldname] = updated
			_log_legacy_roots(f"Serienbrief Textbaustein {row.name}", fieldname, updated)
		if updates:
			frappe.db.set_value("Serienbrief Textbaustein", row.name, updates, update_modified=False)


def _drop_legacy_reference_doctype() -> None:
	if not frappe.db.exists("DocType", "Serienbrief Textbaustein Referenz"):
		return
	try:
		frappe.delete_doc(
			"DocType",
			"Serienbrief Textbaustein Referenz",
			force=True,
			ignore_permissions=True,
		)
	except Exception:
		frappe.log_error(
			title="Serienbrief Legacy-Referenz Doctype entfernen",
			message=frappe.get_traceback(),
		)
