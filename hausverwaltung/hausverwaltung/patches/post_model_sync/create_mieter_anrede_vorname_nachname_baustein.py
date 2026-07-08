"""Create a sentence-friendly tenant salutation/name block."""

from __future__ import annotations

import frappe

from hausverwaltung.hausverwaltung.patches.post_model_sync.migrate_serienbrief_to_placeholder_tokens import (
	_patch_baustein,
)


TITLE = "MieterAnredeVornameNachnameAlle"

HTML_CONTENT = """\
{%- macro _person_line(p) -%}
{%- set sal = (p.get('salutation') or '') -%}
{%- set first = (p.get('first_name') or '') -%}
{%- set last = (p.get('last_name') or '') -%}
{%- set fallback = (p.get('company_name') or p.get('name') or '') -%}
{%- set full_name = (first ~ ' ' ~ last)|replace('  ', ' ')|trim -%}
{%- if not full_name -%}
{%- set full_name = fallback -%}
{%- endif -%}
{{ (sal ~ (' ' if sal and full_name else '') ~ full_name)|replace('  ', ' ')|trim }}
{%- endmacro -%}
{%- set rollen_text = (rollen if rollen is defined else 'Hauptmieter')|trim -%}
{%- if not rollen_text -%}
{%- set rollen_text = 'Hauptmieter' -%}
{%- endif -%}
{%- set include_all = rollen_text|lower in ['*', 'alle'] -%}
{%- set erlaubte_rollen = [] -%}
{%- for rolle in (rollen_text|replace(';', ',')).split(',') -%}
{%- set role = rolle|trim -%}
{%- if role and not include_all -%}
{%- set _ = erlaubte_rollen.append(role) -%}
{%- endif -%}
{%- endfor -%}
{%- if not include_all and not erlaubte_rollen -%}
{%- set _ = erlaubte_rollen.append('Hauptmieter') -%}
{%- endif -%}
{%- set frauen = [] -%}
{%- set andere = [] -%}
{%- for vp in (mietvertrag.mieter or []) -%}
{%- set rolle = (vp.rolle or '')|trim -%}
{%- if vp.kontakt and ((include_all and rolle != 'Ausgezogen') or (rolle in erlaubte_rollen)) -%}
{%- if vp.kontakt.salutation == 'Frau' -%}
{%- set _ = frauen.append(vp.kontakt) -%}
{%- else -%}
{%- set _ = andere.append(vp.kontakt) -%}
{%- endif -%}
{%- endif -%}
{%- endfor -%}
{%- set personen = frauen + andere -%}
{%- if not personen -%}
{{ frappe.throw("Mietvertrag " ~ mietvertrag.name ~ " hat keine passenden Vertragspartner mit Contact-Verknüpfung für Rollen '" ~ rollen_text ~ "' — die Anrede mit Vorname/Nachname kann nicht generiert werden.") }}
{%- endif -%}
{%- set lines = [] -%}
{%- for p in personen -%}
{%- set line = _person_line(p)|trim -%}
{%- if line -%}
{%- set _ = lines.append(line) -%}
{%- endif -%}
{%- endfor -%}
{%- if sep is defined -%}
{{ lines|join(sep) }}
{%- else -%}
{%- set op = (verknuepfungsoperator if verknuepfungsoperator is defined else 'und')|trim -%}
{%- if not op -%}
{%- set op = 'und' -%}
{%- endif -%}
{%- if op in [', und', ',und', 'komma und', 'komma_und'] -%}
{%- for line in lines -%}
{{ line }}{%- if not loop.last -%}{%- if loop.revindex == 2 %} und {% else %}, {% endif -%}{%- endif -%}
{%- endfor -%}
{%- elif op == ',' -%}
{{ lines|join(', ') }}
{%- else -%}
{{ lines|join(' ' ~ op ~ ' ') }}
{%- endif -%}
{%- endif -%}
"""

DESCRIPTION = (
	"Gibt alle Hauptmieter als Satzbaustein mit Anrede, Vorname und Nachname aus, "
	"z.B. 'Frau Maria Musterfrau und Herr Max Mustermann'. "
	"Die optionale Variable 'verknuepfungsoperator' steuert die Verbindung "
	"zwischen mehreren Namen: 'und' (Standard), ',', oder ', und'. "
	"Die optionale Variable 'rollen' steuert die berücksichtigten Vertragspartner-Rollen "
	"als kommagetrennte Liste, Standard ist 'Hauptmieter'. "
	"Der Output 'anzahl' enthält die Anzahl der berücksichtigten Personen."
)


