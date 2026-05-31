from __future__ import annotations

from typing import Any

import frappe
from frappe import _


SERIENBRIEF_FIELDNAME = "hv_serienbrief_vorlage"
SERIENBRIEF_WERTE_FIELDNAME = "hv_serienbrief_werte"


def sync_serienbrief_vorlage_from_dunning_type(doc, method=None) -> None:
	"""Backfill a Serienbrief Vorlage from the selected Dunning Type.

	We only fill the field when the Mahnung itself has no explicit template yet, so
	users can still override the default on a single Dunning document.
	"""
	if not frappe.db.has_column("Dunning", SERIENBRIEF_FIELDNAME):
		return

	if not doc.get("dunning_type"):
		return

	if doc.get(SERIENBRIEF_FIELDNAME):
		return

	if not frappe.db.has_column("Dunning Type", SERIENBRIEF_FIELDNAME):
		return

	template = frappe.db.get_value("Dunning Type", doc.dunning_type, SERIENBRIEF_FIELDNAME)
	if template:
		doc.set(SERIENBRIEF_FIELDNAME, template)


def _collect_werte_rows(rows) -> dict[str, dict[str, Any]]:
	werte: dict[str, dict[str, Any]] = {}
	for row in rows or []:
		name = (row.get("variable") or "").strip()
		if not name:
			continue
		werte[frappe.scrub(name)] = {"value": row.get("wert")}
	return werte


def collect_serienbrief_werte(dunning) -> dict[str, dict[str, Any]]:
	"""Sammle Serienbrief-Variablenwerte aus Dunning Type und Dunning.

	Liefert ein Mapping im selben Format wie ``variablen_werte``
	(``{scrub(variable): {"value": wert}}``), das der Serienbrief-Durchlauf in den
	Pro-Empfänger-Override (`row._iteration_variablen_werte`) mergen kann. Werte
	aus dem Dunning Type bilden den Default; Werte auf der konkreten Mahnung
	überschreiben gleichnamige Defaults.

	Defensiv: fehlende Tabelle / fehlende Spalte → ``{}``.
	``dunning`` darf ein Doc oder ein Dunning-Name (str) sein.
	"""
	dunning_type = None
	dunning_doc = None
	if isinstance(dunning, str):
		try:
			dunning_doc = frappe.get_cached_doc("Dunning", dunning)
		except frappe.DoesNotExistError:
			dunning_doc = None
	else:
		dunning_doc = dunning

	if dunning_doc:
		dunning_type = getattr(dunning_doc, "dunning_type", None)

	werte: dict[str, dict[str, Any]] = {}

	# Table-Felder haben keine Spalte am Parent — daher Meta-Check statt has_column.
	if dunning_type and frappe.get_meta("Dunning Type").get_field(SERIENBRIEF_WERTE_FIELDNAME):
		try:
			type_doc = frappe.get_cached_doc("Dunning Type", dunning_type)
		except frappe.DoesNotExistError:
			type_doc = None
		if type_doc:
			werte.update(_collect_werte_rows(type_doc.get(SERIENBRIEF_WERTE_FIELDNAME) or []))

	if dunning_doc and frappe.get_meta("Dunning").get_field(SERIENBRIEF_WERTE_FIELDNAME):
		werte.update(_collect_werte_rows(dunning_doc.get(SERIENBRIEF_WERTE_FIELDNAME) or []))

	return werte


def validate_serienbrief_werte(doc, method=None) -> None:
	"""Verhindert, dass zwei hv_serienbrief_werte-Zeilen nach frappe.scrub()
	denselben Variablennamen liefern. Sonst würden Werte stumm überschrieben
	(siehe collect_serienbrief_werte → dict-Assignment).

	Beispiele für Kollisionen: "Frist Tage" + "frist_tage", "Ueberschrift" +
	"Überschrift". Beide werden zu "frist_tage" bzw. "ueberschrift" — der zweite
	Eintrag gewänne stumm.
	"""
	rows = doc.get(SERIENBRIEF_WERTE_FIELDNAME) or []
	seen: dict[str, list[tuple[int, str]]] = {}
	for row in rows:
		name = (getattr(row, "variable", None) or "").strip()
		if not name:
			continue
		key = frappe.scrub(name)
		seen.setdefault(key, []).append((getattr(row, "idx", 0), name))

	duplicates = [(key, occ) for key, occ in seen.items() if len(occ) > 1]
	if not duplicates:
		return

	parts = []
	for key, occ in duplicates:
		labels = ", ".join(f"#{idx} „{name}\"" for idx, name in occ)
		parts.append(f"<li><code>{key}</code> ({labels})</li>")
	frappe.throw(
		_(
			"Im Feld <strong>Serienbrief-Werte</strong> gibt es Variablen, "
			"die nach Normalisierung identisch sind und sich gegenseitig "
			"stumm überschreiben würden:<ul>{0}</ul>"
			"Bitte jede Variable nur einmal vergeben."
		).format("".join(parts)),
		title=_("Doppelte Variablen"),
	)


def validate_dunning_type_serienbrief_werte(doc, method=None) -> None:
	validate_serienbrief_werte(doc, method=method)


def validate_dunning(doc, method=None) -> None:
	sync_serienbrief_vorlage_from_dunning_type(doc, method=method)
	validate_serienbrief_werte(doc, method=method)
