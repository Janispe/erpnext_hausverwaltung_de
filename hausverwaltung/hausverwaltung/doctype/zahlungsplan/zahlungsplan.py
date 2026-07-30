from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import add_months, cstr, flt, getdate, now_datetime, nowdate

from hausverwaltung.hausverwaltung.utils.buchung import (
	DEFAULT_SERVICE_ITEM_CODE,
	ensure_default_service_item,
)
from hausverwaltung.hausverwaltung.utils.immobilie_accounts import get_immobilie_primary_bank_account

RHYTHMUS_MONTHS: dict[str, int] = {
	"Monatlich": 1,
	"Alle 2 Monate": 2,
	"Vierteljährlich": 3,
	"Halbjährlich": 6,
	"Jährlich": 12,
}

MODUS_ABSCHLAGSPLAN = "Abschlagsplan"
MODUS_ZAHLUNGSPLAN = "Zahlungsplan"


class Zahlungsplan(Document):
	def validate(self):
		# Backward-compat: existing records ohne modus bekommen Default
		if not self.get("modus"):
			self.modus = MODUS_ABSCHLAGSPLAN

		if self.get("betrag") not in (None, "") and float(self.betrag) < 0:
			frappe.throw("Der Default-Betrag darf nicht negativ sein.")

		# Modus-spezifische Validierung
		if self.modus == MODUS_ZAHLUNGSPLAN:
			if flt(self.get("vor_systemstart_bezahlt")) > 0:
				frappe.throw(
					"Im Modus 'Zahlungsplan' werden Plan-Zeilen direkt als "
					"Eingangsrechnungen gebucht. Eine Vorzahlung vor Systemstart "
					"hat hier keine Auswirkung — bitte das Feld leeren oder zu "
					"'Abschlagsplan' wechseln."
				)
		else:
			_validate_historical_prepayment_config(self)

		# Server-side defaults: if user (or API) didn't fill these, derive from immobilie/kostenart.
		# JS already does this on field change, but this is the fallback for programmatic creation.
		if self.get("immobilie"):
			if not self.get("bank_account"):
				self.bank_account = _resolve_bank_account_for_immobilie(self.immobilie)
			if not self.get("cost_center"):
				self.cost_center = _get_from_immobilie(self, "kostenstelle")

		# Kostenart-Typ als Single-Source-of-Truth: das andere Feld leeren, damit
		# beim Wechsel kein altes Link bleibt. Auto-Detect für Records ohne typ
		# (Legacy / API-erstellt) — wenn genau eines der Felder gesetzt ist,
		# leiten wir typ daraus ab.
		typ = (self.get("kostenart_typ") or "").strip()
		if typ == "umlegbar":
			if self.get("kostenart_nicht_umlagefaehig"):
				self.kostenart_nicht_umlagefaehig = None
		elif typ == "nicht umlegbar":
			if self.get("kostenart"):
				self.kostenart = None
		elif not typ:
			if self.get("kostenart") and not self.get("kostenart_nicht_umlagefaehig"):
				self.kostenart_typ = "umlegbar"
			elif self.get("kostenart_nicht_umlagefaehig") and not self.get("kostenart"):
				self.kostenart_typ = "nicht umlegbar"

		if self.get("kostenart") and self.get("kostenart_nicht_umlagefaehig"):
			frappe.throw(
				"Bitte entweder 'Umlagefähige Kostenart' oder 'Kostenart (nicht umlagefähig)' setzen, nicht beides."
			)

		if not (self.get("kostenart") or self.get("kostenart_nicht_umlagefaehig")):
			frappe.throw(
				"Bitte eine Kostenart angeben — entweder 'Umlagefähige Kostenart' oder "
				"'Kostenart (nicht umlagefähig)'. Ohne Kostenart kann beim automatischen "
				"Erzeugen einer Eingangsrechnung kein korrektes Aufwandskonto bestimmt werden."
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

		_validate_payment_allocations(self)
		self.status = _compute_status(self)

	def on_update(self):
		_sync_purchase_invoices_for_plan(self)

	@frappe.whitelist()
	def plan_vorbelegen(self, rhythmus: str, von: str, bis: str, betrag: float | None = None, replace: int | bool = 0):
		"""Generate plan rows for a fixed monthly rhythm."""
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

		Nur für Modus = Abschlagsplan sinnvoll.

		Dialog values are persisted on the doc so they show up as defaults next time.
		"""
		self.check_permission("write")
		# ``for_update`` performs the first critical read after acquiring the
		# lock.  A separate SELECT + reload can stay on an older REPEATABLE READ
		# snapshot and is not sufficient for booking decisions.
		self = frappe.get_doc("Zahlungsplan", self.name, for_update=True)

		if self.modus != MODUS_ABSCHLAGSPLAN:
			frappe.throw(
				f"Jahresabrechnung ist nur für Modus '{MODUS_ABSCHLAGSPLAN}' verfügbar. "
				f"Aktueller Modus: '{self.modus}'."
			)

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

		# Accounting documents and plan state form one transaction.  In particular,
		# never show a historical payment as settled unless it exists in the ledger.
		# This workflow intentionally supports company currency only: treating a
		# foreign supplier advance as 1:1 would silently corrupt both open items.
		currency_context = _validate_single_currency_booking_context(self)
		payable_account = currency_context.payable_account

		_require_doctype_permissions("Purchase Invoice", ("create", "submit"))
		if flt(self.get("vor_systemstart_bezahlt")) > 0:
			_require_doctype_permissions("Journal Entry", ("create", "submit"))

		# Find real, still-unallocated advance Payment Entries linked to this plan.
		amount_by_payment, amount_by_plan_row = _active_allocation_amounts(
			self,
			from_date=self.ja_von,
			to_date=self.ja_bis,
			unsettled_only=True,
		)
		unlinked_abschlagsplan_rows = []
		for plan_row in self.get("plan") or []:
			row_date = (
				getdate(plan_row.faelligkeitsdatum)
				if plan_row.get("faelligkeitsdatum")
				else None
			)
			if row_date and (
				row_date < getdate(self.ja_von)
				or row_date > getdate(self.ja_bis)
			):
				continue
			if amount_by_plan_row.get(plan_row.name, 0.0) < flt(plan_row.get("betrag")) - 0.01:
				unlinked_abschlagsplan_rows.append(plan_row.idx)

		pes_by_name = {}
		for payment_entry, linked_amount in sorted(amount_by_payment.items()):
			try:
				pe = frappe.get_doc("Payment Entry", payment_entry, for_update=True)
			except frappe.DoesNotExistError:
				continue
			if (
				pe.docstatus != 1
				or pe.party_type != "Supplier"
				or pe.party != self.lieferant
				or pe.payment_type != "Pay"
				or pe.company != self.company
				or flt(pe.unallocated_amount) <= 0
				):
				continue
			_validate_payment_entry_currency(pe, currency_context)
			pe["linked_plan_amount"] = flt(linked_amount)
			pes_by_name[pe.name] = pe
		pes = list(pes_by_name.values())
		pes.sort(key=lambda pe: getdate(pe.posting_date) if pe.posting_date else getdate(self.ja_von))

		settlement_rows = _get_trackable_settlement_rows(
			self,
			payment_amounts={
				pe.name: flt(pe.get("linked_plan_amount"))
				for pe in pes
			},
			from_date=self.ja_von,
			to_date=self.ja_bis,
		)
		historical_advance = _ensure_historical_advance_journal(
			self,
			payable_account,
			currency_context=currency_context,
		)
		pi = _create_jahresabrechnung_pi(
			self,
			currency_context=currency_context,
		)

		# Reconcile real ledger advances against the new Purchase Invoice.
		remaining = float(self.ja_betrag)
		entry_list = []
		pe_names = []
		reconciled_by_payment: dict[str, float] = {}
		summe_abschlaege = sum(
			min(
				flt(pe.unallocated_amount),
				flt(pe.get("linked_plan_amount")) or flt(pe.unallocated_amount),
			)
			for pe in pes
		)

		for pe in pes:
			if remaining <= 0.01:
				break
			linked_plan_amount = flt(pe.get("linked_plan_amount")) or flt(pe.unallocated_amount)
			alloc = min(float(pe.unallocated_amount), linked_plan_amount, remaining)
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
			reconciled_by_payment[pe.name] = (
				reconciled_by_payment.get(pe.name, 0.0) + alloc
			)
			remaining -= alloc

		historical_available = flt(historical_advance.get("available"))
		for advance_row in historical_advance.get("rows") or []:
			if remaining <= 0.01:
				break
			available = flt(advance_row.get("available"))
			alloc = min(available, remaining)
			if alloc <= 0:
				continue
			entry_list.append(
				frappe._dict({
					"voucher_type": "Journal Entry",
					"voucher_no": historical_advance.get("name"),
					"voucher_detail_no": advance_row.get("name"),
					"against_voucher_type": "Purchase Invoice",
					"against_voucher": pi.name,
					"account": payable_account,
					"exchange_rate": flt(advance_row.get("exchange_rate")) or 1,
					"party_type": "Supplier",
					"party": self.lieferant,
					"is_advance": 1,
					"dr_or_cr": "debit_in_account_currency",
					"unreconciled_amount": available,
					"unadjusted_amount": available,
					"allocated_amount": alloc,
					"difference_amount": 0,
					"difference_account": None,
					"difference_posting_date": nowdate(),
				})
			)
			remaining -= alloc

		if entry_list:
			from erpnext.accounts.utils import reconcile_against_document
			reconcile_against_document(entry_list, skip_ref_details_update_for_pe=True)
		_settle_payment_allocations(
			settlement_rows,
			settlement_invoice=pi.name,
			reconciled_by_payment=reconciled_by_payment,
		)

		# Result fields are based exclusively on posted, eligible advances.
		vorzahlung = historical_available
		summe_anzahlungen = summe_abschlaege + historical_available
		differenz = float(self.ja_betrag) - summe_anzahlungen
		if differenz > 0.01:
			status = f"Nachzahlung: {differenz:,.2f} EUR"
		elif differenz < -0.01:
			status = f"Guthaben: {abs(differenz):,.2f} EUR"
		else:
			status = "Ausgeglichen"

		actual_outstanding = flt(
			frappe.db.get_value("Purchase Invoice", pi.name, "outstanding_amount")
		)
		expected_outstanding = max(differenz, 0.0)
		if abs(actual_outstanding - expected_outstanding) > 0.01:
			frappe.throw(
				"Die Jahresabrechnung konnte nicht konsistent verrechnet werden: "
				f"erwartet offen {expected_outstanding:.2f} EUR, tatsächlich "
				f"{actual_outstanding:.2f} EUR. Es wurde nichts gespeichert."
			)

		self.db_set("ja_purchase_invoice", pi.name)
		self.db_set("ja_status", status)
		self.db_set("ja_differenz", differenz)
		self.db_set("status", "Abgerechnet")

		return {
			"purchase_invoice": pi.name,
			"status": status,
			"differenz": differenz,
			"reconciled_count": len(pe_names),
			"summe_abschlaege": summe_abschlaege,
			"vor_systemstart_bezahlt": vorzahlung,
			"vor_systemstart_journal_entry": historical_advance.get("name"),
			"summe_anzahlungen": summe_anzahlungen,
			"unlinked_count": len(unlinked_abschlagsplan_rows),
			"unlinked_rows": unlinked_abschlagsplan_rows,
		}

	@frappe.whitelist()
	def create_due_purchase_invoices(self) -> dict:
		"""Modus=Zahlungsplan: erzeuge PIs für alle fälligen Plan-Zeilen ohne PI.

		Idempotent: Plan-Zeilen mit existierendem (und nicht-storniertem) ``purchase_invoice``
		werden übersprungen.
		"""
		self.check_permission("write")
		# ``self`` wurde für den Methodenaufruf bereits vor dem Lock geladen.
		# Unter MariaDB REPEATABLE READ könnte ein normales ``reload()`` deshalb
		# weiterhin den alten Snapshot liefern. Der Current Read lädt Parent und
		# Child-Zeilen erst nach dem Lock neu.
		self = frappe.get_doc("Zahlungsplan", self.name, for_update=True)

		if self.modus != MODUS_ZAHLUNGSPLAN:
			frappe.throw(
				f"Auto-Eingangsrechnungs-Erzeugung ist nur für Modus '{MODUS_ZAHLUNGSPLAN}' verfügbar. "
				f"Aktueller Modus: '{self.modus}'."
			)
		_require_doctype_permissions("Purchase Invoice", ("create", "submit"))

		today_d = getdate(nowdate())
		created: list[str] = []
		errors: list[dict] = []
		skipped = 0

		for row in self.get("plan") or []:
			if not row.get("faelligkeitsdatum"):
				skipped += 1
				continue
			if getdate(row.faelligkeitsdatum) > today_d:
				skipped += 1
				continue
			savepoint = f"zahlungsplan_pi_{row.idx}"
			frappe.db.savepoint(savepoint)
			try:
				existing_pi = row.get("purchase_invoice")
				if existing_pi:
					try:
						# Auch der Belegstatus muss ein Current Read sein. Ein
						# zweiter Request kann die alte Rechnung gerade storniert
						# haben, während dieser Methodenaufruf schon gestartet war.
						existing_doc = frappe.get_doc(
							"Purchase Invoice",
							existing_pi,
							for_update=True,
						)
						docstatus = int(existing_doc.docstatus or 0)
					except frappe.DoesNotExistError:
						docstatus = None
					if docstatus is not None and int(docstatus) != 2:
						skipped += 1
						continue
					row.db_set("purchase_invoice", None, update_modified=False)
					row.db_set("pi_erstellt_am", None, update_modified=False)
				pi = _create_purchase_invoice_for_plan_row(self, row)
				row.db_set("purchase_invoice", pi.name, update_modified=False)
				row.db_set("pi_erstellt_am", now_datetime(), update_modified=False)
				row.db_set("pi_fehler", None, update_modified=False)
				created.append(pi.name)
			except Exception as exc:
				frappe.db.rollback(save_point=savepoint)
				errors.append({"row": row.idx, "error": str(exc)})
				try:
					row.db_set("pi_fehler", str(exc)[:1000], update_modified=False)
				except Exception:
					pass
				frappe.log_error(
					frappe.get_traceback(),
					f"Zahlungsplan {self.name} Zeile {row.idx}: PI-Erzeugung fehlgeschlagen",
				)

		self.db_set("pi_letzter_lauf", now_datetime(), update_modified=False)

		return {
			"created": created,
			"errors": errors,
			"skipped_count": skipped,
		}


def _require_doctype_permissions(doctype: str, permission_types: tuple[str, ...]) -> None:
	for permission_type in permission_types:
		if frappe.has_permission(doctype, ptype=permission_type):
			continue
		frappe.throw(
			f"Keine Berechtigung für '{permission_type}' auf {doctype}.",
			frappe.PermissionError,
		)


def _lock_document_row(doctype: str, name: str | None) -> None:
	if not name:
		frappe.throw(f"{doctype} muss vor der Buchung gespeichert werden.")
	table = frappe.qb.DocType(doctype)
	found = (
		frappe.qb.from_(table)
		.select(table.name)
		.where(table.name == name)
		.for_update()
	).run()
	if not found:
		frappe.throw(f"{doctype} {name} wurde während der Buchung gelöscht.")


def _validate_single_currency_booking_context(doc: Zahlungsplan) -> frappe._dict:
	"""Resolve the supplier payable account and reject every foreign-currency path.

	The annual-settlement reconciler currently supplies amounts in account
	currency and therefore must never invent an exchange rate.  All participating
	documents/accounts have to use the company currency before any ledger document
	is submitted.
	"""
	company = doc.get("company")
	supplier = doc.get("lieferant")
	if not company or not supplier:
		frappe.throw("Company und Lieferant müssen gesetzt sein.")

	company_currency = frappe.db.get_value("Company", company, "default_currency")
	if not company_currency:
		frappe.throw(f"Für Company {company} ist keine Firmenwährung hinterlegt.")

	from erpnext.accounts.party import get_party_account

	payable_account = get_party_account("Supplier", supplier, company)
	if not payable_account:
		frappe.throw(
			f"Für Lieferant {supplier} ist in Company {company} kein "
			"Verbindlichkeitskonto hinterlegt."
		)
	account = frappe.db.get_value(
		"Account",
		payable_account,
		["name", "company", "is_group", "account_type", "account_currency"],
		as_dict=True,
	)
	if not account:
		frappe.throw(f"Verbindlichkeitskonto {payable_account} wurde nicht gefunden.")
	if account.company != company or int(account.is_group or 0):
		frappe.throw(
			f"Verbindlichkeitskonto {payable_account} ist für Company {company} "
			"nicht bebuchbar."
		)
	if account.account_type != "Payable":
		frappe.throw(
			f"Lieferantenkonto {payable_account} ist kein Verbindlichkeitskonto."
		)
	if account.account_currency != company_currency:
		frappe.throw(
			"Fremdwährung ist für Zahlungsplan-Jahresabrechnungen nicht unterstützt: "
			f"Firmenwährung {company_currency}, Lieferantenkonto "
			f"{payable_account} in {account.account_currency or 'ohne Währung'}."
		)

	return frappe._dict({
		"company": company,
		"supplier": supplier,
		"company_currency": company_currency,
		"payable_account": payable_account,
	})


def _validate_payment_entry_currency(pe, currency_context: frappe._dict) -> None:
	"""Ensure an advance PE is on the exact payable account in company currency."""
	if pe.get("company") != currency_context.company:
		frappe.throw(f"Payment Entry {pe.get('name')} gehört zu einer anderen Company.")
	if pe.get("paid_to") != currency_context.payable_account:
		frappe.throw(
			f"Payment Entry {pe.get('name')} bucht auf {pe.get('paid_to') or 'kein Konto'}, "
			f"die Jahresrechnung aber auf {currency_context.payable_account}. "
			"Eine automatische Verrechnung ist nicht sicher möglich."
		)
	paid_to_currency = pe.get("paid_to_account_currency") or frappe.db.get_value(
		"Account", pe.get("paid_to"), "account_currency"
	)
	if paid_to_currency != currency_context.company_currency:
		frappe.throw(
			"Fremdwährung ist für Zahlungsplan-Jahresabrechnungen nicht unterstützt: "
			f"Payment Entry {pe.get('name')} führt das Lieferantenkonto in "
			f"{paid_to_currency or 'unbekannter Währung'}, erwartet wird "
			f"{currency_context.company_currency}."
		)


def _validate_purchase_invoice_currency(
	pi: Document,
	currency_context: frappe._dict,
) -> None:
	"""Final guard immediately before submitting a generated Purchase Invoice."""
	if (
		pi.get("company") != currency_context.company
		or pi.get("supplier") != currency_context.supplier
		or pi.get("credit_to") != currency_context.payable_account
	):
		frappe.throw(
			"Die erzeugte Eingangsrechnung verwendet nicht exakt Company, Lieferant "
			"und Verbindlichkeitskonto des Zahlungsplans."
		)
	if pi.get("currency") != currency_context.company_currency:
		frappe.throw(
			"Fremdwährung ist für Zahlungsplan-Buchungen nicht unterstützt: "
			f"Eingangsrechnung {pi.get('currency') or 'ohne Währung'}, "
			f"Company {currency_context.company_currency}."
		)
	if abs(flt(pi.get("conversion_rate")) - 1.0) > 0.000001:
		frappe.throw(
			"Eine Eingangsrechnung in Firmenwährung muss einen Umrechnungskurs von 1 haben."
		)


def _validate_historical_prepayment_config(
	doc: Zahlungsplan,
	*,
	strict: bool = False,
) -> None:
	amount = flt(doc.get("vor_systemstart_bezahlt"))
	if amount < 0:
		frappe.throw("Die Zahlung vor Systemstart darf nicht negativ sein.")

	previous = None
	if doc.get("name") and not getattr(doc, "is_new", lambda: True)():
		previous = frappe.db.get_value(
			"Zahlungsplan",
			doc.name,
			[
				"vor_systemstart_bezahlt",
				"vor_systemstart_buchungsdatum",
				"vor_systemstart_gegenkonto",
				"vor_systemstart_journal_entry",
			],
			as_dict=True,
		)

	previous_journal = previous.get("vor_systemstart_journal_entry") if previous else None
	if previous_journal and frappe.db.get_value("Journal Entry", previous_journal, "docstatus") == 1:
		changed = (
			abs(flt(previous.get("vor_systemstart_bezahlt")) - amount) > 0.005
			or getdate(previous.get("vor_systemstart_buchungsdatum"))
			!= getdate(doc.get("vor_systemstart_buchungsdatum"))
			or (previous.get("vor_systemstart_gegenkonto") or None)
			!= (doc.get("vor_systemstart_gegenkonto") or None)
			or (doc.get("vor_systemstart_journal_entry") or None) != previous_journal
		)
		if changed:
			frappe.throw(
				f"Die historische Zahlung ist bereits mit Journal Entry {previous_journal} "
				"gebucht. Bitte diesen Beleg zuerst stornieren, bevor Betrag, Datum "
				"oder Gegenkonto geändert werden."
			)

	if amount <= 0:
		return

	legacy_unchanged = bool(
		previous
		and abs(flt(previous.get("vor_systemstart_bezahlt")) - amount) <= 0.005
		and not previous.get("vor_systemstart_buchungsdatum")
		and not previous.get("vor_systemstart_gegenkonto")
		and not previous.get("vor_systemstart_journal_entry")
		and not doc.get("vor_systemstart_buchungsdatum")
		and not doc.get("vor_systemstart_gegenkonto")
		and not doc.get("vor_systemstart_journal_entry")
	)
	if legacy_unchanged and not strict:
		# Existing virtual prepayments are kept editable for unrelated fields, but
		# annual settlement below calls this validator in strict mode and therefore
		# cannot continue until date/account are explicitly reviewed.
		return
	if not doc.get("vor_systemstart_buchungsdatum"):
		frappe.throw("Bitte das Buchungsdatum der Zahlung vor Systemstart angeben.")
	if not doc.get("vor_systemstart_gegenkonto"):
		frappe.throw("Bitte das Gegenkonto der Zahlung vor Systemstart angeben.")

	account = frappe.db.get_value(
		"Account",
		doc.get("vor_systemstart_gegenkonto"),
		["name", "company", "is_group", "root_type", "account_type", "account_currency"],
		as_dict=True,
	)
	if not account:
		frappe.throw("Das Gegenkonto der Zahlung vor Systemstart wurde nicht gefunden.")
	if account.company != doc.get("company"):
		frappe.throw("Das Gegenkonto der Zahlung vor Systemstart gehört zu einer anderen Company.")
	if int(account.is_group or 0):
		frappe.throw("Das Gegenkonto der Zahlung vor Systemstart muss ein bebuchbares Blattkonto sein.")
	if account.root_type not in {"Asset", "Liability", "Equity"}:
		frappe.throw("Das Gegenkonto der Zahlung vor Systemstart muss ein Bilanzkonto sein.")
	if account.account_type in {"Bank", "Cash", "Receivable", "Payable"}:
		frappe.throw(
			"Für die historische Übernahme ist ein Eröffnungs-/Verrechnungskonto "
			"erforderlich; Bank, Kasse, Debitoren und Kreditoren sind nicht zulässig."
		)

	company_currency = frappe.db.get_value("Company", doc.get("company"), "default_currency")
	if account.account_currency and account.account_currency != company_currency:
		frappe.throw(
			"Das Gegenkonto der historischen Zahlung muss in der Firmenwährung geführt werden."
		)

	payable_account = frappe.db.get_value("Company", doc.get("company"), "default_payable_account")
	if payable_account and payable_account == account.name:
		frappe.throw("Verbindlichkeitskonto und Gegenkonto der historischen Zahlung dürfen nicht identisch sein.")
	payable_currency = (
		frappe.db.get_value("Account", payable_account, "account_currency")
		if payable_account
		else None
	)
	if payable_currency and payable_currency != company_currency:
		frappe.throw(
			"Historische Zahlungen in Fremdwährung werden in diesem Workflow nicht unterstützt."
		)


def _locked_journal_entry_account_rows(journal_entry: str) -> list[dict]:
	"""Return one current, locked snapshot of all rows belonging to a Journal Entry."""
	return frappe.db.sql(
		"""
		SELECT
			name,
			idx,
			account,
			party_type,
			party,
			is_advance,
			debit_in_account_currency,
			credit_in_account_currency,
			exchange_rate,
			reference_type,
			reference_name
		FROM `tabJournal Entry Account`
		WHERE parent = %(journal_entry)s
		  AND parenttype = 'Journal Entry'
		ORDER BY idx ASC, name ASC
		FOR UPDATE
		""",
		{"journal_entry": journal_entry},
		as_dict=True,
	) or []


def _historical_advance_rows(
	journal_entry: str,
	*,
	payable_account: str,
	supplier: str,
	account_rows: list[dict] | None = None,
) -> list[dict]:
	"""Return only the supplier advance that is still open in Payment Ledger.

	ERPNext splits a Journal Entry Account row when it is partially reconciled.
	The current unreferenced JEA row and the active self-referenced Payment Ledger
	balance must therefore agree.  Any discrepancy is ambiguous and blocks the
	annual settlement instead of reusing a nominal/original advance amount.
	"""
	all_rows = (
		account_rows
		if account_rows is not None
		else _locked_journal_entry_account_rows(journal_entry)
	)
	rows = [
		frappe._dict(dict(row))
		for row in all_rows
		if row.get("account") == payable_account
		and row.get("party_type") == "Supplier"
		and row.get("party") == supplier
	]
	ledger_rows = frappe.db.sql(
		"""
		SELECT
			name,
			voucher_detail_no,
			against_voucher_type,
			against_voucher_no,
			amount_in_account_currency
		FROM `tabPayment Ledger Entry`
		WHERE delinked = 0
		  AND account_type = 'Payable'
		  AND account = %(payable_account)s
		  AND party_type = 'Supplier'
		  AND party = %(supplier)s
		  AND voucher_type = 'Journal Entry'
		  AND voucher_no = %(journal_entry)s
		ORDER BY name ASC
		FOR UPDATE
		""",
		{
			"journal_entry": journal_entry,
			"payable_account": payable_account,
			"supplier": supplier,
		},
		as_dict=True,
	) or []
	open_by_detail: dict[str, float] = {}
	for ledger_row in ledger_rows:
		if (
			ledger_row.get("against_voucher_type") != "Journal Entry"
			or ledger_row.get("against_voucher_no") != journal_entry
		):
			continue
		detail_name = (ledger_row.get("voucher_detail_no") or "").strip()
		if not detail_name:
			frappe.throw(
				f"Der offene Payment-Ledger-Saldo von {journal_entry} ist keiner "
				"Journal-Entry-Zeile zugeordnet."
			)
		# Payable advances are debit balances and therefore negative in PLE.
		open_by_detail[detail_name] = open_by_detail.get(detail_name, 0.0) - flt(
			ledger_row.get("amount_in_account_currency")
		)

	result: list[dict] = []
	for row in rows:
		if row.get("reference_type") not in (None, ""):
			continue
		row_amount = flt(row.get("debit_in_account_currency")) - flt(
			row.get("credit_in_account_currency")
		)
		ledger_available = open_by_detail.pop(row.get("name"), 0.0)
		if row_amount <= 0.005 and abs(ledger_available) <= 0.005:
			continue
		if (
			ledger_available <= 0.005
			or abs(row_amount - ledger_available) > 0.01
		):
			frappe.throw(
				f"Der offene Lieferantenvorschuss in Journal Entry {journal_entry} "
				"ist zwischen Journal Entry und Payment Ledger nicht konsistent."
			)
		row["available"] = ledger_available
		result.append(row)
	if any(abs(amount) > 0.005 for amount in open_by_detail.values()):
		frappe.throw(
			f"Der offene Payment-Ledger-Saldo von Journal Entry {journal_entry} "
			"kann keiner unverrechneten Lieferantenzeile zugeordnet werden."
		)
	return result


def _ensure_historical_advance_journal(
	doc: Zahlungsplan,
	payable_account: str,
	*,
	currency_context: frappe._dict | None = None,
) -> dict:
	amount = flt(doc.get("vor_systemstart_bezahlt"))
	if amount <= 0:
		return {"name": None, "rows": [], "available": 0.0}

	currency_context = currency_context or _validate_single_currency_booking_context(doc)
	if payable_account != currency_context.payable_account:
		frappe.throw(
			"Das Verbindlichkeitskonto der historischen Zahlung stimmt nicht mit "
			"dem Lieferantenkonto überein."
		)
	_validate_historical_prepayment_config(doc, strict=True)
	if doc.get("vor_systemstart_gegenkonto") == payable_account:
		frappe.throw(
			"Verbindlichkeitskonto und Gegenkonto der historischen Zahlung "
			"dürfen nicht identisch sein."
	)
	existing_name = doc.get("vor_systemstart_journal_entry")
	if existing_name:
		existing_rows = frappe.db.sql(
			"""
			SELECT name, docstatus, company, posting_date, user_remark, is_opening
			FROM `tabJournal Entry`
			WHERE name = %(journal_entry)s
			FOR UPDATE
			""",
			{"journal_entry": existing_name},
			as_dict=True,
		) or []
		existing = existing_rows[0] if existing_rows else None
		if existing and int(existing.docstatus or 0) == 1:
			if existing.company != doc.company:
				frappe.throw(f"Journal Entry {existing_name} gehört zu einer anderen Company.")
			if getdate(existing.posting_date) != getdate(doc.vor_systemstart_buchungsdatum):
				frappe.throw(f"Journal Entry {existing_name} hat ein unerwartetes Buchungsdatum.")
			marker = f"[Zahlungsplan:{doc.name}]"
			if marker not in (existing.user_remark or ""):
				frappe.throw(
					f"Journal Entry {existing_name} ist nicht eindeutig diesem Zahlungsplan zugeordnet."
				)
			if existing.is_opening != "Yes":
				frappe.throw(f"Journal Entry {existing_name} ist keine Eröffnungsbuchung.")
			all_rows = _locked_journal_entry_account_rows(existing_name)
			all_party_rows = [
				row
				for row in all_rows
				if row.get("account") == payable_account
				and row.get("party_type") == "Supplier"
				and row.get("party") == doc.lieferant
			]
			counter_rows = [row for row in all_rows if row not in all_party_rows]
			if not all_party_rows or any(row.get("is_advance") != "Yes" for row in all_party_rows):
				frappe.throw(f"Journal Entry {existing_name} enthält keinen gültigen Lieferantenvorschuss.")
			if (
				len(counter_rows) != 1
				or counter_rows[0].get("account") != doc.vor_systemstart_gegenkonto
				or abs(flt(counter_rows[0].get("credit_in_account_currency")) - amount) > 0.01
				or flt(counter_rows[0].get("debit_in_account_currency")) > 0.005
			):
				frappe.throw(f"Journal Entry {existing_name} hat ein unerwartetes Gegenkonto.")
			booked_amount = sum(
				flt(row.get("debit_in_account_currency"))
				- flt(row.get("credit_in_account_currency"))
				for row in all_party_rows
			)
			if abs(booked_amount - amount) > 0.01:
				frappe.throw(
					f"Journal Entry {existing_name} enthält {booked_amount:.2f} EUR, "
					f"im Zahlungsplan stehen {amount:.2f} EUR."
				)
			rows = _historical_advance_rows(
				existing_name,
				payable_account=payable_account,
				supplier=doc.lieferant,
				account_rows=all_rows,
			)
			if any(
				row.get("exchange_rate")
				and abs(flt(row.get("exchange_rate")) - 1.0) > 0.000001
				for row in rows
			):
				frappe.throw(
					f"Journal Entry {existing_name} enthält einen Fremdwährungskurs. "
					"Dieser Workflow unterstützt ausschließlich Firmenwährung."
				)
			return {
				"name": existing_name,
				"rows": rows,
				"available": sum(flt(row.get("available")) for row in rows),
			}
		if existing and int(existing.docstatus or 0) == 0:
			frappe.throw(
				f"Der verknüpfte Journal Entry {existing_name} ist nur ein Entwurf. "
				"Bitte einreichen oder löschen."
			)
		doc.db_set("vor_systemstart_journal_entry", None, update_modified=False)
		doc.vor_systemstart_journal_entry = None

	marker = f"[Zahlungsplan:{doc.name}]"
	remark = f"{marker} Historische Anzahlung vor Systemstart"
	if doc.get("vor_systemstart_bemerkung"):
		remark += f" | {cstr(doc.vor_systemstart_bemerkung).strip()}"

	je = frappe.new_doc("Journal Entry")
	je.update({
		"voucher_type": "Journal Entry",
		"is_opening": "Yes",
		"company": doc.company,
		"posting_date": getdate(doc.vor_systemstart_buchungsdatum),
		"user_remark": remark,
		"remark": remark,
	})
	je.append("accounts", {
		"account": payable_account,
		"party_type": "Supplier",
		"party": doc.lieferant,
		"is_advance": "Yes",
		"debit_in_account_currency": amount,
	})
	je.append("accounts", {
		"account": doc.vor_systemstart_gegenkonto,
		"credit_in_account_currency": amount,
	})
	je.insert()
	je.submit()

	doc.db_set("vor_systemstart_journal_entry", je.name, update_modified=False)
	doc.vor_systemstart_journal_entry = je.name
	rows = _historical_advance_rows(
		je.name,
		payable_account=payable_account,
		supplier=doc.lieferant,
	)
	if any(
		row.get("exchange_rate")
		and abs(flt(row.get("exchange_rate")) - 1.0) > 0.000001
		for row in rows
	):
		frappe.throw(
			"Die historische Zahlung wurde mit einem Fremdwährungskurs erzeugt; "
			"es wurde nichts gespeichert."
		)
	available = sum(flt(row.get("available")) for row in rows)
	if abs(available - amount) > 0.01:
		frappe.throw(
			"Die historische Zahlung wurde nicht als offener Lieferantenvorschuss gebucht. "
			"Es wurde nichts gespeichert."
		)
	return {"name": je.name, "rows": rows, "available": available}


def _allocation_claim_amount(allocation) -> float:
	"""Amount still owned by this plan allocation after released credit."""
	return max(
		flt(allocation.get("allocated_amount"))
		- flt(allocation.get("released_amount")),
		0.0,
	)


def _allocation_reserved_amount(allocation) -> float:
	"""Amount currently reserving the PE's ledger-level unallocated balance."""
	if allocation.get("settlement_invoice"):
		return 0.0
	return _allocation_claim_amount(allocation)


def _reserved_payment_amount_from_db(
	payment_entry: str,
	*,
	exclude_parent: str | None = None,
	for_update: bool = False,
) -> float:
	conditions = [
		"payment_entry = %(payment_entry)s",
		"status = 'Aktiv'",
		"(settlement_invoice IS NULL OR settlement_invoice = '')",
	]
	values = {"payment_entry": payment_entry}
	if exclude_parent:
		conditions.append("parent != %(exclude_parent)s")
		values["exclude_parent"] = exclude_parent
	if for_update:
		rows = frappe.db.sql(
			f"""
			SELECT name, allocated_amount, released_amount
			FROM `tabZahlungsplan Zahlung Zuordnung`
			WHERE {" AND ".join(conditions)}
			ORDER BY name ASC
			FOR UPDATE
			""",
			values,
			as_dict=True,
		) or []
		return sum(
			max(
				flt(row.get("allocated_amount"))
				- flt(row.get("released_amount")),
				0.0,
			)
			for row in rows
		)
	rows = frappe.db.sql(
		f"""
		SELECT COALESCE(
			SUM(GREATEST(allocated_amount - COALESCE(released_amount, 0), 0)),
			0
		)
		FROM `tabZahlungsplan Zahlung Zuordnung`
		WHERE {" AND ".join(conditions)}
		""",
		values,
	)
	return flt(rows[0][0]) if rows else 0.0


def _plan_row_is_in_period(plan_row, *, from_date=None, to_date=None) -> bool:
	row_date = (
		getdate(plan_row.get("faelligkeitsdatum"))
		if plan_row.get("faelligkeitsdatum")
		else None
	)
	if from_date and row_date and row_date < getdate(from_date):
		return False
	if to_date and row_date and row_date > getdate(to_date):
		return False
	return True


def _get_trackable_settlement_rows(
	doc: Zahlungsplan,
	*,
	payment_amounts: dict[str, float],
	from_date=None,
	to_date=None,
) -> dict[str, list[Document]]:
	"""Return locked allocation rows and reject untrackable legacy-only links."""
	if not payment_amounts:
		return {}
	plan_rows = {row.name: row for row in (doc.get("plan") or []) if row.get("name")}
	rows_by_payment: dict[str, list[Document]] = {}
	for allocation in doc.get("zahlungen") or []:
		if (allocation.get("status") or "Aktiv") != "Aktiv":
			continue
		if allocation.get("settlement_invoice"):
			continue
		plan_row = plan_rows.get(allocation.get("plan_zeile"))
		if not plan_row or not _plan_row_is_in_period(
			plan_row,
			from_date=from_date,
			to_date=to_date,
		):
			continue
		payment_entry = allocation.get("payment_entry")
		if payment_entry not in payment_amounts or _allocation_claim_amount(allocation) <= 0:
			continue
		rows_by_payment.setdefault(payment_entry, []).append(allocation)

	for payment_entry, expected in sorted(payment_amounts.items()):
		rows = rows_by_payment.get(payment_entry) or []
		tracked = sum(_allocation_claim_amount(row) for row in rows)
		if abs(tracked - flt(expected)) > 0.01:
			frappe.throw(
				f"Payment Entry {payment_entry} enthält eine nicht eindeutig "
				"nachverfolgbare Alt-Zuordnung. Bitte zuerst die "
				"Zahlungszuordnungen migrieren bzw. prüfen; es wurde nichts gebucht."
			)
		rows.sort(
			key=lambda row: (
				flt(row.get("plan_zeile_idx")),
				flt(row.get("idx")),
				row.get("name") or "",
			)
		)

	# Parent was loaded FOR UPDATE, but lock the concrete child rows too so a
	# direct child-table update cannot race the consumption write.
	for row_name in sorted(
		row.get("name")
		for rows in rows_by_payment.values()
		for row in rows
		if row.get("name")
	):
		_lock_document_row("Zahlungsplan Zahlung Zuordnung", row_name)
	return rows_by_payment


def _settle_payment_allocations(
	rows_by_payment: dict[str, list[Document]],
	*,
	settlement_invoice: str,
	reconciled_by_payment: dict[str, float],
) -> list[str]:
	"""Close period allocations and release the unused supplier-credit remainder."""
	updated: list[str] = []
	for payment_entry, rows in sorted(rows_by_payment.items()):
		remaining_consumption = flt(reconciled_by_payment.get(payment_entry))
		total_claim = sum(_allocation_claim_amount(row) for row in rows)
		if remaining_consumption > total_claim + 0.01:
			frappe.throw(
				f"Payment Entry {payment_entry} sollte mit {remaining_consumption:.2f} EUR "
				f"verrechnet werden, ist im Zahlungsplan aber nur mit "
				f"{total_claim:.2f} EUR nachverfolgbar."
			)

		for allocation in rows:
			claim = _allocation_claim_amount(allocation)
			consumed = min(claim, max(remaining_consumption, 0.0))
			remaining_consumption -= consumed
			new_released = (
				flt(allocation.get("released_amount"))
				+ claim
				- consumed
			)
			values = {
				"consumed_amount": consumed,
				"released_amount": new_released,
				"settlement_invoice": settlement_invoice,
			}
			frappe.db.set_value(
				"Zahlungsplan Zahlung Zuordnung",
				allocation.name,
				values,
				update_modified=False,
			)
			for fieldname, value in values.items():
				allocation.set(fieldname, value)
			updated.append(allocation.name)

		if remaining_consumption > 0.01:
			frappe.throw(
				f"Payment Entry {payment_entry} konnte nicht vollständig einer "
				"Zahlungszuordnung zugeordnet werden."
			)
	return updated


def _validate_payment_allocations(doc: Zahlungsplan) -> None:
	"""Validate the many-to-many mapping without relying on legacy row links."""
	allocations = [
		row
		for row in (doc.get("zahlungen") or [])
		if (row.get("status") or "Aktiv") == "Aktiv"
	]
	if not allocations:
		return
	if doc.get("modus") != MODUS_ABSCHLAGSPLAN:
		frappe.throw("Zahlungszuordnungen sind nur im Modus 'Abschlagsplan' zulässig.")

	plan_rows = {row.name: row for row in (doc.get("plan") or []) if row.get("name")}
	seen_pairs: set[tuple[str, str]] = set()
	amount_by_plan_row: dict[str, float] = {}
	reserved_by_payment: dict[str, float] = {}

	for allocation in allocations:
		row_name = (allocation.get("plan_zeile") or "").strip()
		payment_entry = (allocation.get("payment_entry") or "").strip()
		amount = flt(allocation.get("allocated_amount"))
		consumed = flt(allocation.get("consumed_amount"))
		released = flt(allocation.get("released_amount"))
		if row_name not in plan_rows:
			frappe.throw("Eine Zahlungszuordnung verweist auf eine unbekannte Plan-Zeile.")
		if not payment_entry:
			frappe.throw("In einer Zahlungszuordnung fehlt der Payment Entry.")
		if amount <= 0:
			frappe.throw("Der zugeordnete Zahlungsbetrag muss positiv sein.")
		if (
			consumed < -0.005
			or released < -0.005
			or consumed + released > amount + 0.01
		):
			frappe.throw(
				f"Zahlungszuordnung für Payment Entry {payment_entry} enthält "
				"inkonsistente verrechnete/freigegebene Beträge."
			)
		if consumed > 0.005 and not allocation.get("settlement_invoice"):
			frappe.throw(
				f"Zahlungszuordnung für Payment Entry {payment_entry} hat einen "
				"verrechneten Betrag ohne Jahresrechnung."
			)
		pair = (row_name, payment_entry)
		if pair in seen_pairs:
			frappe.throw(
				f"Payment Entry {payment_entry} ist der Plan-Zeile "
				f"{plan_rows[row_name].idx} mehrfach zugeordnet."
			)
		seen_pairs.add(pair)
		amount_by_plan_row[row_name] = (
			amount_by_plan_row.get(row_name, 0.0)
			+ _allocation_claim_amount(allocation)
		)
		reserved_by_payment[payment_entry] = (
			reserved_by_payment.get(payment_entry, 0.0)
			+ _allocation_reserved_amount(allocation)
		)

	for row_name, allocated in amount_by_plan_row.items():
		planned = flt(plan_rows[row_name].get("betrag"))
		if allocated > planned + 0.01:
			frappe.throw(
				f"Plan-Zeile {plan_rows[row_name].idx} ist mit {allocated:.2f} EUR "
				f"über ihren Betrag von {planned:.2f} EUR hinaus bezahlt."
			)

	for payment_entry, reserved in reserved_by_payment.items():
		pe = frappe.db.get_value(
			"Payment Entry",
			payment_entry,
			[
				"docstatus",
				"company",
				"party_type",
				"party",
				"payment_type",
				"paid_amount",
				"unallocated_amount",
			],
			as_dict=True,
		)
		if not pe or int(pe.docstatus or 0) != 1:
			frappe.throw(f"Payment Entry {payment_entry} ist nicht eingereicht.")
		if (
			pe.company != doc.get("company")
			or pe.party_type != "Supplier"
			or pe.party != doc.get("lieferant")
			or pe.payment_type != "Pay"
		):
			frappe.throw(
				f"Payment Entry {payment_entry} passt nicht zu Company und Lieferant des Zahlungsplans."
			)
		external_reserved = _reserved_payment_amount_from_db(
			payment_entry,
			exclude_parent=doc.get("name") or None,
		)
		total_reserved = reserved + external_reserved
		if total_reserved > flt(pe.unallocated_amount) + 0.01:
			frappe.throw(
				f"Payment Entry {payment_entry} reserviert planübergreifend "
				f"{total_reserved:.2f} EUR, hat im Ledger aber nur "
				f"{flt(pe.unallocated_amount):.2f} EUR unverrechnetes Guthaben."
			)


def _active_allocation_amounts(
	doc: Zahlungsplan,
	*,
	from_date=None,
	to_date=None,
	unsettled_only: bool = False,
) -> tuple[dict[str, float], dict[str, float]]:
	"""Return (amount by PE, amount by plan-row), including safe legacy links."""
	plan_rows = {row.name: row for row in (doc.get("plan") or []) if row.get("name")}
	amount_by_payment: dict[str, float] = {}
	amount_by_plan_row: dict[str, float] = {}
	known_pairs = {
		(allocation.get("plan_zeile"), allocation.get("payment_entry"))
		for allocation in (doc.get("zahlungen") or [])
		if allocation.get("plan_zeile") and allocation.get("payment_entry")
	}

	for allocation in doc.get("zahlungen") or []:
		if (allocation.get("status") or "Aktiv") != "Aktiv":
			continue
		if unsettled_only and allocation.get("settlement_invoice"):
			continue
		row_name = allocation.get("plan_zeile")
		plan_row = plan_rows.get(row_name)
		if not plan_row or not _plan_row_is_in_period(
			plan_row,
			from_date=from_date,
			to_date=to_date,
		):
			continue
		payment_entry = allocation.get("payment_entry")
		amount = _allocation_claim_amount(allocation)
		if not payment_entry or amount <= 0:
			continue
		amount_by_payment[payment_entry] = amount_by_payment.get(payment_entry, 0.0) + amount
		amount_by_plan_row[row_name] = amount_by_plan_row.get(row_name, 0.0) + amount

	# Compatibility during rollout: a legacy one-to-one row link counts only
	# when it has not already been migrated to the allocation table.  A
	# non-active "Prüfen"/"Storniert" row deliberately suppresses the legacy
	# fallback, otherwise an ambiguous or cancelled link would become active
	# again during annual settlement.
	for plan_row in plan_rows.values():
		if not _plan_row_is_in_period(
			plan_row,
			from_date=from_date,
			to_date=to_date,
		):
			continue
		payment_entry = plan_row.get("payment_entry")
		if not payment_entry or (plan_row.name, payment_entry) in known_pairs:
			continue
		amount = flt(plan_row.get("betrag"))
		if amount <= 0:
			continue
		amount_by_payment[payment_entry] = amount_by_payment.get(payment_entry, 0.0) + amount
		amount_by_plan_row[plan_row.name] = amount_by_plan_row.get(plan_row.name, 0.0) + amount

	return amount_by_payment, amount_by_plan_row


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
	"""Daily entrypoint: recompute status across all Zahlungspläne (handles time transitions)."""
	names = frappe.get_all("Zahlungsplan", pluck="name")
	for name in names:
		try:
			doc = frappe.get_doc("Zahlungsplan", name)
			new_status = _compute_status(doc)
			if doc.get("status") != new_status:
				doc.db_set("status", new_status, update_modified=False)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"Zahlungsplan Status-Update: {name}")


