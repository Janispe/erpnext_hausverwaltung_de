from __future__ import annotations

import re
from datetime import date

import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from frappe import _
from frappe.utils import cint, cstr, get_last_day, getdate

from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import (
	lock_mietvertrag_booking_identity,
)
from hausverwaltung.hausverwaltung.utils.sollstellung_titel import build_sollstellung_titel
from hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff import (
	get_sales_invoice_writeoff_status,
)

_MV_MARKER_RE = re.compile(r"\[MV:([^\]\r\n]+)\]")
_MIETABRECHNUNG_PERIOD_RE = re.compile(r"(?:0[1-9]|1[0-2])/\d{4}")


def default_wertstellungsdatum_from_posting_date(doc):
	"""Default Sales Invoice value date to posting date when no explicit value exists."""
	if not doc.meta.has_field("custom_wertstellungsdatum"):
		return
	if doc.get("custom_wertstellungsdatum") or not doc.get("posting_date"):
		return

	doc.set("custom_wertstellungsdatum", getdate(doc.get("posting_date")))


def _contract_reference(
	*,
	mietabrechnung_id: object,
	remarks: object,
	document_label: str,
) -> frappe._dict:
	"""Extract one unambiguous Mietvertrag reference or fail closed."""
	structured_id = cstr(mietabrechnung_id or "").strip()
	structured_mv = None
	if structured_id:
		mv_part, separator, period = structured_id.rpartition("|")
		if (
			not separator
			or not mv_part.strip()
			or not _MIETABRECHNUNG_PERIOD_RE.fullmatch(period.strip())
		):
			frappe.throw(
				_(
					"{0} enthält eine ungültige mietabrechnung_id ({1}). Erwartet "
					"wird '<Mietvertrag>|MM/JJJJ'; es wurde nichts gebucht."
				).format(document_label, structured_id),
				frappe.ValidationError,
			)
		structured_mv = mv_part.strip()
		month, year = period.strip().split("/")
		period_start = date(int(year), int(month), 1)
	else:
		period_start = None

	remarks_text = cstr(remarks or "")
	marker_values = [
		cstr(value).strip()
		for value in _MV_MARKER_RE.findall(remarks_text)
	]
	if remarks_text.count("[MV:") != len(marker_values) or any(
		not value for value in marker_values
	):
		frappe.throw(
			_("{0} enthält einen ungültigen [MV:]-Marker.").format(document_label),
			frappe.ValidationError,
		)
	distinct_markers = sorted(set(marker_values))
	if len(distinct_markers) > 1:
		frappe.throw(
			_(
				"{0} enthält mehrere widersprüchliche [MV:]-Marker ({1}); "
				"es wurde nichts gebucht."
			).format(document_label, ", ".join(distinct_markers)),
			frappe.ValidationError,
		)
	marker_mv = distinct_markers[0] if distinct_markers else None

	if structured_mv and marker_mv and structured_mv != marker_mv:
		frappe.throw(
			_(
				"{0} enthält widersprüchliche Mietvertragsreferenzen "
				"({1} / {2}); es wurde nichts gebucht."
			).format(document_label, structured_mv, marker_mv),
			frappe.ValidationError,
		)
	return frappe._dict(
		mietvertrag=structured_mv or marker_mv,
		mietabrechnung_id=structured_id or None,
		period_start=period_start,
	)


def _return_source_header(
	return_against: str,
	*,
	for_update: bool = False,
	include_cost_center: bool = False,
) -> frappe._dict | None:
	fields = [
		"name",
		"docstatus",
		"customer",
		"company",
		"wohnung",
		"mietabrechnung_id",
		"remarks",
	]
	if include_cost_center:
		fields.append("cost_center")
	return frappe.db.get_value(
		"Sales Invoice",
		return_against,
		fields,
		as_dict=True,
		for_update=for_update,
	)


def _return_source_items(
	return_against: str,
	*,
	include_cost_center: bool,
) -> list[frappe._dict]:
	cost_center_select = ", cost_center" if include_cost_center else ""
	return frappe.db.sql(
		f"""
		SELECT name, idx, wohnung{cost_center_select}
		FROM `tabSales Invoice Item`
		WHERE parent = %s
		ORDER BY idx ASC, name ASC
		FOR UPDATE
		""",
		(return_against,),
		as_dict=True,
	)


