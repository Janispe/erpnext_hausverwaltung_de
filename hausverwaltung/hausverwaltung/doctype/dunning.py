from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, nowdate


SERIENBRIEF_FIELDNAME = "hv_serienbrief_vorlage"
SERIENBRIEF_WERTE_FIELDNAME = "hv_serienbrief_werte"
DUNNING_FEE_SALES_INVOICE_FIELDNAME = "hv_dunning_fee_sales_invoice"
SALES_INVOICE_DUNNING_FIELDNAME = "hv_dunning"
SALES_INVOICE_IS_DUNNING_FEE_FIELDNAME = "hv_is_dunning_fee_invoice"


def sync_serienbrief_vorlage_from_dunning_type(doc, method=None) -> None:
	"""Backfill a Serienbrief Vorlage from the selected Dunning Type.

	We only fill the field when the Mahnung itself has no explicit template yet, so
	users can still override the default on a single Dunning document.
	"""
	if not frappe.db.has_column("Dunning", SERIENBRIEF_FIELDNAME):
		return

	if not doc.get("dunning_type"):
		return

	if doc.get(SERIENBRIEF_FIELDNAME):
		return

	if not frappe.db.has_column("Dunning Type", SERIENBRIEF_FIELDNAME):
		return

	template = frappe.db.get_value("Dunning Type", doc.dunning_type, SERIENBRIEF_FIELDNAME)
	if template:
		doc.set(SERIENBRIEF_FIELDNAME, template)


def _collect_werte_rows(rows) -> dict[str, dict[str, Any]]:
	werte: dict[str, dict[str, Any]] = {}
	for row in rows or []:
		name = (row.get("variable") or "").strip()
		if not name:
			continue
		werte[frappe.scrub(name)] = {"value": row.get("wert")}
	return werte


def collect_serienbrief_werte(dunning) -> dict[str, dict[str, Any]]:
	"""Sammle Serienbrief-Variablenwerte aus Dunning Type und Dunning.

	Liefert ein Mapping im selben Format wie ``variablen_werte``
	(``{scrub(variable): {"value": wert}}``), das der Serienbrief-Durchlauf in den
	Pro-Empfänger-Override (`row._iteration_variablen_werte`) mergen kann. Werte
	aus dem Dunning Type bilden den Default; Werte auf der konkreten Mahnung
	überschreiben gleichnamige Defaults.

	Defensiv: fehlende Tabelle / fehlende Spalte → ``{}``.
	``dunning`` darf ein Doc oder ein Dunning-Name (str) sein.
	"""
	dunning_type = None
	dunning_doc = None
	if isinstance(dunning, str):
		try:
			dunning_doc = frappe.get_cached_doc("Dunning", dunning)
		except frappe.DoesNotExistError:
			dunning_doc = None
	else:
		dunning_doc = dunning

	if dunning_doc:
		dunning_type = getattr(dunning_doc, "dunning_type", None)

	werte: dict[str, dict[str, Any]] = {}

	# Table-Felder haben keine Spalte am Parent — daher Meta-Check statt has_column.
	if dunning_type and frappe.get_meta("Dunning Type").get_field(SERIENBRIEF_WERTE_FIELDNAME):
		try:
			type_doc = frappe.get_cached_doc("Dunning Type", dunning_type)
		except frappe.DoesNotExistError:
			type_doc = None
		if type_doc:
			werte.update(_collect_werte_rows(type_doc.get(SERIENBRIEF_WERTE_FIELDNAME) or []))

	if dunning_doc and frappe.get_meta("Dunning").get_field(SERIENBRIEF_WERTE_FIELDNAME):
		werte.update(_collect_werte_rows(dunning_doc.get(SERIENBRIEF_WERTE_FIELDNAME) or []))

	return werte


def validate_serienbrief_werte(doc, method=None) -> None:
	"""Verhindert, dass zwei hv_serienbrief_werte-Zeilen nach frappe.scrub()
	denselben Variablennamen liefern. Sonst würden Werte stumm überschrieben
	(siehe collect_serienbrief_werte → dict-Assignment).

	Beispiele für Kollisionen: "Frist Tage" + "frist_tage", "Ueberschrift" +
	"Überschrift". Beide werden zu "frist_tage" bzw. "ueberschrift" — der zweite
	Eintrag gewänne stumm.
	"""
	rows = doc.get(SERIENBRIEF_WERTE_FIELDNAME) or []
	seen: dict[str, list[tuple[int, str]]] = {}
	for row in rows:
		name = (getattr(row, "variable", None) or "").strip()
		if not name:
			continue
		key = frappe.scrub(name)
		seen.setdefault(key, []).append((getattr(row, "idx", 0), name))

	duplicates = [(key, occ) for key, occ in seen.items() if len(occ) > 1]
	if not duplicates:
		return

	parts = []
	for key, occ in duplicates:
		labels = ", ".join(f"#{idx} „{name}\"" for idx, name in occ)
		parts.append(f"<li><code>{key}</code> ({labels})</li>")
	frappe.throw(
		_(
			"Im Feld <strong>Serienbrief-Werte</strong> gibt es Variablen, "
			"die nach Normalisierung identisch sind und sich gegenseitig "
			"stumm überschreiben würden:<ul>{0}</ul>"
			"Bitte jede Variable nur einmal vergeben."
		).format("".join(parts)),
		title=_("Doppelte Variablen"),
	)


