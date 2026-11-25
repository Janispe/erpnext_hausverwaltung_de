import json

import frappe
from erpnext.support.doctype.issue import issue as erpnext_issue
from frappe import _
from frappe.permissions import has_permission
from frappe.utils import cint


def is_damage(doc):
	return bool(cint(doc.get("hv_wohnungsschaden")))


def is_damage_issue(name, *, for_update=False):
	return bool(
		name and frappe.get_meta("Issue").has_field("hv_wohnungsschaden")
		and cint(frappe.db.get_value("Issue", name, "hv_wohnungsschaden", for_update=for_update))
	)


def is_damage_staff(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or (
		frappe.get_cached_value("User", user, "user_type") == "System User"
		and bool({"Hausverwalter", "System Manager"}.intersection(frappe.get_roles(user)))
	)


class IssueMixin:
	# Frappe's website list applies this condition even when ERPNext lists without Desk permissions.
	website = {"condition_field": "hv_issue_portal_visible"}

	def set_lead_contact(self, email_id):
		if not is_damage(self):
			return super().set_lead_contact(email_id)

		# A reporter can belong to several debtors. Only the explicit contract can set Customer.
		self.customer = None
		self.customer_name = None

	@frappe.whitelist()
	def split_issue(self, subject, communication_id):
		if is_damage(self):
			frappe.throw(_("Wohnungsschäden können nicht über „Issue teilen“ aufgeteilt werden."))
		return super().split_issue(subject, communication_id)


def validate_issue(doc, method=None):
	previous = doc.get_doc_before_save()
	if previous and is_damage(previous) and not is_damage(doc):
		frappe.throw(_("Ein Wohnungsschaden kann nicht in ein normales Issue zurückgewandelt werden."))

	doc.hv_issue_portal_visible = int(not is_damage(doc))
	if not is_damage(doc):
		# Prevent a standard Issue from storing hidden damage information.
		for field in frappe.get_meta("Issue").fields:
			if field.fieldname.startswith("hv_") and field.depends_on == "eval:doc.hv_wohnungsschaden":
				doc.set(field.fieldname, None)
		return

	if not is_damage_staff() or doc.via_customer_portal:
		frappe.throw(_("Wohnungsschäden werden intern in der Hausverwaltung bearbeitet."), frappe.PermissionError)
	if previous and not has_permission("Issue", ptype="write", doc=previous, print_logs=False):
		frappe.throw(_("Keine Schreibberechtigung für den bisherigen Vorgang."), frappe.PermissionError)

	if doc.hv_eingang == "Telefon":
		if not (doc.hv_telefonnotiz or "").strip() or doc.hv_eingangsmail:
			frappe.throw(_("Bitte eine Telefonnotiz ohne Eingangsmail erfassen."))
	elif doc.hv_eingang == "E-Mail" and doc.hv_eingangsmail:
		if not previous or previous.hv_eingangsmail != doc.hv_eingangsmail:
			if not doc.flags.hv_link_incoming_mail:
				frappe.throw(_("Bitte die Eingangsmail vom Communication-Formular übernehmen."))
	else:
		frappe.throw(_("Bitte den Eingang per Telefon erfassen oder eine E-Mail übernehmen."))

	if previous and previous.hv_eingangsmail and previous.hv_eingangsmail != doc.hv_eingangsmail:
		frappe.throw(_("Die übernommene Eingangsmail bleibt am Wohnungsschaden verknüpft."))

	if doc.hv_wohnung:
		property_name = frappe.db.get_value("Wohnung", doc.hv_wohnung, "immobilie")
		if doc.hv_immobilie and doc.hv_immobilie != property_name:
			frappe.throw(_("Die Wohnung gehört nicht zur gewählten Immobilie."))
		doc.hv_immobilie = property_name

	if doc.hv_mietvertrag:
		contract = frappe.get_doc("Mietvertrag", doc.hv_mietvertrag)
		if not doc.hv_wohnung or contract.wohnung != doc.hv_wohnung:
			frappe.throw(_("Der gewählte Mietvertrag muss zur gewählten Wohnung gehören."))
		if contract.docstatus == 2 or not contract.kunde:
			frappe.throw(_("Der Mietvertrag muss gültig sein und einen Customer haben."))
		if frappe.db.exists("Mietvertrag", {"kunde": contract.kunde, "name": ("!=", contract.name)}):
			frappe.throw(_("Der Customer ist mehreren Mietverträgen zugeordnet."))
		doc.customer = contract.kunde
		doc.customer_name = frappe.db.get_value("Customer", contract.kunde, "customer_name")

	from .permissions import bind_communications_to_issue, can_access_objects, check_conversion

	if not can_access_objects(doc, frappe.session.user):
		frappe.throw(_("Keine Leseberechtigung für die Zuordnung des Wohnungsschadens."), frappe.PermissionError)
	if previous and not is_damage(previous):
		communications = check_conversion(doc.name, doc.attachment)
		bind_communications_to_issue(doc.name, communications)
	elif doc.attachment:
		from .permissions import check_attachment_url

		check_attachment_url(doc.attachment, doc.name)

	if doc.status in ("Resolved", "Closed") and not (doc.hv_rueckmeldung or "").strip():
		if previous and doc.flags.ignore_permissions and doc.flags.ignore_mandatory:
			# ERPNext's auto-close job saves Replied issues with both flags.
			doc.status = previous.status
		else:
			frappe.throw(_("Bitte vor der Erledigung die Rückmeldung erfassen."))


def check_issue_delete(doc, method=None):
	if is_damage(doc):
		if not frappe.has_permission("Issue", ptype="delete", doc=doc):
			raise frappe.PermissionError


@frappe.whitelist(methods=["POST"])
def take_incoming_email(communication: str):
	if not is_damage_staff():
		raise frappe.PermissionError

	# Serialize retries and simultaneous clicks on the existing inbox record.
	mail = frappe.get_doc("Communication", communication, for_update=True)
	mail.check_permission("read")
	if mail.communication_medium != "Email" or mail.sent_or_received != "Received":
		frappe.throw(_("Bitte eine eingegangene E-Mail auswählen."))

	if mail.reference_doctype == "Issue" and mail.reference_name:
		issue = frappe.get_doc("Issue", mail.reference_name, for_update=True)
		issue.check_permission("read")
		if is_damage(issue):
			return issue.name
		issue.check_permission("write")
	elif mail.reference_name:
		frappe.throw(_("Die E-Mail ist bereits mit einem anderen Vorgang verknüpft."))
	else:
		mail.check_permission("write")
		issue = frappe.new_doc("Issue")
		issue.subject = mail.subject or _("Wohnungsschaden per E-Mail")
		issue.raised_by = mail.sender

	if not issue.description:
		issue.description = mail.content
	if issue.status in ("Resolved", "Closed"):
		issue.status = "Open"

	from .permissions import check_conversion

	check_conversion(communication=mail.name)
	issue.update({"hv_wohnungsschaden": 1, "hv_eingang": "E-Mail", "hv_eingangsmail": mail.name})
	issue.flags.hv_link_incoming_mail = True
	issue.save()
	if not mail.reference_name:
		mail.update({"reference_doctype": "Issue", "reference_name": issue.name, "status": "Linked"})
		mail.save()
	return issue.name


@frappe.whitelist()
def set_status(name, status):
	if not is_damage_issue(name):
		return erpnext_issue.set_status(name, status)
	issue = frappe.get_doc("Issue", name)
	issue.status = status
	issue.save()


@frappe.whitelist()
def set_multiple_status(names, status):
	for name in json.loads(names):
		set_status(name, status)
