from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import add_months, cstr, getdate, nowdate

from hausverwaltung.hausverwaltung.utils.buchung import (
	DEFAULT_SERVICE_ITEM_CODE,
	ensure_default_service_item,
)
from hausverwaltung.hausverwaltung.utils.immobilie_accounts import get_immobilie_primary_bank_account


RHYTHMUS_MONTHS: dict[str, int] = {
	"Monatlich": 1,
	"Vierteljährlich": 3,
	"Halbjährlich": 6,
	"Jährlich": 12,
}


class Abschlagszahlung(Document):
	def validate(self):
		if self.get("betrag") not in (None, "") and float(self.betrag) < 0:
			frappe.throw("Der Default-Betrag darf nicht negativ sein.")

		# Server-side defaults: if user (or API) didn't fill these, derive from immobilie/kostenart.
		# JS already does this on field change, but this is the fallback for programmatic creation.
		if self.get("immobilie"):
			if not self.get("bank_account"):
				self.bank_account = _resolve_bank_account_for_immobilie(self.immobilie)
			if not self.get("cost_center"):
				self.cost_center = _get_from_immobilie(self, "kostenstelle")

		if self.get("kostenart") and self.get("kostenart_nicht_umlagefaehig"):
			frappe.throw(
				"Bitte entweder 'Kostenart (umlagefähig)' oder 'Kostenart (nicht umlagefähig)' setzen, nicht beides."
			)

		if self.get("kostenart") or self.get("kostenart_nicht_umlagefaehig"):
			if not self.get("expense_account"):
				self.expense_account = _get_expense_account_from_kostenart(self)
			if not self.get("item_code"):
				self.item_code = _get_item_code_from_kostenart(self)

		seen: set[str] = set()
		for row in self.get("plan") or []:
			if not row.get("faelligkeitsdatum"):
				continue
			key = str(getdate(row.faelligkeitsdatum))
			if key in seen:
				frappe.throw(f"Plan enthält das Datum {key} mehrfach.")
			seen.add(key)
			if row.get("betrag") in (None, "") or float(row.betrag) < 0:
				frappe.throw(f"Plan-Zeile {row.idx}: Betrag muss >= 0 sein.")

		self.status = _compute_status(self)

	@frappe.whitelist()
	def plan_vorbelegen(self, rhythmus: str, von: str, bis: str, betrag: float | None = None, replace: int | bool = 0):
		"""Generate plan rows for a fixed rhythm (Monatlich/Vierteljährlich/Halbjährlich/Jährlich)."""
		self.check_permission("write")

		if rhythmus not in RHYTHMUS_MONTHS:
			frappe.throw(f"Unbekannter Rhythmus: {rhythmus}")

		von_d = getdate(von)
		bis_d = getdate(bis)
		if bis_d < von_d:
			frappe.throw("'Bis' darf nicht vor 'Von' liegen.")

		amount = float(betrag) if betrag not in (None, "") else float(self.get("betrag") or 0)
		if amount <= 0:
			frappe.throw("Bitte einen positiven Betrag angeben.")

		step = RHYTHMUS_MONTHS[rhythmus]

		if int(replace or 0):
			self.set("plan", [])

		existing = {str(getdate(r.faelligkeitsdatum)) for r in (self.get("plan") or []) if r.get("faelligkeitsdatum")}

		current = von_d
		added = 0
		skipped = 0
		# Safety cap: max 120 rows generated per call
		while current <= bis_d and added + skipped < 120:
			key = str(current)
			if key in existing:
				skipped += 1
			else:
				self.append("plan", {"faelligkeitsdatum": current, "betrag": amount})
				existing.add(key)
				added += 1
			current = getdate(add_months(current, step))

		self.save(ignore_permissions=True)
		return {"added": added, "skipped": skipped, "total_rows": len(self.get("plan") or [])}

	@frappe.whitelist()
	def jahresabrechnung_erstellen(
		self,
		ja_von: str | None = None,
		ja_bis: str | None = None,
		ja_betrag: float | None = None,
		ja_rechnungsnr: str | None = None,
		ja_rechnungsdatum: str | None = None,
		ja_wertstellungsdatum: str | None = None,
		kostenart: str | None = None,
		kostenart_nicht_umlagefaehig: str | None = None,
		expense_account: str | None = None,
		cost_center: str | None = None,
		item_code: str | None = None,
	):
		"""Create a Purchase Invoice for the annual bill and reconcile advance Payment Entries against it.

		Dialog values are persisted on the doc so they show up as defaults next time.
		"""
		self.check_permission("write")

		updates = {
			"ja_von": ja_von,
			"ja_bis": ja_bis,
			"ja_betrag": ja_betrag,
			"ja_rechnungsnr": ja_rechnungsnr,
			"ja_rechnungsdatum": ja_rechnungsdatum,
			"ja_wertstellungsdatum": ja_wertstellungsdatum,
			"kostenart": kostenart,
			"kostenart_nicht_umlagefaehig": kostenart_nicht_umlagefaehig,
			"expense_account": expense_account,
			"cost_center": cost_center,
			"item_code": item_code,
		}
		if any(v not in (None, "") for v in updates.values()):
			for fieldname, value in updates.items():
				if value not in (None, ""):
					self.set(fieldname, value)
			self.save(ignore_permissions=True)

		# Validate
		if not self.get("ja_von") or not self.get("ja_bis"):
			frappe.throw("Bitte Abrechnungszeitraum (von/bis) ausfüllen.")
		if not self.get("ja_betrag") or float(self.ja_betrag) <= 0:
			frappe.throw("Bitte einen positiven Jahresrechnungsbetrag eingeben.")
		if getdate(self.ja_bis) < getdate(self.ja_von):
			frappe.throw("'Bis' darf nicht vor 'Von' liegen.")
		if not self.get("company") or not self.get("lieferant"):
			frappe.throw("Company und Lieferant müssen gesetzt sein.")
		if not self.get("ja_wertstellungsdatum"):
			frappe.throw("Bitte ein Wertstellungsdatum angeben.")
		wsd = getdate(self.ja_wertstellungsdatum)
		if wsd < getdate(self.ja_von) or wsd > getdate(self.ja_bis):
			frappe.throw(
				f"Wertstellungsdatum ({wsd}) muss innerhalb des Abrechnungszeitraums "
				f"({getdate(self.ja_von)} bis {getdate(self.ja_bis)}) liegen."
			)

		# Guard: check if last PI is still active
		if self.get("ja_purchase_invoice"):
			existing = frappe.db.get_value("Purchase Invoice", self.ja_purchase_invoice, "docstatus")
			if existing == 1:
				frappe.throw(
					f"Es existiert bereits eine aktive Eingangsrechnung ({self.ja_purchase_invoice}). "
					"Bitte zuerst stornieren, bevor eine neue erstellt wird."
				)

		# 1. Create and submit Purchase Invoice
		pi = _create_jahresabrechnung_pi(self)

		# 2. Find unreconciled advance Payment Entries in the period
		payable_account = frappe.db.get_value("Company", self.company, "default_payable_account")
		if not payable_account:
			frappe.throw("In der Company ist kein 'default_payable_account' hinterlegt.")

		pes = frappe.get_all(
			"Payment Entry",
			filters={
				"party_type": "Supplier",
				"party": self.lieferant,
				"payment_type": "Pay",
				"company": self.company,
				"docstatus": 1,
				"posting_date": ["between", [self.ja_von, self.ja_bis]],
				"unallocated_amount": [">", 0],
			},
			fields=["name", "paid_amount", "unallocated_amount", "posting_date"],
			order_by="posting_date asc",
		)

		# 3. Reconcile advances against PI
		remaining = float(self.ja_betrag)
		entry_list = []
		pe_names = []
		summe_abschlaege = 0.0

		for pe in pes:
			if remaining <= 0.01:
				break
			alloc = min(float(pe.unallocated_amount), remaining)
			if alloc <= 0:
				continue
			entry_list.append(
				frappe._dict({
					"voucher_type": "Payment Entry",
					"voucher_no": pe.name,
					"voucher_detail_no": None,
					"against_voucher_type": "Purchase Invoice",
					"against_voucher": pi.name,
					"account": payable_account,
					"exchange_rate": 1,
					"party_type": "Supplier",
					"party": self.lieferant,
					"is_advance": 1,
					"dr_or_cr": "debit_in_account_currency",
					"unreconciled_amount": float(pe.unallocated_amount),
					"unadjusted_amount": float(pe.unallocated_amount),
					"allocated_amount": alloc,
					"difference_amount": 0,
					"difference_account": None,
					"difference_posting_date": nowdate(),
				})
			)
			pe_names.append(pe.name)
			summe_abschlaege += alloc
			remaining -= alloc

		if entry_list:
			from erpnext.accounts.utils import reconcile_against_document
			reconcile_against_document(entry_list, skip_ref_details_update_for_pe=True)

		# 4. Calculate result
		differenz = float(self.ja_betrag) - summe_abschlaege
		if differenz > 0.01:
			status = f"Nachzahlung: {differenz:,.2f} EUR"
		elif differenz < -0.01:
			status = f"Guthaben: {abs(differenz):,.2f} EUR"
		else:
			status = "Ausgeglichen"

		# 5. Update result fields
		self.db_set("ja_purchase_invoice", pi.name)
		self.db_set("ja_status", status)
		self.db_set("ja_differenz", differenz)
		self.db_set("status", "Abgerechnet")

		frappe.db.commit()

		return {
			"purchase_invoice": pi.name,
			"status": status,
			"differenz": differenz,
			"reconciled_count": len(pe_names),
			"summe_abschlaege": summe_abschlaege,
		}