def _document_is_cancelled_or_missing(doctype: str, name: str | None) -> bool:
	if not name:
		return False
	docstatus = frappe.db.get_value(doctype, name, "docstatus")
	if docstatus is None:
		return True
	try:
		return int(docstatus) == 2
	except Exception:
		return False


def _lock_documents_by_name(
	doctype: str,
	names,
	*,
	allow_missing: bool = False,
) -> dict[str, Document | None]:
	"""Lock documents in deterministic name order and return their current state."""
	locked: dict[str, Document | None] = {}
	for name in sorted({cstr(value).strip() for value in names if value}):
		try:
			locked[name] = frappe.get_doc(doctype, name, for_update=True)
		except frappe.DoesNotExistError:
			if not allow_missing:
				raise
			locked[name] = None
	return locked


def _locked_document_is_cancelled_or_missing(doc: Document | None) -> bool:
	return doc is None or int(doc.get("docstatus") or 0) == 2


def _recompute_zahlungsplan_status(name: str) -> None:
	try:
		doc = frappe.get_doc("Zahlungsplan", name)
		doc.db_set("status", _compute_status(doc), update_modified=False)
	except Exception:
		frappe.log_error(frappe.get_traceback(), f"Zahlungsplan Status-Recompute: {name}")


def _sync_purchase_invoices_for_plan(doc: Zahlungsplan) -> dict:
	"""Keep generated row invoices in sync while they are still fully open.

	Submitted Purchase Invoices are accounting documents. Instead of mutating a
	submitted invoice amount/item in place, we cancel the still-unpaid generated
	invoice and create a replacement from the current plan row.
	"""
	if doc.get("modus") != MODUS_ZAHLUNGSPLAN:
		return {"checked": 0, "updated": []}

	checked = 0
	updated: list[dict[str, str]] = []
	skipped: list[dict[str, str]] = []

	for row in doc.get("plan") or []:
		pi_name = row.get("purchase_invoice")
		if not pi_name:
			continue
		checked += 1
		_lock_document_row("Zahlungsplan Zeile", row.name)
		try:
			# Locking/current read is essential here: after waiting for a
			# concurrent Payment Entry, a regular REPEATABLE-READ lookup could
			# still expose the old outstanding amount and cancel a now-paid PI.
			pi = frappe.get_doc("Purchase Invoice", pi_name, for_update=True)
		except frappe.DoesNotExistError:
			row.db_set("purchase_invoice", None, update_modified=False)
			row.db_set("pi_erstellt_am", None, update_modified=False)
			row.db_set("pi_fehler", f"Eingangsrechnung {pi_name} nicht gefunden.", update_modified=False)
			skipped.append({"row": row.name, "reason": "missing"})
			continue

		if int(pi.docstatus or 0) == 2:
			row.db_set("purchase_invoice", None, update_modified=False)
			row.db_set("pi_erstellt_am", None, update_modified=False)
			continue
		if int(pi.docstatus or 0) != 1:
			continue
		if _purchase_invoice_matches_plan_row(doc, row, pi):
			if row.get("pi_fehler"):
				row.db_set("pi_fehler", None, update_modified=False)
			continue
		if not _purchase_invoice_is_unreconciled(pi):
			message = (
				f"Eingangsrechnung {pi.name} ist bereits teilbezahlt/verrechnet "
				"und wurde nicht automatisch angepasst."
			)
			row.db_set("pi_fehler", message, update_modified=False)
			skipped.append({"row": row.name, "reason": "reconciled"})
			continue

		# Cancellation, replacement and relinking deliberately share the caller's
		# transaction.  Any failure must propagate so the old submitted invoice is
		# restored by rollback instead of leaving the row orphaned.
		pi.cancel()
		new_pi = _create_purchase_invoice_for_plan_row(doc, row)
		row.db_set("purchase_invoice", new_pi.name, update_modified=False)
		row.db_set("pi_erstellt_am", now_datetime(), update_modified=False)
		row.db_set("pi_fehler", None, update_modified=False)
		updated.append({"row": row.name, "old": pi.name, "new": new_pi.name})

	return {"checked": checked, "updated": updated, "skipped": skipped}


