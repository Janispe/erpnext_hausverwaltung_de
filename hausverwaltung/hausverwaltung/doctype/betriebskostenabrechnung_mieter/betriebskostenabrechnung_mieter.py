from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any, Dict, Iterable, List, Mapping

import frappe
from frappe.contacts.doctype.address.address import get_default_address
from frappe.model.document import Document
from frappe.utils import cint, cstr, getdate

from hausverwaltung.hausverwaltung.utils.mieter_name import (
	get_contact_last_name,
	get_hauptmieter_display_name,
	pick_preferred_mieter_contact,
	sanitize_name_part,
)
from hausverwaltung.hausverwaltung.utils.betriebskostenregelung import (
	BK_REGELUNG_VORAUSZAHLUNG,
	normalize_bk_regelung,
)


def _row_value(row: object, fieldname: str) -> Any:
	getter = getattr(row, "get", None)
	return getter(fieldname) if callable(getter) else getattr(row, fieldname, None)


def _get_locked_settlement_allocations(
	invoice_names: Iterable[str],
	*,
	ignored_journal_entries_by_invoice: Mapping[str, Iterable[str]] | None = None,
) -> Dict[str, List[Dict[str, Any]]]:
	"""Lock settlement invoices and their PE/JE references; return active allocations.

	All reference rows are locked, including rows belonging to draft vouchers.
	That closes the window in which an already prepared Payment Entry or Journal
	Entry could otherwise be submitted while the settlement invoice is cancelled.
	"""
	names = sorted({cstr(name).strip() for name in invoice_names if cstr(name).strip()})
	if not names:
		return {}

	placeholders = ", ".join(["%s"] * len(names))
	params = tuple(names)
	invoice_rows = frappe.db.sql(
		f"""
		SELECT name, docstatus
		FROM `tabSales Invoice`
		WHERE name IN ({placeholders})
		ORDER BY name
		FOR UPDATE
		""",
		params,
		as_dict=True,
	)
	found = {cstr(_row_value(row, "name")) for row in invoice_rows}
	missing = sorted(set(names) - found)
	if missing:
		frappe.throw(
			"Storno aus Sicherheitsgründen abgebrochen: Die verknüpften "
			f"Sales-Invoice-Belege fehlen: {', '.join(missing)}."
		)

	payment_rows = frappe.db.sql(
		f"""
		SELECT
			per.name AS reference_row,
			per.reference_name AS invoice,
			per.parent AS voucher,
			per.allocated_amount AS allocated_amount,
			pe.docstatus AS voucher_docstatus,
			pe.posting_date AS posting_date
		FROM `tabPayment Entry Reference` per
		INNER JOIN `tabPayment Entry` pe ON pe.name = per.parent
		WHERE per.reference_doctype = 'Sales Invoice'
		  AND per.reference_name IN ({placeholders})
		ORDER BY per.reference_name, per.parent, per.name
		FOR UPDATE
		""",
		params,
		as_dict=True,
	)
	journal_rows = frappe.db.sql(
		f"""
		SELECT
			jea.name AS reference_row,
			jea.reference_name AS invoice,
			jea.parent AS voucher,
			jea.debit_in_account_currency AS debit_amount,
			jea.credit_in_account_currency AS credit_amount,
			je.docstatus AS voucher_docstatus,
			je.posting_date AS posting_date
		FROM `tabJournal Entry Account` jea
		INNER JOIN `tabJournal Entry` je ON je.name = jea.parent
		WHERE jea.reference_type = 'Sales Invoice'
		  AND jea.reference_name IN ({placeholders})
		ORDER BY jea.reference_name, jea.parent, jea.name
		FOR UPDATE
		""",
		params,
		as_dict=True,
	)

	allocations: Dict[str, List[Dict[str, Any]]] = {name: [] for name in names}
	for row in payment_rows:
		if int(_row_value(row, "voucher_docstatus") or 0) != 1:
			continue
		amount = abs(float(_row_value(row, "allocated_amount") or 0))
		if amount <= 0.000001:
			continue
		invoice = cstr(_row_value(row, "invoice")).strip()
		allocations[invoice].append(
			{
				"document_type": "Payment Entry",
				"document": _row_value(row, "voucher"),
				"payment_entry": _row_value(row, "voucher"),
				"allocated_amount": amount,
				"posting_date": _row_value(row, "posting_date"),
			}
		)

	ignored_by_invoice = {
		cstr(invoice).strip(): {cstr(name).strip() for name in ignored if cstr(name).strip()}
		for invoice, ignored in (ignored_journal_entries_by_invoice or {}).items()
	}
	for row in journal_rows:
		if int(_row_value(row, "voucher_docstatus") or 0) != 1:
			continue
		invoice = cstr(_row_value(row, "invoice")).strip()
		voucher = cstr(_row_value(row, "voucher")).strip()
		if voucher in ignored_by_invoice.get(invoice, set()):
			# This settlement owns the consolidation JE and cancels it first in
			# the same transaction.
			continue
		amount = max(
			abs(float(_row_value(row, "debit_amount") or 0)),
			abs(float(_row_value(row, "credit_amount") or 0)),
		)
		if amount <= 0.000001:
			continue
		allocations[invoice].append(
			{
				"document_type": "Journal Entry",
				"document": voucher,
				"journal_entry": voucher,
				"allocated_amount": amount,
				"posting_date": _row_value(row, "posting_date"),
			}
		)

	return allocations


