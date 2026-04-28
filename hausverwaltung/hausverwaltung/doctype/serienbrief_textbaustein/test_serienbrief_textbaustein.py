# See license.txt

from __future__ import annotations

import csv
import os

import frappe
from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
	_render_serienbrief_template,
)


def _app_data_path(*parts: str) -> str:
	return os.path.abspath(os.path.join(frappe.get_app_path("hausverwaltung"), "..", "data", *parts))


def _read_csv_block(block_title: str) -> dict[str, str]:
	with open(_app_data_path("Serienbrief Textbaustein.csv"), encoding="utf-8", newline="") as handle:
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


class TestSerienbriefTextbaustein(FrappeTestCase):
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

