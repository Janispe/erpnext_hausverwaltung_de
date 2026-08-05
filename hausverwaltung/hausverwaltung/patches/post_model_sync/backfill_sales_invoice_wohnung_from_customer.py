"""Fehlende Wohnungsdimensionen auf Sales Invoices per Customer ergänzen.

Customer und Mietvertrag sind fachlich 1:1 verknüpft. Der Patch übernimmt die
Wohnung deshalb nur, wenn für den Customer exakt ein Mietvertrag mit einer
nichtleeren Wohnung existiert. Bestehende oder widersprüchliche Dimensionen
werden niemals überschrieben.

Bei eingereichten Rechnungen reicht ein reines Header-Update nicht aus:
Positionen und GL Entries müssen dieselbe Accounting Dimension tragen. Der
Patch aktualisiert daher alle drei Ebenen gemeinsam innerhalb der von Frappe
verwalteten Patch-Transaktion. Beträge und Konten bleiben unverändert.
"""

from __future__ import annotations

import frappe


_TEMP_TABLE = "_hv_sales_invoice_wohnung_backfill"
_REQUIRED_COLUMNS = (
	("Sales Invoice", "wohnung"),
	("Sales Invoice Item", "wohnung"),
	("GL Entry", "wohnung"),
)


def _candidate_select_sql() -> str:
	return """
		SELECT
			si.name AS invoice_name,
			unique_contract.wohnung
		FROM `tabSales Invoice` si
		INNER JOIN (
			SELECT
				mv.kunde,
				MIN(mv.wohnung) AS wohnung
			FROM `tabMietvertrag` mv
			WHERE COALESCE(mv.kunde, '') != ''
			GROUP BY mv.kunde
			HAVING COUNT(*) = 1
			   AND MIN(COALESCE(mv.wohnung, '')) != ''
		) unique_contract
		  ON unique_contract.kunde = si.customer
		WHERE COALESCE(si.wohnung, '') = ''
		  AND NOT EXISTS (
				SELECT 1
				FROM `tabSales Invoice Item` sii
				WHERE sii.parent = si.name
				  AND COALESCE(sii.wohnung, '') != ''
				  AND sii.wohnung != unique_contract.wohnung
		  )
		  AND NOT EXISTS (
				SELECT 1
				FROM `tabGL Entry` gl
				WHERE gl.voucher_type = 'Sales Invoice'
				  AND gl.voucher_no = si.name
				  AND COALESCE(gl.wohnung, '') != ''
				  AND gl.wohnung != unique_contract.wohnung
		  )
	"""


def execute() -> None:
	if not all(
		frappe.db.has_column(doctype, fieldname)
		for doctype, fieldname in _REQUIRED_COLUMNS
	):
		return

	frappe.db.sql(f"DROP TEMPORARY TABLE IF EXISTS `{_TEMP_TABLE}`")
	try:
		frappe.db.sql(
			f"""
			CREATE TEMPORARY TABLE `{_TEMP_TABLE}` (
				invoice_name VARCHAR(140) NOT NULL PRIMARY KEY,
				wohnung VARCHAR(140) NOT NULL
			) ENGINE=InnoDB
			AS
			{_candidate_select_sql()}
			"""
		)
		count_row = frappe.db.sql(
			f"SELECT COUNT(*) AS total FROM `{_TEMP_TABLE}`",
			as_dict=True,
		)
		total = int(count_row[0].get("total") or 0) if count_row else 0
		if not total:
			return

		# Zuerst Child- und Ledgerdimensionen, den sichtbaren Header zuletzt.
		# Die Patch-Transaktion stellt sicher, dass kein Teilzustand committed wird.
		frappe.db.sql(
			f"""
			UPDATE `tabSales Invoice Item` sii
			INNER JOIN `{_TEMP_TABLE}` candidates
			  ON candidates.invoice_name = sii.parent
			SET sii.wohnung = candidates.wohnung
			WHERE COALESCE(sii.wohnung, '') = ''
			"""
		)
		frappe.db.sql(
			f"""
			UPDATE `tabGL Entry` gl
			INNER JOIN `{_TEMP_TABLE}` candidates
			  ON candidates.invoice_name = gl.voucher_no
			SET gl.wohnung = candidates.wohnung
			WHERE gl.voucher_type = 'Sales Invoice'
			  AND COALESCE(gl.wohnung, '') = ''
			"""
		)
		frappe.db.sql(
			f"""
			UPDATE `tabSales Invoice` si
			INNER JOIN `{_TEMP_TABLE}` candidates
			  ON candidates.invoice_name = si.name
			SET si.wohnung = candidates.wohnung
			WHERE COALESCE(si.wohnung, '') = ''
			"""
		)
		print(
			"backfill_sales_invoice_wohnung_from_customer: "
			f"rechnungen={total}"
		)
	finally:
		frappe.db.sql(f"DROP TEMPORARY TABLE IF EXISTS `{_TEMP_TABLE}`")
