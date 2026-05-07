"""Migration zur Platzhalter-Notation ``{{$ pfad $}}`` und deklarativen
Bausteinen.

Idempotent — kann beliebig oft laufen, macht nur was die Datenlage verlangt:

1. Bauseite-Tokens: alle reinen ``{{ X.Y.Z }}``-Pfade in Vorlagen + Bausteinen
   auf ``{{$ X.Y.Z $}}`` umschreiben (außer Tokens mit Logik/Filter/``or``).
2. Bausteine ``Bankverbindung Immobilie`` und ``MieterAnredeNameAlle``:
   Variable + Standardpfade + Body deklarativ machen, sodass Iterations-
   Doctype-aware mit dem Resolver gerendert wird.
3. Bausteine ``BK-Abrechnung-Einleitung``, ``BK-Abrechnung-Schluss``,
   ``Miethistorie``: Body so anpassen, dass das alte ``set objekt = ...``-
   Konstrukt durch die deklarierte Block-Variable ersetzt wird.
"""

from __future__ import annotations

import json
import re

import frappe


# Matcht: ``{{ A.B.C }}`` mit reinen Punkt-Pfaden, optionalen ``[<digit>]``-
# Indices, KEINE Operatoren / Filter. Negativ-Lookahead ``(?!\$)`` verhindert,
# dass schon migrierte ``{{$ ... $}}``-Tokens erneut gewrappt werden.
_SIMPLE_PATH_RE = re.compile(
	r"\{\{(?!\$)\s*"
	r"([a-zA-Z_][\w]*(?:\[\d+\])?(?:\.[a-zA-Z_][\w]*(?:\[\d+\])?)+)"
	r"\s*\}\}"
)


# === Baustein-Bodies (deklarativ neu) ====================================

BANKVERBINDUNG_BODY = """\
{%- if not immobilie.bank_konto -%}
{{ frappe.throw("Bankverbindung-Baustein: Immobilie " ~ immobilie.name ~ " hat kein Hauptkonto mit Bank-Account-Link — bitte unter Immobilie ▸ Bankkonten ein Hauptkonto pflegen, dessen Account einen verknüpften Bank-Account hat.") }}
{%- endif -%}
<p>Bankverbindung: {{ immobilie.bank_konto.account_name }} · IBAN {{ immobilie.bank_konto.iban }} · {{ immobilie.bank_konto.bank }}</p>
"""

MIETER_ANREDE_BODY = """\
{%- macro _person_line(p) -%}
{%- set sal = (p.salutation or '') -%}
{%- set last = (p.last_name or '') -%}
{%- if sal == 'Herr' -%}
{%- set greet = 'Sehr geehrter Herr' -%}
{%- elif sal == 'Frau' -%}
{%- set greet = 'Sehr geehrte Frau' -%}
{%- else -%}
{%- set greet = sal -%}
{%- endif -%}
{{ (greet ~ (' ' if greet and last else '') ~ last ~ (',' if greet or last else ''))|replace('  ', ' ')|trim }}
{%- endmacro -%}
{%- set sep = (sep if sep is defined else '<br/>') -%}
{%- set personen = [] -%}
{%- for vp in (mietvertrag.mieter or []) -%}
{%- if vp.kontakt -%}{%- set _ = personen.append(vp.kontakt) -%}{%- endif -%}
{%- endfor -%}
{%- if not personen -%}
{{ frappe.throw("Mietvertrag " ~ mietvertrag.name ~ " hat keine Vertragspartner mit Contact-Verknüpfung — die Anrede kann nicht generiert werden. Bitte unter Mietvertrag → Mieter mindestens einen Vertragspartner mit gepflegtem Mieter-Contact ergänzen.") }}
{%- endif -%}
{%- for p in personen -%}
{{ _person_line(p) }}{% if not loop.last %}{{ sep | safe }}{% endif %}
{%- endfor -%}
"""


def _migrate_text_to_placeholder_tokens(text: str) -> tuple[str, int]:
	"""Wrap ``{{ X.Y.Z }}``-Pfade in ``{{$ X.Y.Z $}}``. Idempotent."""
	if not text or "{{" not in text:
		return text, 0
	count = 0

	def _replace(m: "re.Match[str]") -> str:
		nonlocal count
		count += 1
		return f"{{{{$ {m.group(1)} $}}}}"

	new_text = _SIMPLE_PATH_RE.sub(_replace, text)
	return new_text, count


def _ensure_variable(doc, variable: str, label: str, reference_doctype: str) -> bool:
	"""Idempotent: Variable mit Doctype-Reference ergänzen, falls nicht vorhanden."""
	for row in doc.get("variables") or []:
		if (row.variable or "").strip() == variable:
			return False
	doc.append(
		"variables",
		{
			"variable": variable,
			"label": label,
			"variable_type": "Doctype",
			"reference_doctype": reference_doctype,
		},
	)
	return True