def _validate_invoice_values(
	*,
	customer: object,
	company: object,
	wohnung: object,
	cost_center: object,
	items: object,
	identity: frappe._dict,
	document_label: str,
	has_header_cost_center: bool,
	has_item_cost_center: bool,
) -> None:
	expected_customer = cstr(identity.kunde).strip()
	expected_company = cstr(identity.company).strip()
	expected_wohnung = cstr(identity.wohnung).strip()

	if cstr(customer or "").strip() != expected_customer:
		frappe.throw(
			_(
				"{0} verwendet nicht den aktuellen Customer {1} des Mietvertrags "
				"{2}; es wurde nichts gebucht."
			).format(document_label, expected_customer, identity.name),
			frappe.ValidationError,
		)
	if cstr(company or "").strip() != expected_company:
		frappe.throw(
			_(
				"{0} verwendet nicht die Property-Company {1} des Mietvertrags "
				"{2}; es wurde nichts gebucht."
			).format(document_label, expected_company, identity.name),
			frappe.ValidationError,
		)
	if cstr(wohnung or "").strip() != expected_wohnung:
		frappe.throw(
			_(
				"{0} verwendet am Belegkopf nicht die aktuelle Wohnung {1} des "
				"Mietvertrags {2}; es wurde nichts gebucht."
			).format(document_label, expected_wohnung, identity.name),
			frappe.ValidationError,
		)
	if (
		has_header_cost_center
		and cstr(cost_center or "").strip() != cstr(identity.cost_center).strip()
	):
		frappe.throw(
			_(
				"{0} verwendet am Belegkopf nicht die aktuelle "
				"Property-Kostenstelle {1}; es wurde nichts gebucht."
			).format(document_label, identity.cost_center),
			frappe.ValidationError,
		)

	item_rows = list(items or [])
	if not item_rows:
		frappe.throw(
			_("{0} enthält keine prüfbaren Rechnungspositionen.").format(document_label),
			frappe.ValidationError,
		)
	for index, item in enumerate(item_rows, start=1):
		item_wohnung = cstr(
			item.get("wohnung") if hasattr(item, "get") else getattr(item, "wohnung", None)
		).strip()
		if item_wohnung != expected_wohnung:
			frappe.throw(
				_(
					"{0}, Position {1}, verwendet nicht die aktuelle Wohnung {2} "
					"des Mietvertrags {3}; es wurde nichts gebucht."
				).format(document_label, index, expected_wohnung, identity.name),
				frappe.ValidationError,
			)
		if has_item_cost_center:
			item_cost_center = cstr(
				item.get("cost_center")
				if hasattr(item, "get")
				else getattr(item, "cost_center", None)
			).strip()
			if item_cost_center != cstr(identity.cost_center).strip():
				frappe.throw(
					_(
						"{0}, Position {1}, verwendet nicht die aktuelle "
						"Property-Kostenstelle {2}; es wurde nichts gebucht."
					).format(
						document_label,
						index,
						identity.cost_center,
					),
					frappe.ValidationError,
				)


def _validate_contract_period(
	identity: frappe._dict,
	period_start: date | None,
	*,
	document_label: str,
) -> None:
	if not period_start:
		return
	if not identity.get("von"):
		frappe.throw(
			_(
				"Mietvertrag {0} hat kein Vertragsbeginn-Datum; der strukturierte "
				"Abrechnungsmonat von {1} kann nicht geprüft werden."
			).format(identity.name, document_label),
			frappe.ValidationError,
		)
	try:
		contract_start = getdate(identity.von)
		contract_end = getdate(identity.bis) if identity.get("bis") else None
	except Exception:
		frappe.throw(
			_(
				"Mietvertrag {0} enthält keinen prüfbaren Vertragszeitraum; "
				"{1} wurde nicht gebucht."
			).format(identity.name, document_label),
			frappe.ValidationError,
		)
	period_end = get_last_day(period_start)
	if (
		(contract_start and contract_start > period_end)
		or (contract_end and contract_end < period_start)
	):
		frappe.throw(
			_(
				"{0} verwendet den Abrechnungsmonat {1}, der den aktuellen "
				"Vertragszeitraum von Mietvertrag {2} nicht schneidet; "
				"es wurde nichts gebucht."
			).format(
				document_label,
				period_start.strftime("%m/%Y"),
				identity.name,
			),
			frappe.ValidationError,
		)


