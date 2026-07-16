from __future__ import annotations

import frappe


BLOCK_NAME = "Betriebskostenabrechnungsposten"

HTML_CONTENT = """
<div class="bk-abrechnung">
  <style>
    .bk-abrechnung {
      font-size: 9.2pt;
      color: #1f2933;
    }
    .bk-abrechnung h3 {
      margin: 0 0 5px 0;
      font-size: 12pt;
      font-weight: 700;
      color: #111827;
    }
    .bk-abrechnung .bk-period {
      margin: 0 0 6px 0;
      font-size: 8.7pt;
      color: #4b5563;
    }
    .bk-abrechnung table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      font-size: 8.1pt;
      line-height: 1.16;
    }
    .bk-abrechnung th {
      padding: 3px 4px;
      border: 0;
      border-bottom: 1px solid #8b95a1;
      background: #f4f6f8;
      color: #374151;
      font-weight: 700;
      text-align: left;
    }
    .bk-abrechnung td {
      padding: 3px 4px;
      border: 0;
      border-top: 1px solid #d8dee6;
      vertical-align: top;
    }
    .bk-abrechnung tbody tr:first-child td {
      border-top: 0;
    }
    .bk-abrechnung tbody tr:nth-child(even):not(.bk-total):not(.bk-balance) td {
      background: #fafbfc;
    }
    .bk-abrechnung .num {
      text-align: right;
      white-space: nowrap;
      font-variant-numeric: tabular-nums;
    }
    .bk-abrechnung .muted {
      color: #6b7280;
    }
    .bk-abrechnung .bk-total td {
      border-top: 1.4px solid #4b5563;
      background: #f7f8fa;
      font-weight: 700;
    }
    .bk-abrechnung .bk-prepay td {
      background: #fff;
    }
    .bk-abrechnung .bk-balance td {
      border-top: 1.4px solid #111827;
      background: #eef2f7;
      font-weight: 700;
    }
  </style>

  <h3>Betriebskostenabrechnung</h3>
  <p class="bk-period"><strong>Ihr Abrechnungszeitraum:</strong> {{ d(objekt.von) if objekt else "" }} &ndash; {{ d(objekt.bis) if objekt else "" }}</p>

  <table>
    {% if matrix and matrix|length %}
      <colgroup>
        <col style="width:30%;">
        <col style="width:14%;">
        <col style="width:18%;">
        <col style="width:19%;">
        <col style="width:19%;">
      </colgroup>
    {% else %}
      <colgroup>
        <col style="width:52%;">
        <col style="width:24%;">
        <col style="width:24%;">
      </colgroup>
    {% endif %}
    <thead>
      {% if matrix and matrix|length %}
        <tr>
          <th>Betriebskostenart</th>
          <th>Verteilung</th>
          <th class="num">Basis (Ihr/Ges.)</th>
          <th class="num">Gesamt</th>
          <th class="num">Ihr Anteil</th>
        </tr>
      {% else %}
        <tr>
          <th>Betriebskostenart</th>
          <th>Verteilung</th>
          <th class="num">Betrag</th>
        </tr>
      {% endif %}
    </thead>

    <tbody>
      {% if matrix and matrix|length %}
        {% for row in matrix %}
          {% set art = frappe.get_cached_doc("Betriebskostenart", row.betriebskostenart) if row.betriebskostenart else None %}
          <tr>
            <td>{{ (art.name1 if art else row.bezeichnung or row.betriebskostenart) or "" }}</td>
            <td class="muted">{{ (art.verteilung if art else "") or "" }}</td>
            <td class="num muted">
              {{ basis_label(art) }}
            </td>
            <td class="num">{{ eur(row.immobilie) }}</td>
            <td class="num">{{ eur(row.wohnung) }}</td>
          </tr>
        {% endfor %}

        <tr class="bk-total">
          <td colspan="4" class="num">Gesamtkosten (Ihr Anteil)</td>
          <td class="num">{{ eur(ns.summe) }}</td>
        </tr>

      {% elif posten and posten|length %}
        {% for row in posten %}
          {% set art = frappe.get_cached_doc("Betriebskostenart", row.betriebskostenart) if row.betriebskostenart else None %}
          <tr>
            <td>{{ (art.name1 if art else row.bezeichnung or row.betriebskostenart) or "" }}</td>
            <td class="muted">{{ (art.verteilung if art else "") or "" }}</td>
            <td class="num">{{ eur(row.betrag) }}</td>
          </tr>
        {% endfor %}

        <tr class="bk-total">
          <td colspan="2" class="num">Gesamtkosten</td>
          <td class="num">{{ eur(ns.summe) }}</td>
        </tr>

      {% else %}
        <tr>
          <td colspan="{% if matrix and matrix|length %}5{% else %}3{% endif %}" class="muted">
            Keine Abrechnungsposten vorhanden.
          </td>
        </tr>
      {% endif %}

      <tr class="bk-prepay">
        <td colspan="{% if matrix and matrix|length %}4{% else %}2{% endif %}" class="num">Vorauszahlungen</td>
        <td class="num">{{ eur(voraus) }}</td>
      </tr>

      <tr class="bk-balance">
        <td colspan="{% if matrix and matrix|length %}4{% else %}2{% endif %}" class="num">{{ diff_label }}</td>
        <td class="num">{{ eur(diff) }}</td>
      </tr>
    </tbody>
  </table>
</div>
""".strip()