def _compute_status(doc) -> str:
	"""Status: Abgerechnet (JA done) > Läuft (any future plan row) > Vergangenheit."""
	if doc.get("ja_purchase_invoice"):
		return "Abgerechnet"
	today_d = getdate(nowdate())
	for row in doc.get("plan") or []:
		if row.get("faelligkeitsdatum") and getdate(row.faelligkeitsdatum) >= today_d:
			return "Läuft"
	return "Vergangenheit"


def update_statuses_for_list():
	"""Daily entrypoint: recompute status across all Abschlagszahlungen (handles time transitions)."""
	names = frappe.get_all("Abschlagszahlung", pluck="name")
	for name in names:
		try:
			doc = frappe.get_doc("Abschlagszahlung", name)
			new_status = _compute_status(doc)
			if doc.get("status") != new_status:
				doc.db_set("status", new_status, update_modified=False)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Abschlagszahlung Status-Update: {name}")


def _resolve_bank_account_for_immobilie(immobilie: str) -> str | None:
	"""Find a Bank Account doctype whose GL account matches the Immobilie's primary Hauptkonto."""
	if not immobilie:
		return None
	konto = get_immobilie_primary_bank_account(immobilie)
	if not konto:
		return None
	# Prefer enabled company bank accounts; fall back to any Bank Account with that GL account.
	for filters in (
		{"account": konto, "is_company_account": 1, "disabled": 0},
		{"account": konto},
	):
		name = frappe.db.get_value("Bank Account", filters, "name")
		if name:
			return name
	return None