class BetriebskostenabrechnungMieter(Document):
	def autoname(self) -> None:
		if getattr(self, "name", None):
			return

		mieter_contact = pick_preferred_mieter_contact(getattr(self, "mieter", None))
		base_parts = [
			mieter_contact or "Mieter",
			self.wohnung,
			self.von,
			self.bis,
		]
		base_parts = [sanitize_name_part(str(p)) for p in base_parts if p]
		base_name = "-".join([p for p in base_parts if p]).strip()
		if not base_name:
			return

		last_name = sanitize_name_part(get_contact_last_name(mieter_contact))
		if last_name:
			base_name = f"{base_name} - {last_name}"

		candidate = base_name
		suffix = 1
		while frappe.db.exists("Betriebskostenabrechnung Mieter", candidate, cache=False):
			suffix += 1
			candidate = f"{base_name}-{suffix}"
		self.name = candidate

	def _cancel_linked_document(self, linked) -> None:
		"""Cancel an already ownership-validated document."""
		if not linked:
			return
		doctype = cstr(getattr(linked, "doctype", None) or "")
		name = cstr(getattr(linked, "name", None) or "")
		if getattr(linked, "docstatus", None) == 2:
			return

		try:
			linked.flags.ignore_permissions = True
			if getattr(linked, "docstatus", None) == 0:
				linked.delete(ignore_permissions=True)
			else:
				linked.cancel()
		except Exception as e:
			frappe.throw(f"Verknüpfter Beleg konnte nicht storniert werden ({doctype} {name}): {e}")

	def _assert_bijective_voucher_link(
		self,
		fieldname: str,
		voucher_name: str,
	) -> None:
		if fieldname in ("sales_invoice", "credit_note"):
			rows = frappe.db.sql(
				"""
				SELECT name, sales_invoice, credit_note
				FROM `tabBetriebskostenabrechnung Mieter`
				WHERE sales_invoice = %(voucher)s
				   OR credit_note = %(voucher)s
				ORDER BY name
				FOR UPDATE
				""",
				{"voucher": voucher_name},
				as_dict=True,
			)
			opposite = (
				"credit_note"
				if fieldname == "sales_invoice"
				else "sales_invoice"
			)
			exact = (
				len(rows) == 1
				and cstr(_row_value(rows[0], "name")) == cstr(self.name)
				and cstr(_row_value(rows[0], fieldname) or "").strip()
				== voucher_name
				and cstr(_row_value(rows[0], opposite) or "").strip()
				!= voucher_name
			)
		else:
			rows = frappe.db.sql(
				f"""
				SELECT name, `{fieldname}`
				FROM `tabBetriebskostenabrechnung Mieter`
				WHERE `{fieldname}` = %s
				ORDER BY name
				FOR UPDATE
				""",
				(voucher_name,),
				as_dict=True,
			)
			exact = (
				len(rows) == 1
				and cstr(_row_value(rows[0], "name")) == cstr(self.name)
				and cstr(_row_value(rows[0], fieldname) or "").strip()
				== voucher_name
			)
		names = [cstr(_row_value(row, "name")) for row in rows]
		if not exact:
			frappe.throw(
				"Storno aus Sicherheitsgründen abgebrochen: Der Beleg "
				f"{voucher_name} ist nicht bijektiv über {fieldname} mit "
				f"{self.name} verknüpft ({', '.join(names) or 'kein Rücklink'}).",
				frappe.ValidationError,
			)

	def _validate_owned_sales_invoice(
		self,
		fieldname: str,
		name: str,
		*,
		expected_return: int,
		expected_item: str,
	):
		self._assert_bijective_voucher_link(fieldname, name)
		try:
			invoice = frappe.get_doc("Sales Invoice", name, for_update=True)
		except Exception as exc:
			frappe.throw(
				f"Storno aus Sicherheitsgründen abgebrochen: Sales Invoice "
				f"{name} konnte nicht eindeutig geladen werden ({exc}).",
				frappe.ValidationError,
			)
		if cint(getattr(invoice, "docstatus", 0)) not in (1, 2):
			frappe.throw(
				f"Storno aus Sicherheitsgründen abgebrochen: Sales Invoice "
				f"{name} ist nicht eingereicht.",
				frappe.ValidationError,
			)

		items = list(getattr(invoice, "items", None) or [])
		remarks = cstr(getattr(invoice, "remarks", None) or "")
		markers = re.findall(
			r"\[((?:BK|HK)-SETTLEMENT):([^\]\r\n]+)\]",
			remarks,
		)
		has_own_token = markers == [("BK-SETTLEMENT", cstr(self.name))]
		has_marker_syntax = bool(
			markers
			or "BK-SETTLEMENT" in remarks
			or "HK-SETTLEMENT" in remarks
		)
		if has_marker_syntax and not has_own_token:
			frappe.throw(
				f"Storno aus Sicherheitsgründen abgebrochen: Sales Invoice "
				f"{name} trägt einen fremden BK-Settlement-Marker.",
				frappe.ValidationError,
			)

		customer_matches = (
			cstr(getattr(invoice, "customer", None) or "").strip()
			== cstr(self.customer or "").strip()
		)
		direction_and_item_match = (
			cint(getattr(invoice, "is_return", 0)) == expected_return
			and len(items) == 1
			and cstr(_row_value(items[0], "item_code") or "").strip()
			== expected_item
		)
		invoice_wohnung = cstr(
			getattr(invoice, "wohnung", None) or ""
		).strip()
		item_wohnung = (
			cstr(_row_value(items[0], "wohnung") or "").strip()
			if items
			else ""
		)
		direct_wohnung_matches = (
			invoice_wohnung == cstr(self.wohnung or "").strip()
			and item_wohnung == cstr(self.wohnung or "").strip()
		)
		if not customer_matches or not direction_and_item_match:
			frappe.throw(
				"Storno aus Sicherheitsgründen abgebrochen: Sales Invoice "
				f"{name} passt nicht exakt zu Customer, Richtung und "
				f"Settlement-Item von {self.name}.",
				frappe.ValidationError,
			)

		from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import (
			_company_via_wohnung,
		)

		expected_company = cstr(
			_company_via_wohnung(cstr(self.wohnung or "").strip()) or ""
		).strip()
		company_currency = cstr(
			frappe.db.get_value(
				"Company",
				expected_company,
				"default_currency",
			)
			or ""
		).strip()
		account_name = cstr(
			getattr(invoice, "debit_to", None) or ""
		).strip()
		account_rows = frappe.db.sql(
			"""
			SELECT name, company, account_type, account_currency
			FROM `tabAccount`
			WHERE name = %s
			FOR UPDATE
			""",
			(account_name,),
			as_dict=True,
		) if account_name else []
		account = account_rows[0] if len(account_rows) == 1 else {}
		if (
			not expected_company
			or not company_currency
			or cstr(getattr(invoice, "company", None) or "").strip()
			!= expected_company
			or cstr(getattr(invoice, "currency", None) or "").strip()
			!= company_currency
			or cstr(_row_value(account, "company") or "").strip()
			!= expected_company
			or cstr(_row_value(account, "account_type") or "").strip()
			!= "Receivable"
			or cstr(_row_value(account, "account_currency") or "").strip()
			!= company_currency
		):
			frappe.throw(
				"Storno aus Sicherheitsgründen abgebrochen: Company, "
				f"Währung oder Debitorenkonto von Sales Invoice {name} "
				"sind nicht kanonisch für die Wohnung.",
				frappe.ValidationError,
			)

		if has_own_token and not direct_wohnung_matches:
			frappe.throw(
				f"Storno aus Sicherheitsgründen abgebrochen: Sales Invoice "
				f"{name} trägt den neuen Marker, aber nicht die exakte Wohnung "
				"auf Beleg und Item.",
				frappe.ValidationError,
			)
		if not has_own_token:
			expected_wohnung = cstr(self.wohnung or "").strip()
			if (
				(invoice_wohnung and invoice_wohnung != expected_wohnung)
				or (item_wohnung and item_wohnung != expected_wohnung)
			):
				frappe.throw(
					f"Storno aus Sicherheitsgründen abgebrochen: Der "
					f"markerlose Altbeleg {name} trägt eine abweichende Wohnung.",
					frappe.ValidationError,
				)
			contract_rows = frappe.db.sql(
				"""
				SELECT name, kunde, wohnung
				FROM `tabMietvertrag`
				WHERE name = %s
				FOR UPDATE
				""",
				(cstr(self.mietvertrag or "").strip(),),
				as_dict=True,
			)
			if len(contract_rows) != 1:
				frappe.throw(
					"Storno aus Sicherheitsgründen abgebrochen: Der "
					"markerlose Altbeleg hat keinen eindeutig gesperrten "
					"Mietvertrag.",
					frappe.ValidationError,
				)
			contract = contract_rows[0]
			if (
				cstr(_row_value(contract, "kunde") or "").strip()
				!= cstr(self.customer or "").strip()
				or cstr(_row_value(contract, "wohnung") or "").strip()
				!= expected_wohnung
			):
				frappe.throw(
					"Storno aus Sicherheitsgründen abgebrochen: Customer/"
					"Wohnung des markerlosen Altbelegs sind nicht über den "
					"Mietvertrag belegbar.",
					frappe.ValidationError,
				)
			if cstr(
				getattr(invoice, "custom_wertstellungsdatum", None) or ""
			) != cstr(self.bis or ""):
				frappe.throw(
					"Storno aus Sicherheitsgründen abgebrochen: Der "
					"markerlose Altbeleg hat nicht das exakte "
					"Abrechnungs-Wertstellungsdatum.",
					frappe.ValidationError,
				)
			if (
				not getattr(invoice, "posting_date", None)
				or getdate(invoice.posting_date) != getdate(self.bis)
			):
				frappe.throw(
					"Storno aus Sicherheitsgründen abgebrochen: Das "
					f"Postdatum des markerlosen Altbelegs {name} passt nicht "
					"zum Abrechnungsende.",
					frappe.ValidationError,
				)
			from hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen import (
				_build_settlement_remark,
			)

			expected_legacy_remark = _build_settlement_remark(
				self.von,
				self.bis,
			)
			if remarks.strip() != expected_legacy_remark:
				frappe.throw(
					"Storno aus Sicherheitsgründen abgebrochen: Der Zeitraum "
					f"im markerlosen Altbeleg {name} ist nicht exakt "
					"nachweisbar.",
					frappe.ValidationError,
				)
			total = sum(
				(
					Decimal(str(_row_value(row, "betrag") or 0))
					for row in getattr(self, "abrechnung", None) or []
				),
				Decimal("0"),
			)
			expected_amount = (
				total - Decimal(str(self.vorrauszahlungen or 0))
			).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
			actual_amount = Decimal(
				str(getattr(invoice, "grand_total", 0) or 0)
			).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
			item_amount = Decimal(
				str(_row_value(items[0], "net_amount") or 0)
			).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
			if actual_amount != expected_amount or item_amount != actual_amount:
				frappe.throw(
					"Storno aus Sicherheitsgründen abgebrochen: Betrag des "
					f"markerlosen Altbelegs {name} ({actual_amount:.2f}) passt "
					f"nicht exakt zur Abrechnung ({expected_amount:.2f}).",
					frappe.ValidationError,
				)
			if cstr(getattr(invoice, "return_against", None) or "").strip():
				frappe.throw(
					"Storno aus Sicherheitsgründen abgebrochen: Der "
					f"markerlose Altbeleg {name} ist kein eigenständiger "
					"Settlement-Beleg.",
					frappe.ValidationError,
				)
			taxes = list(getattr(invoice, "taxes", None) or [])
			if (
				Decimal(
					str(
						getattr(
							invoice,
							"total_taxes_and_charges",
							0,
						)
						or 0
					)
				).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
				!= Decimal("0.00")
				or any(
					Decimal(
						str(_row_value(tax, "tax_amount") or 0)
					).quantize(
						Decimal("0.01"),
						rounding=ROUND_HALF_UP,
					)
					!= Decimal("0.00")
					for tax in taxes
				)
			):
				frappe.throw(
					f"Storno aus Sicherheitsgründen abgebrochen: Der "
					f"markerlose Altbeleg {name} enthält Steuern.",
					frappe.ValidationError,
				)
			income_account = cstr(
				_row_value(items[0], "income_account") or ""
			).strip()
			cost_center = cstr(
				_row_value(items[0], "cost_center") or ""
			).strip()
			income_rows = frappe.db.sql(
				"""
				SELECT name, company
				FROM `tabAccount`
				WHERE name = %s
				FOR UPDATE
				""",
				(income_account,),
				as_dict=True,
			) if income_account else []
			cost_center_rows = frappe.db.sql(
				"""
				SELECT name, company
				FROM `tabCost Center`
				WHERE name = %s
				FOR UPDATE
				""",
				(cost_center,),
				as_dict=True,
			) if cost_center else []
			if (
				len(income_rows) != 1
				or cstr(_row_value(income_rows[0], "company") or "").strip()
				!= expected_company
				or len(cost_center_rows) != 1
				or cstr(
					_row_value(cost_center_rows[0], "company") or ""
				).strip()
				!= expected_company
			):
				frappe.throw(
					"Storno aus Sicherheitsgründen abgebrochen: Income "
					f"Account oder Cost Center von Altbeleg {name} gehören "
					"nicht zur kanonischen Company.",
					frappe.ValidationError,
				)
		return invoice, has_own_token

	def _validate_owned_journal_entry(
		self,
		name: str,
		owned_invoices: Dict[str, bool],
	):
		self._assert_bijective_voucher_link(
			"consolidation_journal_entry",
			name,
		)
		if not owned_invoices:
			frappe.throw(
				"Storno aus Sicherheitsgründen abgebrochen: Der "
				"Konsolidierungs-JE besitzt keinen eigenen Ausgleichsbeleg.",
				frappe.ValidationError,
			)
		try:
			journal = frappe.get_doc("Journal Entry", name, for_update=True)
		except Exception as exc:
			frappe.throw(
				f"Storno aus Sicherheitsgründen abgebrochen: Journal Entry "
				f"{name} konnte nicht eindeutig geladen werden ({exc}).",
				frappe.ValidationError,
			)
		if cint(getattr(journal, "docstatus", 0)) not in (1, 2):
			frappe.throw(
				f"Storno aus Sicherheitsgründen abgebrochen: Journal Entry "
				f"{name} ist nicht eingereicht.",
				frappe.ValidationError,
			)

		remark = cstr(getattr(journal, "user_remark", None) or "")
		token = f"[BK-SETTLEMENT:{self.name}]"
		markers = re.findall(
			r"\[((?:BK|HK)-SETTLEMENT):([^\]\r\n]+)\]",
			remark,
		)
		has_own_token = (
			markers == [("BK-SETTLEMENT", cstr(self.name))]
			and remark.count(token) == 1
		)
		if (
			not has_own_token
			or remark.count("BK-SETTLEMENT") != 1
			or "HK-SETTLEMENT" in remark
		):
			frappe.throw(
				f"Storno aus Sicherheitsgründen abgebrochen: Journal Entry "
				f"{name} trägt nicht genau den eigenen BK-Settlement-Marker.",
				frappe.ValidationError,
			)
		if not all(owned_invoices.values()):
			frappe.throw(
				f"Storno aus Sicherheitsgründen abgebrochen: Journal Entry "
				f"{name} ist markiert, sein Ausgleichsbeleg aber nicht.",
				frappe.ValidationError,
			)

		from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import (
			_company_via_wohnung,
		)
		from hausverwaltung.hausverwaltung.scripts.betriebskosten.operating_cost_prepaiment_calc import (
			_bk_invoice_names_for_wohnung,
		)

		expected_company = cstr(
			_company_via_wohnung(cstr(self.wohnung or "").strip()) or ""
		).strip()
		company_currency = cstr(
			frappe.db.get_value(
				"Company",
				expected_company,
				"default_currency",
			)
			or ""
		).strip()
		if (
			not expected_company
			or not company_currency
			or cstr(getattr(journal, "company", None) or "").strip()
			!= expected_company
		):
			frappe.throw(
				f"Storno aus Sicherheitsgründen abgebrochen: Journal Entry "
				f"{name} gehört nicht zur kanonischen Company der Wohnung.",
				frappe.ValidationError,
			)

		contract_identity = {
			"name": cstr(self.mietvertrag or "").strip(),
			"kunde": cstr(self.customer or "").strip(),
			"wohnung": cstr(self.wohnung or "").strip(),
		}
		source_names = set(
			_bk_invoice_names_for_wohnung(
				contract_identity["wohnung"],
				self.von,
				self.bis,
				customer=contract_identity["kunde"],
				mietvertrag=contract_identity["name"],
				company=expected_company,
				contract_identity=contract_identity,
				lock=True,
			)
			or []
		)
		target_names = set(owned_invoices)
		source_names -= target_names

		accounts = list(getattr(journal, "accounts", None) or [])
		if len(accounts) < 2:
			frappe.throw(
				f"Storno aus Sicherheitsgründen abgebrochen: Journal Entry "
				f"{name} enthält keine vollständige Verrechnung.",
				frappe.ValidationError,
			)
		account_names = sorted(
			{
				cstr(_row_value(row, "account") or "").strip()
				for row in accounts
				if cstr(_row_value(row, "account") or "").strip()
			}
		)
		placeholders = ", ".join(["%s"] * len(account_names))
		account_rows = (
			frappe.db.sql(
				f"""
				SELECT name, company, account_type, account_currency
				FROM `tabAccount`
				WHERE name IN ({placeholders})
				ORDER BY name
				FOR UPDATE
				""",
				tuple(account_names),
				as_dict=True,
			)
			if account_names
			else []
		)
		account_by_name = {
			cstr(_row_value(row, "name") or "").strip(): row
			for row in account_rows
		}
		if len(account_by_name) != len(account_names):
			frappe.throw(
				f"Storno aus Sicherheitsgründen abgebrochen: Journal Entry "
				f"{name} verwendet ein unbekanntes Konto.",
				frappe.ValidationError,
			)

		reference_names: List[str] = []
		total_debit = Decimal("0")
		total_credit = Decimal("0")
		for row in accounts:
			account_name = cstr(
				_row_value(row, "account") or ""
			).strip()
			account = account_by_name.get(account_name) or {}
			reference_name = cstr(
				_row_value(row, "reference_name") or ""
			).strip()
			debit = Decimal(
				str(_row_value(row, "debit_in_account_currency") or 0)
			).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
			credit = Decimal(
				str(_row_value(row, "credit_in_account_currency") or 0)
			).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
			base_debit = Decimal(
				str(_row_value(row, "debit") or 0)
			).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
			base_credit = Decimal(
				str(_row_value(row, "credit") or 0)
			).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
			if (
				cstr(_row_value(account, "company") or "").strip()
				!= expected_company
				or cstr(_row_value(account, "account_type") or "").strip()
				!= "Receivable"
				or cstr(
					_row_value(account, "account_currency") or ""
				).strip()
				!= company_currency
				or cstr(_row_value(row, "party_type") or "").strip()
				!= "Customer"
				or cstr(_row_value(row, "party") or "").strip()
				!= contract_identity["kunde"]
				or cstr(_row_value(row, "reference_type") or "").strip()
				!= "Sales Invoice"
				or not reference_name
				or reference_name not in target_names | source_names
				or debit < 0
				or credit < 0
				or (debit > 0) == (credit > 0)
				or debit != base_debit
				or credit != base_credit
			):
				frappe.throw(
					f"Storno aus Sicherheitsgründen abgebrochen: Journal "
					f"Entry {name} enthält eine fremde oder nicht kanonische "
					"Konten-/Referenzzeile.",
					frappe.ValidationError,
				)
			if reference_name in reference_names:
				frappe.throw(
					f"Storno aus Sicherheitsgründen abgebrochen: Journal "
					f"Entry {name} referenziert {reference_name} mehrfach.",
					frappe.ValidationError,
				)
			reference_names.append(reference_name)
			invoice = frappe.get_doc(
				"Sales Invoice",
				reference_name,
				for_update=True,
			)
			if (
				cint(getattr(invoice, "docstatus", 0)) not in (1, 2)
				or cstr(getattr(invoice, "company", None) or "").strip()
				!= expected_company
				or cstr(getattr(invoice, "customer", None) or "").strip()
				!= contract_identity["kunde"]
				or cstr(getattr(invoice, "debit_to", None) or "").strip()
				!= account_name
			):
				frappe.throw(
					f"Storno aus Sicherheitsgründen abgebrochen: Die "
					f"Sales-Invoice-Referenz {reference_name} in Journal "
					f"Entry {name} passt nicht zur Kontenzeile.",
					frappe.ValidationError,
				)
			if reference_name in target_names:
				direction_valid = debit > 0 and credit == 0
			elif cint(getattr(invoice, "is_return", 0)):
				direction_valid = debit > 0 and credit == 0
			else:
				direction_valid = credit > 0 and debit == 0
			if not direction_valid:
				frappe.throw(
					f"Storno aus Sicherheitsgründen abgebrochen: Die "
					f"Buchungsrichtung für {reference_name} in Journal Entry "
					f"{name} ist nicht konsistent.",
					frappe.ValidationError,
				)
			total_debit += debit
			total_credit += credit

		target_references = target_names.intersection(reference_names)
		source_references = source_names.intersection(reference_names)
		if (
			len(target_references) != 1
			or not source_references
			or total_debit != total_credit
			or total_debit <= 0
		):
			frappe.throw(
				f"Storno aus Sicherheitsgründen abgebrochen: Journal Entry "
				f"{name} enthält nicht genau den eigenen Zielbeleg, sichere "
				"BK-Quellbelege und einen ausgeglichenen Betrag.",
				frappe.ValidationError,
			)
		return journal

	def _validated_settlement_documents(self) -> List[object]:
		sales_name = cstr(self.get("sales_invoice") or "").strip()
		credit_name = cstr(self.get("credit_note") or "").strip()
		journal_name = cstr(
			self.get("consolidation_journal_entry") or ""
		).strip()
		if sales_name and credit_name:
			frappe.throw(
				"Settlement-Ownership ist nicht eindeutig: Nachzahlung und "
				"Gutschrift sind gleichzeitig verknüpft.",
				frappe.ValidationError,
			)
		if journal_name and not (sales_name or credit_name):
			frappe.throw(
				"Settlement-Ownership ist nicht eindeutig: Der "
				"Konsolidierungs-JE hat keinen verknüpften Ausgleichsbeleg.",
				frappe.ValidationError,
			)
		validated_sales: List[object] = []
		owned_invoices: Dict[str, bool] = {}
		if sales_name:
			invoice, marked = self._validate_owned_sales_invoice(
				"sales_invoice",
				sales_name,
				expected_return=0,
				expected_item="BK Nachzahlung",
			)
			validated_sales.append(invoice)
			owned_invoices[sales_name] = marked
		if credit_name:
			invoice, marked = self._validate_owned_sales_invoice(
				"credit_note",
				credit_name,
				expected_return=1,
				expected_item="BK Guthaben",
			)
			validated_sales.append(invoice)
			owned_invoices[credit_name] = marked
		journal = (
			self._validate_owned_journal_entry(journal_name, owned_invoices)
			if journal_name
			else None
		)
		# Journal first, then the invoice(s) it references.
		return ([journal] if journal else []) + validated_sales

	def _cancel_settlement_documents(self) -> None:
		"""Storniert automatisch erzeugte Ausgleichsbelege (Nachzahlung/Guthaben/Konsolidierung)."""
		for linked in self._validated_settlement_documents():
			self._cancel_linked_document(linked)

	def _can_manual_cancel(self) -> bool:
		"""Prüft, ob der aktuelle Nutzer das Dokument direkt stornieren darf."""
		try:
			return bool(
				frappe.has_permission(
					"Betriebskostenabrechnung Mieter",
					ptype="cancel",
					doc=self,
				)
			)
		except Exception:
			return False

	def _sum_abrechnung(self) -> float:
		"""Summe der Abrechnungsposten (Float)."""
		total = 0.0
		for r in getattr(self, "abrechnung", []) or []:
			try:
				total += float(r.get("betrag") or 0)
			except Exception:
				continue
		return round(total, 2)

	def onload(self):
		# Virtuelle Felder setzen
		self.gesamtkosten = self._sum_abrechnung()
		try:
			self.differenz = round(float(self.gesamtkosten or 0) - float(self.vorrauszahlungen or 0), 2)
		except Exception:
			self.differenz = 0.0
		self.set_onload("can_manual_cancel", self._can_manual_cancel())

	def validate(self):
		self.abrechnungsart = normalize_bk_regelung(
			getattr(self, "abrechnungsart", None)
		)
		if self.abrechnungsart != BK_REGELUNG_VORAUSZAHLUNG:
			frappe.throw(
				"Eine Mieter-BK-Abrechnung darf nur für Vorauszahlungszeiträume erstellt werden."
			)
		if self.mietvertrag:
			mv = frappe.db.get_value(
				"Mietvertrag",
				self.mietvertrag,
				["kunde", "wohnung"],
				as_dict=True,
			) or {}
			if not mv.get("kunde"):
				frappe.throw(
					f"Mietvertrag {self.mietvertrag} hat keinen Customer; "
					"die Abrechnung kann nicht sicher gebucht werden."
				)
			if self.customer and self.customer != mv.get("kunde"):
				frappe.throw(
					f"Customer {self.customer} passt nicht zum Mietvertrag "
					f"{self.mietvertrag} ({mv.get('kunde')})."
				)
			if self.wohnung and self.wohnung != mv.get("wohnung"):
				frappe.throw(
					f"Wohnung {self.wohnung} passt nicht zum Mietvertrag "
					f"{self.mietvertrag} ({mv.get('wohnung')})."
				)
			self.customer = mv.get("kunde")
			self.wohnung = mv.get("wohnung")

		# Rechne bei Änderungen neu
		self.onload()
		# Optional: Markiere ausgeglichen, wenn Differenz ~ 0
		try:
			self.abrechnung_ausgeglichen = 1 if abs(float(self.differenz or 0)) < 0.01 else 0
		except Exception:
			self.abrechnung_ausgeglichen = 0

	def before_submit(self):
		if not getattr(
			getattr(self, "flags", object()),
			"allow_submit_via_head",
			False,
		):
			frappe.throw(
				"Direktes Einreichen ist nicht erlaubt. Bitte die "
				"Betriebskostenabrechnung Immobilie einreichen.",
				frappe.ValidationError,
			)
		head_name = cstr(self.get("immobilien_abrechnung") or "").strip()
		if not head_name:
			frappe.throw(
				"Einreichen ohne verknüpften BK-Kopf ist nicht erlaubt.",
				frappe.ValidationError,
			)
		if any(
			cstr(self.get(fieldname) or "").strip()
			for fieldname in (
				"sales_invoice",
				"credit_note",
				"consolidation_journal_entry",
			)
		):
			frappe.throw(
				"Einreichen abgebrochen: Settlement-Links dürfen vor dem "
				"Header-Workflow nicht vorbelegt sein.",
				frappe.ValidationError,
			)
		head = frappe.get_doc(
			"Betriebskostenabrechnung Immobilie",
			head_name,
			for_update=True,
		)
		if cint(getattr(head, "docstatus", 0)) != 1:
			frappe.throw(
				f"Einreichen abgebrochen: BK-Kopf {head_name} ist nicht "
				"eingereicht.",
				frappe.ValidationError,
			)

	def after_insert(self):
		"""Financial documents are created only after the submitted head."""
		return

	def before_insert(self):
		"""Manuelle Erstellung verhindern: Abrechnungen dürfen nur über das Immobilien-Abrechnungsobjekt entstehen."""
		if not getattr(getattr(self, "flags", object()), "allow_manual_create", False):
			raise frappe.ValidationError(
				"Manuelle Erstellung nicht erlaubt. Bitte erzeugen Sie Abrechnungen über 'Betriebskostenabrechnung Immobilie'."
			)

	def before_cancel(self):
		via_head = bool(
			getattr(
				getattr(self, "flags", object()),
				"allow_cancel_via_head",
				False,
			)
		)
		linked_head = cstr(self.get("immobilien_abrechnung") or "").strip()
		if linked_head and not via_head:
			raise frappe.ValidationError(
				"Verknüpfte Mieter-Abrechnungen dürfen ausschließlich über "
				"die Betriebskostenabrechnung Immobilie storniert werden."
			)
		if not linked_head and not (via_head or self._can_manual_cancel()):
			raise frappe.ValidationError(
				"Abbrechen ist nicht erlaubt. Nutzen Sie das Immobilien-Abrechnungsobjekt für Korrekturen."
			)

		# Only the submitted head is an expected backlink during the cascade.
		# All other backlinks remain protected by Frappe's normal cancel checks.
		if via_head:
			self.ignore_linked_doctypes = ["Betriebskostenabrechnung Immobilie"]

		# Validate ownership before Frappe mutates this child. The same check is
		# repeated immediately before voucher cancellation in on_cancel.
		self._validated_settlement_documents()

		invoices = [
			cstr(self.get(fieldname) or "").strip()
			for fieldname in ("sales_invoice", "credit_note")
		]
		invoices = [name for name in invoices if name]
		own_journal = cstr(self.get("consolidation_journal_entry") or "").strip()
		ignored_journals = (
			{invoice: {own_journal} for invoice in invoices}
			if own_journal
			else None
		)
		allocations = _get_locked_settlement_allocations(
			invoices,
			ignored_journal_entries_by_invoice=ignored_journals,
		)
		blocked = {invoice: rows for invoice, rows in allocations.items() if rows}
		if blocked:
			sources = sorted(
				{
					f"{row['document_type']} {row['document']}"
					for rows in blocked.values()
					for row in rows
				}
			)
			frappe.throw(
				"Storno nicht möglich: Mindestens ein Ausgleichsbeleg besitzt "
				"eine aktive Zahlungs- oder Journal-Zuordnung "
				f"({', '.join(sources)}). Bitte zuerst die Zuordnungen auflösen."
			)

	def on_cancel(self):
		via_head = bool(
			getattr(
				getattr(self, "flags", object()),
				"allow_cancel_via_head",
				False,
			)
		)
		linked_head = cstr(self.get("immobilien_abrechnung") or "").strip()
		if linked_head and not via_head:
			raise frappe.ValidationError(
				"Verknüpfte Mieter-Abrechnungen dürfen ausschließlich über "
				"die Betriebskostenabrechnung Immobilie storniert werden."
			)
		if not linked_head and not (via_head or self._can_manual_cancel()):
			raise frappe.ValidationError(
				"Abbrechen ist nicht erlaubt. Nutzen Sie das Immobilien-Abrechnungsobjekt für Korrekturen."
			)
		self._cancel_settlement_documents()

	def before_delete(self):
		if not getattr(getattr(self, "flags", object()), "allow_cancel_via_head", False):
			raise frappe.ValidationError("Löschen ist nicht erlaubt. Nutzen Sie das Immobilien-Abrechnungsobjekt für Korrekturen.")

	def get_kostenmatrix_rows(self) -> List[Dict[str, object]]:
		"""Kombiniert Immobilien- und Wohnungsanteile je Betriebskostenart für Druck und Export."""
		combined: Dict[tuple[str, str], Dict[str, object]] = {}

		def accumulate(items, column: str) -> None:
			for row in items or []:
				betriebskostenart = row.get("betriebskostenart")
				bezeichnung = row.get("bezeichnung")
				label = betriebskostenart or bezeichnung
				if not label:
					continue
				try:
					amount = round(float(row.get("betrag") or 0), 2)
				except Exception:
					amount = 0.0
				# Freie Bezeichnungen sind keine Links auf Betriebskostenart. Der
				# Typ ist Teil des Schlüssels, damit eine freie Position nicht mit
				# einer gleichnamigen verlinkten Kostenart zusammenfällt.
				key = (
					("betriebskostenart", betriebskostenart)
					if betriebskostenart
					else ("bezeichnung", bezeichnung)
				)
				entry = combined.setdefault(
					key,
					{
						"betriebskostenart": betriebskostenart,
						"bezeichnung": None if betriebskostenart else bezeichnung,
						"immobilie": 0.0,
						"wohnung": 0.0,
					},
				)
				entry[column] = round(float(entry.get(column) or 0) + amount, 2)

		immobilien_items = []
		if getattr(self, "immobilien_abrechnung", None):
			immobilien_items = _get_abrechnungsposten_rows(
				"Betriebskostenabrechnung Immobilie",
				self.immobilien_abrechnung,
				"kosten_pro_art",
			)
		elif getattr(self, "immobilien_kosten", None):
			immobilien_items = self.immobilien_kosten

		accumulate(immobilien_items, "immobilie")
		accumulate(getattr(self, "abrechnung", []) or [], "wohnung")

		from hausverwaltung.hausverwaltung.utils.bk_sort import sort_key

		return sorted(
			combined.values(),
			key=lambda row: sort_key(row.get("betriebskostenart") or row.get("bezeichnung")),
		)

	def get_immobilien_basis(self) -> Dict[str, Any]:
		"""Basis-Summen für die Drucktabelle."""
		return _get_immobilien_basis_for_doc(self)

	def get_print_context(self) -> Dict[str, object]:
		"""Kontext für freie BK-Print-Formate.

		Serienbrief-Vorlagen erwarten historisch
		``objekt``, ``empfaenger`` und ``datum``. Ein Frappe Print Format bekommt
		standardmäßig nur ``doc``; diese Methode stellt die fehlenden Werte
		für beliebige BK-Mieter-Layouts bereit.
		"""
		address = self._get_print_recipient_address()
		display_name = self._get_print_recipient_name()
		return frappe._dict(
			objekt=self,
			datum=frappe.utils.formatdate(self.get("datum") or frappe.utils.today(), "dd.MM.yyyy"),
			empfaenger=frappe._dict(
				name=self.get("customer") or self.name,
				anzeigename=display_name,
				mieter_name=display_name,
				strasse=address.get("street", ""),
				plz=address.get("zip", ""),
				ort=address.get("city", ""),
				plz_ort=address.get("plz_ort", ""),
				adresse=address.get("display", ""),
			),
		)

	def _get_print_recipient_name(self) -> str:
		name = get_hauptmieter_display_name(getattr(self, "mieter", None))
		if name:
			return name

		customer = cstr(self.get("customer")).strip()
		if customer:
			customer_name = cstr(frappe.db.get_value("Customer", customer, "customer_name")).strip()
			if customer_name:
				return customer_name
			return customer

		return cstr(self.name).strip()

	def _get_print_recipient_address(self) -> Dict[str, str]:
		customer = cstr(self.get("customer")).strip()
		if customer:
			address = self._get_print_address_for_link("Customer", customer)
			if address:
				return address

		wohnung = cstr(self.get("wohnung")).strip()
		if wohnung:
			try:
				immobilie = cstr(frappe.db.get_value("Wohnung", wohnung, "immobilie")).strip()
			except Exception:
				immobilie = ""
			if immobilie:
				try:
					linked_address = cstr(frappe.db.get_value("Immobilie", immobilie, "adresse")).strip()
				except Exception:
					linked_address = ""
				address = self._print_address_dict_from_name(linked_address)
				if address:
					return address
				address = self._get_print_address_for_link("Immobilie", immobilie)
				if address:
					return address

		return {}

	def _get_print_address_for_link(self, link_doctype: str, link_name: str) -> Dict[str, str]:
		try:
			address_name = get_default_address(link_doctype, link_name)
		except Exception:
			address_name = None
		return self._print_address_dict_from_name(address_name)

	def _print_address_dict_from_name(self, address_name: str | None) -> Dict[str, str]:
		address_name = cstr(address_name).strip()
		if not address_name:
			return {}
		try:
			address = frappe.get_cached_doc("Address", address_name)
		except Exception:
			return {}

		street = ", ".join(
			filter(
				None,
				[
					cstr(getattr(address, "address_line1", "")).strip(),
					cstr(getattr(address, "address_line2", "")).strip(),
				],
			)
		)
		zip_code = cstr(getattr(address, "pincode", None) or getattr(address, "zip", None)).strip()
		city = cstr(getattr(address, "city", "")).strip()
		plz_ort = " ".join(p for p in (zip_code, city) if p).strip()
		return {
			"street": street,
			"zip": zip_code,
			"city": city,
			"plz_ort": plz_ort,
			"display": "\n".join(filter(None, [street, plz_ort])),
		}


