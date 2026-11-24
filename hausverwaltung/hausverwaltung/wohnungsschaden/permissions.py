import frappe
from frappe import _
from frappe.permissions import has_permission
from frappe.utils import cint
from pypika.functions import Coalesce, NullIf

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
	visited = set()
	while doctype == "Communication" and name and name not in visited:
		visited.add(name)
		doctype, name = frappe.db.get_value(
			"Communication", name, ["reference_doctype", "reference_name"], for_update=for_update,
		) or (None, None)
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
	user = user or frappe.session.user
	if user == "Administrator" or not frappe.get_meta("Issue").has_field("hv_wohnungsschaden"):
		return "1=1"
	# Include native Issue restrictions (such as if-owner) as well as the damage object scope.
	unreadable = "damage_issue.`hv_wohnungsschaden` = 1"
	if is_damage_staff(user) and has_permission("Issue", user=user, print_logs=False):
		readable = frappe.get_list("Issue", fields=["name"], user=user, order_by="name", run=False)
		unreadable += f" and damage_issue.`name` not in ({readable})"
	return f"""not exists (
		select 1 from `tabIssue` as damage_issue where {doctype} = 'Issue' and {name} = damage_issue.`name`
		and {unreadable}
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


def _communication_tree(issue, communication):
	mails = set()
	if issue:
		mails.update(frappe.qb.get_query(
			"Communication", fields=["name"], filters={"reference_doctype": "Issue", "reference_name": issue},
			for_update=True,
		).run(pluck=True))
	if communication:
		mails.add(communication)

	frontier = mails.copy()
	while frontier:
		replies = frappe.qb.get_query(
			"Communication",
			fields=["name"],
			filters={"reference_doctype": "Communication", "reference_name": ("in", sorted(frontier))},
			for_update=True,
		).run(pluck=True)
		frontier = set(replies) - mails
		mails.update(frontier)
	return sorted(mails)


def check_conversion(issue=None, attachment=None, communication=None):
	mails = _communication_tree(issue, communication)

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
	return mails


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


def bind_communications_to_issue(issue, communications):
	if not communications:
		return
	frappe.db.delete(
		"Communication Link",
		{"parenttype": "Communication", "parentfield": "timeline_links", "parent": ("in", communications)},
	)

	# Keep the actual reply chain and make the Issue the permission boundary for each message.
	mail = frappe.qb.DocType("Communication")
	(
		frappe.qb.update(mail)
		.set(mail.in_reply_to, Coalesce(NullIf(mail.in_reply_to, ""), mail.reference_name))
		.set(mail.reference_owner, frappe.db.get_value("Issue", issue, "owner"))
		.set(mail.reference_doctype, "Issue")
		.set(mail.reference_name, issue)
		.where((mail.reference_doctype == "Communication") & mail.name.isin(communications))
	).run()


def validate_communication(doc, method=None):
	previous = doc.get_doc_before_save()
	issue = protected_issue(doc.reference_doctype, doc.reference_name, for_update=True)
	if previous:
		previous_issue = protected_issue(previous.reference_doctype, previous.reference_name)
		if previous_issue and previous_issue != issue:
			frappe.throw(_("Eine Schadensmeldung bleibt mit ihrem Vorgang verknüpft."))
	if issue:
		communications = check_conversion(communication=doc.name)
		bind_communications_to_issue(issue, [name for name in communications if name != doc.name])

		if doc.reference_doctype == "Communication":
			doc.in_reply_to = doc.in_reply_to or doc.reference_name
			doc.reference_doctype = "Issue"
			doc.reference_name = issue
			doc.reference_owner = frappe.db.get_value("Issue", issue, "owner")
		# The stock timeline reads this child table without a Communication permission check.
		doc.set("timeline_links", [])


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