@frappe.whitelist()
def get_defaults_for_immobilie(immobilie: str | None = None) -> dict:
	"""Return derived defaults (bank_account, cost_center) for a given Immobilie. Used by the form."""
	if not immobilie:
		return {}
	cost_center = None
	try:
		cost_center = frappe.get_cached_value("Immobilie", immobilie, "kostenstelle")
	except Exception:
		pass
	return {
		"bank_account": _resolve_bank_account_for_immobilie(immobilie),
		"cost_center": cost_center,
	}


@frappe.whitelist()
def get_defaults_for_kostenart(
	kostenart: str | None = None,
	kostenart_nicht_umlagefaehig: str | None = None,
) -> dict:
	"""Return derived defaults (expense_account, item_code) for either Kostenart variant."""
	stub = frappe._dict({
		"kostenart": kostenart,
		"kostenart_nicht_umlagefaehig": kostenart_nicht_umlagefaehig,
	})
	return {
		"expense_account": _get_expense_account_from_kostenart(stub),
		"item_code": _get_item_code_from_kostenart(stub),
	}


@frappe.whitelist()
def get_defaults_for_konto(konto: str | None = None) -> dict:
	"""Reverse-lookup: given a GL Account, find the matching Kostenart entry in either tab.

	Returns {kostenart, kostenart_nicht_umlagefaehig, item_code}. Empty dict if no match.
	"""
	if not konto:
		return {}
	for fieldname, doctype in KOSTENART_DOCTYPES:
		try:
			row = frappe.db.get_value(doctype, {"konto": konto}, ["name", "artikel"], as_dict=True)
		except Exception:
			row = None
		if row:
			result = {
				"kostenart": None,
				"kostenart_nicht_umlagefaehig": None,
				"item_code": row.get("artikel"),
			}
			result[fieldname] = row.get("name")
			return result
	return {}


