import frappe
from frappe import _
from frappe.permissions import has_permission
from frappe.utils import cint

from .issue import is_damage, is_damage_issue, is_damage_staff

TIMELINE_LINKS = {
	"Comment": ("reference_doctype", "reference_name"),
	"Version": ("ref_doctype", "docname"),
}

OBJECT_LINKS = (
	("hv_immobilie", "Immobilie"),
	("hv_wohnung", "Wohnung"),
	("hv_mietvertrag", "Mietvertrag"),
	("hv_anlagenmangel", "Anlagenmangel"),
	("hv_versicherungsfall", "Versicherungsfall"),
)


def can_access_objects(doc, user):
	return all(
		not doc.get(field) or _can_read_object(doctype, doc.get(field), user)
		for field, doctype in OBJECT_LINKS
	)


def _can_read_object(doctype, name, user):
	if doctype == "Wohnung" and user != "Administrator":
		# Checking the Wohnung document directly loads its computed Mietvertraege tables.
		# Use the native list permission for this single Wohnung without materializing them.
		return has_permission(doctype, user=user, print_logs=False) and bool(
			frappe.get_list(doctype, filters={"name": name}, pluck="name", user=user, limit=1)
		)
	return has_permission(doctype, ptype="read", doc=name, user=user, print_logs=False)


def has_issue_permission(doc, ptype, user=None, **kwargs):
	if not is_damage(doc):
		return True
	return ptype != "share" and is_damage_staff(user) and can_access_objects(doc, user)


def has_website_permission(doc, **kwargs):
	return not is_damage(doc)


class WebFormMixin:
	def has_web_form_permission(self, doctype, name, ptype="read"):
		# The default Web Form also allows access via document ownership.
		if doctype == "Issue" and is_damage_issue(name):
			return False
		return super().has_web_form_permission(doctype, name, ptype)


def issue_match(user=None):
	user = user or frappe.session.user
	if user == "Administrator" or not frappe.get_meta("Issue").has_field("hv_wohnungsschaden"):
		return ""
	normal = "coalesce(`tabIssue`.`hv_wohnungsschaden`, 0) = 0"
	if not is_damage_staff(user):
		return normal

	object_checks = []
	for field, doctype in OBJECT_LINKS:
		link = f"`tabIssue`.`{field}`"
		empty = f"coalesce({link}, '') = ''"
		if has_permission(doctype, user=user, print_logs=False):
			query = frappe.get_list(doctype, fields=["name"], user=user, order_by="name", run=False)
			empty += f" or {link} in ({query})"
		object_checks.append(f"({empty})")
	return f"({normal} or ({' and '.join(object_checks)}))"


def _case_reads(user, issue_name):
	return has_permission("Issue", doc=issue_name, user=user, print_logs=False)


def protected_issue(doctype, name, *, for_update=False):
	if not name:
		return None
	if doctype == "Communication":
		ref = frappe.db.get_value(
			doctype, name, ["reference_doctype", "reference_name"], as_dict=True, for_update=for_update,
		)
		if ref:
			doctype, name = ref.reference_doctype, ref.reference_name
	if doctype == "Issue" and is_damage_issue(name, for_update=for_update):
		return name
	return None


def _allows_reference(doc, doctype_field, name_field, ptype, user):
	issue = protected_issue(doc.get(doctype_field), doc.get(name_field))
	return not issue or (ptype != "share" and _case_reads(user, issue))


def has_communication_permission(doc, ptype, user=None, **kwargs):
	return _allows_reference(doc, "reference_doctype", "reference_name", ptype, user)


def has_timeline_permission(doc, ptype, user=None, **kwargs):
	return _allows_reference(doc, *TIMELINE_LINKS[doc.doctype], ptype, user)


def has_file_permission(doc, ptype, user=None, **kwargs):
	issue = protected_issue(doc.attached_to_doctype, doc.attached_to_name)
	if issue:
		right = "write" if ptype in ("write", "create", "delete") else "read"
		return ptype != "share" and bool(doc.is_private) and has_permission(
			"Issue", ptype=right, doc=issue, user=user, print_logs=False,
		)
	return True


def _issue_ref_match(user, doctype, name):
	condition = issue_match(user)
	if not condition:
		return "1=1"
	# Retain ordinary references. Filter linked damage references using the same object scope as Issue.
	if not has_permission("Issue", user=user, print_logs=False):
		condition = "coalesce(`tabIssue`.`hv_wohnungsschaden`, 0) = 0"
	return f"""not exists (
		select 1 from `tabIssue` where {doctype} = 'Issue' and {name} = `tabIssue`.`name`
		and not ({condition})
	)"""


def communication_match(user=None):
	return _issue_ref_match(user, "`tabCommunication`.`reference_doctype`", "`tabCommunication`.`reference_name`")


def _reference_match(user, doctype, name):
	direct = _issue_ref_match(user, doctype, name)
	return f"""{direct} and not exists (
		select 1 from `tabCommunication`
		where {doctype} = 'Communication'
		and {name} = `tabCommunication`.`name`
		and not ({communication_match(user)})
	)"""


def file_match(user=None):
	return _reference_match(user, "`tabFile`.`attached_to_doctype`", "`tabFile`.`attached_to_name`")


