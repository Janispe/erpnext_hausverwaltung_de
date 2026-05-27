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


def _migrate_source(source: str) -> tuple[str, int, set[str]]:
	"""Ersetzt ``serienbrief.werte.X`` durch ``X`` an allen Stellen im
	Jinja-Source (Output-Expressions UND Statements). Liefert
	(neuer Source, Anzahl Ersetzungen, set der migrierten Variablen-Namen).
	Fast-Path nur auf den unverkennbaren Teil-Strings; die Regex toleriert
	Whitespace zwischen den Punkten und matched dann auch im Fast-Path-Pfad.
	"""
	if not source or "serienbrief" not in source or "werte" not in source:
		return source, 0, set()
	count = 0
	keys: set[str] = set()

	def _sub(m: re.Match) -> str:
		nonlocal count
		count += 1
		key = m.group(1)
		keys.add(key)
		return key

	new_source = _TOKEN_RE.sub(_sub, source)
	return new_source, count, keys


def _migrate_doctype(
	doctype: str, fields: tuple[str, ...]
) -> tuple[int, dict[str, set[str]]]:
	"""Returns (total_token_count, dict mapping doc_name -> migrated variable
	keys for that doc)."""
	total = 0
	touched: dict[str, set[str]] = {}
	for name in frappe.get_all(doctype, pluck="name"):
		changes: dict[str, str] = {}
		doc_keys: set[str] = set()
		for fieldname in fields:
			if not frappe.get_meta(doctype).has_field(fieldname):
				continue
			current = cstr(frappe.db.get_value(doctype, name, fieldname) or "")
			new, count, keys = _migrate_source(current)
			if count and new != current:
				changes[fieldname] = new
				total += count
				doc_keys.update(keys)
		if changes:
			frappe.db.set_value(doctype, name, changes, update_modified=False)
			touched[name] = doc_keys
			print(f"  {doctype} {name}: {len(changes)} Felder, Keys: {sorted(doc_keys)}")
	return total, touched


def _force_optional_for_migrated_keys(touched: dict[str, set[str]]) -> int:
	"""Setzt fuer jede migrierte Vorlage genau die Variablen optional=1, deren
	Tokens migriert wurden. Andere Pflicht-Variablen bleiben strict.

	Hintergrund: Vorlagen, die ``serienbrief.werte.X`` in ``{% if %}``-Statements
	nutzten, evaluierten dort stillschweigend zu ``None`` → ``False``. Nach
	der Token-Migration zu ``{% if X %}`` greift jedoch ``_verify_template_
	variables_resolved`` und wirft, wenn die Variable nicht gesetzt ist (z.B.
	im Browser-Preview ohne Empfaenger-Override). ``optional=1`` lockert
	diesen Check fuer GENAU diese Keys und legt einen leeren String ins
	Context — ``{% if %}`` geht dann sauber den else-Branch.

	Wichtig: wir setzen nicht pauschal alle Variablen der Vorlage optional —
	das wuerde echte Pflicht-Variablen still in leere Strings verwandeln und
	fehlende Daten im Render verstecken.
	"""
	if not touched:
		return 0
	count = 0
	for tpl, keys in touched.items():
		if not keys:
			continue
		for row in frappe.get_all(
			"Serienbrief Vorlage Variable",
			filters={"parent": tpl, "optional": 0},
			fields=["name", "variable"],
		):
			# scrub-vergleich, weil _force_optional_variables historisch mit
			# scrub(variable) operiert hat — keine Sicherheit dass die Editor-
			# gepflegten variable-namen schon gescrubbt sind.
			vkey = frappe.scrub(cstr(row.get("variable") or ""))
			if vkey in keys:
				frappe.db.set_value(
					"Serienbrief Vorlage Variable", row["name"], "optional", 1,
					update_modified=False,
				)
				count += 1
				print(f"    -> {tpl}: {row.get('variable')} optional=1")
	return count


def execute() -> None:
	tpl_count, touched_templates = _migrate_doctype("Serienbrief Vorlage", _TEMPLATE_FIELDS)
	bs_count, _ = _migrate_doctype("Serienbrief Textbaustein", _BAUSTEIN_FIELDS)
	opt_count = _force_optional_for_migrated_keys(touched_templates)
	print(
		f"migrate_serienbrief_werte_token_to_toplevel: "
		f"{tpl_count} Tokens in Vorlagen, {bs_count} Tokens in Bausteinen migriert, "
		f"{opt_count} Variablen gezielt auf optional=1 gesetzt."
	)