def execute() -> None:
	if not frappe.db.exists("DocType", "Serienbrief Textbaustein"):
		return

	payload = {
		"content_type": "HTML + Jinja",
		"html_content": HTML_CONTENT,
		"jinja_content": "",
		"description": DESCRIPTION,
	}

	if frappe.db.exists("Serienbrief Textbaustein", TITLE):
		doc = frappe.get_doc("Serienbrief Textbaustein", TITLE)
		changed = False
		for fieldname, value in payload.items():
			if getattr(doc, fieldname, None) != value:
				setattr(doc, fieldname, value)
				changed = True
		if changed:
			doc.save(ignore_permissions=True)
	else:
		frappe.get_doc(
			{
				"doctype": "Serienbrief Textbaustein",
				"title": TITLE,
				**payload,
			}
		).insert(ignore_permissions=True)

	dunning_mietvertrag = "objekt.overdue_payments.sales_invoice.mietvertrag"
	_patch_baustein(
		TITLE,
		variables=[
			("mietvertrag", "Mietvertrag", "Mietvertrag", "Doctype"),
			("verknuepfungsoperator", "Verknüpfungsoperator", "", "Text"),
			("rollen", "Rollen", "", "Text"),
		],
		standardpfade=[
			("Mietvertrag", {"mietvertrag": "__self__"}),
			("Betriebskostenabrechnung Mieter", {"mietvertrag": "objekt.mietvertrag"}),
			("Dunning", {"mietvertrag": dunning_mietvertrag}),
		],
	)
	_ensure_output()
	_ensure_text_variable_defaults()

	try:
		frappe.clear_cache(doctype="Serienbrief Textbaustein")
	except Exception:
		pass


def mieter_anzahl_provider(context, output_row=None) -> int:
	return len(_matching_mieter_contacts(context))


def _matching_mieter_contacts(context) -> list:
	mietvertrag = _get_context_value(context, "mietvertrag")
	if not mietvertrag:
		return []

	rollen_text = str(_get_context_value(context, "rollen") or "Hauptmieter").strip()
	if not rollen_text:
		rollen_text = "Hauptmieter"

	include_all = rollen_text.lower() in {"*", "alle"}
	erlaubte_rollen: list[str] = []
	for rolle in rollen_text.replace(";", ",").split(","):
		role = rolle.strip()
		if role and not include_all:
			erlaubte_rollen.append(role)
	if not include_all and not erlaubte_rollen:
		erlaubte_rollen.append("Hauptmieter")

	personen = []
	for vp in _get_attr(mietvertrag, "mieter", []) or []:
		rolle = str(_get_attr(vp, "rolle", "") or "").strip()
		kontakt = _get_attr(vp, "kontakt", None)
		if not kontakt:
			continue
		if (include_all and rolle != "Ausgezogen") or (rolle in erlaubte_rollen):
			personen.append(kontakt)
	return personen


def _get_context_value(context, key: str):
	if isinstance(context, dict):
		return context.get(key)
	return getattr(context, key, None)


def _get_attr(value, key: str, default=None):
	if isinstance(value, dict):
		return value.get(key, default)
	get = getattr(value, "get", None)
	if callable(get):
		try:
			return get(key, default)
		except Exception:
			pass
	return getattr(value, key, default)


def _ensure_output() -> None:
	doc = frappe.get_doc("Serienbrief Textbaustein", TITLE)
	changed = False
	config = {
		"output_name": "anzahl",
		"output_type": "Zahl",
		"label": "Anzahl Mieter",
		"provider": (
			"hausverwaltung.hausverwaltung.patches.post_model_sync."
			"create_mieter_anrede_vorname_nachname_baustein.mieter_anzahl_provider"
		),
		"beschreibung": "Anzahl der Personen, die dieser Baustein im Namenstext berücksichtigt.",
	}
	for row in doc.get("outputs") or []:
		if frappe.scrub((row.output_name or "").strip()) != "anzahl":
			continue
		for fieldname, value in config.items():
			if getattr(row, fieldname, None) != value:
				setattr(row, fieldname, value)
				changed = True
		break
	else:
		doc.append("outputs", config)
		changed = True

	if changed:
		doc.save(ignore_permissions=True)


def _ensure_text_variable_defaults() -> None:
	doc = frappe.get_doc("Serienbrief Textbaustein", TITLE)
	changed = False
	defaults = {
		"verknuepfungsoperator": {
			"preview_default": "und",
			"beschreibung": "Optional: 'und' (Standard), ',' oder ', und'.",
		},
		"rollen": {
			"preview_default": "Hauptmieter",
			"beschreibung": "Optional: kommagetrennte Rollen, z.B. 'Hauptmieter, Untermieter' oder 'alle'.",
		},
	}
	for row in doc.get("variables") or []:
		config = defaults.get(frappe.scrub((row.variable or "").strip()))
		if not config:
			continue
		if not getattr(row, "optional", 0):
			row.optional = 1
			changed = True
		if (row.preview_default or "").strip() != config["preview_default"]:
			row.preview_default = config["preview_default"]
			changed = True
		if (row.beschreibung or "").strip() != config["beschreibung"]:
			row.beschreibung = config["beschreibung"]
			changed = True
	if changed:
		doc.save(ignore_permissions=True)
