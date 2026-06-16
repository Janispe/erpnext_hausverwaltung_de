import re

import frappe
from erpnext.accounts.report.accounts_receivable.accounts_receivable import ReceivablePayableReport
from frappe import _
from frappe.utils import flt, getdate, nowdate

from hausverwaltung.hausverwaltung.report.mieterkonto.mieterkonto import ITEM_CATEGORY_MAP
from hausverwaltung.hausverwaltung.utils.report_helpers import enrich_link_titles
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

	if filters.get("gruppieren_pro_monat", 1):
		rows = _group_rows_by_mietabrechnung(rows)

	rows.sort(key=lambda row: _sort_key(row, filters))
	columns = _get_columns(filters)
	enrich_link_titles(rows, columns)
	return columns, rows


def _group_rows_by_mietabrechnung(rows):
	"""Aggregiert Sales-Invoice-Rows derselben Mietabrechnung zu einer Zeile.

	Bucket-Schlüssel: (mietabrechnung_id, party, party_account). G/N-SIs bleiben
	einzeln und werden nicht in die Monatsmiete gemischt. Die zugehörige
	Sammel-Zahlung (Payment Entry) erscheint hier ohnehin nicht, weil der Report
	pro Voucher (SI/PE/JE) eine Row liefert — Payment-Entry-Rows haben keine
	mietabrechnung_id und werden nicht aggregiert.

	Beträge werden summiert; Status worst-case (Overdue → ein Member Overdue);
	Belegnummer = erste SI als Drill-Down-Link, "(+N)" in Belegart.
	"""
	if not rows:
		return rows

	si_rows_by_no = {
		row.get("belegnummer"): row
		for row in rows
		if row.get("belegart") == "Sales Invoice" and row.get("belegnummer")
	}
	if not si_rows_by_no:
		return rows

	mab_map = {}
	if frappe.db.has_column("Sales Invoice", "mietabrechnung_id"):
		for r in frappe.get_all(
			"Sales Invoice",
			filters={"name": ("in", list(si_rows_by_no.keys()))},
			fields=["name", "mietabrechnung_id"],
		):
			value = (r.get("mietabrechnung_id") or "").strip()
			if value:
				mab_map[r["name"]] = value

	if not mab_map:
		return rows

	gn_invoice_names = _resolve_guthaben_nachzahlung_invoice_names(si_rows_by_no)

	# Bucket Aggregat-Members; Pass-through für alles ohne mab_id.
	out = []
	buckets: dict[tuple, dict] = {}
	bucket_position: dict[tuple, int] = {}

	def _worst_status(a, b):
		# "Overdue" dominiert; sonst beibehalten was schon drin ist.
		order = {None: 0, "Paid": 1, "Partly Paid": 2, "Unpaid": 3, "Overdue": 4}
		return a if order.get(a, 0) >= order.get(b, 0) else b

	for row in rows:
		mab = mab_map.get(row.get("belegnummer")) if row.get("belegart") == "Sales Invoice" else None
		if not mab or row.get("belegnummer") in gn_invoice_names:
			out.append(row)
			continue

		key = (mab, row.get("party"), row.get("party_account"))
		if key not in buckets:
			merged = dict(row)
			merged["_member_count"] = 1
			merged["_member_voucher_nos"] = [row.get("belegnummer")]
			merged["_member_remarks"] = [row.get("bemerkungen")]
			# Aggregat verlinkt weiterhin die erste Member-SI (Dynamic Link OK).
			buckets[key] = merged
			bucket_position[key] = len(out)
			out.append(merged)
		else:
			merged = buckets[key]
			merged["rechnungsbetrag"] = flt(merged.get("rechnungsbetrag")) + flt(row.get("rechnungsbetrag"))
			merged["bezahlt"] = flt(merged.get("bezahlt")) + flt(row.get("bezahlt"))
			merged["offen"] = flt(merged.get("offen")) + flt(row.get("offen"))
			# Worst-Case-Verbindlichkeit: ältestes Fälligkeitsdatum, höchstes Alter.
			if row.get("faellig_am") and (
				not merged.get("faellig_am") or row["faellig_am"] < merged["faellig_am"]
			):
				merged["faellig_am"] = row["faellig_am"]
			if row.get("alter_tage") and (row["alter_tage"] or 0) > (merged.get("alter_tage") or 0):
				merged["alter_tage"] = row["alter_tage"]
			merged["status"] = _worst_status(merged.get("status"), row.get("status"))
			merged["zahlungsrichtung"] = _zahlungsrichtung_after_merge(merged)
			merged["can_write_off"] = max(
				int(merged.get("can_write_off") or 0),
				int(row.get("can_write_off") or 0),
			)
			merged["mahnstufe"] = max(
				int(merged.get("mahnstufe") or 0),
				int(row.get("mahnstufe") or 0),
			)
			merged["_member_count"] += 1
			merged["_member_voucher_nos"].append(row.get("belegnummer"))
			merged["_member_remarks"].append(row.get("bemerkungen"))

	# Aggregate finalisieren. `belegart` muss der echte DocType bleiben,
	# weil die Belegnummer-Spalte ein Dynamic Link auf dieses Feld ist.
	for merged in buckets.values():
		count = merged.pop("_member_count", 1)
		member_voucher_nos = [name for name in merged.pop("_member_voucher_nos", []) if name]
		member_remarks = [remark for remark in merged.pop("_member_remarks", []) if remark]
		if member_voucher_nos:
			merged["member_voucher_nos"] = member_voucher_nos
		if member_remarks:
			merged["bemerkungen"] = _combine_monthly_sollstellung_remarks(member_remarks)
		if count > 1:
			merged["beleg_count"] = count

	return out