JINJA_CONTENT = """
{% set objekt = betriebskostenabrechnung_mieter %}

{% macro eur(v) -%}
  {%- set n = (v or 0) | float -%}
  {{ ('{:,.2f}'.format(n)).replace(',', 'X').replace('.', ',').replace('X', '.') }} €
{%- endmacro %}

{% macro num(v) -%}
  {%- set n = (v or 0) | float -%}
  {{ ('{:,.2f}'.format(n)).replace(',', 'X').replace('.', ',').replace('X', '.') }}
{%- endmacro %}

{% macro d(dt) -%}
  {{ frappe.utils.formatdate(dt) if dt else "" }}
{%- endmacro %}

{% macro basis_label(art) -%}
  {%- if art and art.verteilung == "qm" -%}
    {{ num(qm) }} / {{ num(total_qm) }} qm
  {%- elif art and art.verteilung == "Bewohner" -%}
    {{ num(bewohner) }} / {{ num(total_bewohner) }}
  {%- elif art and art.verteilung in ["Schlüssel", "Schluessel"] -%}
    {%- set key = art.get("schlüssel") or art.get("schluessel") -%}
    {%- set own = (wohnung_schluesselwerte.get(key) or 0) | float -%}
    {%- set total = (schluessel_totals.get(key) or 0) | float -%}
    {%- if key and (own or total) -%}
      {{ num(own) }} / {{ num(total) }}
    {%- else -%}
      &nbsp;
    {%- endif -%}
  {%- else -%}
    &nbsp;
  {%- endif -%}
{%- endmacro %}

{% set matrix = (objekt.get_kostenmatrix_rows() if objekt and objekt.get_kostenmatrix_rows else []) %}
{% set posten = (objekt.abrechnung if objekt and objekt.abrechnung else []) %}

{% set basis = objekt.get_immobilien_basis() if objekt and objekt.get_immobilien_basis else {} %}
{% set total_qm = ((basis.get("total_qm") or 0) | float) %}
{% set total_bewohner = ((basis.get("total_bewohner") or 0) | float) %}
{% set schluessel_totals = basis.get("schluessel_totals") or {} %}
{% set wohnung_schluesselwerte = basis.get("wohnung_schluesselwerte") or {} %}

{# Anteile/Basis #}
{% set qm = ((objekt.get("größe") or 0) | float) if objekt else 0 %}
{% set bewohner = (objekt.get("mieter")|length) if objekt and objekt.get("mieter") else 0 %}

{# Summen: im Matrix-Fall nur "objekt.wohnung" (Mieteranteil) summieren #}
{% set ns = namespace(summe=0) %}
{% if matrix and matrix|length %}
  {% for r in matrix %}
    {% set ns.summe = ns.summe + ((r.wohnung or 0) | float) %}
  {% endfor %}
{% else %}
  {% for r in posten %}
    {% set ns.summe = ns.summe + ((r.betrag or 0) | float) %}
  {% endfor %}
{% endif %}

{% set voraus = ((objekt.vorrauszahlungen or 0) | float) if objekt else 0 %}
{% set diff = (ns.summe - voraus) %}
{% set diff_label = ("Nachzahlung" if diff > 0 else "Guthaben" if diff < 0 else "Ausgeglichen") %}
""".strip()


def execute():
	if not frappe.db.exists("Serienbrief Textbaustein", BLOCK_NAME):
		return

	frappe.db.set_value(
		"Serienbrief Textbaustein",
		BLOCK_NAME,
		{
			"html_content": HTML_CONTENT,
			"jinja_content": JINJA_CONTENT,
		},
		update_modified=False,
	)