def _ensure_standardpfad(doc, startobjekt: str, mapping: dict[str, str]) -> bool:
	"""Idempotent: Standardpfad-Row für (Baustein × startobjekt) mergen."""
	existing = next(
		(p for p in (doc.get("standardpfade") or []) if (p.startobjekt or "").strip() == startobjekt),
		None,
	)
	if existing is None:
		doc.append(
			"standardpfade",
			{
				"startobjekt": startobjekt,
				"pfad_zuordnung": json.dumps(mapping, ensure_ascii=False),
			},
		)
		return True
	current = {}
	try:
		current = json.loads(existing.pfad_zuordnung or "{}")
	except Exception:
		current = {}
	merged = dict(current)
	merged.update(mapping)
	if merged == current:
		return False
	existing.pfad_zuordnung = json.dumps(merged, ensure_ascii=False)
	return True


def _patch_baustein(name: str, *, html_content: str | None = None, body_replacements: list[tuple[str, str]] | None = None,
                    variables: list[tuple[str, str, str]] | None = None,
                    standardpfade: list[tuple[str, dict[str, str]]] | None = None) -> bool:
	if not frappe.db.exists("Serienbrief Textbaustein", name):
		return False
	doc = frappe.get_doc("Serienbrief Textbaustein", name)
	changed = False

	for variable, label, ref_dt in (variables or []):
		if _ensure_variable(doc, variable, label, ref_dt):
			changed = True

	for startobjekt, mapping in (standardpfade or []):
		if _ensure_standardpfad(doc, startobjekt, mapping):
			changed = True

	if html_content is not None and (doc.html_content or "").strip() != html_content.strip():
		doc.html_content = html_content
		doc.jinja_content = None
		changed = True

	for old, new in (body_replacements or []):
		for field in ("html_content", "jinja_content"):
			value = getattr(doc, field, None) or ""
			if value and old in value:
				setattr(doc, field, value.replace(old, new))
				changed = True

	if changed:
		doc.save(ignore_permissions=True)
	return changed


def execute() -> None:
	# 1) Bankverbindung Immobilie — deklarativ machen
	_patch_baustein(
		"Bankverbindung Immobilie",
		html_content=BANKVERBINDUNG_BODY,
		variables=[("immobilie", "Immobilie", "Immobilie")],
		standardpfade=[("Mietvertrag", {"immobilie": "objekt.wohnung.immobilie"})],
	)

	# 2) MieterAnredeNameAlle — deklarativ + throw bei leerer Personen-Liste
	_patch_baustein(
		"MieterAnredeNameAlle",
		html_content=MIETER_ANREDE_BODY,
		variables=[("mietvertrag", "Mietvertrag", "Mietvertrag")],
		standardpfade=[
			("Mietvertrag", {"mietvertrag": "__self__"}),
			("Betriebskostenabrechnung Mieter", {"mietvertrag": "objekt.mietvertrag"}),
		],
	)

	# 3) BK-Abrechnung-Einleitung / -Schluss — alten ``set objekt``-Hack
	#    durch die deklarierte Block-Variable ersetzen.
	for name in ("BK-Abrechnung-Einleitung", "BK-Abrechnung-Schluss"):
		_patch_baustein(
			name,
			body_replacements=[
				(
					"{%- set objekt = objekt or objekt or objekt -%}",
					"{%- set objekt = betriebskostenabrechnung_mieter -%}",
				),
			],
		)

	# 4) Miethistorie — alten ``set mv``-Hack durch die deklarierte
	#    Block-Variable ersetzen.
	_patch_baustein(
		"Miethistorie",
		body_replacements=[
			("{% set mv = objekt or objekt %}", "{% set mv = mietvertrag %}"),
		],
	)

	# 5) Token-Migration für alle Vorlagen + Bausteine — reine Pfade
	#    auf ``{{$ ... $}}`` umschreiben.
	for v in frappe.get_all("Serienbrief Vorlage", fields=["name", "content"]):
		new_content, n = _migrate_text_to_placeholder_tokens(v.content or "")
		if n > 0:
			frappe.db.set_value(
				"Serienbrief Vorlage", v.name, "content", new_content, update_modified=False
			)

	for b in frappe.get_all(
		"Serienbrief Textbaustein",
		fields=["name", "jinja_content", "html_content"],
	):
		updates: dict[str, str] = {}
		for field in ("jinja_content", "html_content"):
			text = getattr(b, field, None) or ""
			new_text, n = _migrate_text_to_placeholder_tokens(text)
			if n > 0:
				updates[field] = new_text
		if updates:
			frappe.db.set_value(
				"Serienbrief Textbaustein", b.name, updates, update_modified=False
			)

	frappe.db.commit()