def _combine_monthly_sollstellung_remarks(remarks: list[str]) -> str:
	"""Verdichtet Member-Bemerkungen wie Miete/BK/HK 06/2026 fürs Aggregat."""
	seen: set[str] = set()
	parts: list[str] = []
	for remark in remarks:
		value = str(remark or "").strip()
		if value and value not in seen:
			seen.add(value)
			parts.append(value)
	if not parts:
		return ""

	parsed = [_parse_monthly_sollstellung_remark(part) for part in parts]
	if all(parsed):
		periods = {period for _label, period in parsed}
		if len(periods) == 1:
			period = periods.pop()
			sort_order = {"Miete": 0, "BK": 1, "HK": 2, "UMZ": 3}
			labels = [
				label
				for label, _period in sorted(
					parsed,
					key=lambda item: sort_order.get(item[0], 99),
				)
			]
			return f"{', '.join(labels)} {period}"

	return " · ".join(parts)


def _parse_monthly_sollstellung_remark(remark: str) -> tuple[str, str] | None:
	match = re.fullmatch(r"(Miete|BK|HK|UMZ)\s+(\d{2}/\d{4})", str(remark or "").strip())
	if not match:
		return None
	return match.group(1), match.group(2)


def _resolve_guthaben_nachzahlung_invoice_names(si_rows_by_no):
	invoice_names = list(si_rows_by_no)
	if not invoice_names:
		return set()

	gn_names = set()
	for item in frappe.get_all(
		"Sales Invoice Item",
		filters={"parent": ("in", invoice_names)},
		fields=["parent", "item_code", "amount", "base_amount"],
	):
		if ITEM_CATEGORY_MAP.get(item.get("item_code")) != "guthaben_nachzahlungen":
			continue
		if abs(flt(item.get("base_amount") or item.get("amount"))) > OUTSTANDING_TOLERANCE:
			gn_names.add(item.get("parent"))
	return gn_names