@frappe.whitelist()
def get_immobilien_kosten(name: str) -> List[Dict[str, object]]:
	"""Liefert die Kosten aus der verknüpften Immobilienabrechnung."""
	if not name:
		return []
	try:
		doc = frappe.get_doc("Betriebskostenabrechnung Mieter", name)
		doc.check_permission("read")
	except Exception:
		return []
	head_name = doc.get("immobilien_abrechnung")
	if not head_name:
		return []
	try:
		head = frappe.get_doc("Betriebskostenabrechnung Immobilie", head_name)
	except Exception:
		# falls Berechtigung/Fehler: lieber leer zurückgeben statt Frontend zu blockieren
		return []
	rows: List[Dict[str, object]] = []
	for row in head.get("kosten_pro_art") or []:
		try:
			amount = round(float(row.get("betrag") or 0), 2)
		except Exception:
			amount = 0.0
		rows.append({
			"betriebskostenart": row.get("betriebskostenart"),
			"bezeichnung": row.get("bezeichnung"),
			"betrag": amount,
		})
	# Auch hier gruppiert sortieren — wirkt rückwirkend für bestehende BKs,
	# bei denen kosten_pro_art noch alphabetisch persistiert wurde.
	from hausverwaltung.hausverwaltung.utils.bk_sort import sort_key

	rows.sort(key=lambda r: sort_key(r.get("betriebskostenart") or r.get("bezeichnung")))
	return rows


