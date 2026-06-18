from __future__ import annotations

import frappe


FIELDS = [
	"name",
	"supplier",
	"supplier_name",
	"docstatus",
	"status",
	"amended_from",
	"grand_total",
	"outstanding_amount",
	"creation",
	"modified",
]


def _get_purchase_invoice_row(name: str) -> frappe._dict | None:
	return frappe.db.get_value("Purchase Invoice", name, FIELDS, as_dict=True)


@frappe.whitelist()
def get_purchase_invoice_amendment_chain(name: str) -> dict:
	"""Return the full amendment chain for a Purchase Invoice.

	Frappe only stores the direct predecessor on ``amended_from``. The standard
	connections tab therefore does not show the complete amendment chain.
	"""
	if not name:
		frappe.throw("Bitte eine Eingangsrechnung angeben.")

	doc = frappe.get_doc("Purchase Invoice", name)
	doc.check_permission("read")

	root_name = doc.name
	visited: set[str] = set()
	while root_name:
		if root_name in visited:
			frappe.throw("Zyklische Amendment-Verknüpfung gefunden.")
		visited.add(root_name)
		row = _get_purchase_invoice_row(root_name)
		if not row:
			break
		if not row.get("amended_from"):
			break
		root_name = row.get("amended_from")

	chain: list[dict] = []
	seen: set[str] = set()

	def walk(invoice_name: str, depth: int = 0) -> None:
		if not invoice_name or invoice_name in seen:
			return
		seen.add(invoice_name)
		row = _get_purchase_invoice_row(invoice_name)
		if not row:
			return
		children = frappe.get_all(
			"Purchase Invoice",
			filters={"amended_from": invoice_name},
			fields=FIELDS,
			order_by="creation asc",
		)
		chain.append({
			"name": row.name,
			"supplier": row.supplier,
			"supplier_name": row.supplier_name,
			"docstatus": int(row.docstatus or 0),
			"status": row.status,
			"amended_from": row.amended_from,
			"grand_total": row.grand_total,
			"outstanding_amount": row.outstanding_amount,
			"creation": str(row.creation),
			"modified": str(row.modified),
			"depth": depth,
			"is_current": row.name == name,
			"has_successor": bool(children),
		})
		for child in children:
			walk(child.name, depth + 1)

	walk(root_name)

	leaf_rows = [row for row in chain if not row.get("has_successor")]
	active_leaf_rows = [row for row in leaf_rows if int(row.get("docstatus") or 0) != 2]
	latest = (active_leaf_rows or leaf_rows or chain or [{}])[-1]

	previous_name = next((row.get("amended_from") for row in chain if row.get("name") == name), None)
	next_names = [row.get("name") for row in chain if row.get("amended_from") == name]

	return {
		"name": name,
		"root": root_name,
		"latest": latest.get("name"),
		"previous": previous_name,
		"next": next_names,
		"chain": chain,
		"has_chain": len(chain) > 1,
	}
