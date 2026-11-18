"""Receipt-specific regressions at the vision transport and accounting boundaries."""

import base64
import io
import json
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from PIL import Image

from hausverwaltung.hausverwaltung.page.buchen_cockpit import buchen_cockpit
from hausverwaltung.hausverwaltung.services import bulk_extraction, receipt_pilot as pilot


class TestReceiptPilot(unittest.TestCase):
	def test_original_photo_and_all_scan_pages_reach_vision(self):
		red, blue = (210, 20, 40), (50, 40, 220)
		photo, scan = io.BytesIO(), io.BytesIO()
		first = Image.new("RGB", (60, 80), red)
		second = Image.new("RGB", (60, 80), blue)
		first.save(photo, format="PNG")
		first.save(scan, format="PDF", save_all=True, append_images=[second])
		prompt = "Anstrich"
		fake_response = {
			"haendler": "Testmarkt",
			"datum": "2026-10-08",
			"waehrung": "EUR",
			"gesamtbetrag": "15.50",
			"positionen": [
				{"beschreibung": "Farbe", "betrag": "10.00", "kostenart": "1"},
				{"beschreibung": "Pinsel", "betrag": "5.50", "kostenart": "99"},
			],
			"kostenstelle": "UNTRUSTED",
			"zahlungskonto": "UNTRUSTED",
		}
		for content, extension, expected in [(photo.getvalue(), "png", [red]), (scan.getvalue(), "pdf", [red, blue])]:
			with self.subTest(extension=extension):
				def observe(messages, **kwargs):
					parts = messages[1]["content"]
					self.assertIn(prompt, parts[0]["text"])
					self.assertEqual(len(parts), len(expected) + 1)
					for item, color in zip(parts[1:], expected, strict=True):
						self.assertEqual(item["type"], "image_url")
						prefix, encoded = item["image_url"].split(",", 1)
						self.assertEqual(prefix, "data:image/png;base64")
						payload = base64.b64decode(encoded, validate=True)
						if extension == "png":
							self.assertEqual(payload, content)
						with Image.open(io.BytesIO(payload)) as image:
							actual = image.convert("RGB").getpixel((image.width // 2, image.height // 2))
						self.assertTrue(all(abs(a - b) < 5 for a, b in zip(actual, color, strict=True)))
					return {"choices": [{"message": {"content": json.dumps(fake_response)}}]}

				category = {"name": prompt, "umlagefaehig": "Kostenart nicht umlagefaehig"}
				with (
					patch.object(pilot.mistral_client, "ensure_configured"),
					patch.object(pilot.mistral_client, "_vision_model", return_value="receipt-vision"),
					patch.object(pilot.mistral_client, "_post_chat", side_effect=observe) as transport,
					patch.object(pilot.invoice_extraction, "_load_kostenarten_for_prompt", return_value=[category]),
					patch.object(pilot.invoice_extraction, "_exact_supplier_lookup", return_value=None),
				):
					data = pilot._extract(content, extension)
				transport.assert_called_once()
				self.assertEqual(data["belegsumme"], 15.5)
				self.assertEqual(data["llm_lieferant"], "Testmarkt")
				self.assertEqual(data["fields"]["rechnungsdatum"], "2026-10-08")
				self.assertEqual([line["kostenart"] for line in data["positionen"]], ["Anstrich", ""])
				self.assertNotIn("kostenstelle", data["positionen"][0])
				self.assertNotIn("zahlungskonto", data)

	def test_no_account_is_inferred_even_when_cost_center_is_valid(self):
		doc = {"receipt_context": {"kostenstelle": "Testobjekt", "zahlungsquelle": "Privat vorgestreckt"}}
		with (
			patch.object(frappe.db, "get_value", return_value=frappe._dict(company="HV", disabled=0, is_group=0)),
			patch.object(frappe, "get_list", return_value=[]),
		):
			result = pilot.review_context(doc)
		self.assertEqual(result["kostenstelle"], "Testobjekt")
		self.assertEqual(result["zahlungskonto"], "")
		self.assertEqual(len(result["fragen"]), 2)

	def test_repeated_upload_and_retry_stay_with_same_original(self):
		batch = str(uuid.uuid4())
		# A per-run pixel avoids relying on previous runs or filename uniqueness.
		image = io.BytesIO()
		Image.new("RGB", (51, 51), tuple(uuid.UUID(batch).bytes[:3])).save(image, format="PNG")
		content = image.getvalue()
		frappe.db.savepoint("receipt_test")
		target = None
		try:
			with patch.object(pilot, "enabled", return_value=True):
				def upload(filename, context):
					request = SimpleNamespace(files={"file": SimpleNamespace(filename=filename, stream=io.BytesIO(content))})
					with patch.object(frappe, "request", request):
						return pilot.upload_receipt(batch, context)

				first = upload("bon.png", {"zahlungsquelle": "Objektkasse"})
				second = upload("nochmal.png", {"zahlungsquelle": "Privat vorgestreckt"})
				self.assertEqual(first["name"], second["name"])
				self.assertTrue(second["existing"])
				doc = frappe.get_doc(pilot.PROPOSAL, first["name"])
				target = Path(pilot.get_files_path(is_private=1)) / doc.file_url.rsplit("/", 1)[-1]
				self.assertEqual(target.read_bytes(), content)
				original, received = pilot.verified_original(doc, for_update=True)
				self.assertTrue(original.is_private)
				self.assertEqual(received, content)
				target.write_bytes(b"changed receipt")
				with self.assertRaisesRegex(ValueError, "stimmt nicht"):
					pilot.verified_original(doc)
				target.unlink()
				with self.assertRaises(FileNotFoundError):
					pilot.verified_original(doc)
				self.assertEqual(json.loads(doc.receipt_context)["zahlungsquelle"], "Objektkasse")
				self.assertEqual(frappe.db.count("File", {"attached_to_doctype": pilot.PROPOSAL, "attached_to_name": doc.name}), 1)
				self.assertEqual(len(bulk_extraction.get_vorschlag_full(doc.name)["receipt"]["fragen"]), 2)
		finally:
			frappe.db.rollback(save_point="receipt_test")
			if target:
				target.unlink(missing_ok=True)

	def test_booking_requires_eur_and_explicit_expense_categories(self):
		category = {"kostenart": "Material", "umlagefaehig": "Kostenart nicht umlagefaehig"}
		foreign = SimpleNamespace(extracted_data=json.dumps({"waehrung": "CHF"}))
		unknown = SimpleNamespace(extracted_data=json.dumps({"waehrung": ""}))
		with self.assertRaisesRegex(frappe.ValidationError, "Fremdwährungsbelege"):
			pilot.validate_booking_confirmation(foreign, [category], eur_confirmed=True)
		with self.assertRaisesRegex(frappe.ValidationError, "in EUR"):
			pilot.validate_booking_confirmation(unknown, [category], eur_confirmed=False)
		with self.assertRaisesRegex(frappe.ValidationError, "Kostenart"):
			pilot.validate_booking_confirmation(
				unknown, [{"umlagefaehig": "Betriebskostenart"}], eur_confirmed=True,
			)
		pilot.validate_booking_confirmation(unknown, [category], eur_confirmed=True)

	def test_reconciles_calculated_total_and_settlement_after_exclusive_item_tax(self):
		with self.assertRaisesRegex(frappe.ValidationError, "Endbetrag"):
			# Gross 100.00 passed as rates, but ERPNext added 19.00 exclusive item tax.
			buchen_cockpit._validate_receipt_total({"net_total": 100, "grand_total": 119}, 100)
		with self.assertRaisesRegex(frappe.ValidationError, "Endbetrag"):
			buchen_cockpit._validate_receipt_total({"grand_total": 100, "outstanding_amount": 119}, 100)
		buchen_cockpit._validate_receipt_total({"grand_total": 100, "outstanding_amount": 100}, 100)

	def test_agent_capability_requires_role_and_booking_checks_ledger_permissions(self):
		with patch.object(pilot, "enabled", return_value=True), patch.object(frappe, "get_roles", return_value=[]):
			with self.assertRaises(frappe.PermissionError):
				pilot.pending_receipts()
			with self.assertRaises(frappe.PermissionError):
				pilot.prepare_receipt("BV-DOES-NOT-EXIST")
		with patch.object(frappe, "has_permission", return_value=False):
			with self.assertRaises(frappe.PermissionError):
				buchen_cockpit.create_purchase_invoice(vorschlag_name="BV-DOES-NOT-EXIST", zahlung_sofort=True)