def _purchase_invoice_is_unreconciled(pi: Document) -> bool:
	total = flt(pi.get("rounded_total")) or flt(pi.get("grand_total"))
	return abs(flt(pi.get("outstanding_amount")) - total) <= 0.01


def _purchase_invoice_matches_plan_row(doc: Zahlungsplan, row: Document, pi: Document) -> bool:
	try:
		item_code, expense_account, cost_center = _resolve_pi_fields(doc)
	except Exception:
		return False

	expected_amount = flt(row.get("betrag"))
	expected_date = getdate(row.get("faelligkeitsdatum")) if row.get("faelligkeitsdatum") else None
	expected_remarks = _build_plan_row_pi_remarks(doc, row)
	items = pi.get("items") or []

	if pi.get("company") != doc.get("company") or pi.get("supplier") != doc.get("lieferant"):
		return False
	if expected_date and getdate(pi.get("posting_date")) != expected_date:
		return False
	if expected_date and getdate(pi.get("bill_date")) != expected_date:
		return False
	if pi.meta.get_field("custom_wertstellungsdatum") and expected_date:
		if getdate(pi.get("custom_wertstellungsdatum")) != expected_date:
			return False
	if (pi.get("remarks") or "") != expected_remarks:
		return False
	if len(items) != 1:
		return False

	item = items[0]
	if item.get("item_code") != item_code:
		return False
	if abs(flt(item.get("rate")) - expected_amount) > 0.01:
		return False
	if item.get("expense_account") != expense_account:
		return False
	if (item.get("cost_center") or None) != (cost_center or None):
		return False

	return True