def _create_payment_entry_for_plan_row(doc: Abschlagszahlung, row: Document, posting_date_override=None):
	"""Build, insert and submit a supplier advance Payment Entry for a single plan row.

	posting_date_override allows callers (e.g. bank import auto-match) to use the actual
	bank booking date instead of the planned faelligkeitsdatum.
	"""
	if not doc.get("company"):
		frappe.throw("Bitte eine Company auswählen.")
	if not doc.get("lieferant"):
		frappe.throw("Bitte einen Lieferanten auswählen.")
	if not doc.get("bank_account"):
		frappe.throw("Bitte ein Bankkonto auswählen (Feld 'Bankkonto').")

	amount = float(row.betrag)
	if amount <= 0:
		frappe.throw(f"Plan-Zeile {row.idx}: Betrag muss positiv sein.")

	posting_date = getdate(posting_date_override) if posting_date_override else getdate(row.faelligkeitsdatum)

	paid_from = frappe.get_cached_value("Bank Account", doc.bank_account, "account")
	if not paid_from:
		frappe.throw("Im Bankkonto ist kein 'Account' hinterlegt.")

	paid_to = frappe.db.get_value("Company", doc.company, "default_payable_account")
	if not paid_to:
		frappe.throw("In der Company ist kein 'default_payable_account' hinterlegt.")

	pe = frappe.new_doc("Payment Entry")
	pe.update({
		"payment_type": "Pay",
		"company": doc.company,
		"posting_date": posting_date,
		"party_type": "Supplier",
		"party": doc.lieferant,
		"bank_account": doc.bank_account,
		"paid_from": paid_from,
		"paid_to": paid_to,
		"paid_amount": amount,
		"received_amount": amount,
		"remarks": _build_remarks(doc) + f" | Plan-Zeile {row.idx}",
	})

	if doc.get("reference_no"):
		_set_if_field(pe, "reference_no", doc.reference_no)
		_set_if_field(pe, "reference_date", posting_date)

	pe.set("references", [])

	pe.insert(ignore_permissions=True)
	pe.submit()
	return pe


def _doctype_has_field(doctype: str, fieldname: str) -> bool:
	try:
		return bool(frappe.get_meta(doctype).get_field(fieldname))
	except Exception:
		return False


def _set_if_field(doc: Document, fieldname: str, value):
	try:
		if doc.meta.get_field(fieldname):
			doc.set(fieldname, value)
	except Exception:
		pass


def _get_company_default(company: str, fieldname: str):
	try:
		return frappe.get_cached_value("Company", company, fieldname)
	except Exception:
		return None


def _get_from_immobilie(doc: Abschlagszahlung, fieldname: str):
	immobilie = doc.get("immobilie")
	if not immobilie:
		return None
	if fieldname == "konto":
		return get_immobilie_primary_bank_account(immobilie)
	try:
		return frappe.get_cached_value("Immobilie", immobilie, fieldname)
	except Exception:
		return None


KOSTENART_DOCTYPES: tuple[tuple[str, str], ...] = (
	("kostenart", "Betriebskostenart"),
	("kostenart_nicht_umlagefaehig", "Kostenart nicht umlagefaehig"),
)