def validate_dunning_type_serienbrief_werte(doc, method=None) -> None:
	validate_serienbrief_werte(doc, method=method)


def validate_dunning(doc, method=None) -> None:
	sync_serienbrief_vorlage_from_dunning_type(doc, method=method)
	validate_serienbrief_werte(doc, method=method)


def _meta_has_field(doctype: str, fieldname: str) -> bool:
	try:
		return bool(frappe.get_meta(doctype).get_field(fieldname))
	except Exception:
		return False


def _ensure_dunning_fee_invoice_fields() -> None:
	if _meta_has_field("Dunning", DUNNING_FEE_SALES_INVOICE_FIELDNAME):
		return
	try:
		from hausverwaltung.install import ensure_dunning_fee_invoice_fields

		ensure_dunning_fee_invoice_fields()
		frappe.clear_cache(doctype="Dunning")
		frappe.clear_cache(doctype="Sales Invoice")
	except Exception:
		frappe.log_error(frappe.get_traceback(), "Dunning fee invoice field setup failed")


def _dunning_fee_sales_invoice(dunning_name: str) -> str | None:
	_ensure_dunning_fee_invoice_fields()
	if not _meta_has_field("Dunning", DUNNING_FEE_SALES_INVOICE_FIELDNAME):
		return None
	return frappe.db.get_value("Dunning", dunning_name, DUNNING_FEE_SALES_INVOICE_FIELDNAME)


def _dunning_overdue_sales_invoices(doc) -> list[str]:
	invoices: list[str] = []
	for row in doc.get("overdue_payments") or []:
		sales_invoice = row.get("sales_invoice")
		if sales_invoice and sales_invoice not in invoices:
			invoices.append(sales_invoice)
	return invoices


def _first_invoice_doc(invoice_names: list[str]):
	for name in invoice_names:
		try:
			return frappe.get_cached_doc("Sales Invoice", name)
		except Exception:
			continue
	return None


def _fallback_income_account(company: str) -> str | None:
	if not company:
		return None

	account = frappe.db.get_value("Company", company, "default_income_account")
	if account:
		return account

	rows = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "root_type": "Income"},
		pluck="name",
		limit=1,
	)
	return rows[0] if rows else None


def _fallback_cost_center(company: str) -> str | None:
	if not company:
		return None

	accounting_dimensions = frappe.get_all(
		"Accounting Dimension",
		filters={"document_type": "Cost Center", "disabled": 0},
		pluck="fieldname",
		limit=1,
	)
	if not accounting_dimensions:
		return None

	try:
		if frappe.get_meta("Company").get_field("cost_center"):
			cost_center = frappe.db.get_value("Company", company, "cost_center")
			if cost_center:
				return cost_center
	except Exception:
		pass

	rows = frappe.get_all(
		"Cost Center",
		filters={"company": company, "is_group": 0},
		pluck="name",
		limit=1,
	)
	return rows[0] if rows else None


def _copy_invoice_context(si, source_si) -> None:
	if not source_si:
		return

	for fieldname in ("mietvertrag", "wohnung", "immobilie", "cost_center", "debit_to", "currency"):
		if si.meta.get_field(fieldname) and source_si.meta.get_field(fieldname):
			value = source_si.get(fieldname)
			if value:
				si.set(fieldname, value)


