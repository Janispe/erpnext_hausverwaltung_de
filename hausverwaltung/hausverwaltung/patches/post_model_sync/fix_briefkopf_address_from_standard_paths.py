"""Render Briefkopf recipient from declared block variables."""

from __future__ import annotations

import json

import frappe


BRIEFKOPF_JINJA = """\
{% set _adressfenster_zeilen = [] %}
{% set _namen = [] %}
{% if var is defined and var %}
  {% if var is mapping or var is string %}
    {% set _var_items = [var] %}
  {% else %}
    {% set _var_items = var %}
  {% endif %}
  {% for item in _var_items if item %}
    {% set rolle = item.rolle if item.rolle is defined else "" %}
    {% if not rolle or rolle == "Hauptmieter" %}
      {% set kontakt = item.kontakt if item.kontakt is defined and item.kontakt else item %}
      {% set first = kontakt.first_name if kontakt.first_name is defined and kontakt.first_name else "" %}
      {% set last = kontakt.last_name if kontakt.last_name is defined and kontakt.last_name else "" %}
      {% set full = (first ~ " " ~ last) | trim %}
      {% if not full and kontakt.company_name is defined and kontakt.company_name %}
        {% set full = kontakt.company_name %}
      {% endif %}
      {% if not full and kontakt.name is defined and kontakt.name %}
        {% set full = kontakt.name %}
      {% endif %}
      {% if full %}
        {% set _ = _namen.append(full) %}
      {% endif %}
    {% endif %}
  {% endfor %}
{% endif %}
{% if _namen %}
  {% set _ = _adressfenster_zeilen.append(_namen | join("<br/>")) %}
{% endif %}
{% if address is defined and address %}
  {% set _address_line_added = namespace(value=false) %}
  {% if address.address_line1 is defined and address.address_line1 %}
    {% set _ = _adressfenster_zeilen.append(address.address_line1) %}
    {% set _address_line_added.value = true %}
  {% endif %}
  {% if address.address_line2 is defined and address.address_line2 %}
    {% set _ = _adressfenster_zeilen.append(address.address_line2) %}
    {% set _address_line_added.value = true %}
  {% endif %}
  {% set _plz = address.pincode if address.pincode is defined and address.pincode else "" %}
  {% set _ort = address.city if address.city is defined and address.city else "" %}
  {% set _plz_ort = (_plz ~ " " ~ _ort) | trim %}
  {% if address.plz_ort is defined and address.plz_ort %}
    {% set _plz_ort = address.plz_ort %}
  {% endif %}
  {% if _plz_ort %}
    {% set _ = _adressfenster_zeilen.append(_plz_ort) %}
    {% set _address_line_added.value = true %}
  {% endif %}
  {% if not _address_line_added.value and not _namen and address.adresse is defined and address.adresse %}
    {% set _ = _adressfenster_zeilen.append(address.adresse) %}
  {% endif %}
{% endif %}
{% set adressfenster = _adressfenster_zeilen | join("<br/>") %}
{% set brief_datum = datum if datum is defined and datum else frappe.utils.formatdate(frappe.utils.nowdate(), "dd.MM.yyyy") %}
"""


BRIEFKOPF_HTML = """\
<!-- Peters Briefkopf -->
<div class="sb-letterhead sb-letterhead-peters" style="position: relative; min-height: 4.1cm;">
  {% if not (an_verwaltung | int) %}
  <div style="position:absolute; left:0; top:0; line-height:1;">
    <img src="/files/{% if druck_schwarz_weiss is defined and (druck_schwarz_weiss | int) %}peters-siegel-sw.svg{% else %}peters-lockup.svg{% endif %}" alt="Peters Hausverwaltung" style="height:{% if druck_schwarz_weiss is defined and (druck_schwarz_weiss | int) %}1.15cm{% else %}1.42cm{% endif %};width:auto;" />
  </div>
  {% endif %}

  <div class="sb-address-window">
    <div class="sb-return-address">
      Hausverwaltung, Inga Peters, Tristanstr. 4, 14109 Berlin
    </div>
    <div class="sb-recipient">
      {% if (an_verwaltung | int) %}
      Hausverwaltung<br/>
      Inga Peters<br/>
      Tristanstr. 4<br/>
      14109 Berlin
      {% else %}
      {{ adressfenster | safe }}
      {% endif %}
    </div>
  </div>

  {% if (an_verwaltung | int) and kopf_rechts is defined and kopf_rechts %}
  <div class="sb-sender">
    <div style="font-weight: bold; margin-bottom: 10px;">
      {{ (kopf_rechts | string).replace('\\\\n', '<br/>').replace('\\n', '<br/>') | safe }}
    </div>
  </div>
  {% endif %}

  {% if not (an_verwaltung | int) %}
  <div class="sb-sender">
    <div style="line-height:1.25;">
      Hausverwaltung<br/>
      Inga Peters<br/>
      Tristanstr. 4<br/>
      14109 Berlin<br/>
      Tel.: 030/319 536-20<br/>
      Fax: 030/319 536-19<br/>
      <div class="sb-office-hours">
        Sprechzeiten: Mo + Do<br/>
        9.30 &ndash; 13.00 Uhr<br/>
        verwaltung@haus-peters.de
      </div>
    </div>
  </div>
  {% endif %}
</div>

<div class="sb-date">
  Berlin, den {{ brief_datum }}
</div>"""