def _release_settlement_allocations(purchase_invoice_name: str) -> list[str]:
	"""Undo allocation consumption after a settlement PI was cancelled.

	``released_amount`` deliberately stays in place: that portion was unused by
	the settlement and may already be reserved by a later plan.  Only the amount
	that had actually been consumed becomes an open reservation again.
	"""
	candidates = frappe.get_all(
		"Zahlungsplan Zahlung Zuordnung",
		filters={"settlement_invoice": purchase_invoice_name},
		fields=["name", "parent", "payment_entry"],
		order_by="parent asc, payment_entry asc, name asc",
	)
	if not candidates:
		return []

	# Match the booking lock order (plan -> payment -> child) to avoid deadlocks.
	for parent in sorted({row.get("parent") for row in candidates if row.get("parent")}):
		frappe.get_doc("Zahlungsplan", parent, for_update=True)
	payments = {}
	for payment_entry in sorted(
		{row.get("payment_entry") for row in candidates if row.get("payment_entry")}
	):
		payments[payment_entry] = frappe.get_doc(
			"Payment Entry",
			payment_entry,
			for_update=True,
		)

	allocations = []
	for candidate in candidates:
		allocation = frappe.get_doc(
			"Zahlungsplan Zahlung Zuordnung",
			candidate.name,
			for_update=True,
		)
		if allocation.get("settlement_invoice") != purchase_invoice_name:
			continue
		allocations.append(allocation)

	restore_by_payment: dict[str, float] = {}
	for allocation in allocations:
		payment_entry = allocation.get("payment_entry")
		restore_by_payment[payment_entry] = (
			restore_by_payment.get(payment_entry, 0.0)
			+ _allocation_claim_amount(allocation)
		)
	for payment_entry, restored in restore_by_payment.items():
		pe = payments.get(payment_entry)
		if not pe:
			frappe.throw(
				f"Payment Entry {payment_entry} der Jahresabrechnung wurde nicht gefunden."
			)
		already_reserved = _reserved_payment_amount_from_db(
			payment_entry,
			for_update=True,
		)
		if already_reserved + restored > flt(pe.get("unallocated_amount")) + 0.01:
			frappe.throw(
				f"Storno von {purchase_invoice_name} würde Payment Entry "
				f"{payment_entry} doppelt reservieren: verfügbar "
				f"{flt(pe.get('unallocated_amount')):.2f} EUR, benötigt "
				f"{already_reserved + restored:.2f} EUR. Das Storno wurde abgebrochen."
			)

	released: list[str] = []
	for allocation in allocations:
		allocation.db_set(
			{
				"consumed_amount": 0,
				"settlement_invoice": None,
			},
			update_modified=False,
		)
		released.append(allocation.name)
	return released