def validate_mietvertrag_sales_invoice_identity(doc) -> None:
	"""Validate every contract-marked Sales Invoice against locked live data."""
	label = cstr(getattr(doc, "name", None) or _("Neue Sales Invoice"))
	direct_reference = _contract_reference(
		mietabrechnung_id=doc.get("mietabrechnung_id"),
		remarks=doc.get("remarks"),
		document_label=label,
	)

	is_linked_return = bool(cint(doc.get("is_return"))) and bool(
		cstr(doc.get("return_against")).strip()
	)
	return_against = cstr(doc.get("return_against")).strip()
	source_hint = (
		_return_source_header(return_against)
		if is_linked_return
		else None
	)
	source_reference = (
		_contract_reference(
			mietabrechnung_id=source_hint.get("mietabrechnung_id"),
			remarks=source_hint.get("remarks"),
			document_label=_("Ursprungsrechnung {0}").format(return_against),
		)
		if source_hint
		else frappe._dict(mietvertrag=None, mietabrechnung_id=None)
	)

	direct_mv = direct_reference.get("mietvertrag")
	source_mv = source_reference.get("mietvertrag")
	if direct_mv and source_mv and direct_mv != source_mv:
		frappe.throw(
			_(
				"Return {0} und Ursprungsrechnung {1} verweisen auf verschiedene "
				"Mietverträge; es wurde nichts gebucht."
			).format(label, return_against),
			frappe.ValidationError,
		)
	direct_period = direct_reference.get("period_start")
	source_period = source_reference.get("period_start")
	if direct_period and source_period and direct_period != source_period:
		frappe.throw(
			_(
				"Return {0} und Ursprungsrechnung {1} verwenden verschiedene "
				"Abrechnungsmonate; es wurde nichts gebucht."
			).format(label, return_against),
			frappe.ValidationError,
		)
	structured_period = direct_period or source_period
	mietvertrag = direct_mv or source_mv
	if not mietvertrag:
		# Ordinary ERPNext invoices and returns deliberately remain untouched.
		return

	try:
		item_meta = frappe.get_meta("Sales Invoice Item")
		has_header_wohnung = bool(doc.meta.has_field("wohnung"))
		has_item_wohnung = bool(item_meta.has_field("wohnung"))
		has_header_cost_center = bool(doc.meta.has_field("cost_center"))
		has_item_cost_center = bool(item_meta.has_field("cost_center"))
	except Exception:
		frappe.throw(
			_(
				"Die Accounting-Dimensionen der Sales Invoice konnten nicht "
				"zuverlässig gelesen werden; es wurde nichts gebucht."
			),
			frappe.ValidationError,
		)
	if not has_header_wohnung or not has_item_wohnung:
		frappe.throw(
			_(
				"Die Accounting Dimension Wohnung fehlt auf Sales Invoice oder "
				"Sales Invoice Item; eine Mietvertragsrechnung darf nicht gebucht werden."
			),
			frappe.ValidationError,
		)

	# First and globally deterministic lock: Mietvertrag.  The helper then locks
	# Wohnung, Immobilie and financial masters in the same order as the generator.
	identity = lock_mietvertrag_booking_identity(mietvertrag)

	locked_source = None
	source_items: list[frappe._dict] = []
	if is_linked_return:
		locked_source = _return_source_header(
			return_against,
			for_update=True,
			include_cost_center=has_header_cost_center,
		)
		if not locked_source or cint(locked_source.get("docstatus")) != 1:
			frappe.throw(
				_(
					"Die Ursprungsrechnung {0} ist nicht mehr gebucht oder nicht "
					"verfügbar; Return abgebrochen."
				).format(return_against),
				frappe.ValidationError,
			)
		locked_reference = _contract_reference(
			mietabrechnung_id=locked_source.get("mietabrechnung_id"),
			remarks=locked_source.get("remarks"),
			document_label=_("Ursprungsrechnung {0}").format(return_against),
		)
		locked_mv = locked_reference.get("mietvertrag")
		if locked_mv and locked_mv != identity.name:
			frappe.throw(
				_(
					"Die Ursprungsrechnung {0} verweist aktuell auf Mietvertrag {1}, "
					"der Return aber auf {2}; es wurde nichts gebucht."
				).format(return_against, locked_mv, identity.name),
				frappe.ValidationError,
			)
		locked_period = locked_reference.get("period_start")
		if direct_period and locked_period and direct_period != locked_period:
			frappe.throw(
				_(
					"Return {0} und Ursprungsrechnung {1} verwenden aktuell "
					"verschiedene Abrechnungsmonate; es wurde nichts gebucht."
				).format(label, return_against),
				frappe.ValidationError,
			)
		structured_period = direct_period or locked_period
		if not direct_mv and not locked_mv:
			frappe.throw(
				_(
					"Die Mietvertragsidentität der Ursprungsrechnung {0} ist nicht "
					"mehr eindeutig; Return abgebrochen."
				).format(return_against),
				frappe.ValidationError,
			)
		source_items = _return_source_items(
			return_against,
			include_cost_center=has_item_cost_center,
		)
		_validate_invoice_values(
			customer=locked_source.get("customer"),
			company=locked_source.get("company"),
			wohnung=locked_source.get("wohnung"),
			cost_center=locked_source.get("cost_center"),
			items=source_items,
			identity=identity,
			document_label=_("Ursprungsrechnung {0}").format(return_against),
			has_header_cost_center=has_header_cost_center,
			has_item_cost_center=has_item_cost_center,
		)

		# ERPNext returns may omit custom accounting dimensions during mapping.
		# Missing values are inherited only after the locked source itself passed
		# all identity checks; conflicting non-empty values are never overwritten.
		if not cstr(doc.get("wohnung")).strip():
			doc.set("wohnung", identity.wohnung)
		if has_header_cost_center and not cstr(doc.get("cost_center")).strip():
			doc.set("cost_center", identity.cost_center)
		for item in doc.get("items") or []:
			if not cstr(item.get("wohnung")).strip():
				item.set("wohnung", identity.wohnung)
			if has_item_cost_center and not cstr(item.get("cost_center")).strip():
				item.set("cost_center", identity.cost_center)
		if (
			not cstr(doc.get("mietabrechnung_id")).strip()
			and locked_reference.get("mietabrechnung_id")
			and doc.meta.has_field("mietabrechnung_id")
		):
			doc.set(
				"mietabrechnung_id",
				locked_reference.mietabrechnung_id,
			)

	_validate_contract_period(
		identity,
		structured_period,
		document_label=label,
	)
	_validate_invoice_values(
		customer=doc.get("customer"),
		company=doc.get("company"),
		wohnung=doc.get("wohnung"),
		cost_center=doc.get("cost_center"),
		items=doc.get("items"),
		identity=identity,
		document_label=label,
		has_header_cost_center=has_header_cost_center,
		has_item_cost_center=has_item_cost_center,
	)


class CustomSalesInvoice(SalesInvoice):
	def validate(self):
		# Custom Accounting Dimensions may be absent on ERPNext's mapped return
		# document.  Inherit them from a locked, fully validated source before
		# standard validation can reject the otherwise safe return.
		if cint(self.get("is_return")) and cstr(self.get("return_against")).strip():
			validate_mietvertrag_sales_invoice_identity(self)

		super().validate()

		default_wertstellungsdatum_from_posting_date(self)
		# Re-check after ERPNext's setters/defaults so no standard validation
		# step can replace the authoritative contract/property identity.
		validate_mietvertrag_sales_invoice_identity(self)

		if self.meta.has_field("hv_sollstellung_titel"):
			self.hv_sollstellung_titel = build_sollstellung_titel(self)

	def set_status(self, update=False, status=None, update_modified=True):
		super().set_status(update=False, status=status, update_modified=update_modified)

		writeoff_status = get_sales_invoice_writeoff_status(
			self.name,
			outstanding_amount=self.outstanding_amount,
		)
		if not status and writeoff_status:
			self.status = writeoff_status

		if update:
			self.db_set("status", self.status, update_modified=update_modified)
