import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from PIL import Image
from process_engine.process_engine.processes import ProcessEngine
from werkzeug.wrappers import Request

from hausverwaltung.hausverwaltung.integrations import paperless
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture

from .doctype.wohnungsabnahme import process, wohnungsabnahme as abnahme

DAY = "2026-01-01"


def _fixtures():
	_, _, _, flat, old = fixture(compact=True, with_contact=True)
	old.bis = "2025-12-31"
	old.save()
	contact = frappe.get_doc({
		"doctype": "Contact", "first_name": "Einzug", "last_name": frappe.generate_hash(length=10),
	}).insert()
	new = frappe.get_doc({
		"doctype": "Mietvertrag", "wohnung": flat.name, "von": DAY,
		"mieter": [{"mieter": contact.name, "rolle": "Hauptmieter"}],
	}).insert()
	meter = frappe.get_doc({
		"doctype": "Zaehler", "zaehlerart": "Strom", "zaehlernummer": frappe.generate_hash(length=12),
	}).insert()
	frappe.get_doc({
		"doctype": "Zaehler Zuordnung", "zaehler": meter.name,
		"bezugsobjekt_typ": "Wohnung", "bezugsobjekt": flat.name, "von": "2025-01-01",
	}).insert()
	return flat, old, new, meter


def seed_mobile_test():
	from hausverwaltung.cypress_fixtures import _check_disposable_site

	_check_disposable_site()
	flat, old, new, meter = _fixtures()
	assert old.kunde != new.kunde
	return {"wohnung": flat.name, "old": old.name, "new": new.name, "meter": meter.name, "day": DAY}