def _zahlungsrichtung_after_merge(merged):
	# Aggregation läuft nur über Sales Invoices (Forderungen-Mode); zur Sicherheit
	# nehmen wir trotzdem `art` aus dem gemergten Row.
	return _get_payment_direction(merged.get("art") or "Forderungen", flt(merged.get("offen")))


def _get_rows_for_mode(filters, mode):
	account_type = "Payable" if mode == "Rechnungen" else "Receivable"
	party_type = "Supplier" if mode == "Rechnungen" else "Customer"

	if not _filters_apply_to_mode(filters, account_type):
		return []

	# Stichtag für Outstanding-Berechnung ist immer heute. ``bis_faelligkeit``
	# ist ein Filter aufs due_date (siehe ``_filter_and_map_rows``) und darf
	# NICHT als Stichtag verwendet werden — sonst ignoriert ERPNext alle
	# GL-Entries nach ``bis_faelligkeit`` und Rechnungen aus späteren Perioden
	# fehlen komplett im Report.
	report_date = getdate(nowdate())

	# ``cost_center`` bewusst NICHT durchreichen: ERPNext filtert auf
	# ``gl_entry.cost_center``. Bei historisch importierten Sales/Purchase
	# Invoices war der Header-cost_center leer und damit auch die zugehörige
	# Receivable-/Payable-GL-Zeile — diese Forderungen wären für den Filter
	# unsichtbar. Auf Item-Ebene ist die Kostenstelle dagegen flächendeckend
	# gepflegt; wir matchen sie selbst in ``_filter_and_map_rows``. Eine
	# einmalige Backfill-Patch (``patches/post_model_sync/
	# backfill_invoice_cost_center.py``) hat die Bestandsdaten bereits
	# nachgezogen — der Item-Match bleibt aber als Defense-in-Depth für
	# künftige Imports und für theoretische Multi-Kostenstellen-Rechnungen.
	erpnext_filters = frappe._dict(
		{
			"company": filters.company,
			"report_date": report_date,
			"ageing_based_on": "Due Date",
			"calculate_ageing_with": "Report Date",
			"range": "30, 60, 90, 120",
			"party_type": party_type,
			"party": filters.get("party"),
			"party_account": filters.get("party_account"),
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

	# Beide Datums-Filter sind optional. Leer = kein Lower- bzw. Upper-Bound auf
	# due_date. Wenn ``bis_faelligkeit`` leer ist, nutzen wir heute als Stichtag
	# (= "was ist gerade noch offen"). Wenn nur ``von_faelligkeit`` leer ist,
	# kein Lower-Bound (zeigt also alle historischen Treffer mit).
	if filters.get("von_faelligkeit"):
		filters.von_faelligkeit = getdate(filters.von_faelligkeit)
	else:
		filters.von_faelligkeit = None

	if filters.get("bis_faelligkeit"):
		filters.bis_faelligkeit = getdate(filters.bis_faelligkeit)
	else:
		filters.bis_faelligkeit = None

	if (
		filters.von_faelligkeit
		and filters.bis_faelligkeit
		and filters.von_faelligkeit > filters.bis_faelligkeit
	):
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
	cost_center_filter = filters.get("cost_center")
	invoice_cc_map = _resolve_invoice_cost_centers(source_rows)
	remarks_map = _resolve_voucher_remarks(source_rows)
	abschlagsplan_payment_entries = _resolve_abschlagsplan_payment_entries(source_rows)

	for row in source_rows or []:
		row = frappe._dict(row)
		is_abschlagszahlung = (
			row.get("voucher_type") == "Payment Entry"
			and row.get("voucher_no") in abschlagsplan_payment_entries
		)
		if filters.get("hide_abschlagszahlungen") and is_abschlagszahlung:
			continue

		# Fallback auf posting_date für Vouchers ohne due_date (Journal Entries
		# und unallokierte Payment Entries / Vorauszahlungen). Sonst würden
		# diese komplett aus dem Report ausgefiltert, obwohl sie offene
		# Forderungen/Verbindlichkeiten darstellen.
		due_date = row.get("due_date") or row.get("posting_date")
		if not due_date:
			continue

		due_date = getdate(due_date)
		if filters.von_faelligkeit and due_date < filters.von_faelligkeit:
			continue
		if filters.bis_faelligkeit and due_date > filters.bis_faelligkeit:
			continue

		if voucher_type and row.get("voucher_type") != voucher_type:
			continue

		row_ccs = _row_cost_centers(row, invoice_cc_map)
		if cost_center_filter and cost_center_filter not in row_ccs:
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

		direction = "Abschlag" if is_abschlagszahlung else _get_payment_direction(mode, outstanding)
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
				"kostenstelle": _format_cost_centers(row_ccs) or row.get("cost_center"),
				"waehrung": row.get("currency"),
				"bemerkungen": remarks_map.get((row.get("voucher_type"), row.get("voucher_no"))),
				"can_write_off": _can_write_off_row(row, mode, outstanding, invoice_status),
				"mahnstufe": _get_mahnstufe_row(row, mode),
			}
		)

	return rows


