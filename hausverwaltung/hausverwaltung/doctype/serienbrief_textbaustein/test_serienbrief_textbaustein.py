# See license.txt

from __future__ import annotations

import csv
import os

import frappe
import unittest

from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
	_render_serienbrief_template,
)

_MIETHISTORIE_HTML = """<h3>Miethistorie</h3>
{% if segmente and segmente|length %}
<table>
  <tbody>
    {% for segment in segmente %}
    <tr data-von="{{ segment.von }}" data-bis="{{ segment.bis or '' }}" data-nk="{{ segment.nk }}" data-bk="{{ segment.bk }}" data-hk="{{ segment.hk }}">
      <td>{{ frappe.utils.formatdate(segment.von) }}</td>
      <td>{{ frappe.utils.formatdate(segment.bis) if segment.bis else 'laufend' }}</td>
      <td>{{ frappe.utils.fmt_money(segment.nk, currency='EUR') }}</td>
      <td>{{ frappe.utils.fmt_money(segment.bk, currency='EUR') }}</td>
      <td>{{ frappe.utils.fmt_money(segment.hk, currency='EUR') }}</td>
    </tr>
    {% endfor %}
  </tbody>
</table>
{% else %}
<p>Keine Miethistorie vorhanden.</p>
{% endif %}"""

_MIETHISTORIE_JINJA = """{% set mv = mietvertrag or iteration_objekt %}
{% set nk_rows = (mv.miete if mv and mv.miete else []) %}
{% set bk_rows = (mv.betriebskosten if mv and mv.betriebskosten else []) %}
{% set hk_rows = (mv.heizkosten if mv and mv.heizkosten else []) %}
{% set breakpoints = [] %}
{% for row in (nk_rows + bk_rows + hk_rows) %}
  {% if row.von %}
    {% set start_date = frappe.utils.getdate(row.von) %}
    {% if start_date and start_date not in breakpoints %}
      {% set _ = breakpoints.append(start_date) %}
    {% endif %}
  {% endif %}
{% endfor %}
{% set breakpoints = breakpoints | sort %}
{% macro amount_for(rows, start_date) -%}
  {% set ns = namespace(value=0) %}
  {% for r in (rows | sort(attribute='von')) %}
    {% if r.von and frappe.utils.getdate(r.von) <= start_date %}
      {% set ns.value = (r.miete or 0) %}
    {% endif %}
  {% endfor %}
  {{ ns.value }}
{%- endmacro %}
{% set segmente = [] %}
{% for start_date in breakpoints %}
  {% set next_start = (breakpoints[loop.index] if loop.index < (breakpoints | length) else None) %}
  {% set _ = segmente.append({
    'von': start_date,
    'bis': (frappe.utils.add_days(next_start, -1) if next_start else None),
    'nk': (amount_for(nk_rows, start_date) | float),
    'bk': (amount_for(bk_rows, start_date) | float),
    'hk': (amount_for(hk_rows, start_date) | float)
  }) %}
{% endfor %}"""


def _app_data_path(*parts: str) -> str:
	return os.path.abspath(os.path.join(frappe.get_app_path("hausverwaltung"), "..", "data", *parts))


def _read_csv_block(block_title: str) -> dict[str, str]:
	path = _app_data_path("Serienbrief Textbaustein.csv")
	if not os.path.exists(path) and block_title == "Miethistorie":
		return {
			"id": "Miethistorie",
			"title": "Miethistorie",
			"html_content": _MIETHISTORIE_HTML,
			"jinja_content": _MIETHISTORIE_JINJA,
		}

	with open(path, encoding="utf-8", newline="") as handle:
		reader = csv.DictReader(handle)
		current_id = None
		for row in reader:
			row_id = (row.get("ID") or "").strip()
			if row_id:
				current_id = row_id
			elif current_id:
				row_id = current_id
			else:
				continue

			title = (row.get("Titel") or "").strip()
			if title == block_title:
				return {
					"id": row_id,
					"title": title,
					"html_content": row.get("HTML") or "",
					"jinja_content": row.get("Jinja") or "",
				}

	raise AssertionError(f"Block {block_title!r} not found in CSV")