class TestWohnungsabnahme(IntegrationTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, frappe.session.user)
		frappe.set_user("Administrator")
		self.flat, self.old, self.new, self.meter = _fixtures()
		self.assertNotEqual(self.old.kunde, self.new.kunde)

	def _draft(self, contract, direction, value="45,5", stand=0, **overrides):
		content = {
			"rooms": [{"id": "zimmer", "label": "Wohnzimmer", "condition": "Sauber", "defects": "Kratzer"}],
			"keys": [{"label": "Haustür", "count": 2}],
			"meters": [{"name": self.meter.name, "date": DAY, "value": value}],
			**overrides,
		}
		return abnahme.save_draft(contract.name, direction, DAY, json.dumps(content), stand)

	def _photo(self, view):
		image = BytesIO()
		Image.new("RGB", (30, 20), "#334455").save(image, "PNG")
		image.seek(0)
		previous = getattr(frappe.local, "request", None)
		frappe.local.request = Request.from_values(method="POST", data={"photo": (image, "testfoto.png")})
		try:
			return abnahme.upload_photo(view["name"], view["stand"], "zimmer")
		finally:
			frappe.local.request = previous

	def _complete(self, draft):
		return abnahme.complete(draft["name"], draft["stand"])

	def _reading_rows(self):
		return frappe.get_all("Zaehlerstand", filters={"parent": self.meter.name, "datum": DAY}, pluck="zaehlerstand")

	def _process(self):
		if not frappe.db.exists("Prozess Typ", "mieterwechsel"):
			frappe.get_doc({
				"doctype": "Prozess Typ", "name1": "mieterwechsel", "label": "Mieterwechsel",
			}).insert()
		doc = frappe.get_doc({
			"doctype": process.PROCESS, "name": "TEST-MW-" + frappe.generate_hash(length=10),
			"prozess_typ": "mieterwechsel", "status": "Entwurf", "orchestrator_backend": "local",
			"payload_json": json.dumps({
				"wohnung": self.flat.name, "alter_mietvertrag": self.old.name, "neuer_mietvertrag": self.new.name,
			}),
			"aufgaben": [{
				"aufgabe": "Abnahmeprotokoll", "step_key": "abnahmeprotokoll", "task_type": "paperless_export",
				"pflicht": 1, "status": "Offen",
			}],
		})
		# The public app need not install a Mieterwechsel version. Supply the
		# same runtime task as the real definition, without the private plugins.
		doc.set_user_and_timestamp()
		doc.db_insert()
		for row in doc.aufgaben:
			row.db_insert()
		return doc

	def test_two_protocols_conflict_retry_and_paperless(self):
		out = self._photo(self._draft(self.old, "Auszug"))
		resumed = abnahme.load(self.old.name, "Auszug")["draft"]
		self.assertEqual(out, resumed)
		photo = frappe.get_doc("File", out["rooms"][0]["photos"][0]["name"])
		self.assertTrue(photo.is_private)
		self.assertTrue(photo.file_url.startswith("/private/files/"))
		self.assertEqual(photo.attached_to_name, out["name"])

		export_config = SimpleNamespace(url="https://paperless.example/")
		with patch.object(abnahme, "render_pdf", side_effect=RuntimeError("simulierter PDF-Fehler")):
			with self.assertRaisesRegex(RuntimeError, "PDF-Fehler"):
				self._complete(out)
		self.assertFalse(frappe.db.get_value(abnahme.DOCTYPE, out["name"], "protokoll"))
		self.assertEqual(self._reading_rows(), [])

		out_done = self._complete(out)
		self.assertEqual(self._complete(out), out_done)
		in_draft = self._draft(self.new, "Einzug", "46")
		conflict = self._complete(in_draft)
		self.assertIn("45.5", conflict["klaerfall"])
		self.assertIn("46", conflict["klaerfall"])
		self.assertFalse(conflict["protokoll"])
		self.assertEqual(self._reading_rows(), [45.5])
		in_done = self._complete(self._draft(self.new, "Einzug", stand=conflict["stand"]))
		self.assertNotEqual(in_done["protokoll"], out_done["protokoll"])
		self.assertEqual(self._reading_rows(), [45.5])
		for item in (in_done, out_done):
			file = frappe.get_doc("File", {"file_url": item["protokoll"]})
			self.assertEqual(file.attached_to_name, item["name"])
			self.assertTrue(file.is_private)
			self.assertTrue(file.get_content(encodings=[]).startswith(b"%PDF"))

		change = self._process()
		self.assertEqual({step["name"] for step in abnahme.load(self.old.name, "Auszug")["steps"]}, {change.name})
		self.assertEqual(process.process_contracts(change.name), {"Einzug": self.new.name, "Auszug": self.old.name})
		engine = ProcessEngine.for_instance(change)
		task = change.aufgaben[0].name
		process.select_protocol(out_done["name"], change.name)
		with self.assertRaisesRegex(frappe.ValidationError, "bereits eine Datei"):
			process.select_protocol(in_done["name"], change.name)

		with (
			patch.object(paperless.PaperlessConfig, "from_conf", return_value=export_config),
			patch.object(paperless, "_ensure_tag_ids", return_value=[]),
			patch.object(paperless, "_find_protocol_document", side_effect=[None, 22]),
			patch.object(paperless, "_post_to_paperless", return_value=(True, 21, None)) as post,
		):
			first = engine.export_file_task_to_paperless(change.name, task)["link"]
			self.assertEqual(engine.export_file_task_to_paperless(change.name, task)["link"], first)
			process.select_protocol(in_done["name"], change.name)
			second = engine.export_file_task_to_paperless(change.name, task)["link"]
			self.assertNotEqual(first, second)
			process.select_protocol(out_done["name"], change.name)
			self.assertEqual(engine.export_file_task_to_paperless(change.name, task)["link"], first)
			post.assert_called_once()

	def test_validation_and_access(self):
		employee = frappe.get_doc({
			"doctype": "User", "email": f"{frappe.generate_hash(length=12)}@example.invalid",
			"first_name": "Hausverwalter", "send_welcome_email": 0,
			"roles": [{"role": "Hausverwalter"}],
		}).insert()
		frappe.set_user(employee.name)
		draft = self._photo(self._draft(self.old, "Auszug"))
		self.assertEqual(abnahme.load(self.old.name, "Auszug")["draft"], draft)
		photo = frappe.get_doc("File", draft["rooms"][0]["photos"][0]["name"])
		self.assertTrue(photo.is_downloadable())
		self.assertFalse(photo.has_permission("write"))
		self.assertNotEqual(photo.owner, employee.name)
		with self.assertRaisesRegex(frappe.ValidationError, "inzwischen geändert"):
			self._draft(self.old, "Auszug")
		with self.assertRaisesRegex(frappe.ValidationError, "nicht zugeordnet"):
			self._complete(self._draft(self.old, "Auszug", stand=draft["stand"], meters=[
				{"name": self.meter.name, "date": "2024-12-31", "value": "10"},
			]))
		frappe.set_user("Administrator")
		doc = frappe.get_doc(abnahme.DOCTYPE, draft["name"])
		doc.protokoll = "/private/files/manipuliert.pdf"
		with self.assertRaisesRegex(frappe.ValidationError, "Formular Wohnungsabnahme"):
			doc.save()
		user = frappe.get_doc({
			"doctype": "User", "email": f"{frappe.generate_hash(length=12)}@example.invalid",
			"first_name": "Ohne Berechtigung", "send_welcome_email": 0,
		}).insert()
		frappe.set_user(user.name)
		with self.assertRaises(frappe.PermissionError):
			abnahme.load(self.old.name, "Auszug")
		with self.assertRaises(frappe.PermissionError):
			abnahme.complete(draft["name"], draft["stand"])
		self.assertFalse(photo.is_downloadable())


	def test_pending_archive_is_retried_without_reupload(self):
		upload = paperless.PaperlessUpload(file_name="test.pdf", content=b"pdf", checksum=paperless._checksum(b"pdf"))
		name = frappe.generate_hash(length=12)
		key = f"hv:wohnungsabnahme:paperless:{name}:{upload.checksum}"
		self.addCleanup(frappe.cache.delete_value, key)
		with (
			patch.object(paperless, "_find_protocol_document", return_value=None),
			patch.object(paperless, "_post_to_paperless", return_value=(True, None, "test-task")) as post,
			patch.object(paperless, "_paperless_get", side_effect=[
				[{"task_id": "test-task", "status": "STARTED"}],
				[{"task_id": "test-task", "status": "SUCCESS", "related_document": "42"}],
			]),
		):
			with self.assertRaisesRegex(frappe.ValidationError, "noch nicht bestätigt"):
				paperless._export_protocol(None, name, None, upload, [], None)
			paperless._export_protocol(None, name, None, upload, [], None)
			self.assertEqual(upload.paperless_id, 42)
			post.assert_called_once()

	def test_archive_lookup_checks_the_original_bytes(self):
		upload = paperless.PaperlessUpload(file_name="test.pdf", content=b"pdf", checksum=paperless._checksum(b"pdf"))
		with patch.object(paperless, "_paperless_get", side_effect=[
			{"results": [{"id": 41, "original_file_name": "test.pdf"}, {"id": 42, "original_file_name": "test.pdf"}]},
			{"original_checksum": "wrong"},
			{"original_checksum": upload.checksum},
		]):
			self.assertEqual(paperless._find_protocol_document(None, upload), 42)