def sync_cancelled_payment_entry_links(payment_entry_name: str | None = None) -> dict:
	"""Mark allocations cancelled and clear compatible legacy row links."""
	conditions = ["payment_entry IS NOT NULL", "payment_entry != ''"]
	allocation_conditions = [
		"payment_entry IS NOT NULL",
		"payment_entry != ''",
		"status != 'Storniert'",
	]
	values: dict[str, str] = {}
	if payment_entry_name:
		conditions.append("payment_entry = %(payment_entry_name)s")
		allocation_conditions.append("payment_entry = %(payment_entry_name)s")
		values["payment_entry_name"] = payment_entry_name

	rows = frappe.db.sql(
		f"""
		SELECT name, parent, payment_entry
		FROM `tabZahlungsplan Zeile`
		WHERE {" AND ".join(conditions)}
		ORDER BY parent ASC, name ASC
		""",
		values,
		as_dict=True,
	) or []
	allocations = frappe.db.sql(
		f"""
		SELECT name, parent, payment_entry
		FROM `tabZahlungsplan Zahlung Zuordnung`
		WHERE {" AND ".join(allocation_conditions)}
		ORDER BY parent ASC, name ASC
		""",
		values,
		as_dict=True,
	) or []

	# Preserve the booking lock order: plan -> Payment Entry -> child rows.
	parent_names = {
		row.get("parent")
		for row in [*rows, *allocations]
		if row.get("parent")
	}
	locked_parents = _lock_documents_by_name("Zahlungsplan", parent_names)
	payment_names = {
		row.get("payment_entry")
		for row in [*rows, *allocations]
		if row.get("payment_entry")
	}
	locked_payments = _lock_documents_by_name(
		"Payment Entry",
		payment_names,
		allow_missing=True,
	)
	locked_allocations = _lock_documents_by_name(
		"Zahlungsplan Zahlung Zuordnung",
		[allocation.get("name") for allocation in allocations],
		allow_missing=True,
	)
	locked_rows = _lock_documents_by_name(
		"Zahlungsplan Zeile",
		[row.get("name") for row in rows],
		allow_missing=True,
	)

	cleared: list[str] = []
	cancelled_allocations: list[str] = []
	affected_parents: set[str] = set()
	for candidate in allocations:
		allocation = locked_allocations.get(candidate.get("name"))
		if (
			not allocation
			or allocation.get("parent") != candidate.get("parent")
			or allocation.get("payment_entry") != candidate.get("payment_entry")
			or allocation.get("status") == "Storniert"
			or not locked_parents.get(candidate.get("parent"))
			or not _locked_document_is_cancelled_or_missing(
				locked_payments.get(candidate.get("payment_entry"))
			)
		):
			continue
		frappe.db.set_value(
			"Zahlungsplan Zahlung Zuordnung",
			allocation.name,
			"status",
			"Storniert",
			update_modified=False,
		)
		cancelled_allocations.append(allocation.name)
		if allocation.get("parent"):
			affected_parents.add(allocation.parent)

	for candidate in rows:
		row = locked_rows.get(candidate.get("name"))
		if (
			not row
			or row.get("parent") != candidate.get("parent")
			or row.get("payment_entry") != candidate.get("payment_entry")
			or not locked_parents.get(candidate.get("parent"))
			or not _locked_document_is_cancelled_or_missing(
				locked_payments.get(candidate.get("payment_entry"))
			)
		):
			continue
		frappe.db.set_value(
			"Zahlungsplan Zeile",
			row.name,
			{
				"payment_entry": None,
				"bank_transaction": None,
				"gebucht_am": None,
			},
			update_modified=False,
		)
		cleared.append(row.name)
		if row.get("parent"):
			affected_parents.add(row.parent)

	for parent in sorted(affected_parents):
		_recompute_zahlungsplan_status(parent)

	return {
		"checked": len(rows),
		"cleared": len(cleared),
		"rows": cleared,
		"checked_allocations": len(allocations),
		"cancelled_allocations": cancelled_allocations,
	}