def _resolve_kostenart_source(doc) -> tuple[str | None, str | None]:
	"""Return (doctype, name) of the active Kostenart on a doc/dict, or (None, None)."""
	for fieldname, doctype in KOSTENART_DOCTYPES:
		value = doc.get(fieldname)
		if value:
			return doctype, value
	return None, None


def _get_item_code_from_kostenart(doc: Abschlagszahlung):
	doctype, name = _resolve_kostenart_source(doc)
	if not (doctype and name):
		return None
	try:
		if _doctype_has_field(doctype, "artikel"):
			return frappe.get_cached_value(doctype, name, "artikel")
	except Exception:
		return None
	return None


def _get_expense_account_from_kostenart(doc: Abschlagszahlung):
	doctype, name = _resolve_kostenart_source(doc)
	if not (doctype and name):
		return None
	try:
		if _doctype_has_field(doctype, "konto"):
			return frappe.get_cached_value(doctype, name, "konto")
	except Exception:
		return None
	return None


def _set_payable_account_if_available(pi: Document, company: str):
	try:
		payable = frappe.db.get_value("Company", company, "default_payable_account")
		if payable and frappe.db.exists("Account", payable):
			_set_if_field(pi, "credit_to", payable)
	except Exception:
		return


def _build_remarks(doc: Abschlagszahlung) -> str:
	parts = []
	if doc.get("bezeichnung"):
		parts.append(cstr(doc.get("bezeichnung")))
	if doc.get("vertragsnummer"):
		parts.append(f"Vertrag: {doc.get('vertragsnummer')}")
	if doc.get("immobilie"):
		parts.append(f"Immobilie: {doc.get('immobilie')}")
	if doc.get("wohnung"):
		parts.append(f"Wohnung: {doc.get('wohnung')}")
	return " | ".join(parts) or f"Abschlagszahlung ({DEFAULT_SERVICE_ITEM_CODE})"


def _resolve_pi_fields(doc: Abschlagszahlung):
	"""Resolve item_code, expense_account, cost_center using the existing fallback chains."""
	item_code = doc.get("item_code") or _get_item_code_from_kostenart(doc) or ensure_default_service_item()
	expense_account = doc.get("expense_account") or _get_expense_account_from_kostenart(doc) or _get_from_immobilie(doc, "konto")
	cost_center = doc.get("cost_center") or _get_from_immobilie(doc, "kostenstelle") or _get_company_default(doc.company, "cost_center")
	if not expense_account and doc.get("immobilie"):
		frappe.throw("Für die Immobilie ist kein Haupt-Bankkonto hinterlegt.")
	if not expense_account:
		expense_account = _get_company_default(doc.company, "default_expense_account")
	if not expense_account:
		frappe.throw("Bitte ein Aufwandskonto angeben oder in der Company ein Standard-Aufwandskonto pflegen.")
	return item_code, expense_account, cost_center


def _create_jahresabrechnung_pi(doc: Abschlagszahlung):
	"""Create and submit a Purchase Invoice for the annual bill."""
	item_code, expense_account, cost_center = _resolve_pi_fields(doc)

	posting_date = doc.get("ja_rechnungsdatum") or nowdate()
	pi = frappe.new_doc("Purchase Invoice")
	pi.update({
		"company": doc.company,
		"supplier": doc.lieferant,
		"posting_date": posting_date,
		"bill_date": posting_date,
		"bill_no": doc.get("ja_rechnungsnr"),
		"remarks": _build_remarks(doc) + f" | Jahresabrechnung {doc.ja_von} - {doc.ja_bis}",
	})
	wertstellung = doc.get("ja_wertstellungsdatum") or doc.get("ja_bis")
	if wertstellung:
		_set_if_field(pi, "custom_wertstellungsdatum", wertstellung)
	_set_payable_account_if_available(pi, doc.company)
	pi.append("items", {
		"item_code": item_code,
		"qty": 1,
		"rate": float(doc.ja_betrag),
		"expense_account": expense_account,
		"cost_center": cost_center,
	})
	pi.insert(ignore_permissions=True)
	pi.submit()
	return pi
