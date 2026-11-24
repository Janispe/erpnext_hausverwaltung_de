from email.message import EmailMessage
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import frappe
from frappe.core.doctype.file.utils import find_file_by_url
from frappe.email.receive import InboundMail
from frappe.permissions import add_permission, has_permission
from frappe.tests import IntegrationTestCase
from frappe.www.list import get_list_data

from .issue import set_status, take_incoming_email
from .permissions import zip_files


class TestWohnungsschaden(IntegrationTestCase):
	def setUp(self):
		self.addCleanup(frappe.set_user, "Administrator")
		self.key = uuid4().hex[:10]
		self.email = f"schaden-{self.key}@example.invalid"
		self.property = self.record("Immobilie", "A")
		self.units = [self.record("Wohnung", key, immobilie=self.property.name) for key in ("A", "B")]
		self.debtors = [self.record("Customer", key, customer_name=f"Testdebitor {key}") for key in ("A", "B")]
		contact = frappe.get_doc({"doctype": "Contact", "first_name": "Synthetischer Mehrfachmieter"})
		contact.add_email(self.email, is_primary=True)
		for debtor in self.debtors:
			contact.append("links", {"link_doctype": "Customer", "link_name": debtor.name})
		self.contact = contact.insert()
		self.contracts = [
			self.record(
				"Mietvertrag", key, wohnung=unit.name, kunde=debtor.name, immobilie=self.property.name,
				mieter=[{"mieter": self.contact.name, "rolle": "Hauptmieter"}],
			)
			for key, unit, debtor in zip(("A", "B"), self.units, self.debtors, strict=True)
		]

	def record(self, doctype, key, **values):
		# The workflow relies on these relationships, not accounting or rental setup.
		doc = frappe.get_doc({"doctype": doctype, "name": f"HV67-{self.key}-{key}", **values})
		doc.db_insert()
		for child in doc.get_all_children():
			child.db_insert()
		return doc

	def normal_issue(self):
		return frappe.get_doc({
			"doctype": "Issue",
			"subject": "Synthetischer Support-Eingang",
			"raised_by": self.email,
		}).insert()

	def phone_issue(self):
		return frappe.get_doc({
			"doctype": "Issue",
			"subject": "Telefonisch gemeldeter Schaden",
			"raised_by": self.email,
			"customer": self.debtors[1].name,
			"hv_wohnungsschaden": 1,
			"hv_eingang": "Telefon",
			"hv_telefonnotiz": "Feuchtigkeit neben der Balkontür.",
		}).insert()

	def incoming(self, append_to="Communication"):
		account = self.record(
			"Email Account", "Posteingang", email_id=f"service-{self.key}@example.invalid",
			append_to=append_to,
		)
		message = EmailMessage()
		message["From"] = self.email
		message["To"] = account.email_id
		message["Subject"] = f"Wasser am Fenster {self.key}"
		message["Message-ID"] = f"<{self.key}@example.invalid>"
		message.set_content("Feuchtigkeit am Fenster im Wohnzimmer")
		mail = InboundMail(message.as_bytes(), account).process()
		self.assertEqual(InboundMail(message.as_bytes(), account).process().name, mail.name)
		return mail

	def assign_contract(self, issue, index):
		issue.hv_wohnung = self.units[index].name
		issue.hv_mietvertrag = self.contracts[index].name
		issue.save()
		self.assertEqual(issue.hv_immobilie, self.property.name)
		self.assertEqual(issue.customer, self.debtors[index].name)

	def test_unlinked_mail_is_taken_once_with_its_existing_photo(self):
		mail = self.incoming()
		file = self.photo(mail)
		name = take_incoming_email(mail.name)
		self.assertEqual(take_incoming_email(mail.name), name)
		mail.reload()
		self.assertEqual((mail.reference_doctype, mail.reference_name), ("Issue", name))
		issue = frappe.get_doc("Issue", name)
		self.assertEqual(issue.hv_eingangsmail, mail.name)
		self.assertEqual(issue.hv_eingang, "E-Mail")
		self.assertIn("Fenster", issue.description)
		self.assertFalse(issue.hv_wohnung)
		self.assertFalse(issue.customer)
		self.assertEqual(file.reload().attached_to_name, mail.name)
		self.assign_contract(issue, 1)

	def test_imported_issue_is_converted_in_place_and_normal_issue_keeps_customer(self):
		mail = self.incoming(append_to="Issue")
		self.assertEqual(mail.reference_doctype, "Issue")
		issue = frappe.get_doc("Issue", mail.reference_name)
		self.assertTrue(issue.customer)
		normal = self.normal_issue()
		self.assertEqual(normal.contact, self.contact.name)
		self.assertEqual(normal.customer, self.contact.get_link_for("Customer"))
		self.assertEqual(normal.hv_issue_portal_visible, 1)
		before = frappe.db.count("Issue")
		self.assertEqual(take_incoming_email(mail.name), issue.name)
		self.assertEqual(frappe.db.count("Issue"), before)
		self.assertFalse(issue.reload().customer)
		self.assertFalse(issue.hv_issue_portal_visible)
		self.assign_contract(issue, 0)
		set_status(normal.name, "Closed")
		self.assertEqual(normal.reload().status, "Closed")

	def test_phone_contract_conflict_and_contractor_completion(self):
		issue = self.phone_issue()
		self.assertFalse(issue.customer)
		self.assertFalse(issue.hv_immobilie)
		issue.hv_wohnung = self.units[0].name
		issue.hv_mietvertrag = self.contracts[1].name
		with self.assertRaisesRegex(frappe.ValidationError, "zur gewählten Wohnung"):
			issue.save()

		self.assign_contract(issue.reload(), 0)
		supplier = self.record("Supplier", "Handwerk", supplier_name="Synthetischer Fensterbetrieb")
		issue.update({
			"hv_zustaendig": "Administrator",
			"hv_handwerksbetrieb": supplier.name,
			"hv_handwerkertermin": "2026-12-07 10:30:00",
			"hv_wiedervorlage": "2026-12-08",
			"status": "On Hold",
		}).save()
		issue.reload()
		self.assertEqual(issue.hv_handwerksbetrieb, supplier.name)
		self.assertEqual(str(issue.hv_handwerkertermin), "2026-12-07 10:30:00")
		self.assertEqual(str(issue.hv_wiedervorlage), "2026-12-08")
		with self.assertRaisesRegex(frappe.ValidationError, "Rückmeldung"):
			set_status(issue.name, "Closed")
		issue.update({"hv_rueckmeldung": "Fenster neu abgedichtet, Bereich trocken.", "status": "Resolved"}).save()
		self.assertEqual(issue.reload().status, "Resolved")
		self.assertFalse(issue.hv_anlagenmangel)
		self.assertFalse(issue.hv_versicherungsfall)

	def test_desk_lists_and_downloads_follow_unit_permission(self):
		allowed = self.phone_issue()
		restricted = self.phone_issue()
		self.assign_contract(allowed, 0)
		self.assign_contract(restricted, 1)
		allowed_file = self.photo(allowed, suffix="erlaubt")
		restricted_file = self.photo(restricted, suffix="gesperrt")
		staff = frappe.get_doc({
			"doctype": "User",
			"email": f"bearbeitung-{self.key}@example.invalid",
			"first_name": "Synthetische Schadenbearbeitung",
			"user_type": "System User",
			"send_welcome_email": 0,
			"roles": [{"role": "System Manager"}, {"role": "Hausverwalter"}],
		}).insert()
		for doctype in ("Issue", "Immobilie", "Wohnung", "Mietvertrag"):
			if not has_permission(doctype, user=staff.name, print_logs=False):
				add_permission(doctype, "System Manager", ptype="read")
		frappe.get_doc({
			"doctype": "User Permission",
			"user": staff.name,
			"allow": "Wohnung",
			"for_value": self.units[0].name,
			"apply_to_all_doctypes": 1,
		}).insert()

		frappe.set_user(staff.name)
		self.assertTrue(has_permission("Issue", doc=allowed, print_logs=False))
		self.assertFalse(has_permission("Issue", doc=restricted, print_logs=False))
		issue_names = frappe.get_list(
			"Issue", filters={"name": ("in", [allowed.name, restricted.name])}, pluck="name",
		)
		self.assertEqual(issue_names, [allowed.name])
		self.assertIsNotNone(find_file_by_url(allowed_file.file_url, name=allowed_file.name))
		self.assertIsNone(find_file_by_url(restricted_file.file_url, name=restricted_file.name))

	def photo(self, target, is_private=1, suffix=""):
		return frappe.get_doc({
			"doctype": "File",
			"file_name": f"foto-{self.key}{suffix}.png",
			"content": b"synthetisches Dateimaterial " + (self.key + suffix).encode(),
			"is_private": is_private,
			"attached_to_doctype": target.doctype,
			"attached_to_name": target.name,
		}).insert()

	def test_public_mail_attachment_prevents_conversion(self):
		mail = self.incoming()
		self.photo(mail, is_private=0)
		with self.assertRaisesRegex(frappe.ValidationError, "öffentliche Anhänge"):
			take_incoming_email(mail.name)
		self.assertFalse(mail.reload().reference_name)

	def test_portal_and_file_views_hide_damage_even_from_reporter(self):
		normal = self.normal_issue()
		issue = self.phone_issue()
		file = self.photo(issue, is_private=0)
		self.assertEqual(file.is_private, 1)
		self.assertTrue(file.file_url.startswith("/private/files/"))
		frappe.get_doc({
			"doctype": "User",
			"email": self.email,
			"first_name": "Synthetischer Portalnutzer",
			"user_type": "Website User",
			"send_welcome_email": 0,
			"roles": [{"role": "Customer"}],
		}).insert()
		frappe.db.set_value("Contact", self.contact.name, "user", self.email)
		frappe.db.set_value("File", file.name, "owner", self.email)
		frappe.set_user(self.email)
		self.assertTrue(frappe.has_website_permission(normal))
		self.assertFalse(frappe.has_website_permission(issue))
		self.assertFalse(frappe.get_doc("Web Form", "issues").has_web_form_permission("Issue", issue.name))
		self.assertFalse(has_permission("Issue", doc=issue))
		self.assertIsNone(find_file_by_url(file.file_url, name=file.name))
		zip_files(frappe.as_json([file.name]))
		with ZipFile(BytesIO(frappe.response.filecontent)) as archive:
			self.assertEqual(archive.namelist(), [])
		rows = get_list_data("Issue", web_form_name="issues", hv_issue_portal_visible="0")
		self.assertIn(normal.name, {row.name for row in rows})
		self.assertNotIn(issue.name, {row.name for row in rows})