def sync_cancelled_purchase_invoice_links(purchase_invoice_name: str | None = None) -> dict:
	"""Gibt Zahlungsplan-PI-Links frei, deren Purchase Invoice storniert oder gelöscht ist."""
	row_conditions = ["purchase_invoice IS NOT NULL", "purchase_invoice != ''"]
	parent_conditions = ["ja_purchase_invoice IS NOT NULL", "ja_purchase_invoice != ''"]
	values: dict[str, str] = {}
	if purchase_invoice_name:
		row_conditions.append("purchase_invoice = %(purchase_invoice_name)s")
		parent_conditions.append("ja_purchase_invoice = %(purchase_invoice_name)s")
		values["purchase_invoice_name"] = purchase_invoice_name

	rows = frappe.db.sql(
		f"""
		SELECT name, parent, purchase_invoice
		FROM `tabZahlungsplan Zeile`
		WHERE {" AND ".join(row_conditions)}
		ORDER BY parent ASC, name ASC
		""",
		values,
		as_dict=True,
	) or []
	parents = frappe.db.sql(
		f"""
		SELECT name, ja_purchase_invoice
		FROM `tabZahlungsplan`
		WHERE {" AND ".join(parent_conditions)}
		ORDER BY name ASC
		""",
		values,
		as_dict=True,
	) or []

	# Preserve the same order as invoice generation: plan -> Purchase Invoice ->
	# child row.  Every link is compared again on its locked current document.
	parent_names = {
		row.get("parent") for row in rows if row.get("parent")
	} | {
		parent.get("name") for parent in parents if parent.get("name")
	}
	locked_parents = _lock_documents_by_name("Zahlungsplan", parent_names)
	invoice_names = {
		row.get("purchase_invoice") for row in rows if row.get("purchase_invoice")
	} | {
		parent.get("ja_purchase_invoice")
		for parent in parents
		if parent.get("ja_purchase_invoice")
	}
	locked_invoices = _lock_documents_by_name(
		"Purchase Invoice",
		invoice_names,
		allow_missing=True,
	)
	locked_rows = _lock_documents_by_name(
		"Zahlungsplan Zeile",
		[row.get("name") for row in rows],
		allow_missing=True,
	)

	cleared_rows: list[str] = []
	affected_parents: set[str] = set()
	for candidate in rows:
		row = locked_rows.get(candidate.get("name"))
		if (
			not row
			or row.get("parent") != candidate.get("parent")
			or row.get("purchase_invoice") != candidate.get("purchase_invoice")
			or not locked_parents.get(candidate.get("parent"))
			or not _locked_document_is_cancelled_or_missing(
				locked_invoices.get(candidate.get("purchase_invoice"))
			)
		):
			continue
		frappe.db.set_value(
			"Zahlungsplan Zeile",
			row.name,
			{
				"purchase_invoice": None,
				"pi_erstellt_am": None,
			},
			update_modified=False,
		)
		cleared_rows.append(row.name)
		if row.get("parent"):
			affected_parents.add(row.parent)

	cleared_plans: list[str] = []
	for candidate in parents:
		parent = locked_parents.get(candidate.get("name"))
		if (
			not parent
			or parent.get("ja_purchase_invoice")
			!= candidate.get("ja_purchase_invoice")
			or not _locked_document_is_cancelled_or_missing(
				locked_invoices.get(candidate.get("ja_purchase_invoice"))
			)
		):
			continue
		frappe.db.set_value(
			"Zahlungsplan",
			parent.name,
			{
				"ja_purchase_invoice": None,
				"ja_status": None,
				"ja_differenz": None,
			},
			update_modified=False,
		)
		cleared_plans.append(parent.name)
		affected_parents.add(parent.name)

	for parent in sorted(affected_parents):
		_recompute_zahlungsplan_status(parent)

	return {
		"checked_rows": len(rows),
		"cleared_rows": cleared_rows,
		"checked_plans": len(parents),
		"cleared_plans": cleared_plans,
	}