def comment_match(user=None):
	return _reference_match(user, "`tabComment`.`reference_doctype`", "`tabComment`.`reference_name`")


def version_match(user=None):
	return _reference_match(user, "`tabVersion`.`ref_doctype`", "`tabVersion`.`docname`")


def check_attachment_url(url, issue=None, *, communication=False):
	if communication and url.startswith(("https://", "http://")):
		return
	if not url.startswith("/private/files/"):
		frappe.throw(_("Fotos am Wohnungsschaden müssen als private lokale Anhänge gespeichert werden."))
	if issue and not frappe.db.exists(
		"File", {"file_url": url, "is_private": 1, "attached_to_doctype": "Issue", "attached_to_name": issue},
	):
		frappe.throw(_("Bitte die Datei direkt und privat am Wohnungsschaden anhängen."))


def _check_unshared(doctype, names):
	if names and frappe.db.exists("DocShare", {"share_doctype": doctype, "share_name": ("in", names)}):
		frappe.throw(_("Bitte vorhandene Dokumentfreigaben für {0} vor der Übernahme entfernen.").format(doctype))


def check_conversion(issue=None, attachment=None, communication=None):
	mails = (
		frappe.get_all("Communication", filters={"reference_doctype": "Issue", "reference_name": issue}, pluck="name")
		if issue else []
	)
	if communication and communication not in mails:
		mails.append(communication)

	if issue:
		_check_unshared("Issue", [issue])
	if attachment:
		check_attachment_url(attachment, issue)
	_check_unshared("Communication", mails)

	files = []
	for doctype, names in (("Issue", [issue] if issue else []), ("Communication", mails)):
		if names:
			files.extend(frappe.get_all(
				"File", filters={"attached_to_doctype": doctype, "attached_to_name": ("in", names)},
				fields=["name", "file_url", "is_private", "attached_to_doctype"],
			))
	for doctype, (type_field, name_field) in TIMELINE_LINKS.items():
		entries = []
		for target_type, target_names in (("Issue", [issue] if issue else []), ("Communication", mails)):
			if target_names:
				entries.extend(frappe.get_all(
					doctype, filters={type_field: target_type, name_field: ("in", target_names)}, pluck="name",
				))
		_check_unshared(doctype, entries)

	for file in files:
		if not file.is_private:
			frappe.throw(_("Bitte öffentliche Anhänge vor der Übernahme privat speichern."))
		check_attachment_url(file.file_url or "", communication=file.attached_to_doctype == "Communication")
	_check_unshared("File", [file.name for file in files])


class FileMixin:
	def before_insert(self):
		if protected_issue(self.attached_to_doctype, self.attached_to_name, for_update=True):
			if self.file_url:
				check_attachment_url(self.file_url, communication=self.attached_to_doctype == "Communication")
			self.is_private = 1
		return super().before_insert()

	def validate(self):
		previous = self.get_doc_before_save()
		if previous and protected_issue(previous.attached_to_doctype, previous.attached_to_name, for_update=True):
			if (previous.attached_to_doctype, previous.attached_to_name) != (
				self.attached_to_doctype, self.attached_to_name
			):
				frappe.throw(_("Ein geschützter Schadensanhang bleibt mit seinem Vorgang verknüpft."))
		if protected_issue(self.attached_to_doctype, self.attached_to_name, for_update=True):
			self.check_permission("write" if previous else "create")
			if not cint(self.is_private):
				frappe.throw(_("Schadensanhänge müssen privat bleiben."))
			check_attachment_url(self.file_url or "", communication=self.attached_to_doctype == "Communication")
		return super().validate()

	def unzip(self):
		if protected_issue(self.attached_to_doctype, self.attached_to_name):
			self.check_permission("write")
		return super().unzip()

	def is_downloadable(self):
		if protected_issue(self.attached_to_doctype, self.attached_to_name):
			return has_file_permission(self, "read")
		return super().is_downloadable()


def validate_communication(doc, method=None):
	previous = doc.get_doc_before_save()
	if previous and protected_issue(previous.reference_doctype, previous.reference_name):
		if (previous.reference_doctype, previous.reference_name) != (doc.reference_doctype, doc.reference_name):
			frappe.throw(_("Eine Schadensmeldung bleibt mit ihrem Vorgang verknüpft."))
	if protected_issue(doc.reference_doctype, doc.reference_name, for_update=True):
		check_conversion(communication=doc.name)


def validate_share(doc, method=None):
	doctype, name = doc.share_doctype, doc.share_name
	fields = ("attached_to_doctype", "attached_to_name") if doctype == "File" else TIMELINE_LINKS.get(doctype)
	if fields:
		doctype, name = frappe.db.get_value(doctype, name, fields) or (None, None)
	if protected_issue(doctype, name, for_update=True):
		frappe.throw(_("Wohnungsschäden und ihre verknüpften Unterlagen können nicht einzeln freigegeben werden."))


@frappe.whitelist()
def zip_files(files: str):
	from frappe.core.api.file import zip_files as frappe_zip_files

	allowed = []
	for name in frappe.parse_json(files):
		file = frappe.get_doc("File", name)
		if has_file_permission(file, "read"):
			allowed.append(name)
	return frappe_zip_files(frappe.as_json(allowed))
