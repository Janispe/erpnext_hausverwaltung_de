import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate

from erpnext.accounts.report.accounts_receivable.accounts_receivable import ReceivablePayableReport
from hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff import (
	PARTLY_PAID_AND_WRITTEN_OFF_STATUS,
	WRITTEN_OFF_STATUS,
)

OUTSTANDING_TOLERANCE = 0.01


def execute(filters=None):
	filters = frappe._dict(filters or {})
	_validate_filters(filters)
	mode = _get_mode(filters)

	rows = []
	for report_mode in _get_report_modes(mode):
		rows.extend(_get_rows_for_mode(filters, report_mode))

	rows.sort(key=lambda row: _sort_key(row, filters))
	return _get_columns(), rows


def _get_rows_for_mode(filters, mode):
	account_type = "Payable" if mode == "Rechnungen" else "Receivable"
	party_type = "Supplier" if mode == "Rechnungen" else "Customer"

	if not _filters_apply_to_mode(filters, account_type):
		return []

	erpnext_filters = frappe._dict(
		{
			"company": filters.company,
			"report_date": filters.bis_faelligkeit,
			"ageing_based_on": "Due Date",
			"calculate_ageing_with": "Report Date",
			"range": "30, 60, 90, 120",
			"party_type": party_type,
			"party": filters.get("party"),
			"party_account": filters.get("party_account"),
			"cost_center": filters.get("cost_center"),
		}
	)

	args = {
		"account_type": account_type,
		"naming_by": (
			["Buying Settings", "supp_master_name"]
			if mode == "Rechnungen"
			else ["Selling Settings", "cust_master_name"]
		),
	}
	include_settled = bool(filters.get("show_settled")) or (
		mode == "Forderungen" and bool(filters.get("show_written_off"))
	)
	report_class = AllRowsReceivableReport if include_settled else ReceivablePayableReport
	_, source_rows, _, _, _, _ = report_class(erpnext_filters).run(args)

	return _filter_and_map_rows(source_rows, filters, mode)


class AllRowsReceivableReport(ReceivablePayableReport):
	def build_data(self):
		for _key, row in self.voucher_balance.items():
			row.outstanding = flt(row.invoiced - row.paid - row.credit_note, self.currency_precision)
			row.outstanding_in_account_currency = flt(
				row.invoiced_in_account_currency
				- row.paid_in_account_currency
				- row.credit_note_in_account_currency,
				self.currency_precision,
			)
			row.invoice_grand_total = row.invoiced
			self.append_row(row)


def _validate_filters(filters):
	if not filters.get("company"):
		frappe.throw(_("Bitte eine Firma wählen."))

	if not filters.get("von_faelligkeit") or not filters.get("bis_faelligkeit"):
		frappe.throw(_("Bitte Von Fälligkeit und Bis Fälligkeit wählen."))

	filters.von_faelligkeit = getdate(filters.von_faelligkeit)
	filters.bis_faelligkeit = getdate(filters.bis_faelligkeit)

	if filters.von_faelligkeit > filters.bis_faelligkeit:
		frappe.throw(_("Von Fälligkeit darf nicht nach Bis Fälligkeit liegen."))

	zahlungsrichtung = filters.get("zahlungsrichtung")
	if zahlungsrichtung and zahlungsrichtung not in (
		"Geld bekommen",
		"Geld bezahlen / erstatten",
		"Ausgeglichen",
	):
		frappe.throw(_("Bitte eine gültige Zahlungsrichtung wählen."))

	sortierung = filters.get("sortierung") or "Fällig am"
	if sortierung not in (
		"Fällig am",
		"Richtung: Geld bekommen zuerst",
		"Richtung: Geld bezahlen zuerst",
		"Offener Betrag absteigend",
	):
		frappe.throw(_("Bitte eine gültige Sortierung wählen."))


def _get_mode(filters):
	mode = filters.get("mode") or "Forderungen"
	if mode not in ("Forderungen", "Rechnungen", "Beides"):
		frappe.throw(_("Bitte Forderungen, Rechnungen oder Beides wählen."))
	return mode


def _get_report_modes(mode):
	if mode == "Beides":
		return ("Forderungen", "Rechnungen")
	return (mode,)


def _filters_apply_to_mode(filters, account_type):
	if filters.get("party_account"):
		return (
			frappe.db.get_value("Account", filters.party_account, "account_type") == account_type
		)

	return bool(
		frappe.db.exists(
			"Account",
			{
				"company": filters.company,
				"account_type": account_type,
				"is_group": 0,
				"disabled": 0,
			},
		)
	)