def _create_fee_sales_invoice_doc(doc, amount: float, invoice_names: list[str]):
	from hausverwaltung.hausverwaltung.utils.rent_items import ensure_dunning_fee_item

	source_si = _first_invoice_doc(invoice_names)
	income_account = doc.get("income_account") or _fallback_income_account(doc.company)
	cost_center = doc.get("cost_center") or getattr(source_si, "cost_center", None) or _fallback_cost_center(doc.company)
	item_code = ensure_dunning_fee_item(company=doc.company, income_account=income_account)
	reference_text = ", ".join(invoice_names)

	si = frappe.new_doc("Sales Invoice")
	si.customer = doc.customer
	si.customer_name = doc.get("customer_name")
	si.company = doc.company
	si.posting_date = doc.get("posting_date") or nowdate()
	si.due_date = si.posting_date
	si.ignore_pricing_rule = 1
	si.remarks = _("Mahngebühr/Verzugszinsen aus Mahnung {0} zu {1}").format(doc.name, reference_text)
	_copy_invoice_context(si, source_si)

	if _meta_has_field("Sales Invoice", SALES_INVOICE_DUNNING_FIELDNAME):
		si.set(SALES_INVOICE_DUNNING_FIELDNAME, doc.name)
	if _meta_has_field("Sales Invoice", SALES_INVOICE_IS_DUNNING_FEE_FIELDNAME):
		si.set(SALES_INVOICE_IS_DUNNING_FEE_FIELDNAME, 1)

	row = {
		"item_code": item_code,
		"item_name": "Mahngebühr",
		"description": _("Mahngebühr/Verzugszinsen aus Mahnung {0}").format(doc.name),
		"qty": 1,
		"rate": amount,
	}
	if income_account:
		row["income_account"] = income_account
	if cost_center:
		row["cost_center"] = cost_center
	si.append("items", row)
	return si


def create_dunning_fee_invoice(doc, method=None) -> None:
	"""Create and submit the fee/interest Sales Invoice for a submitted Dunning."""
	_ensure_dunning_fee_invoice_fields()
	if not _meta_has_field("Dunning", DUNNING_FEE_SALES_INVOICE_FIELDNAME):
		return
	if doc.get(DUNNING_FEE_SALES_INVOICE_FIELDNAME):
		return

	amount = flt(doc.get("dunning_amount"))
	if amount <= 0:
		return

	invoice_names = _dunning_overdue_sales_invoices(doc)
	if not invoice_names:
		frappe.throw(_("Die Mahnung enthält keine verknüpfte Sales Invoice."))

	si = _create_fee_sales_invoice_doc(doc, amount, invoice_names)
	si.insert(ignore_permissions=True)
	si.submit()

	doc.db_set(DUNNING_FEE_SALES_INVOICE_FIELDNAME, si.name, update_modified=False)
	doc.add_comment(
		"Info",
		_("Mahngebühr/Verzugszinsen wurden als Sales Invoice {0} gebucht.").format(
			frappe.utils.get_link_to_form("Sales Invoice", si.name)
		),
	)


def cancel_dunning_fee_invoice(doc, method=None) -> None:
	fee_invoice = doc.get(DUNNING_FEE_SALES_INVOICE_FIELDNAME) or _dunning_fee_sales_invoice(doc.name)
	if not fee_invoice:
		return

	try:
		si = frappe.get_doc("Sales Invoice", fee_invoice)
	except frappe.DoesNotExistError:
		return

	if si.docstatus == 1:
		si.cancel()
	elif si.docstatus == 0:
		si.delete(ignore_permissions=True)


def validate_payment_entry_not_against_fee_dunning(doc, method=None) -> None:
	for row in doc.get("references") or []:
		if row.get("reference_doctype") != "Dunning" or not row.get("reference_name"):
			continue
		fee_invoice = _dunning_fee_sales_invoice(row.reference_name)
		detail = (
			_(" Die Mahngebühr ist als Sales Invoice {0} gebucht.").format(fee_invoice)
			if fee_invoice
			else ""
		)
		frappe.throw(
			_(
				"Zahlungen auf Mahnung {0} sind deaktiviert.{1} Bitte die Zahlung "
				"gegen die offenen Sales Invoices ausgleichen."
			).format(row.reference_name, detail),
			title=_("Zahlung gegen Mahnung nicht erlaubt"),
		)


@frappe.whitelist()
def get_payment_entry_guarded(dt, dn, *args, **kwargs):
	if dt == "Dunning":
		fee_invoice = _dunning_fee_sales_invoice(dn)
		detail = (
			_(" Die Mahngebühr ist als Sales Invoice {0} gebucht.").format(fee_invoice)
			if fee_invoice
			else ""
		)
		frappe.throw(
			_(
				"Zahlungen werden nicht aus der Mahnung erstellt.{0} Bitte Zahlung "
				"gegen die offenen Sales Invoices erstellen."
			).format(detail),
			title=_("Zahlung über Rechnung buchen"),
		)

	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	return get_payment_entry(dt, dn, *args, **kwargs)
