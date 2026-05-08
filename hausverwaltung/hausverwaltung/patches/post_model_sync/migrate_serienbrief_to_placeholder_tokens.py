"""Migration zur Platzhalter-Notation ``{{$ pfad $}}`` und deklarativen
Bausteinen.

Idempotent — kann beliebig oft laufen, macht nur was die Datenlage verlangt:

1. Datentokens mit altem Root wie ``{{ iteration_doc.X }}`` in Vorlagen +
   Bausteinen auf ``{{$ objekt.X $}}`` umschreiben (außer Tokens mit
   Logik/Filter/``or``).
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
# Indices, KEINE Operatoren / Filter. Die Migration ersetzt nur offizielle
# Daten-Roots; lokale Jinja-Variablen und deklarierte Block-Inputs bleiben
# Jinja.
_SIMPLE_PATH_RE = re.compile(
	r"\{\{(?!\$)\s*"
	r"([a-zA-Z_][\w]*(?:\[\d+\])?(?:\.[a-zA-Z_][\w]*(?:\[\d+\])?)+)"
	r"\s*\}\}"
)
_PLACEHOLDER_PATH_RE = re.compile(r"\{\{\s*\$\s*([^{}]+?)\s*\$\s*\}\}")
_MIGRATABLE_BODY_ROOTS = {"iteration_doc", "iteration_objekt", "doc", "objekt"}
_RAW_PATH_RE = re.compile(
	r"^(?:iteration_doc|iteration_objekt|doc)(?:\[\d+\])?"
	r"(?:\.[a-zA-Z_][\w]*(?:\[\d+\])?)*"
	r"(?:\[\])?$"
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
	"""Alte Daten-Root-Pfade in ``{{$ objekt.X $}}`` migrieren. Idempotent."""
	if not text or "{{" not in text:
		return text, 0
	count = 0

	def _replace_existing(m: "re.Match[str]") -> str:
		nonlocal count
		old_path = m.group(1).strip()
		new_path = _normalize_path_root(old_path)
		if new_path != old_path:
			count += 1
		return f"{{{{$ {new_path} $}}}}"

	def _replace(m: "re.Match[str]") -> str:
		nonlocal count
		path = m.group(1).strip()
		root = re.split(r"[\.\[]", path, maxsplit=1)[0]
		if root not in _MIGRATABLE_BODY_ROOTS:
			return m.group(0)
		count += 1
		return f"{{{{$ {_normalize_path_root(path)} $}}}}"

	new_text = _PLACEHOLDER_PATH_RE.sub(_replace_existing, text)
	new_text = _SIMPLE_PATH_RE.sub(_replace, new_text)
	return new_text, count


def _normalize_path_root(path: str) -> str:
	"""Alte Iterationsdaten-Roots auf den offiziellen ``objekt``-Root umstellen."""
	value = (path or "").strip()
	for legacy in ("iteration_doc", "iteration_objekt", "doc"):
		if value == legacy:
			return "objekt"
		if value.startswith(f"{legacy}."):
			return f"objekt.{value[len(legacy) + 1:]}"
		if value.startswith(f"{legacy}["):
			return f"objekt{value[len(legacy):]}"
	return value


def _looks_like_path(value: str) -> bool:
	value = (value or "").strip()
	return bool(_RAW_PATH_RE.match(value))


def _migrate_path_string(value: str) -> tuple[str, bool]:
	if not isinstance(value, str):
		return value, False
	raw = value.strip()
	if not raw or raw == "__self__":
		return value, False
	if raw.startswith("{{"):
		match = _PLACEHOLDER_PATH_RE.match(raw) or _SIMPLE_PATH_RE.match(raw)
		if not match:
			return value, False
		normalized = _normalize_path_root(match.group(1))
		return normalized, normalized != value
	if not _looks_like_path(raw):
		return value, False
	normalized = _normalize_path_root(raw)
	return normalized, normalized != value


def _migrate_path_payload(value, *, path_keys: set[str] | None = None, current_key: str | None = None):
	changed = False
	if isinstance(value, str):
		if path_keys is not None and current_key not in path_keys:
			return value, False
		return _migrate_path_string(value)
	if isinstance(value, list):
		new_items = []
		for item in value:
			new_item, item_changed = _migrate_path_payload(item, path_keys=path_keys)
			new_items.append(new_item)
			changed = changed or item_changed
		return new_items, changed
	if isinstance(value, dict):
		new_data = {}
		for key, item in value.items():
			new_item, item_changed = _migrate_path_payload(
				item, path_keys=path_keys, current_key=str(key)
			)
			new_data[key] = new_item
			changed = changed or item_changed
		return new_data, changed
	return value, False


def _migrate_json_field(
	raw: str | None, *, path_keys: set[str] | None = None
) -> tuple[str | None, bool]:
	if not raw:
		return raw, False
	try:
		data = json.loads(raw)
	except Exception:
		new_value, changed = _migrate_path_string(raw)
		return new_value, changed
	new_data, changed = _migrate_path_payload(data, path_keys=path_keys)
	if not changed:
		return raw, False
	return json.dumps(new_data, ensure_ascii=False), True


def _existing_fields(doctype: str, candidates: tuple[str, ...]) -> list[str]:
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return []
	return [field for field in candidates if meta.has_field(field)]


def _migrate_text_fields(doctype: str, candidates: tuple[str, ...]) -> None:
	fields = _existing_fields(doctype, candidates)
	if not fields:
		return
	for row in frappe.get_all(doctype, fields=["name", *fields]):
		updates: dict[str, str] = {}
		for field in fields:
			text = getattr(row, field, None) or ""
			new_text, n = _migrate_text_to_placeholder_tokens(text)
			if n > 0:
				updates[field] = new_text
		if updates:
			frappe.db.set_value(doctype, row.name, updates, update_modified=False)


def _migrate_json_path_fields(
	doctype: str, candidates: tuple[str, ...], *, path_keys: set[str] | None = None
) -> None:
	fields = _existing_fields(doctype, candidates)
	if not fields:
		return
	for row in frappe.get_all(doctype, fields=["name", *fields]):
		updates: dict[str, str] = {}
		for field in fields:
			raw = getattr(row, field, None)
			new_raw, changed = _migrate_json_field(raw, path_keys=path_keys)
			if changed:
				updates[field] = new_raw
		if updates:
			frappe.db.set_value(doctype, row.name, updates, update_modified=False)


def _ensure_variable(
	doc,
	variable: str,
	label: str,
	reference_doctype: str,
	variable_type: str = "Doctype",
) -> bool:
	"""Idempotent: Variable mit Doctype-Reference ergänzen, falls nicht vorhanden.

	Wenn schon eine Variable mit dem Namen existiert (egal welcher Typ),
	wird sie auf den geforderten Typ + reference_doctype upgegradet, falls
	abweichend.
	"""
	for row in doc.get("variables") or []:
		if frappe.scrub((row.variable or "").strip()) != frappe.scrub(variable):
			continue
		changed = False
		if (row.variable or "").strip() != variable:
			row.variable = variable
			changed = True
		if (row.variable_type or "").strip() != variable_type:
			row.variable_type = variable_type
			changed = True
		if (row.reference_doctype or "").strip() != reference_doctype:
			row.reference_doctype = reference_doctype
			changed = True
		return changed
	doc.append(
		"variables",
		{
			"variable": variable,
			"label": label,
			"variable_type": variable_type,
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


def _patch_baustein(
	name: str,
	*,
	html_content: str | None = None,
	body_replacements: list[tuple[str, str]] | None = None,
	body_regex_replacements: list[tuple[str, str]] | None = None,
	variables: list[tuple[str, str, str, str]] | None = None,
	standardpfade: list[tuple[str, dict[str, str]]] | None = None,
) -> bool:
	"""variables-Tuple: ``(variable, label, reference_doctype, variable_type)``."""
	if not frappe.db.exists("Serienbrief Textbaustein", name):
		return False
	doc = frappe.get_doc("Serienbrief Textbaustein", name)
	changed = False

	for variable, label, ref_dt, var_type in (variables or []):
		if _ensure_variable(doc, variable, label, ref_dt, variable_type=var_type):
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

	for pattern, replacement in (body_regex_replacements or []):
		for field in ("html_content", "jinja_content"):
			value = getattr(doc, field, None) or ""
			if not value:
				continue
			new_value = re.sub(pattern, replacement, value)
			if new_value != value:
				setattr(doc, field, new_value)
				changed = True

	if changed:
		doc.save(ignore_permissions=True)
	return changed


def execute() -> None:
	# 1) Bankverbindung Immobilie — deklarativ machen
	_patch_baustein(
		"Bankverbindung Immobilie",
		html_content=BANKVERBINDUNG_BODY,
		variables=[("immobilie", "Immobilie", "Immobilie", "Doctype")],
		standardpfade=[("Mietvertrag", {"immobilie": "objekt.wohnung.immobilie"})],
	)

	# 2) MieterAnredeNameAlle — deklarativ + throw bei leerer Personen-Liste
	_patch_baustein(
		"MieterAnredeNameAlle",
		html_content=MIETER_ANREDE_BODY,
		variables=[("mietvertrag", "Mietvertrag", "Mietvertrag", "Doctype")],
		standardpfade=[
			("Mietvertrag", {"mietvertrag": "__self__"}),
			("Betriebskostenabrechnung Mieter", {"mietvertrag": "objekt.mietvertrag"}),
		],
	)

	# 3) Briefkopf — Empfänger-Adresse + Mieter-Liste pro Iterations-Doctype.
	#    ``var`` ist eine Doctype-Liste (Vertragspartner), ``address`` das
	#    Briefanschrift-Adress-Doc. Bestehende ``Address``-Schreibweisen werden
	#    auf die gescrubbte Variable normalisiert.
	_patch_baustein(
		"Briefkopf",
		variables=[
			("var", "Empfänger-Liste", "Contact", "Doctype Liste"),
			("address", "Briefanschrift", "Address", "Doctype"),
		],
		body_regex_replacements=[(r"\bAddress\b", "address")],
		standardpfade=[
			("Mietvertrag", {
				"var": "objekt.mieter",
				"address": "objekt.kunde.briefanschrift",
			}),
			("Betriebskostenabrechnung Mieter", {
				"var": "objekt.mietvertrag.mieter",
				"address": "objekt.mietvertrag.kunde.briefanschrift",
			}),
			("Dunning", {"address": "objekt.kunde.briefanschrift"}),
		],
	)

	# 4) Unterschrift — Vertragspartner-Liste pro Iterations-Doctype.
	_patch_baustein(
		"Unterschrift",
		variables=[("var", "Unterschrift-Liste", "Contact", "Doctype Liste")],
		standardpfade=[
			("Mietvertrag", {"var": "objekt.mieter"}),
			("Betriebskostenabrechnung Mieter", {"var": "objekt.mietvertrag.mieter"}),
		],
	)

	# 5) Miethistorie — Mietvertrag-Variable + Body-Anpassung.
	_patch_baustein(
		"Miethistorie",
		variables=[("mietvertrag", "Mietvertrag", "Mietvertrag", "Doctype")],
		standardpfade=[("Mietvertrag", {"mietvertrag": "__self__"})],
		body_replacements=[
			("{% set mv = objekt or objekt %}", "{% set mv = mietvertrag %}"),
		],
	)

	# 6) BK-Abrechnung-Einleitung / -Schluss / -Posten — Variable +
	#    Standardpfad + alten ``set objekt``-Hack ersetzen.
	for name in ("BK-Abrechnung-Einleitung", "BK-Abrechnung-Schluss", "Betriebskostenabrechnungsposten"):
		_patch_baustein(
			name,
			variables=[(
				"betriebskostenabrechnung_mieter",
				"BK Mieter",
				"Betriebskostenabrechnung Mieter",
				"Doctype",
			)],
			standardpfade=[(
				"Betriebskostenabrechnung Mieter",
				{"betriebskostenabrechnung_mieter": "__self__"},
			)],
			body_replacements=[
				(
					"{%- set objekt = objekt or objekt or objekt -%}",
					"{%- set objekt = betriebskostenabrechnung_mieter -%}",
				),
			],
		)

	# 7) Token-Migration für alle Vorlagen + Bausteine — reine Pfade
	#    auf ``{{$ ... $}}`` umschreiben und alte Daten-Roots normalisieren.
	_migrate_text_fields("Serienbrief Vorlage", ("content", "html_content", "jinja_content"))
	_migrate_text_fields("Serienbrief Textbaustein", ("html_content", "jinja_content"))

	# 8) Pfad-/Mapping-Felder migrieren. Diese Felder enthalten rohe Resolver-
	#    Pfade oder JSON-Payloads, also keine Body-Platzhalter.
	for doctype, fields in {
		"Serienbrief Vorlage": ("pfad_zuordnung",),
		"Serienbrief Vorlagenbaustein": ("pfad_zuordnung",),
		"Serienbrief Textbaustein Standardpfad": ("pfad_zuordnung",),
		"Serienbrief Globaler Standardpfad": ("pfad_zuordnung",),
		"Serienbrief PDF Feld Mapping": ("value_path",),
		"Serienbrief Textbaustein Output": ("value_path",),
	}.items():
		_migrate_json_path_fields(doctype, fields)

	for doctype, fields in {
		"Serienbrief Vorlage": ("variablen_werte",),
		"Serienbrief Vorlagenbaustein": ("variablen_werte",),
		"Serienbrief Durchlauf": ("variablen_werte",),
		"Serienbrief Iterationsobjekt": ("variablen_werte",),
		"Serienbrief Dokument": ("variablen_werte",),
	}.items():
		_migrate_json_path_fields(doctype, fields, path_keys={"path", "value_path"})

	frappe.db.commit()
