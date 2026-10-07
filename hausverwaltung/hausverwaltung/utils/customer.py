"""Customer helpers used by Mietvertrag and other domain code."""

from __future__ import annotations

import frappe

from hausverwaltung.hausverwaltung.utils.document_naming import make_document_name


def get_or_create_customer_group() -> str:
	"""Stellt sicher, dass die Customer Group *Mieter* existiert."""
	if frappe.db.exists("Customer Group", "Mieter"):
		return "Mieter"

	def _ensure_customer_group_root() -> str:
		for preferred in ("All Customer Groups", "Alle Kundengruppen"):
			try:
				if frappe.db.exists("Customer Group", preferred):
					return preferred
			except Exception:
				pass

		try:
			rows = frappe.get_all(
				"Customer Group",
				fields=["name", "parent_customer_group", "is_group"],
				limit=200,
			)
			for row in rows:
				if row.get("is_group") and not row.get("parent_customer_group"):
					return row["name"]
		except Exception:
			pass

		try:
			doc = (
				frappe.get_doc(
					{
						"doctype": "Customer Group",
						"customer_group_name": "All Customer Groups",
						"is_group": 1,
					}
				)
				.insert(ignore_if_duplicate=True, ignore_permissions=True)
			)
			return doc.name
		except Exception:
			return "All Customer Groups"

	parent = _ensure_customer_group_root()
	return (
		frappe.get_doc(
			{
				"doctype": "Customer Group",
				"customer_group_name": "Mieter",
				"parent_customer_group": parent,
			}
		)
		.insert(ignore_if_duplicate=True, ignore_permissions=True)
		.name
	)


def build_customer_id(wohnlabel: str, von_date: str, nachname: str) -> str:
	"""Reserve a new Debitor ID for an import before its contract is inserted.

	The arguments remain compatible with existing importers. Person, apartment
	and contract dates belong in display fields and do not form the database ID.
	Every call reserves a separate ID; a second tenancy never reuses a Customer.
	"""
	return make_document_name("Customer")


def build_contract_customer_id(base_name: str, mietvertrag: str) -> str:
	"""Reserve a short Debitor ID for a persisted, uniquely identified contract.

	The existing signature remains compatible; the readable prefix is no longer
	part of the database ID. The contract retains its Customer link permanently.
	"""
	contract_name = (mietvertrag or "").strip()
	if not contract_name:
		frappe.throw(
			"Ein Customer kann nicht ohne eindeutigen Mietvertrag angelegt werden.",
			frappe.ValidationError,
		)

	return make_document_name("Customer")


def get_or_create_customer(
	cust_id: str,
	customer_name: str | None = None,
	company: str | None = None,
	*,
	reuse_existing: bool = False,
	hv_display_title: str | None = None,
) -> str:
	"""Erzeugt (oder holt) einen Customer-Datensatz.

	Die Buchung läuft über ein Sammelkonto Debitoren (Company.default_receivable_account);
	pro Customer wird kein eigenes Konto gepinnt.

	Der ``cust_id``-Parameter (typischerweise eine reservierte ``DEB-#####``)
	wird als Doc-Name erzwungen,
	auch wenn ``Selling Settings.cust_master_name`` auf "Naming Series" steht.
	Die ``customer_name``-Anzeige bleibt der Personen-/Familienname.

	Standardmäßig wird eine Namenskollision blockiert. Dieser
	Modus ist für vertragsgebundene Customer zwingend, damit ein fremder
	gleichnamiger Debitor niemals still übernommen wird.
	"""
	customer_name = (customer_name or cust_id or "").strip() or cust_id

	if frappe.db.exists("Customer", cust_id):
		if not reuse_existing:
			frappe.throw(
				f"Customer '{cust_id}' existiert bereits und gehört nicht nachweisbar "
				"zu diesem Mietvertrag. Es wurde kein Customer wiederverwendet.",
				frappe.ValidationError,
			)
		if frappe.db.get_value("Customer", cust_id, "customer_name") != customer_name:
			frappe.db.set_value("Customer", cust_id, "customer_name", customer_name, update_modified=False)
		return cust_id

	group = get_or_create_customer_group()

	doc = frappe.new_doc("Customer")
	doc.customer_name = customer_name
	doc.customer_type = "Individual"
	doc.customer_group = group
	if company:
		doc.company = company
	doc.hv_display_title = (hv_display_title or customer_name).strip()[:240]
	# Die reservierte Debitoren-ID als Doc-Name erzwingen.
	# `flags.name_set` verhindert, dass Frappes autoname-Logik ihn überschreibt
	# (relevant wenn Selling Settings.cust_master_name = "Naming Series").
	doc.name = cust_id
	doc.flags.name_set = True
	# ignore_permissions: Hausverwalter hat KEIN create-Recht auf Customer
	# (Customers werden ausschließlich über diese Funktion erzeugt — kein
	# manuelles Anlegen über die Customer-Liste).
	doc.insert(ignore_permissions=True)
	return doc.name