def on_payment_entry_cancel(doc, method=None) -> None:
	sync_cancelled_payment_entry_links(payment_entry_name=doc.name)


def _unlink_settlement_advances(doc: Document) -> None:
	"""Make PI-cancellation restore advances regardless of the global setting."""
	from erpnext.accounts.utils import unlink_ref_doc_from_payment_entries

	# ERPNext may already have done this via
	# ``unlink_payment_on_cancellation_of_invoice``.  The helper is idempotent
	# when no references remain, and makes the Zahlungsplan invariant independent
	# of that mutable Accounts Settings flag.
	unlink_ref_doc_from_payment_entries(doc)


def on_purchase_invoice_cancel(doc, method=None) -> None:
	is_annual_settlement = bool(
		frappe.db.exists(
			"Zahlungsplan",
			{"ja_purchase_invoice": doc.name},
		)
		or frappe.db.exists(
			"Zahlungsplan Zahlung Zuordnung",
			{"settlement_invoice": doc.name},
		)
	)
	if is_annual_settlement:
		_unlink_settlement_advances(doc)
		_release_settlement_allocations(doc.name)
	sync_cancelled_purchase_invoice_links(purchase_invoice_name=doc.name)


def prevent_historical_journal_entry_cancel_with_active_invoice(doc, method=None) -> None:
	plans = frappe.get_all(
		"Zahlungsplan",
		filters={"vor_systemstart_journal_entry": doc.name},
		fields=["name", "ja_purchase_invoice"],
	)
	for plan in plans:
		if not plan.get("ja_purchase_invoice"):
			continue
		if frappe.db.get_value("Purchase Invoice", plan.ja_purchase_invoice, "docstatus") == 1:
			frappe.throw(
				f"Journal Entry {doc.name} ist als historische Zahlung im Zahlungsplan "
				f"{plan.name} verrechnet. Bitte zuerst die Jahresrechnung "
				f"{plan.ja_purchase_invoice} stornieren."
			)


def on_historical_journal_entry_cancel(doc, method=None) -> None:
	plans = frappe.get_all(
		"Zahlungsplan",
		filters={"vor_systemstart_journal_entry": doc.name},
		fields=["name", "ja_purchase_invoice"],
	)
	for plan in plans:
		updates = {"vor_systemstart_journal_entry": None}
		if plan.get("ja_purchase_invoice"):
			invoice = frappe.db.get_value(
				"Purchase Invoice",
				plan.get("ja_purchase_invoice"),
				["docstatus", "outstanding_amount"],
				as_dict=True,
			)
			if invoice and int(invoice.docstatus or 0) == 1:
				outstanding = flt(invoice.outstanding_amount)
				updates["ja_differenz"] = outstanding
				updates["ja_status"] = (
					f"Nachzahlung: {outstanding:,.2f} EUR"
					if outstanding > 0.01
					else "Ausgeglichen"
				)
		frappe.db.set_value(
			"Zahlungsplan",
			plan.name,
			updates,
			update_modified=False,
		)


def create_due_purchase_invoices_global():
	"""Daily scheduler-entrypoint: erzeuge fällige PIs für alle aktiven Zahlungspläne (Modus=Zahlungsplan)."""
	names = frappe.get_all(
		"Zahlungsplan",
		filters={"modus": MODUS_ZAHLUNGSPLAN, "status": ["!=", "Abgerechnet"]},
		pluck="name",
	)
	for name in names:
		try:
			doc = frappe.get_doc("Zahlungsplan", name)
			doc.create_due_purchase_invoices()
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"Zahlungsplan Auto-PI Lauf: {name}",
			)


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


def _get_abschlag_tolerance_days(default: int = 7) -> int:
	try:
		value = frappe.db.get_single_value(
			"Hausverwaltung Einstellungen", "bankimport_abschlag_toleranz_tage"
		)
		if value is not None and int(value) >= 0:
			return int(value)
	except Exception:
		pass
	return default


def _append_payment_allocation(
	plan: Zahlungsplan,
	plan_row: Document,
	*,
	payment_entry: str,
	allocated_amount: float,
	bank_transaction: str | None = None,
	posting_date=None,
) -> Document:
	amount = flt(allocated_amount)
	if amount <= 0:
		frappe.throw("Der zugeordnete Zahlungsbetrag muss positiv sein.")

	for existing in plan.get("zahlungen") or []:
		if (
			(existing.get("status") or "Aktiv") == "Aktiv"
			and existing.get("plan_zeile") == plan_row.name
			and existing.get("payment_entry") == payment_entry
		):
			if abs(flt(existing.get("allocated_amount")) - amount) <= 0.01:
				return existing
			frappe.throw(
				f"Payment Entry {payment_entry} ist Plan-Zeile {plan_row.idx} "
				"bereits mit einem anderen Betrag zugeordnet."
			)

	_amount_by_payment, amount_by_row = _active_allocation_amounts(plan)
	remaining = flt(plan_row.get("betrag")) - flt(amount_by_row.get(plan_row.name))
	if amount > remaining + 0.01:
		frappe.throw(
			f"Plan-Zeile {plan_row.idx} hat nur noch {max(remaining, 0):.2f} EUR offen."
		)

	return plan.append("zahlungen", {
		"plan_zeile": plan_row.name,
		"plan_zeile_idx": plan_row.idx,
		"payment_entry": payment_entry,
		"bank_transaction": bank_transaction,
		"allocated_amount": amount,
		"consumed_amount": 0,
		"released_amount": 0,
		"posting_date": getdate(posting_date) if posting_date else None,
		"status": "Aktiv",
	})


def record_payment_allocation(
	*,
	plan_name: str,
	plan_row_name: str,
	payment_entry: str,
	allocated_amount: float,
	bank_transaction: str | None = None,
	posting_date=None,
) -> dict:
	"""Atomically add one allocation and keep legacy one-to-one fields compatible."""
	plan = frappe.get_doc("Zahlungsplan", plan_name, for_update=True)
	pe = frappe.get_doc("Payment Entry", payment_entry, for_update=True)
	if plan.get("modus") != MODUS_ABSCHLAGSPLAN:
		frappe.throw("Die ausgewählte Zeile gehört nicht zu einem Abschlagsplan.")
	if plan.get("status") == "Abgerechnet":
		frappe.throw(f"Abschlagsplan {plan.name} ist bereits abgerechnet.")

	plan_row = next(
		(row for row in (plan.get("plan") or []) if row.name == plan_row_name),
		None,
	)
	if not plan_row:
		frappe.throw(f"Plan-Zeile {plan_row_name} wurde nicht gefunden.")

	amount = flt(allocated_amount)
	for existing in plan.get("zahlungen") or []:
		if (
			(existing.get("status") or "Aktiv") == "Aktiv"
			and existing.get("plan_zeile") == plan_row.name
			and existing.get("payment_entry") == payment_entry
		):
			if abs(flt(existing.get("allocated_amount")) - amount) > 0.01:
				frappe.throw(
					f"Payment Entry {payment_entry} ist Plan-Zeile {plan_row.idx} "
					"bereits mit einem anderen Betrag zugeordnet."
				)
			_amount_by_payment, amount_by_row = _active_allocation_amounts(plan)
			return {
				"plan": plan.name,
				"row_idx": plan_row.idx,
				"row_name": plan_row.name,
				"allocation": existing.name,
				"allocated_amount": flt(existing.get("allocated_amount")),
				"paid_amount": flt(amount_by_row.get(plan_row.name)),
				"remaining_amount": max(
					flt(plan_row.get("betrag")) - flt(amount_by_row.get(plan_row.name)),
					0.0,
				),
			}

	if int(pe.docstatus or 0) != 1:
		frappe.throw(f"Payment Entry {payment_entry} ist nicht eingereicht.")
	if (
		pe.company != plan.company
		or pe.party_type != "Supplier"
		or pe.party != plan.lieferant
		or pe.payment_type != "Pay"
	):
		frappe.throw(f"Payment Entry {payment_entry} passt nicht zum Zahlungsplan.")

	allocated_elsewhere = _reserved_payment_amount_from_db(payment_entry)
	available_for_plans = flt(pe.unallocated_amount)
	if allocated_elsewhere + amount > available_for_plans + 0.01:
		frappe.throw(
			f"Payment Entry {payment_entry} hat nur {available_for_plans:.2f} EUR "
			"unzugeordneten Vorschuss; die Zahlungspläne würden zusammen "
			f"{allocated_elsewhere + amount:.2f} EUR beanspruchen."
		)

	allocation = _append_payment_allocation(
		plan,
		plan_row,
		payment_entry=payment_entry,
		allocated_amount=amount,
		bank_transaction=bank_transaction,
		posting_date=posting_date,
	)

	# The old fields can only represent a true one-to-one full payment.  Keep
	# them for compatibility in that case, otherwise leave them empty rather
	# than pointing at one arbitrary partial payment.
	active_for_row = [
		row
		for row in (plan.get("zahlungen") or [])
		if (row.get("status") or "Aktiv") == "Aktiv"
		and row.get("plan_zeile") == plan_row.name
	]
	total_for_row = sum(_allocation_claim_amount(row) for row in active_for_row)
	if (
		len(active_for_row) == 1
		and abs(total_for_row - flt(plan_row.get("betrag"))) <= 0.01
	):
		plan_row.payment_entry = payment_entry
		plan_row.bank_transaction = bank_transaction
		plan_row.gebucht_am = getdate(posting_date) if posting_date else None
	else:
		plan_row.payment_entry = None
		plan_row.bank_transaction = None
		plan_row.gebucht_am = None

	plan.save(ignore_permissions=True)
	return {
		"plan": plan.name,
		"row_idx": plan_row.idx,
		"row_name": plan_row.name,
		"allocation": allocation.name,
		"allocated_amount": flt(allocation.get("allocated_amount")),
		"paid_amount": total_for_row,
		"remaining_amount": max(flt(plan_row.get("betrag")) - total_for_row, 0.0),
	}


