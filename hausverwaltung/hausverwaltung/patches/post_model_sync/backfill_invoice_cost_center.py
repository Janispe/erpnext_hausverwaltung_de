"""Backfill `cost_center` on Sales/Purchase Invoice headers and the
corresponding Receivable/Payable GL Entry rows.

Historische Importe aus dem Vorgänger-System haben den Header-`cost_center`
auf Sales/Purchase Invoice leer gelassen. ERPNext kopiert diesen Wert beim
Buchen auf die Receivable/Payable-GL-Zeile, weshalb auch diese leer sind.
Folge: kostenstellen­basierte Filter (z.B. im Report
„Noch offene Rechnungen und Forderungen") finden die historischen Posten
nicht. Auf den Item-Zeilen ist die Kostenstelle hingegen flächendeckend
gepflegt — wir leiten den Header-Wert von dort ab.

Bewusst NICHT in `patches.txt` eingetragen — manuell ausführen pro Umgebung:

    bench --site <site> execute \\
      hausverwaltung.hausverwaltung.patches.post_model_sync.backfill_invoice_cost_center.execute

Idempotent: alle UPDATEs filtern auf leeren cost_center, erneuter Lauf ist
ein No-op. Multi-cc-Rechnungen (mehrere distinkte cc auf den Items) werden
übersprungen — der zugehörige Report-Code löst diesen Fall ohnehin per
Item-Lookup auf.
"""

import frappe


def execute():
	for doctype, item_doctype, account_type in (
		("Sales Invoice", "Sales Invoice Item", "Receivable"),
		("Purchase Invoice", "Purchase Invoice Item", "Payable"),
	):
		_backfill_for_doctype(doctype, item_doctype, account_type)


def _backfill_for_doctype(doctype: str, item_doctype: str, account_type: str) -> None:
	header_table = f"`tab{doctype}`"
	item_table = f"`tab{item_doctype}`"

	header_before = _count_header_null(header_table)
	gl_before = _count_gl_null(doctype, account_type)

	frappe.log(f"[backfill_cc] {doctype}: {header_before} headers ohne cc, {gl_before} GL-Zeilen ({account_type}) ohne cc")

	header_updated = frappe.db.sql(
		f"""
		UPDATE {header_table} hdr
		JOIN (
			SELECT parent, MIN(cost_center) AS cc
			FROM {item_table}
			WHERE cost_center IS NOT NULL AND cost_center <> ''
			GROUP BY parent
			HAVING COUNT(DISTINCT cost_center) = 1
		) items ON items.parent = hdr.name
		SET hdr.cost_center = items.cc
		WHERE (hdr.cost_center IS NULL OR hdr.cost_center = '')
		  AND hdr.docstatus = 1
		"""
	)

	gl_updated = frappe.db.sql(
		f"""
		UPDATE `tabGL Entry` gl
		JOIN {header_table} hdr ON hdr.name = gl.voucher_no
		JOIN `tabAccount` a ON a.name = gl.account
		SET gl.cost_center = hdr.cost_center
		WHERE gl.voucher_type = %(doctype)s
		  AND a.account_type = %(account_type)s
		  AND gl.is_cancelled = 0
		  AND (gl.cost_center IS NULL OR gl.cost_center = '')
		  AND hdr.cost_center IS NOT NULL AND hdr.cost_center <> ''
		  AND hdr.docstatus = 1
		""",
		{"doctype": doctype, "account_type": account_type},
	)

	frappe.db.commit()

	header_after = _count_header_null(header_table)
	gl_after = _count_gl_null(doctype, account_type)

	frappe.log(
		f"[backfill_cc] {doctype}: header backfill schloss "
		f"{header_before - header_after} (übrig: {header_after} multi-cc/leer), "
		f"GL backfill schloss {gl_before - gl_after} (übrig: {gl_after})"
	)


def _count_header_null(header_table: str) -> int:
	return frappe.db.sql(
		f"""
		SELECT COUNT(*) FROM {header_table}
		WHERE docstatus = 1
		  AND (cost_center IS NULL OR cost_center = '')
		"""
	)[0][0]


def _count_gl_null(doctype: str, account_type: str) -> int:
	return frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabGL Entry` gl
		JOIN `tabAccount` a ON a.name = gl.account
		WHERE gl.voucher_type = %(doctype)s
		  AND a.account_type = %(account_type)s
		  AND gl.is_cancelled = 0
		  AND (gl.cost_center IS NULL OR gl.cost_center = '')
		""",
		{"doctype": doctype, "account_type": account_type},
	)[0][0]
