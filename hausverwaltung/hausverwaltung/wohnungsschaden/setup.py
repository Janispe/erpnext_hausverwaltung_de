import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def sync_fields():
	"""Install on new sites and keep existing sites in sync during migration."""
	fields = [
		("hv_wohnungsschaden", "Wohnungsschaden", "Check", None),
		("hv_schaden_details", "Wohnungsschaden", "Section Break", None),
		("hv_eingang", "Eingang", "Select", "\nE-Mail\nTelefon"),
		("hv_eingangsmail", "Eingangsmail", "Link", "Communication"),
		("hv_telefonnotiz", "Telefonnotiz", "Small Text", None),
		("hv_immobilie", "Immobilie", "Link", "Immobilie"),
		("hv_wohnung", "Wohnung", "Link", "Wohnung"),
		("hv_mietvertrag", "Bestätigter Mietvertrag", "Link", "Mietvertrag"),
		("hv_zustaendig", "Zuständige Person", "Link", "User"),
		("hv_handwerksbetrieb", "Handwerksbetrieb", "Link", "Supplier"),
		("hv_handwerkertermin", "Handwerkertermin", "Datetime", None),
		("hv_wiedervorlage", "Wiedervorlage", "Date", None),
		("hv_rueckmeldung", "Handwerker-Rückmeldung", "Small Text", None),
		("hv_anlagenmangel", "Anlagenmangel", "Link", "Anlagenmangel"),
		("hv_versicherungsfall", "Versicherungsfall", "Link", "Versicherungsfall"),
	]
	issue_fields = []
	previous = "description"
	for name, label, fieldtype, options in fields:
		field = dict(fieldname=name, label=label, fieldtype=fieldtype, insert_after=previous, no_copy=1)
		if options:
			field["options"] = options
		if name != "hv_wohnungsschaden":
			field["depends_on"] = "eval:doc.hv_wohnungsschaden"
		if name == "hv_eingangsmail":
			field["read_only"] = 1
		if name == "hv_wiedervorlage":
			field["in_standard_filter"] = 1
		issue_fields.append(field)
		previous = name
	issue_fields.append(
		dict(
			fieldname="hv_issue_portal_visible",
			label="Im Issue-Portal sichtbar",
			fieldtype="Check",
			insert_after=previous,
			default="1",
			hidden=1,
			read_only=1,
			no_copy=1,
		)
	)
	create_custom_fields({"Issue": issue_fields}, update=True)
	issues = frappe.qb.DocType("Issue")
	(
		frappe.qb.update(issues)
		.set(issues.hv_issue_portal_visible, 1)
		.where(issues.hv_issue_portal_visible.isnull())
	).run()