def link_payment_entry_to_abschlagsplan_row(
	*,
	supplier: str,
	posting_date,
	amount: float,
	payment_entry: str,
	bank_transaction: str | None = None,
	tolerance_days: int | None = None,
	tolerance_amount: float = 0.01,
) -> dict | None:
	"""Find a matching Abschlagsplan plan row for a freshly-created advance PE.

	Searches active Abschlagspläne for the given supplier and allocates only to
	a row whose complete remaining amount matches.  Partial payments require an
	explicit user assignment; guessing them from amount/date is too risky.

	Returns ``{plan, row_idx, faelligkeitsdatum, betrag}`` if linked, else None.
	No-op (returns None) when no Abschlagsplan exists, no matching row is
	found, or multiple rows tie on date difference — the user can still link
	manually in the plan tab.
	"""
	if not supplier or not payment_entry or amount is None:
		return None
	target_date = getdate(posting_date) if posting_date else None
	target_amount = float(amount)
	if target_amount <= 0:
		return None
	if tolerance_days is None:
		tolerance_days = _get_abschlag_tolerance_days()

	plans = frappe.get_all(
		"Zahlungsplan",
		filters={
			"lieferant": supplier,
			"modus": MODUS_ABSCHLAGSPLAN,
			"status": ["!=", "Abgerechnet"],
		},
		pluck="name",
	)
	if not plans:
		return None

	candidates = []
	for plan_name in plans:
		plan = frappe.get_doc("Zahlungsplan", plan_name)
		_amount_by_payment, amount_by_row = _active_allocation_amounts(plan)
		for row in plan.get("plan") or []:
			row_remaining = flt(row.get("betrag")) - flt(amount_by_row.get(row.name))
			if row_remaining <= tolerance_amount:
				continue
			if abs(target_amount - row_remaining) > tolerance_amount:
				continue
			row_date = getdate(row.faelligkeitsdatum) if row.get("faelligkeitsdatum") else None
			if target_date and row_date:
				delta = abs((row_date - target_date).days)
				if delta > tolerance_days:
					continue
			else:
				delta = 9999
			candidates.append((delta, plan, row))

	if not candidates:
		return None
	candidates.sort(key=lambda c: c[0])
	# Tie-break: wenn die zwei besten Kandidaten gleich nah dran sind, lieber
	# nichts verlinken — der User soll bewusst entscheiden.
	if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
		return None

	_, plan, row = candidates[0]
	result = record_payment_allocation(
		plan_name=plan.name,
		plan_row_name=row.name,
		payment_entry=payment_entry,
		allocated_amount=target_amount,
		bank_transaction=bank_transaction,
		posting_date=target_date,
	)
	result.update({
		"faelligkeitsdatum": str(row.faelligkeitsdatum) if row.get("faelligkeitsdatum") else None,
		"betrag": flt(row.get("betrag")),
	})
	return result


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


def _create_payment_entry_for_plan_row(doc: Zahlungsplan, row: Document, posting_date_override=None):
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

	currency_context = _validate_single_currency_booking_context(doc)
	amount = float(row.betrag)
	if amount <= 0:
		frappe.throw(f"Plan-Zeile {row.idx}: Betrag muss positiv sein.")

	posting_date = getdate(posting_date_override) if posting_date_override else getdate(row.faelligkeitsdatum)

	paid_from = frappe.get_cached_value("Bank Account", doc.bank_account, "account")
	if not paid_from:
		frappe.throw("Im Bankkonto ist kein 'Account' hinterlegt.")
	paid_from_currency = frappe.db.get_value("Account", paid_from, "account_currency")
	if paid_from_currency != currency_context.company_currency:
		frappe.throw(
			"Fremdwährung ist für automatische Zahlungsplan-Buchungen nicht unterstützt: "
			f"Bankkonto {paid_from} in {paid_from_currency or 'unbekannter Währung'}, "
			f"Company {currency_context.company_currency}."
		)
	paid_to = currency_context.payable_account

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
		"paid_from_account_currency": currency_context.company_currency,
		"paid_to_account_currency": currency_context.company_currency,
		"paid_amount": amount,
		"received_amount": amount,
		"source_exchange_rate": 1,
		"target_exchange_rate": 1,
		"remarks": _build_remarks(doc) + f" | Plan-Zeile {row.idx}",
	})

	if doc.get("reference_no"):
		_set_if_field(pe, "reference_no", doc.reference_no)
		_set_if_field(pe, "reference_date", posting_date)

	pe.set("references", [])

	pe.insert(ignore_permissions=True)
	pe.submit()
	return pe


def _create_purchase_invoice_for_plan_row(doc: Zahlungsplan, row: Document):
	"""Modus=Zahlungsplan: erzeuge eine eigene Purchase Invoice für eine Plan-Zeile.

	Nutzt die gleichen Felder/Defaults wie ``_create_jahresabrechnung_pi`` — das
	Wertstellungsdatum wird auf das Fälligkeitsdatum der Plan-Zeile gesetzt.
	"""
	if not doc.get("company"):
		frappe.throw("Bitte eine Company auswählen.")
	if not doc.get("lieferant"):
		frappe.throw("Bitte einen Lieferanten auswählen.")

	amount = float(row.betrag)
	if amount <= 0:
		frappe.throw(f"Plan-Zeile {row.idx}: Betrag muss positiv sein.")

	posting_date = getdate(row.faelligkeitsdatum)

	pi = _build_purchase_invoice(
		doc=doc,
		amount=amount,
		posting_date=posting_date,
		bill_no=None,
		wertstellungsdatum=posting_date,
		remarks=_build_plan_row_pi_remarks(doc, row),
	)
	return pi


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


def _get_from_immobilie(doc: Zahlungsplan, fieldname: str):
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


def _get_item_code_from_kostenart(doc: Zahlungsplan):
	doctype, name = _resolve_kostenart_source(doc)
	if not (doctype and name):
		return None
	try:
		if _doctype_has_field(doctype, "artikel"):
			return frappe.get_cached_value(doctype, name, "artikel")
	except Exception:
		return None
	return None


def _get_expense_account_from_kostenart(doc: Zahlungsplan):
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


def _build_remarks(doc: Zahlungsplan) -> str:
	parts = []
	if doc.get("bezeichnung"):
		parts.append(cstr(doc.get("bezeichnung")))
	if doc.get("vertragsnummer"):
		parts.append(f"Vertrag: {doc.get('vertragsnummer')}")
	if doc.get("immobilie"):
		parts.append(f"Immobilie: {doc.get('immobilie')}")
	if doc.get("wohnung"):
		parts.append(f"Wohnung: {doc.get('wohnung')}")
	return " | ".join(parts) or f"Zahlungsplan ({DEFAULT_SERVICE_ITEM_CODE})"


def _build_plan_row_pi_remarks(doc: Zahlungsplan, row: Document) -> str:
	remarks = _build_remarks(doc) + f" | Plan-Zeile {row.idx}"
	bemerkung_extra = (row.get("bemerkung") or "").strip()
	if bemerkung_extra:
		remarks += f" | {bemerkung_extra}"
	return remarks


def _resolve_pi_fields(doc: Zahlungsplan):
	"""Resolve item_code, expense_account, cost_center using the existing fallback chains."""
	item_code = doc.get("item_code") or _get_item_code_from_kostenart(doc) or ensure_default_service_item()
	expense_account = doc.get("expense_account") or _get_expense_account_from_kostenart(doc)
	cost_center = doc.get("cost_center") or _get_from_immobilie(doc, "kostenstelle") or _get_company_default(doc.company, "cost_center")
	if not expense_account:
		expense_account = _get_company_default(doc.company, "default_expense_account")
	if not expense_account:
		frappe.throw("Bitte ein Aufwandskonto angeben oder in der Company ein Standard-Aufwandskonto pflegen.")
	return item_code, expense_account, cost_center


def _build_purchase_invoice(
	*,
	doc: Zahlungsplan,
	amount: float,
	posting_date,
	bill_no: str | None,
	wertstellungsdatum,
	remarks: str,
	currency_context: frappe._dict | None = None,
):
	"""Shared PI-Builder für Jahresabrechnung und einzelne Plan-Zeilen-Rechnungen."""
	currency_context = currency_context or _validate_single_currency_booking_context(doc)
	item_code, expense_account, cost_center = _resolve_pi_fields(doc)

	pi = frappe.new_doc("Purchase Invoice")
	pi.update({
		"company": doc.company,
		"supplier": doc.lieferant,
		"posting_date": posting_date,
		"bill_date": posting_date,
		"bill_no": bill_no,
		"remarks": remarks,
		"credit_to": currency_context.payable_account,
		"currency": currency_context.company_currency,
		"conversion_rate": 1,
	})
	if wertstellungsdatum:
		_set_if_field(pi, "custom_wertstellungsdatum", wertstellungsdatum)
	pi.append("items", {
		"item_code": item_code,
		"qty": 1,
		"rate": float(amount),
		"expense_account": expense_account,
		"cost_center": cost_center,
	})
	pi.insert()
	_validate_purchase_invoice_currency(pi, currency_context)
	pi.submit()
	return pi


def _create_jahresabrechnung_pi(
	doc: Zahlungsplan,
	*,
	currency_context: frappe._dict | None = None,
):
	"""Create and submit a Purchase Invoice for the annual bill."""
	posting_date = doc.get("ja_rechnungsdatum") or nowdate()
	wertstellung = doc.get("ja_wertstellungsdatum") or doc.get("ja_bis")
	remarks = _build_remarks(doc) + f" | Jahresabrechnung {doc.ja_von} - {doc.ja_bis}"
	return _build_purchase_invoice(
		doc=doc,
		amount=float(doc.ja_betrag),
		posting_date=posting_date,
		bill_no=doc.get("ja_rechnungsnr"),
		wertstellungsdatum=wertstellung,
		remarks=remarks,
		currency_context=currency_context,
	)