def _render_miethistorie(context: dict) -> str:
	block = _read_csv_block("Miethistorie")
	template_source = "\n".join([block["jinja_content"], block["html_content"]]).strip()
	return _render_serienbrief_template(template_source, context)


def _mietvertrag(miete=None, betriebskosten=None, heizkosten=None):
	return frappe._dict(
		doctype="Mietvertrag",
		miete=miete or [],
		betriebskosten=betriebskosten or [],
		heizkosten=heizkosten or [],
	)


class TestSerienbriefTextbaustein(unittest.TestCase):
	def test_placeholder_token_resolves_objekt_root(self):
		rendered = _render_serienbrief_template(
			"Aktenzeichen {{$ objekt.name $}}",
			{"objekt": frappe._dict(doctype="Mietvertrag", name="MV-TEST-001")},
		)

		self.assertEqual(rendered, "Aktenzeichen MV-TEST-001")

	def test_placeholder_token_allows_spaces_around_marker(self):
		rendered = _render_serienbrief_template(
			"Aktenzeichen {{ $ objekt.name $ }}",
			{"objekt": frappe._dict(doctype="Mietvertrag", name="MV-TEST-001")},
		)

		self.assertEqual(rendered, "Aktenzeichen MV-TEST-001")

	def test_placeholder_token_resolves_numeric_list_index(self):
		context = {
			"objekt": frappe._dict(
				doctype="Mietvertrag",
				mieter=[
					frappe._dict(
						doctype="Vertragspartner",
						kontakt=frappe._dict(doctype="Contact", last_name="Mustermann"),
					)
				],
			)
		}
		rendered = _render_serienbrief_template(
			"Name {{$ objekt.mieter[0].kontakt.last_name $}}",
			context,
		)

		self.assertEqual(rendered, "Name Mustermann")

	def test_miethistorie_renders_segments_and_open_end(self):
		mv = _mietvertrag(
			miete=[
				frappe._dict(von="2025-01-01", miete=100),
				frappe._dict(von="2025-03-01", miete=120),
			]
		)
		rendered = _render_miethistorie({"mietvertrag": mv, "iteration_objekt": None})

		self.assertIn('data-von="2025-01-01" data-bis="2025-02-28" data-nk="100.0" data-bk="0.0" data-hk="0.0"', rendered)
		self.assertIn('data-von="2025-03-01" data-bis="" data-nk="120.0" data-bk="0.0" data-hk="0.0"', rendered)
		self.assertIn("laufend", rendered)

	def test_miethistorie_merges_nk_bk_hk_timelines(self):
		mv = _mietvertrag(
			miete=[frappe._dict(von="2025-01-01", miete=100)],
			betriebskosten=[frappe._dict(von="2025-02-01", miete=30)],
			heizkosten=[frappe._dict(von="2025-04-01", miete=40)],
		)
		rendered = _render_miethistorie({"mietvertrag": mv, "iteration_objekt": None})

		self.assertIn('data-von="2025-01-01" data-bis="2025-01-31" data-nk="100.0" data-bk="0.0" data-hk="0.0"', rendered)
		self.assertIn('data-von="2025-02-01" data-bis="2025-03-31" data-nk="100.0" data-bk="30.0" data-hk="0.0"', rendered)
		self.assertIn('data-von="2025-04-01" data-bis="" data-nk="100.0" data-bk="30.0" data-hk="40.0"', rendered)

	def test_miethistorie_renders_empty_message_without_history(self):
		mv = _mietvertrag()
		rendered = _render_miethistorie({"mietvertrag": mv, "iteration_objekt": None})
		self.assertIn("Keine Miethistorie vorhanden.", rendered)
