import frappe
from frappe.model.document import Document
from frappe.utils import cint


ROLE_NAMES = ("Hausverwalter", "Hausverwalter (Buchung)")
MODULE_NAME = "Hausverwaltung"
BASE_PERMISSIONS = {
	"select": 1,
	"read": 1,
	"create": 1,
	"write": 1,
	"delete": 0,
	"print": 1,
	"email": 1,
	"report": 1,
	"import": 1,
	"export": 1,
	"share": 1,
	"submit": 1,
	"cancel": 1,
	"amend": 1,
}
EXTRA_DOCTYPE_PERMISSIONS = {
	"Company": {
		"Hausverwalter (Buchung)": {
			"select": 1,
			"read": 1,
			"create": 0,
			"write": 0,
			"delete": 0,
			"print": 1,
			"email": 1,
			"report": 1,
			"import": 0,
			"export": 1,
			"share": 1,
			"submit": 0,
			"cancel": 0,
			"amend": 0,
		}
	},
}


def ensure_role(role_name: str):
	"""Create the role when missing; keep desk access if present."""
	if frappe.db.exists("Role", role_name):
		role = frappe.get_doc("Role", role_name)
		if not role.desk_access:
			role.desk_access = 1
			role.save(ignore_permissions=True)
		return

	role = frappe.get_doc(
		{
			"doctype": "Role",
			"role_name": role_name,
			"desk_access": 1,
		}
	)
	role.insert(ignore_permissions=True)


def get_target_permissions(doctype_meta: Document) -> dict[str, int]:
	"""Return the permission map adjusted to DocType capabilities."""
	perms = BASE_PERMISSIONS.copy()

	if not cint(doctype_meta.allow_import):
		perms["import"] = 0

	if not cint(doctype_meta.is_submittable):
		perms["submit"] = 0
		perms["cancel"] = 0
		perms["amend"] = 0

	if cint(doctype_meta.issingle):
		perms["import"] = 0
		perms["export"] = 0

	return perms


def get_permission_doctype(doctype_name: str) -> str:
	"""Use Custom DocPerm when a DocType already has custom permission overrides."""
	if frappe.db.exists("Custom DocPerm", {"parent": doctype_name}):
		return "Custom DocPerm"
	return "DocPerm"


def dedupe_permissions(permission_doctype: str, doctype_name: str, role_name: str) -> int:
	"""Remove duplicate permission rows for the role/permlevel/if_owner combo."""
	entries = frappe.get_all(
		permission_doctype,
		filters={"parent": doctype_name, "role": role_name, "permlevel": 0},
		fields=["name", "if_owner", "modified"],
		order_by="modified desc",
	)
	if not entries:
		return 0

	seen: set[int] = set()
	to_delete: list[str] = []

	for entry in entries:
		if_owner = cint(entry.get("if_owner", 0))
		if if_owner in seen:
			to_delete.append(entry["name"])
			continue
		seen.add(if_owner)

	for name in to_delete:
		frappe.delete_doc(permission_doctype, name, ignore_permissions=True, force=True)

	return len(to_delete)


def upsert_permission(
	doctype_meta: Document, role_name: str, target_perms: dict[str, int] | None = None
):
	"""Ensure a permission entry with the requested flags exists for the role."""
	permission_doctype = get_permission_doctype(doctype_meta.name)
	dedupe_permissions(permission_doctype, doctype_meta.name, role_name)
	target_perms = target_perms or get_target_permissions(doctype_meta)
	existing_perm = frappe.get_all(
		permission_doctype,
		filters={
			"parent": doctype_meta.name,
			"role": role_name,
			"permlevel": 0,
			"if_owner": 0,
		},
		fields=["name"],
		limit=1,
	)

	if existing_perm:
		perm = frappe.get_doc(permission_doctype, existing_perm[0].name)
		changed = False
		for fieldname, value in target_perms.items():
			if perm.get(fieldname) != value:
				perm.set(fieldname, value)
				changed = True
		if changed:
			perm.save(ignore_permissions=True)
		return

	perm = frappe.get_doc(
		{
			"doctype": permission_doctype,
			"parent": doctype_meta.name,
			"parenttype": "DocType",
			"parentfield": "permissions",
			"role": role_name,
			"permlevel": 0,
		}
	)
	for fieldname, value in target_perms.items():
		perm.set(fieldname, value)
	perm.insert(ignore_permissions=True)


def sync_permissions():
	"""Sync permissions for all Hausverwalter roles in the module."""
	doctypes = frappe.get_all("DocType", filters={"module": MODULE_NAME}, pluck="name")
	for doctype in doctypes:
		doctype_meta = frappe.get_cached_doc("DocType", doctype)
		for role_name in ROLE_NAMES:
			upsert_permission(doctype_meta, role_name)

	for doctype, role_permissions in EXTRA_DOCTYPE_PERMISSIONS.items():
		doctype_meta = frappe.get_cached_doc("DocType", doctype)
		for role_name, target_perms in role_permissions.items():
			upsert_permission(doctype_meta, role_name, target_perms)


def execute():
	for role_name in ROLE_NAMES:
		ensure_role(role_name)
	sync_permissions()
