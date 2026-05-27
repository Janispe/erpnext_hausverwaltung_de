"""Migration: serienbrief.werte.X-Tokens in Vorlagen → top-level X.

Bisher gab es zwei Token-Styles fuer Vorlagen-Variablen:
- ``{{ X }}`` (top-level, vom Editor erzeugt, kanonisch)
- ``{{ serienbrief.werte.X }}`` (gruppierter Namespace, einige
  handgeschriebene Vorlagen — u.a. die konsolidierte Mahn-Vorlage)

Der Render-Code legt Werte nur top-level ab; der zweite Style lief
ueberall auf None und liess den ``Wert ist None``-finalize-Hook werfen.
Statt beide Styles dauerhaft per Spiegelung zu unterstuetzen, migrieren
wir hier alle Bestandsvorlagen auf den top-level Token-Style.

Idempotent: ein Re-Run findet keine matching Tokens mehr und macht nichts.
"""

from __future__ import annotations

import re

import frappe
from frappe.utils import cstr


# Global ``serienbrief.werte.<key>`` → ``<key>``. Matched sowohl in
# Output-Expressions ``{{ ... }}`` als auch in Statements wie
# ``{% if serienbrief.werte.X %}`` und ``{% set y = serienbrief.werte.X | int %}``.
# Ein global-Replace ist hier sicher, weil ``serienbrief.werte.X`` als
# Literal-Text ausserhalb Jinja praktisch nicht vorkommt (kein HTML-
# Attribut benutzt diesen Pfad).
_TOKEN_RE = re.compile(
	r"\bserienbrief\s*\.\s*werte\s*\.\s*([a-zA-Z_][a-zA-Z0-9_]*)"
)

# Felder, die Jinja-Source enthalten koennen.
_TEMPLATE_FIELDS = ("content", "html_content", "jinja_content")

# Auch Bausteine koennen den Style verwendet haben.
# (Schema-Unterschied: Vorlage hat ``content``, Baustein hat ``text_content``.)
_BAUSTEIN_FIELDS = ("text_content", "html_content", "jinja_content")


def _migrate_source(source: str) -> tuple[str, int]:
	"""Ersetzt ``serienbrief.werte.X`` durch ``X`` an allen Stellen im
	Jinja-Source (Output-Expressions UND Statements). Liefert
	(neuer Source, Anzahl Ersetzungen)."""
	if not source or "serienbrief.werte." not in source:
		return source, 0
	count = 0

	def _sub(m: re.Match) -> str:
		nonlocal count
		count += 1
		return m.group(1)

	new_source = _TOKEN_RE.sub(_sub, source)
	return new_source, count


def _migrate_doctype(doctype: str, fields: tuple[str, ...]) -> tuple[int, list[str]]:
	"""Returns (total_token_count, list_of_doc_names_with_changes)."""
	total = 0
	touched: list[str] = []
	for name in frappe.get_all(doctype, pluck="name"):
		changes: dict[str, str] = {}
		for fieldname in fields:
			if not frappe.get_meta(doctype).has_field(fieldname):
				continue
			current = cstr(frappe.db.get_value(doctype, name, fieldname) or "")
			new, count = _migrate_source(current)
			if count and new != current:
				changes[fieldname] = new
				total += count
		if changes:
			frappe.db.set_value(doctype, name, changes, update_modified=False)
			touched.append(name)
			print(f"  {doctype} {name}: {len(changes)} Felder migriert")
	return total, touched


def _force_optional_variables(template_names: list[str]) -> int:
	"""Setzt alle deklarierten Variablen der gegebenen Vorlagen auf optional=1.

	Hintergrund: Vorlagen, die ``serienbrief.werte.X`` in ``{% if %}``-Statements
	nutzten, evaluierten dort stillschweigend zu ``None`` → ``False``. Nach
	der Token-Migration zu ``{% if X %}`` greift jedoch ``_verify_template_
	variables_resolved`` und wirft, wenn die Variable nicht gesetzt ist (z.B.
	im Browser-Preview ohne Empfaenger-Override). ``optional=1`` lockert
	diesen Check und legt einen leeren String ins Context — ``{% if %}`` geht
	dann sauber den else-Branch.
	"""
	if not template_names:
		return 0
	count = 0
	for tpl in template_names:
		for row_name in frappe.get_all(
			"Serienbrief Vorlage Variable",
			filters={"parent": tpl, "optional": 0},
			pluck="name",
		):
			frappe.db.set_value(
				"Serienbrief Vorlage Variable", row_name, "optional", 1,
				update_modified=False,
			)
			count += 1
		if count:
			print(f"  Serienbrief Vorlage {tpl}: Variablen auf optional=1 gesetzt")
	return count


def execute() -> None:
	tpl_count, touched_templates = _migrate_doctype("Serienbrief Vorlage", _TEMPLATE_FIELDS)
	bs_count, _ = _migrate_doctype("Serienbrief Textbaustein", _BAUSTEIN_FIELDS)
	opt_count = _force_optional_variables(touched_templates)
	print(
		f"migrate_serienbrief_werte_token_to_toplevel: "
		f"{tpl_count} Tokens in Vorlagen, {bs_count} Tokens in Bausteinen migriert, "
		f"{opt_count} Variablen auf optional=1 gesetzt."
	)
