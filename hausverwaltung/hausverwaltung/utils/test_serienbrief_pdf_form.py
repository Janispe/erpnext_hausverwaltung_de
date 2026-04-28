from __future__ import annotations

import tempfile
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from hausverwaltung.hausverwaltung.utils.serienbrief_pdf_form import _normalize_mapping_value
from hausverwaltung.hausverwaltung.utils.serienbrief_pdf_form import parse_pdf_pages
from hausverwaltung.hausverwaltung.utils.serienbrief_pdf_form import render_pdf_form_block

try:
	from pypdf import PdfWriter
except Exception:  # pragma: no cover
	from PyPDF2 import PdfWriter


class TestSerienbriefPdfForm(FrappeTestCase):
	def test_parse_pdf_pages(self):
		self.assertEqual(parse_pdf_pages("", 5), [0, 1, 2, 3, 4])
		self.assertEqual(parse_pdf_pages("1,3-4", 5), [0, 2, 3])

	def test_parse_pdf_pages_out_of_bounds(self):
		with self.assertRaises(Exception):
			parse_pdf_pages("9", 2)

	def test_normalize_mapping_value(self):
		self.assertEqual(_normalize_mapping_value("12,5", "Zahl"), 12.5)
		self.assertEqual(_normalize_mapping_value("ja", "Bool"), True)
		self.assertEqual(_normalize_mapping_value("nein", "Bool"), False)

	def test_required_pdf_mapping_raises(self):
		with tempfile.TemporaryDirectory() as tmp:
			pdf_path = Path(tmp) / "sample.pdf"
			writer = PdfWriter()
			writer.add_blank_page(width=595, height=842)
			with open(pdf_path, "wb") as handle:
				writer.write(handle)

			block = frappe._dict(
				name="PDF-BLOCK-1",
				title="PDF Block",
				pdf_file=str(pdf_path),
				pdf_pages="",
				pdf_flatten=1,
				pdf_field_mappings=[
					frappe._dict(
						pdf_field_name="name",
						value_path="mieter.name",
						fallback_value="",
						required=1,
						value_type="String",
					)
				],
			)

			with self.assertRaises(Exception):
				render_pdf_form_block(block, {}, lambda path, context: None)
