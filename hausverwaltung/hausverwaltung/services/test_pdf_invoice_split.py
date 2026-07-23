from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import frappe

from hausverwaltung.hausverwaltung.services.pdf_invoice_split import (
	detect_invoice_groups,
	parse_excluded_pages,
	parse_repeated_page_positions,
	split_pdf_bytes,
)


class TestPdfInvoiceSplit(unittest.TestCase):
	def test_distinct_invoice_numbers_start_new_groups(self):
		groups, warning = detect_invoice_groups([
			"Rechnungsnummer: TW-1001\nRechnung Thermenwartung",
			"Rechnungsnummer: TW-1002\nRechnung Thermenwartung",
			"Rechnungsnummer: TW-1003\nRechnung Thermenwartung",
		])

		self.assertIsNone(warning)
		self.assertEqual([(g["start"], g["end"]) for g in groups], [(0, 0), (1, 1), (2, 2)])
		self.assertEqual([g["invoice_number"] for g in groups], ["TW-1001", "TW-1002", "TW-1003"])

	def test_page_counter_keeps_multi_page_invoices_together(self):
		groups, warning = detect_invoice_groups([
			"Rechnung Nr. A-100\nSeite 1 von 2",
			"Rechnung Nr. A-100\nSeite 2 von 2",
			"Rechnung Nr. A-101\nSeite 1 von 3",
			"Seite 2 von 3",
			"Seite 3 von 3",
		])

		self.assertIsNone(warning)
		self.assertEqual([(g["start"], g["end"]) for g in groups], [(0, 1), (2, 4)])
		self.assertEqual([g["invoice_number"] for g in groups], ["A-100", "A-101"])

	def test_complete_page_counter_keeps_single_multi_page_invoice_together(self):
		groups, warning = detect_invoice_groups([
			"Rechnung Nr. A-100\nSeite 1 von 3",
			"Rechnung Nr. A-100\nSeite 2 von 3",
			"Rechnung Nr. A-100\nSeite 3 von 3",
		])

		self.assertIsNone(warning)
		self.assertEqual([(g["start"], g["end"]) for g in groups], [(0, 2)])
		self.assertEqual(groups[0]["invoice_number"], "A-100")

	def test_inconsistent_page_counter_still_uses_safe_fallback(self):
		groups, warning = detect_invoice_groups([
			"Rechnung Nr. A-100\nSeite 1 von 3",
			"Rechnung Nr. A-100\nSeite 2 von 4",
			"Rechnung Nr. A-100\nSeite 3 von 3",
		])

		self.assertTrue(warning)
		self.assertEqual([(g["start"], g["end"]) for g in groups], [(0, 0), (1, 1), (2, 2)])

	def test_split_pdf_keeps_single_multi_page_invoice_together(self):
		try:
			from pypdf import PdfReader
		except ImportError:
			from PyPDF2 import PdfReader
		from reportlab.pdfgen import canvas

		source = io.BytesIO()
		pdf = canvas.Canvas(source, pagesize=(595, 842))
		for page_number in range(1, 4):
			pdf.drawString(72, 780, "Rechnung Nr. A-100")
			pdf.drawString(72, 40, f"Seite {page_number} von 3")
			pdf.showPage()
		pdf.save()

		parts, warning, metadata = split_pdf_bytes(source.getvalue())

		self.assertIsNone(warning)
		self.assertEqual(len(parts), 1)
		self.assertEqual(parts[0]["source_pages"], [1, 2, 3])
		self.assertEqual(len(PdfReader(io.BytesIO(parts[0]["content"])).pages), 3)
		self.assertEqual(metadata["included_page_count"], 3)

	def test_invoice_number_on_first_page_only_starts_next_invoice(self):
		groups, warning = detect_invoice_groups([
			"Rechnungsnummer 2026-001",
			"Leistungsnachweis ohne wiederholten Rechnungskopf",
			"Rechnungsnummer 2026-002",
			"Anlage zur Wartung",
		])

		self.assertIsNone(warning)
		self.assertEqual([(g["start"], g["end"]) for g in groups], [(0, 1), (2, 3)])

	def test_unknown_boundaries_fall_back_to_one_invoice_per_page(self):
		groups, warning = detect_invoice_groups(["Wartung", "Wartung", "Wartung"])

		self.assertTrue(warning)
		self.assertEqual([(g["start"], g["end"]) for g in groups], [(0, 0), (1, 1), (2, 2)])

	def test_split_pdf_bytes_creates_valid_single_page_pdfs(self):
		try:
			from pypdf import PdfReader, PdfWriter
		except ImportError:
			from PyPDF2 import PdfReader, PdfWriter

		writer = PdfWriter()
		for _index in range(3):
			writer.add_blank_page(width=595, height=842)
		source = io.BytesIO()
		writer.write(source)

		parts, warning, metadata = split_pdf_bytes(source.getvalue())

		self.assertTrue(warning)
		self.assertEqual(metadata["excluded_pages"], [])
		self.assertEqual(len(parts), 3)
		for part in parts:
			self.assertEqual(len(PdfReader(io.BytesIO(part["content"])).pages), 1)

	def test_fixed_pages_per_invoice_keeps_requested_page_blocks(self):
		try:
			from pypdf import PdfReader, PdfWriter
		except ImportError:
			from PyPDF2 import PdfReader, PdfWriter

		writer = PdfWriter()
		for _index in range(5):
			writer.add_blank_page(width=595, height=842)
		source = io.BytesIO()
		writer.write(source)

		parts, warning, metadata = split_pdf_bytes(source.getvalue(), pages_per_invoice=2)

		self.assertTrue(warning)
		self.assertEqual(metadata["included_page_count"], 5)
		self.assertEqual([part["page_count"] for part in parts], [2, 2, 1])
		self.assertEqual(
			[len(PdfReader(io.BytesIO(part["content"])).pages) for part in parts],
			[2, 2, 1],
		)

	def test_excluded_pages_are_removed_before_fixed_size_grouping(self):
		try:
			from pypdf import PdfWriter
		except ImportError:
			from PyPDF2 import PdfWriter

		writer = PdfWriter()
		for _index in range(8):
			writer.add_blank_page(width=595, height=842)
		source = io.BytesIO()
		writer.write(source)

		parts, warning, metadata = split_pdf_bytes(
			source.getvalue(),
			pages_per_invoice=2,
			excluded_pages="3, 6",
		)

		self.assertIsNone(warning)
		self.assertEqual(metadata["excluded_pages"], [3, 6])
		self.assertEqual(metadata["included_page_count"], 6)
		self.assertEqual([part["source_pages"] for part in parts], [[1, 2], [4, 5], [7, 8]])

	def test_excluded_page_ranges_are_parsed(self):
		self.assertEqual(parse_excluded_pages("2, 4-6; 8", page_count=10), [1, 3, 4, 5, 7])

	def test_invalid_or_complete_page_exclusions_are_rejected(self):
		with patch(
			"hausverwaltung.hausverwaltung.services.pdf_invoice_split.frappe.throw",
			side_effect=frappe.ValidationError,
		):
			with self.assertRaises(frappe.ValidationError):
				parse_excluded_pages("2-x", page_count=5)
			with self.assertRaises(frappe.ValidationError):
				parse_excluded_pages("1-5", page_count=5)
			with self.assertRaises(frappe.ValidationError):
				parse_repeated_page_positions("-4", page_count=3)

	def test_repeated_second_page_is_removed_after_grouping(self):
		try:
			from pypdf import PdfWriter
		except ImportError:
			from PyPDF2 import PdfWriter

		writer = PdfWriter()
		for _index in range(6):
			writer.add_blank_page(width=595, height=842)
		source = io.BytesIO()
		writer.write(source)

		parts, warning, metadata = split_pdf_bytes(
			source.getvalue(),
			pages_per_invoice=2,
			excluded_page_positions="2",
		)

		self.assertIsNone(warning)
		self.assertEqual([part["source_pages"] for part in parts], [[1], [3], [5]])
		self.assertEqual(metadata["repeated_excluded_pages"], [2, 4, 6])
		self.assertEqual(metadata["excluded_page_positions"], [2])
		self.assertEqual(metadata["included_page_count"], 3)
		self.assertEqual(metadata["excluded_page_count"], 3)

	def test_repeated_exclusion_keeps_incomplete_last_block(self):
		try:
			from pypdf import PdfWriter
		except ImportError:
			from PyPDF2 import PdfWriter

		writer = PdfWriter()
		for _index in range(5):
			writer.add_blank_page(width=595, height=842)
		source = io.BytesIO()
		writer.write(source)

		parts, warning, metadata = split_pdf_bytes(
			source.getvalue(),
			pages_per_invoice=2,
			excluded_page_positions="2",
		)

		self.assertTrue(warning)
		self.assertEqual([part["source_pages"] for part in parts], [[1], [3], [5]])
		self.assertEqual(metadata["repeated_excluded_pages"], [2, 4])

	def test_minus_one_removes_last_page_of_each_invoice_block(self):
		try:
			from pypdf import PdfWriter
		except ImportError:
			from PyPDF2 import PdfWriter

		writer = PdfWriter()
		for _index in range(6):
			writer.add_blank_page(width=595, height=842)
		source = io.BytesIO()
		writer.write(source)

		parts, warning, metadata = split_pdf_bytes(
			source.getvalue(),
			pages_per_invoice=3,
			excluded_page_positions="-1",
		)

		self.assertIsNone(warning)
		self.assertEqual([part["source_pages"] for part in parts], [[1, 2], [4, 5]])
		self.assertEqual(metadata["repeated_excluded_pages"], [3, 6])
		self.assertEqual(metadata["excluded_page_positions"], [3])

	def test_minus_one_removes_last_page_of_incomplete_final_block(self):
		try:
			from pypdf import PdfWriter
		except ImportError:
			from PyPDF2 import PdfWriter

		writer = PdfWriter()
		for _index in range(5):
			writer.add_blank_page(width=595, height=842)
		source = io.BytesIO()
		writer.write(source)

		parts, warning, metadata = split_pdf_bytes(
			source.getvalue(),
			pages_per_invoice=3,
			excluded_page_positions="-1",
		)

		self.assertTrue(warning)
		self.assertEqual([part["source_pages"] for part in parts], [[1, 2], [4]])
		self.assertEqual(metadata["repeated_excluded_pages"], [3, 5])
		self.assertEqual(metadata["excluded_page_positions"], [3])
		self.assertEqual(metadata["included_page_count"], 3)
		self.assertEqual(metadata["excluded_page_count"], 2)

	def test_negative_page_positions_are_relative_to_block_end(self):
		self.assertEqual(parse_repeated_page_positions("-1", page_count=3), [2])
		self.assertEqual(parse_repeated_page_positions("-2", page_count=3), [1])


if __name__ == "__main__":
	unittest.main()