STANDARDPFADE = {
	"Mietvertrag": {
		"var": "objekt.mieter[]",
		"address": "objekt.kunde.briefanschrift",
	},
	"Betriebskostenabrechnung Mieter": {
		"var": "objekt.mietvertrag.mieter[]",
		"address": "objekt.mietvertrag.kunde.briefanschrift",
	},
	"Dunning": {
		"var": "objekt.overdue_payments.sales_invoice.mietvertrag.mieter[]",
		"address": "objekt.overdue_payments.sales_invoice.mietvertrag.kunde.briefanschrift",
	},
}


VARIABLES = {
	"var": {
		"label": "Empfaenger-Liste",
		"variable_type": "Doctype Liste",
		"reference_doctype": "Contact",
		"optional": 0,
		"preview_default": "",
		"beschreibung": "Vertragspartner-/Contact-Liste fuer die Empfaenger-Namen.",
	},
	"address": {
		"label": "Briefanschrift",
		"variable_type": "Doctype",
		"reference_doctype": "Address",
		"optional": 0,
		"preview_default": "",
		"beschreibung": "Adress-Dokument fuer Strasse, PLZ und Ort im Adressfenster.",
	},
	"an_verwaltung": {
		"label": "An Verwaltung adressieren",
		"variable_type": "Text",
		"reference_doctype": "",
		"optional": 1,
		"preview_default": "0",
		"beschreibung": "'0' = Empfaenger aus var/address, '1' = HV-Adresse.",
	},
	"kopf_rechts": {
		"label": "Titel/Notiz oben rechts",
		"variable_type": "Text",
		"reference_doctype": "",
		"optional": 1,
		"preview_default": "",
		"beschreibung": "Optionaler Text oben rechts, nur wenn 'An Verwaltung adressieren' = 1 ist.",
	},
}


def _find_child_by_scrub(rows, fieldname: str, value: str):
	target = frappe.scrub(value)
	for row in rows or []:
		if frappe.scrub((getattr(row, fieldname, "") or "").strip()) == target:
			return row
	return None


def _sync_variables(doc) -> bool:
	changed = False
	for variable, values in VARIABLES.items():
		row = _find_child_by_scrub(doc.get("variables"), "variable", variable)
		if row is None:
			doc.append("variables", {"variable": variable, **values})
			changed = True
			continue
		if row.variable != variable:
			row.variable = variable
			changed = True
		for field, value in values.items():
			if (getattr(row, field, None) or "") != value:
				setattr(row, field, value)
				changed = True
	return changed


def _sync_standardpfade(doc) -> bool:
	changed = False
	for startobjekt, mapping in STANDARDPFADE.items():
		row = next(
			(
				r
				for r in (doc.get("standardpfade") or [])
				if (getattr(r, "startobjekt", "") or "").strip() == startobjekt
			),
			None,
		)
		payload = json.dumps(mapping, ensure_ascii=False)
		if row is None:
			doc.append(
				"standardpfade",
				{"startobjekt": startobjekt, "pfad_zuordnung": payload},
			)
			changed = True
			continue
		if (row.pfad_zuordnung or "") != payload:
			row.pfad_zuordnung = payload
			changed = True
	return changed


def execute() -> None:
	if not frappe.db.exists("DocType", "Serienbrief Textbaustein"):
		return
	if not frappe.db.exists("Serienbrief Textbaustein", "Briefkopf"):
		return

	doc = frappe.get_doc("Serienbrief Textbaustein", "Briefkopf")
	changed = False

	if (doc.jinja_content or "").strip() != BRIEFKOPF_JINJA.strip():
		doc.jinja_content = BRIEFKOPF_JINJA
		changed = True
	if (doc.html_content or "").strip() != BRIEFKOPF_HTML.strip():
		doc.html_content = BRIEFKOPF_HTML
		changed = True

	changed = _sync_variables(doc) or changed
	changed = _sync_standardpfade(doc) or changed

	if changed:
		doc.save(ignore_permissions=True)