def _resolve_abschlagsplan_payment_entries(source_rows):
	"""Payment Entries ermitteln, die als Abschlagsplan-Zahlung verknüpft sind."""
	payment_entries = {
		(row or {}).get("voucher_no")
		for row in source_rows or []
		if (row or {}).get("voucher_type") == "Payment Entry" and (row or {}).get("voucher_no")
	}
	if not payment_entries:
		return set()

	rows = frappe.db.sql(
		"""
		SELECT DISTINCT zpz.payment_entry
		FROM `tabZahlungsplan Zeile` zpz
		INNER JOIN `tabZahlungsplan` zp ON zp.name = zpz.parent
		WHERE zp.modus = 'Abschlagsplan'
		  AND zpz.payment_entry IN %(payment_entries)s
		""",
		{"payment_entries": tuple(payment_entries)},
		as_dict=True,
	)
	return {row.get("payment_entry") for row in rows if row.get("payment_entry")}


def _resolve_invoice_cost_centers(source_rows):
	"""Sammelt Header- und Item-Kostenstellen für alle Sales/Purchase Invoice-
	Vouchers in ``source_rows``.

	Liefert ``dict[(voucher_type, voucher_no), set[str]]``. Wird genutzt, um
	den Kostenstellen-Filter selbst auszuwerten — siehe Begründung in
	``_get_rows_for_mode``.
	"""
	by_type = {"Sales Invoice": set(), "Purchase Invoice": set()}
	for row in source_rows or []:
		vtype = (row or {}).get("voucher_type")
		vno = (row or {}).get("voucher_no")
		if vtype in by_type and vno:
			by_type[vtype].add(vno)

	cc_map = {}
	for vtype, names in by_type.items():
		if not names:
			continue
		names_list = list(names)
		for name, cc in frappe.get_all(
			vtype,
			filters={"name": ["in", names_list]},
			fields=["name", "cost_center"],
			as_list=True,
		):
			if cc:
				cc_map.setdefault((vtype, name), set()).add(cc)
		for parent, cc in frappe.get_all(
			f"{vtype} Item",
			filters={"parent": ["in", names_list]},
			fields=["parent", "cost_center"],
			as_list=True,
		):
			if cc:
				cc_map.setdefault((vtype, parent), set()).add(cc)
	return cc_map


def _resolve_voucher_remarks(source_rows):
	"""Lädt das Remarks-Feld pro Voucher, in einem Batch pro Belegart."""
	by_type: dict[str, set[str]] = {}
	for row in source_rows or []:
		vtype = (row or {}).get("voucher_type")
		vno = (row or {}).get("voucher_no")
		if vtype and vno:
			by_type.setdefault(vtype, set()).add(vno)

	remark_field = {
		"Sales Invoice": "remarks",
		"Purchase Invoice": "remarks",
		"Payment Entry": "remarks",
		"Journal Entry": "user_remark",
	}

	out: dict[tuple, str] = {}
	for vtype, names in by_type.items():
		field = remark_field.get(vtype)
		if not field or not names:
			continue
		for name, remark in frappe.get_all(
			vtype,
			filters={"name": ["in", list(names)]},
			fields=["name", field],
			as_list=True,
		):
			if remark:
				out[(vtype, name)] = remark
	return out


