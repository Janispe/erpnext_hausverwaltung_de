from email.message import EmailMessage
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZipFile

import frappe
from frappe.core.doctype.communication.email import make as make_communication
from frappe.core.doctype.file.utils import find_file_by_url
from frappe.desk.form.load import get_communications
from frappe.email.receive import InboundMail
from frappe.permissions import add_permission, has_controller_permissions, has_permission, update_permission_property
from frappe.tests import IntegrationTestCase
from frappe.www.list import get_list_data

from hausverwaltung.hausverwaltung.integrations import paperless

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

	def incoming(self, append_to="Communication", message_key="first", reply_to=None):
		account_name = f"HV67-{self.key}-Posteingang"
		if frappe.db.exists("Email Account", account_name):
			account = frappe.get_doc("Email Account", account_name)
		else:
			account = self.record(
				"Email Account", "Posteingang", email_id=f"service-{self.key}@example.invalid",
				append_to=append_to,
			)
		message = EmailMessage()
		message["From"] = self.email
		message["To"] = account.email_id
		message["Subject"] = f"Wasser am Fenster {self.key} {message_key}"
		message["Message-ID"] = f"<{self.key}.{message_key}@example.invalid>"
		if reply_to:
			message["In-Reply-To"] = reply_to.message_id
		message.set_content("Feuchtigkeit am Fenster im Wohnzimmer")
		mail = InboundMail(message.as_bytes(), account).process()
		self.assertEqual(InboundMail(message.as_bytes(), account).process().name, mail.name)
		return mail

	def staff(self, doctypes, *, issue_write=False, issue_if_owner=False):
		staff = frappe.get_doc({
			"doctype": "User",
			"email": f"bearbeitung-{self.key}@example.invalid",
			"first_name": "Synthetische Schadenbearbeitung",
			"user_type": "System User",
			"send_welcome_email": 0,
			"roles": [{"role": "System Manager"}],
		}).insert()
		for doctype in doctypes:
			frappe.clear_cache(doctype=doctype)
			if not has_permission(doctype, user=staff.name, print_logs=False):
				add_permission(doctype, "System Manager", ptype="read")
		update_permission_property("Issue", "System Manager", 0, "write", int(issue_write))
		update_permission_property("Issue", "System Manager", 0, "if_owner", int(issue_if_owner))
		frappe.clear_cache(doctype="Issue")
		return staff

	def assign_contract(self, issue, index):
		issue.hv_wohnung = self.units[index].name
		issue.hv_mietvertrag = self.contracts[index].name
		issue.save()
		self.assertEqual(issue.hv_immobilie, self.property.name)
		self.assertEqual(issue.customer, self.debtors[index].name)

	def test_unlinked_mail_is_taken_once_with_its_existing_photo(self):
		mail = self.incoming()
		reply = self.composer_reply(mail, "Rückfrage vor Zuordnung")
		file = self.photo(mail)
		name = take_incoming_email(mail.name)
		self.assertEqual((reply.reload().reference_doctype, reply.reference_name), ("Issue", name))
		self.assertEqual(reply.in_reply_to, mail.name)
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
		staff = self.staff(("Issue", "Immobilie", "Wohnung", "Mietvertrag"), issue_write=True)
		for issue in (allowed, restricted):
			# The two Issues have the same owner so only the Wohnung scope distinguishes them.
			issue.db_set("owner", staff.name)
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
		self.assertTrue(has_controller_permissions(allowed_file, "read"))
		self.assertFalse(has_controller_permissions(restricted_file, "read"))
		with (
			patch.object(paperless.PaperlessConfig, "from_conf", return_value=SimpleNamespace(url="https://paperless.example/")),
			patch.object(paperless, "_post_to_paperless", return_value=(True, 42, None)) as post,
		):
			result = paperless.export_attachment_to_paperless(
				doctype="Issue", docname=allowed.name, file_url=allowed_file.file_url,
			)
			self.assertEqual(result["paperless_id"], 42)
			for issue, file in ((restricted, restricted_file), (allowed, restricted_file)):
				with self.assertRaises(frappe.PermissionError):
					paperless.export_attachment_to_paperless(
						doctype="Issue", docname=issue.name, file_url=file.file_url,
					)
			post.assert_called_once()

		restricted.hv_wohnung = allowed.hv_wohnung
		restricted.hv_mietvertrag = allowed.hv_mietvertrag
		self.assertTrue(has_permission("Issue", ptype="write", doc=restricted, print_logs=False))
		with self.assertRaisesRegex(frappe.PermissionError, "bisherigen Vorgang"):
			restricted.save()
		self.assertEqual(frappe.db.get_value("Issue", restricted.name, "hv_wohnung"), self.units[1].name)

	def test_damage_mail_and_later_reply_stay_out_of_contact_timeline(self):
		mail = self.incoming(append_to="Issue")
		self.assertIn(self.contact.name, {link.link_name for link in mail.timeline_links})
		issue_name = take_incoming_email(mail.name)
		reply = self.incoming(message_key="reply", reply_to=mail)
		self.assertEqual(reply.reference_name, issue_name)
		self.assertFalse(mail.reload().timeline_links)
		self.assertFalse(reply.reload().timeline_links)
		case_mail = get_communications("Issue", issue_name)
		self.assertEqual({item.name for item in case_mail}, {mail.name, reply.name})

		staff = self.staff(("Issue", "Contact", "Customer"), issue_if_owner=True)
		frappe.set_user(staff.name)
		self.assertFalse(has_permission("Issue", doc=issue_name, print_logs=False))
		self.assertTrue(has_permission("Contact", doc=self.contact, print_logs=False))
		contact_mail = get_communications("Contact", self.contact.name)
		self.assertFalse({mail.name, reply.name}.intersection(item.name for item in contact_mail))

	def composer_reply(self, parent, content):
		result = make_communication(
			doctype="Communication",
			name=parent.name,
			in_reply_to=parent.name,
			subject=f"Re: {parent.subject}",
			content=content,
			sender=f"service-{self.key}@example.invalid",
			recipients=self.email,
			communication_type="Communication",
			send_email=False,
		)
		return frappe.get_doc("Communication", result["name"])

	def test_composer_reply_chain_is_normalized_before_and_after_takeover(self):
		mail = self.incoming(append_to="Issue")
		first = self.composer_reply(mail, "Erste Rückfrage")
		second = self.composer_reply(first, "Zweite Rückfrage")
		self.assertEqual(first.reference_doctype, "Communication")
		self.assertEqual(second.reference_name, first.name)
		self.assertIn(self.contact.name, {link.link_name for link in second.timeline_links})
		photo = self.photo(second)

		issue_name = take_incoming_email(mail.name)
		third = self.composer_reply(second, "Dritte Rückfrage")
		for reply, parent in ((first, mail), (second, first), (third, second)):
			reply.reload()
			self.assertEqual((reply.reference_doctype, reply.reference_name), ("Issue", issue_name))
			self.assertEqual(reply.in_reply_to, parent.name)
			self.assertFalse(reply.timeline_links)

		message_names = {mail.name, first.name, second.name, third.name}
		self.assertEqual({item.name for item in get_communications("Issue", issue_name)}, message_names)
		staff = self.staff(
			("Issue", "Contact", "Customer", "Communication", "File"), issue_if_owner=True,
		)
		frappe.set_user(staff.name)
		self.assertFalse(has_permission("Issue", doc=issue_name, print_logs=False))
		self.assertEqual(
			frappe.get_list("Communication", filters={"name": ("in", sorted(message_names))}, pluck="name"),
			[],
		)
		self.assertFalse(message_names.intersection(item.name for item in get_communications("Contact", self.contact.name)))
		self.assertIsNone(find_file_by_url(photo.file_url, name=photo.name))

	def test_attachment_lists_follow_owner_only_issue_permission(self):
		owned_mail = self.incoming(message_key="owned")
		foreign_mail = self.incoming(message_key="foreign")
		owned = frappe.get_doc("Issue", take_incoming_email(owned_mail.name))
		foreign = frappe.get_doc("Issue", take_incoming_email(foreign_mail.name))
		records = [("Communication", owned_mail.name, foreign_mail.name)]
		owned_file = self.photo(owned_mail, suffix="erlaubt")
		foreign_file = self.photo(foreign_mail, suffix="gesperrt")
		records.append(("File", owned_file.name, foreign_file.name))
		for doctype, fields in (
			("Comment", ("reference_doctype", "reference_name")),
			("Version", ("ref_doctype", "docname")),
		):
			names = [
				self.record(doctype, case.name, **{fields[0]: "Issue", fields[1]: case.name}).name
				for case in (owned, foreign)
			]
			records.append((doctype, *names))

		staff = self.staff(("Issue", "Communication", "File", "Comment", "Version"), issue_if_owner=True)
		frappe.db.set_value("Issue", owned.name, "owner", staff.name)
		frappe.set_user(staff.name)
		self.assertTrue(has_permission("Issue", doc=owned.name, print_logs=False))
		self.assertFalse(has_permission("Issue", doc=foreign.name, print_logs=False))
		for doctype, own, other in records:
			with self.subTest(doctype=doctype):
				rows = frappe.get_list(doctype, filters={"name": ("in", [own, other])}, pluck="name")
				self.assertEqual(rows, [own])

	def photo(self, target, is_private=1, suffix=""):
		return frappe.get_doc({
			"doctype": "File",
			"file_name": f"foto-{self.key}{suffix}.png",
			"content": b"synthetisches Dateimaterial " + (self.key + suffix).encode(),
			"is_private": is_private,
			"attached_to_doctype": target.doctype,
			"attached_to_name": target.name,
		}).insert()

	def test_ordinary_alias_cannot_make_a_shared_damage_attachment_public(self):
		normal = self.normal_issue()
		alias = self.photo(normal, suffix="-shared")
		protected = self.photo(self.phone_issue(), suffix="-shared")
		url = protected.file_url
		self.assertEqual(url, alias.file_url)
		private_path = Path(protected.get_full_path())
		public_path = Path(frappe.get_site_path("public", "files", private_path.name))
		content = private_path.read_bytes()

		alias.is_private = 0
		with self.assertRaisesRegex(frappe.ValidationError, "gemeinsam verwendeten Dateien"):
			alias.save()
		for file in (alias.reload(), protected.reload()):
			self.assertEqual(file.is_private, 1)
			self.assertEqual(file.file_url, url)
		self.assertEqual(private_path.read_bytes(), content)
		self.assertFalse(public_path.exists())

		ordinary = self.photo(normal, suffix="-ordinary")
		ordinary.is_private = 0
		ordinary.save()
		self.assertTrue(ordinary.file_url.startswith("/files/"))

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
