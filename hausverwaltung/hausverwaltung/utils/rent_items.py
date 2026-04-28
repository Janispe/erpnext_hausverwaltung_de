import frappe

from hausverwaltung.hausverwaltung.utils.income_accounts import get_hv_income_accounts


ITEM_CODES = ("Miete", "Betriebskosten", "Heizkosten")


def _ensure_root_item_group() -> str:
	root_name = "All Item Groups"
	if frappe.db.exists("Item Group", root_name):
		return root_name
	root = frappe.get_doc(
		{
			"doctype": "Item Group",
			"item_group_name": root_name,
			"parent_item_group": "",
			"is_group": 1,
		}
	)
	root.insert(ignore_permissions=True, ignore_mandatory=True)
	return root.name


def _ensure_leaf_item_group() -> str:
	try:
		if frappe.db.exists("Item Group", {"name": "Services", "is_group": 0}):
			return "Services"
	except Exception:
		pass

	try:
		leaf_groups = frappe.get_all("Item Group", filters={"is_group": 0}, fields=["name"], limit=1)
		if leaf_groups:
			return leaf_groups[0]["name"]
	except Exception:
		pass

	root_name = _ensure_root_item_group()
	if not frappe.db.exists("Item Group", "Services"):
		ig = frappe.get_doc(
			{
				"doctype": "Item Group",
				"item_group_name": "Services",
				"parent_item_group": root_name,
				"is_group": 0,
			}
		)
		ig.insert(ignore_permissions=True)
	return "Services"


def _ensure_uom(uom_name: str = "Nos") -> str:
	if frappe.db.exists("UOM", uom_name):
		return uom_name

	try:
		any_uom = frappe.get_all("UOM", fields=["name"], limit=1)
		if any_uom:
			return any_uom[0]["name"]
	except Exception:
		pass

	uom_doc = frappe.get_doc(
		{
			"doctype": "UOM",
			"uom_name": uom_name,
			"must_be_whole_number": 1,
		}
	)
	uom_doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return uom_name


def _pick_income_account(company: str) -> str | None:
	acc = frappe.db.get_value("Company", company, "default_income_account")
	if acc:
		return acc
	rows = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "root_type": "Income"},
		pluck="name",
		limit=1,
	)
	return rows[0] if rows else None


def _ensure_item_defaults(item_code: str, company: str, income_account: str | None) -> None:
	if not income_account:
		return
	try:
		doc = frappe.get_doc("Item", item_code)
	except Exception:
		return

	try:
		rows = getattr(doc, "item_defaults", None) or []
	except Exception:
		rows = []

	for row in rows:
		if getattr(row, "company", None) == company:
			if getattr(row, "income_account", None) != income_account:
				row.income_account = income_account
				doc.save(ignore_permissions=True)
			return

	try:
		doc.append("item_defaults", {"company": company, "income_account": income_account})
		doc.save(ignore_permissions=True)
	except Exception:
		return


def _ensure_item(item_code: str, *, item_group: str, stock_uom: str) -> None:
	payload = {
		"is_stock_item": 0,
		"include_item_in_manufacturing": 0,
		"is_sales_item": 1,
		"disabled": 0,
		"item_group": item_group,
		"stock_uom": stock_uom,
	}

	if frappe.db.exists("Item", item_code):
		try:
			doc = frappe.get_doc("Item", item_code)
			changed = False
			for k, v in payload.items():
				if hasattr(doc, k) and getattr(doc, k) != v:
					setattr(doc, k, v)
					changed = True
			if hasattr(doc, "item_name") and not getattr(doc, "item_name", None):
				doc.item_name = item_code
				changed = True
			if changed:
				doc.save(ignore_permissions=True)
		except Exception:
			pass
		return

	try:
		doc = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": item_code,
				"item_name": item_code,
				**payload,
			}
		)
		doc.insert(ignore_permissions=True)
	except Exception:
		pass


def ensure_rent_items(*, company: str | None = None) -> None:
	"""Ensure required service Items exist for rent invoicing.

	Idempotent, safe to call from install hooks, imports and runtime scripts.
	"""
	try:
		if not frappe.db.exists("DocType", "Item"):
			return
	except Exception:
		return

	item_group = _ensure_leaf_item_group()
	stock_uom = _ensure_uom("Nos")

	for code in ITEM_CODES:
		_ensure_item(code, item_group=item_group, stock_uom=stock_uom)

	if company:
		income_accounts = get_hv_income_accounts(company)
		for code in ITEM_CODES:
			_ensure_item_defaults(code, company, income_accounts.get(code))
		return

	try:
		companies = frappe.get_all("Company", filters={"disabled": 0}, pluck="name")
	except Exception:
		companies = frappe.get_all("Company", pluck="name")

	for c in companies or []:
		income_accounts = get_hv_income_accounts(c)
		for code in ITEM_CODES:
			_ensure_item_defaults(code, c, income_accounts.get(code))
