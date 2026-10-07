"""Read-only fingerprints for checking a naming upgrade on an isolated copy."""

from __future__ import annotations

import hashlib
import json

import frappe

from hausverwaltung.hausverwaltung.utils.document_naming import DOCUMENT_SERIES

REFERENCE_DOCTYPES = (
	"Contact", "Address", "Sales Invoice", "Sales Invoice Item", "Payment Entry",
	"Payment Entry Reference", "GL Entry", "Journal Entry", "Journal Entry Account",
	"File", "Communication", "Mail Archive Message", "Mail Archive Folder",
	"Thunderbird Message", "Prozess Instanz", "Prozess Aufgabe",
)


def reference_snapshot() -> dict:
	"""Fingerprint IDs, audit timestamps, explicit links and embedded references.

	Run before/after migration while writers are stopped. Display titles and the
	series table are deliberately omitted: those are the authorized changes.
	No personal data or raw accounting rows are returned.
	"""
	result = {}
	for doctype in (*DOCUMENT_SERIES, *REFERENCE_DOCTYPES):
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		fields = {"name", "creation", "modified", "modified_by", "owner", "docstatus"}
		fields.update(field.fieldname for field in meta.fields
			if field.fieldtype in ("Link", "Dynamic Link") and not field.is_virtual)
		fields.update(field for field in (
			"mietabrechnung_id", "remarks", "payload_json", "result_json", "tag",
			"message_id", "debit", "credit", "grand_total", "allocated_amount",
			"paid_amount", "received_amount",
		) if meta.has_field(field))
		columns = set(frappe.db.get_table_columns(doctype))
		rows = frappe.get_all(doctype, fields=sorted(fields & columns),
			order_by="name", limit_page_length=0)
		result[doctype] = {
			"count": len(rows),
			"stable_fields_sha256": hashlib.sha256(
				json.dumps(rows, ensure_ascii=False, default=str, sort_keys=True).encode()
			).hexdigest(),
		}
	return result