@frappe.whitelist()
def get_immobilien_basis(name: str) -> Dict[str, Any]:
	"""Liefert Basis-Summen für die Immobilie inkl. Schlüsselwerte."""
	if not name:
		return {"total_qm": 0.0, "total_bewohner": 0.0, "schluessel_totals": {}, "wohnung_schluesselwerte": {}}
	try:
		doc = frappe.get_doc("Betriebskostenabrechnung Mieter", name)
		doc.check_permission("read")
	except Exception:
		return {"total_qm": 0.0, "total_bewohner": 0.0, "schluessel_totals": {}, "wohnung_schluesselwerte": {}}

	return _get_immobilien_basis_for_doc(doc)


def _get_immobilien_basis_for_doc(doc) -> Dict[str, Any]:
	"""Liefert Basis-Summen für die Immobilie inkl. Schlüsselwerte."""
	head_name = doc.get("immobilien_abrechnung")
	if not head_name:
		return {"total_qm": 0.0, "total_bewohner": 0.0, "schluessel_totals": {}, "wohnung_schluesselwerte": {}}

	try:
		head = frappe.db.get_value(
			"Betriebskostenabrechnung Immobilie",
			head_name,
			["immobilie", "stichtag", "bis"],
			as_dict=True,
		)
	except Exception:
		return {"total_qm": 0.0, "total_bewohner": 0.0, "schluessel_totals": {}, "wohnung_schluesselwerte": {}}
	if not head:
		return {"total_qm": 0.0, "total_bewohner": 0.0, "schluessel_totals": {}, "wohnung_schluesselwerte": {}}

	from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
		_wohnungen_in_haus,
		_flaeche_qm,
	)
	from hausverwaltung.hausverwaltung.doctype.zustandsschluessel.zustandsschluessel import (
		get_effective_zustandsschluessel_value,
	)

	stichtag = head.get("stichtag") or head.get("bis")
	wohnungen = _wohnungen_in_haus(immobilie=head.get("immobilie"))
	total_qm = 0.0
	for wohnung in wohnungen:
		try:
			total_qm += float(_flaeche_qm(wohnung, stichtag) or 0)
		except Exception:
			continue
	total_qm = round(total_qm, 2)

	children = frappe.get_all(
		"Betriebskostenabrechnung Mieter",
		filters={"immobilien_abrechnung": head_name},
		fields=["name"],
	)

	parent_names = [r.get("name") for r in children if r.get("name")]
	if not parent_names:
		return {"total_qm": total_qm, "total_bewohner": 0.0}

	total_bewohner = 0.0
	try:
		result = frappe.db.sql(
			"""
			select count(*) as cnt
			from `tabVertragspartner`
			where parenttype = 'Betriebskostenabrechnung Mieter'
			  and parent in %(parents)s
			""",
			{"parents": tuple(parent_names)},
			as_dict=True,
		)
		if result:
			total_bewohner = float(result[0].get("cnt") or 0)
	except Exception:
		total_bewohner = 0.0

	schluessel_totals: Dict[str, float] = {}
	wohnung_schluesselwerte: Dict[str, float] = {}
	try:
		arts = frappe.get_all(
			"Betriebskostenart",
			filters={"verteilung": "Schlüssel"},
			fields=["name", "schlüssel"],
			limit_page_length=0,
		)
		schluessel_names = sorted({(row.get("schlüssel") or "").strip() for row in arts or [] if row.get("schlüssel")})
		for schluessel in schluessel_names:
			total = 0.0
			for wohnung in wohnungen:
				try:
					total += float(get_effective_zustandsschluessel_value(wohnung, stichtag, schluessel) or 0)
				except Exception:
					continue
			schluessel_totals[schluessel] = round(total, 2)
			try:
				wohnung_schluesselwerte[schluessel] = round(
					float(get_effective_zustandsschluessel_value(doc.get("wohnung"), stichtag, schluessel) or 0), 2
				)
			except Exception:
				wohnung_schluesselwerte[schluessel] = 0.0
	except Exception:
		schluessel_totals = {}
		wohnung_schluesselwerte = {}

	return {
		"total_qm": total_qm,
		"total_bewohner": total_bewohner,
		"schluessel_totals": schluessel_totals,
		"wohnung_schluesselwerte": wohnung_schluesselwerte,
	}


def _get_abrechnungsposten_rows(parenttype: str, parent: str, parentfield: str) -> List[Dict[str, object]]:
	if not parent:
		return []
	return frappe.get_all(
		"Abrechnungsposten",
		filters={
			"parenttype": parenttype,
			"parent": parent,
			"parentfield": parentfield,
		},
		fields=["betriebskostenart", "bezeichnung", "betrag"],
		order_by="idx asc",
		limit_page_length=0,
	)