def _filter_and_map_rows(source_rows, filters, mode):
	rows = []
	show_settled = bool(filters.get("show_settled"))
	show_written_off = bool(filters.get("show_written_off"))
	voucher_type = filters.get("voucher_type")

	for row in source_rows or []:
		row = frappe._dict(row)

		due_date = row.get("due_date")
		if not due_date:
			continue

		due_date = getdate(due_date)
		if due_date < filters.von_faelligkeit or due_date > filters.bis_faelligkeit:
			continue

		if voucher_type and row.get("voucher_type") != voucher_type:
			continue

		outstanding = flt(row.get("outstanding"))
		invoice_status = _get_sales_invoice_status(row) if mode == "Forderungen" else None
		is_written_off = invoice_status in (WRITTEN_OFF_STATUS, PARTLY_PAID_AND_WRITTEN_OFF_STATUS)
		if (
			not show_settled
			and abs(outstanding) <= OUTSTANDING_TOLERANCE
			and not (show_written_off and is_written_off)
		):
			continue

		direction = _get_payment_direction(mode, outstanding)
		if filters.get("zahlungsrichtung") and direction != filters.get("zahlungsrichtung"):
			continue

		rows.append(
			{
				"aktion": "",
				"art": mode,
				"zahlungsrichtung": direction,
				"status": invoice_status,
				"party_type": row.get("party_type"),
				"faellig_am": due_date,
				"buchungsdatum": row.get("posting_date"),
				"party": row.get("party"),
				"party_account": row.get("party_account"),
				"belegart": row.get("voucher_type"),
				"belegnummer": row.get("voucher_no"),
				"rechnungsbetrag": row.get("invoiced"),
				"bezahlt": row.get("paid"),
				"offen": outstanding,
				"alter_tage": row.get("age"),
				"kostenstelle": row.get("cost_center"),
				"waehrung": row.get("currency"),
				"can_write_off": _can_write_off_row(row, mode, outstanding, invoice_status),
			}
		)

	return rows


def _get_payment_direction(mode, outstanding):
	if abs(flt(outstanding)) <= OUTSTANDING_TOLERANCE:
		return "Ausgeglichen"
	if mode == "Forderungen":
		return "Geld bekommen" if flt(outstanding) > 0 else "Geld bezahlen / erstatten"
	if mode == "Rechnungen":
		return "Geld bezahlen / erstatten" if flt(outstanding) > 0 else "Geld bekommen"
	return ""


def _sort_key(row, filters):
	sortierung = filters.get("sortierung") or "Fällig am"
	base = (
		row.get("faellig_am") or getdate(nowdate()),
		row.get("art") or "",
		row.get("party") or "",
		row.get("belegnummer") or "",
	)
	if sortierung == "Richtung: Geld bekommen zuerst":
		return (0 if row.get("zahlungsrichtung") == "Geld bekommen" else 1, *base)
	if sortierung == "Richtung: Geld bezahlen zuerst":
		return (
			0 if row.get("zahlungsrichtung") == "Geld bezahlen / erstatten" else 1,
			*base,
		)
	if sortierung == "Offener Betrag absteigend":
		return (-abs(flt(row.get("offen"))), *base)
	return base


def _get_sales_invoice_status(row):
	if row.get("voucher_type") != "Sales Invoice":
		return None
	return frappe.db.get_value("Sales Invoice", row.get("voucher_no"), "status")


def _can_write_off_row(row, mode, outstanding, invoice_status=None):
	if mode != "Forderungen":
		return 0
	if row.get("voucher_type") != "Sales Invoice":
		return 0
	if flt(outstanding) <= OUTSTANDING_TOLERANCE:
		return 0

	invoice = frappe.db.get_value(
		"Sales Invoice",
		row.get("voucher_no"),
		["docstatus", "is_return", "status"],
		as_dict=True,
	)
	if not invoice:
		return 0
	if int(invoice.get("docstatus") or 0) != 1 or int(invoice.get("is_return") or 0):
		return 0
	if (invoice_status or invoice.get("status")) in (
		WRITTEN_OFF_STATUS,
		PARTLY_PAID_AND_WRITTEN_OFF_STATUS,
	):
		return 0
	return 1


def _get_columns():
	return [
		{"label": _("Aktion"), "fieldname": "aktion", "fieldtype": "HTML", "width": 110},
		{"label": _("Fällig am"), "fieldname": "faellig_am", "fieldtype": "Date", "width": 100},
		{"label": _("Buchungsdatum"), "fieldname": "buchungsdatum", "fieldtype": "Date", "width": 110},
		{"label": _("Art"), "fieldname": "art", "fieldtype": "Data", "width": 100},
		{"label": _("Richtung"), "fieldname": "zahlungsrichtung", "fieldtype": "Data", "width": 130},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 150},
		{"label": _("Party Type"), "fieldname": "party_type", "fieldtype": "Data", "hidden": 1},
		{
			"label": _("Partei"),
			"fieldname": "party",
			"fieldtype": "Dynamic Link",
			"options": "party_type",
			"width": 240,
		},
		{
			"label": _("Konto"),
			"fieldname": "party_account",
			"fieldtype": "Link",
			"options": "Account",
			"width": 220,
		},
		{"label": _("Belegart"), "fieldname": "belegart", "fieldtype": "Data", "width": 120},
		{
			"label": _("Belegnummer"),
			"fieldname": "belegnummer",
			"fieldtype": "Dynamic Link",
			"options": "belegart",
			"width": 190,
		},
		{
			"label": _("Rechnungsbetrag"),
			"fieldname": "rechnungsbetrag",
			"fieldtype": "Currency",
			"options": "waehrung",
			"width": 130,
		},
		{
			"label": _("Bezahlt"),
			"fieldname": "bezahlt",
			"fieldtype": "Currency",
			"options": "waehrung",
			"width": 120,
		},
		{
			"label": _("Offen"),
			"fieldname": "offen",
			"fieldtype": "Currency",
			"options": "waehrung",
			"width": 120,
		},
		{"label": _("Alter Tage"), "fieldname": "alter_tage", "fieldtype": "Int", "width": 90},
		{
			"label": _("Kostenstelle"),
			"fieldname": "kostenstelle",
			"fieldtype": "Link",
			"options": "Cost Center",
			"width": 160,
		},
		{
			"label": _("Währung"),
			"fieldname": "waehrung",
			"fieldtype": "Link",
			"options": "Currency",
			"width": 80,
		},
	]