def _row_cost_centers(row, invoice_cc_map):
	vtype = row.get("voucher_type")
	if vtype in ("Sales Invoice", "Purchase Invoice"):
		ccs = set(invoice_cc_map.get((vtype, row.get("voucher_no")), ()))
		if row.get("cost_center"):
			ccs.add(row.get("cost_center"))
		return ccs
	if row.get("cost_center"):
		return {row.get("cost_center")}
	return set()


def _format_cost_centers(cost_centers):
	if not cost_centers:
		return None
	if len(cost_centers) == 1:
		return next(iter(cost_centers))
	return ", ".join(sorted(cost_centers))


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


def _get_mahnstufe_row(row, mode):
	if mode != "Forderungen" or row.get("voucher_type") != "Sales Invoice":
		return 0
	sales_invoice = row.get("voucher_no")
	if not sales_invoice:
		return 0

	dunning_names = set()
	if frappe.db.has_column("Dunning", "sales_invoice"):
		dunning_names.update(frappe.get_all(
			"Dunning",
			filters={"docstatus": 1, "sales_invoice": sales_invoice},
			pluck="name",
		))

	table_field = frappe.get_meta("Dunning").get_field("overdue_payments")
	if table_field and table_field.options:
		child_dt = table_field.options
		if frappe.db.has_column(child_dt, "sales_invoice"):
			parents = frappe.get_all(
				child_dt,
				filters={"parenttype": "Dunning", "sales_invoice": sales_invoice},
				pluck="parent",
			)
			parents = list(set(parents))
			if parents:
				dunning_names.update(frappe.get_all(
					"Dunning",
					filters={"name": ("in", parents), "docstatus": 1},
					pluck="name",
				))

	return min(4, len(dunning_names))


def _get_columns(filters):
	mode = filters.get("mode") or "Forderungen"
	columns = []

	if filters.get("show_aktion"):
		columns.append(
			{"label": _("Aktion"), "fieldname": "aktion", "fieldtype": "HTML", "width": 110}
		)

	columns.extend(
		[
			{"label": _("Buchungsdatum"), "fieldname": "buchungsdatum", "fieldtype": "Date", "width": 110},
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
		]
	)

	if mode == "Beides":
		columns.append({"label": _("Art"), "fieldname": "art", "fieldtype": "Data", "width": 100})

	columns.extend(
		[
			{"label": _("Party Type"), "fieldname": "party_type", "fieldtype": "Data", "hidden": 1},
			{
				"label": _("Partei"),
				"fieldname": "party",
				"fieldtype": "Dynamic Link",
				"options": "party_type",
				"width": 240,
			},
			{
				"label": _("Bemerkungen"),
				"fieldname": "bemerkungen",
				"fieldtype": "Small Text",
				"width": 240,
			},
			{
				"label": _("Konto"),
				"fieldname": "party_account",
				"fieldtype": "Link",
				"options": "Account",
				"width": 220,
			},
			{"label": _("Richtung"), "fieldname": "zahlungsrichtung", "fieldtype": "Data", "width": 130},
			{"label": _("Belegart"), "fieldname": "belegart", "fieldtype": "Data", "hidden": 1},
			{
				"label": _("Belegnummer"),
				"fieldname": "belegnummer",
				"fieldtype": "Dynamic Link",
				"options": "belegart",
				"width": 190,
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
			{"label": _("Fällig am"), "fieldname": "faellig_am", "fieldtype": "Date", "width": 100},
		]
	)

	return columns
