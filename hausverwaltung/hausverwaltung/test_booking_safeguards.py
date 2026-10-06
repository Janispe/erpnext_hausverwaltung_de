"""Regression tests for audited booking safeguards; fixtures are rolled back."""

import unittest
from decimal import Decimal

import frappe

from hausverwaltung.hausverwaltung.doctype.heizkostenabrechnung_immobilie.heizkostenabrechnung_immobilie import (
	create_mieter_drafts,
)
from hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen import (
	_ensure_item_with_income,
	_make_sales_invoice,
)


def fixture(*, auto_customer=False, with_contact=False, compact=False):
	token = frappe.generate_hash(length=10)
	company = frappe.get_all("Company", pluck="name", limit=1)[0]
	cc = (
		frappe.db.get_value("Company", company, "cost_center")
		or frappe.get_all("Cost Center", filters={"company": company, "is_group": 0}, pluck="name", limit=1)[
			0
		]
	)
	if not frappe.db.exists(
		"Account",
		{
			"company": company,
			"root_type": "Income",
			"is_group": 0,
			"account_name": "Betriebskostenabrechnung",
		},
	):
		income_parent = frappe.get_all(
			"Account",
			filters={"company": company, "root_type": "Income", "is_group": 1},
			pluck="name",
			limit=1,
			order_by="lft desc",
		)[0]
		frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": "Betriebskostenabrechnung",
				"company": company,
				"parent_account": income_parent,
				"root_type": "Income",
				"is_group": 0,
			}
		).insert()
	if not frappe.db.exists(
		"Fiscal Year",
		{"year_start_date": ["<=", "2026-10-04"], "year_end_date": [">=", "2026-10-04"], "disabled": 0},
	):
		frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": f"Bugtest HK 2026 {token}",
				"year_start_date": "2026-01-01",
				"year_end_date": "2026-12-31",
				"disabled": 0,
				"companies": [{"company": company}],
			}
		).insert()
	# A brand-new site has no address templates. Isolated random-country
	# template keeps this fixture from modifying any existing template.
	country = frappe.get_doc(
		{"doctype": "Country", "country_name": f"Bugtest HK {token}", "code": "DE"}
	).insert(ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Address Template",
			"country": country.name,
			"is_default": 0,
			"template": "{{ address_line1 }}<br>{{ city }}",
		}
	).insert(ignore_permissions=True)
	prop_label = f"BT {token}" if compact else f"Bugtest HK {token}"
	flat_label = f"BT {token}" if compact else f"Bugtest HK {token}"
	addr = frappe.get_doc(
		{
			"doctype": "Address",
			"address_title": prop_label,
			"address_type": "Billing",
			"address_line1": prop_label,
			"city": "Berlin",
			"country": country.name,
		}
	).insert(ignore_permissions=True)
	prop = frappe.get_doc(
		{"doctype": "Immobilie", "bezeichnung": prop_label, "adresse": addr.name, "kostenstelle": cc}
	).insert(ignore_permissions=True)
	flat = frappe.get_doc(
		{
			"doctype": "Wohnung",
			"immobilie": prop.name,
			"name__lage_in_der_immobilie": flat_label,
			"gebaeudeteil": "VH",
		}
	).insert(ignore_permissions=True)
	values = {"doctype": "Mietvertrag", "wohnung": flat.name, "von": "2025-01-01"}
	if not auto_customer:
		customer = frappe.get_doc(
			{"doctype": "Customer", "customer_name": f"Bugtest HK {token}", "customer_type": "Individual"}
		).insert()
		assert "[" not in customer.name
		values["kunde"] = customer.name
	if with_contact:
		contact = frappe.get_doc(
			{"doctype": "Contact", "first_name": "Bugtest", "last_name": f"HK {token}"}
		).insert()
		values["mieter"] = [{"mieter": contact.name, "rolle": "Hauptmieter"}]
	contract = frappe.get_doc(values).insert(ignore_permissions=True)
	return company, cc, prop, flat, contract


def hk_head(prop, costs=100, generate=True):
	doc = frappe.get_doc(
		{
			"doctype": "Heizkostenabrechnung Immobilie",
			"immobilie": prop.name,
			"von": "2025-01-01",
			"bis": "2025-12-31",
			"datum": "2026-10-04",
		}
	).insert()
	if generate:
		create_mieter_drafts(doc.name)
		doc.reload()
		doc.run_method("onload")
		doc.mieter_positionen[0].kosten_gesamt = costs
		doc.save()
	return doc


def bk_fixture(*, with_vacancy=False, compact=True):
	company, _old_cc, prop, flat, contract = fixture(compact=compact)
	token = frappe.generate_hash(length=10)
	cc_parent = frappe.get_all(
		"Cost Center", filters={"company": company, "is_group": 1}, pluck="name", limit=1
	)[0]
	cc = frappe.get_doc(
		{
			"doctype": "Cost Center",
			"cost_center_name": f"Bugtest BK {token}",
			"company": company,
			"parent_cost_center": cc_parent,
			"is_group": 0,
		}
	).insert()
	prop.kostenstelle = cc.name
	prop.save()
	expense_parent = frappe.get_all(
		"Account",
		filters={"company": company, "root_type": "Expense", "is_group": 1},
		pluck="name",
		limit=1,
		order_by="lft desc",
	)[0]
	expense = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": f"Bugtest BK {token}",
			"company": company,
			"parent_account": expense_parent,
			"root_type": "Expense",
			"is_group": 0,
		}
	).insert()
	item = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": f"Bugtest BK {token}",
			"item_name": f"Bugtest BK {token}",
			"item_group": "All Item Groups",
			"stock_uom": "Nos",
			"is_stock_item": 0,
		}
	).insert()
	_art = frappe.get_doc(
		{
			"doctype": "Betriebskostenart",
			"name1": f"Bugtest BK {token}",
			"konto": expense.name,
			"artikel": item.name,
			"verteilung": "qm",
			"kategorie": "Betriebskosten",
		}
	).insert()
	flats = [flat]
	if with_vacancy:
		flats.append(
			frappe.get_doc(
				{
					"doctype": "Wohnung",
					"immobilie": prop.name,
					"name__lage_in_der_immobilie": f"Bugtest vacant {token}",
					"gebaeudeteil": "VH",
				}
			).insert()
		)
	for apartment in flats:
		frappe.get_doc(
			{
				"doctype": "Wohnungszustand",
				"wohnung": apartment.name,
				"ab": "2025-01-01",
				"größe": 50,
				"betriebskostenabrechnung_durch_vermieter": 1,
				"wohnung_aktiv_genutzt": 1,
			}
		).insert().submit()
	cash = frappe.get_all(
		"Account",
		filters={"company": company, "is_group": 0, "account_type": ["in", ["Bank", "Cash"]]},
		pluck="name",
		limit=1,
	)[0]
	cost = frappe.get_doc(
		{
			"doctype": "Journal Entry",
			"voucher_type": "Journal Entry",
			"company": company,
			"posting_date": "2026-03-15",
			"accounts": [
				{"account": expense.name, "debit_in_account_currency": 100, "cost_center": cc.name},
				{"account": cash, "credit_in_account_currency": 100, "cost_center": cc.name},
			],
		}
	).insert()
	cost.submit()
	return prop, flat, contract, flats


def bk_head(prop, von="2026-01-01", bis="2026-12-31"):
	return frappe.get_doc(
		{
			"doctype": "Betriebskostenabrechnung Immobilie",
			"immobilie": prop.name,
			"von": von,
			"bis": bis,
			"stichtag": bis,
			"nachzahlung_faellig_am": "2026-10-25",
		}
	).insert()


class TestBookingSafeguards(unittest.TestCase):
	def setUp(self):
		self.point = "safeguards_" + frappe.generate_hash(length=10)
		frappe.db.savepoint(self.point)
		self.addCleanup(lambda: frappe.db.rollback(save_point=self.point))

	def test_customer_cannot_be_cleared_or_replaced_after_contact_rename(self):
		_, _, _, _, contract = fixture(auto_customer=True, with_contact=True)
		customer = contract.kunde
		contact = frappe.get_doc("Contact", contract.mieter[0].mieter)
		contact.last_name += " Changed"
		contact.save()
		contract.reload()
		self.assertEqual(contract.kunde, customer)
		contract.kunde = None
		with self.assertRaises(frappe.ValidationError):
			contract.save()
		self.assertEqual(frappe.db.get_value("Mietvertrag", contract.name, "kunde"), customer)
		replacement = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "Replacement " + frappe.generate_hash(length=10),
				"customer_type": "Individual",
			}
		).insert()
		contract.reload()
		contract.kunde = replacement.name
		with self.assertRaises(frappe.ValidationError):
			contract.save()
		self.assertEqual(frappe.db.get_value("Mietvertrag", contract.name, "kunde"), customer)

	def test_same_flat_overlap_is_rejected_but_next_day_move_is_valid(self):
		_, _, _, flat, first = fixture()
		first.bis = "2026-01-31"
		first.save()
		for start in ["2025-01-01", "2026-01-31"]:
			with self.subTest(start=start), self.assertRaises(frappe.ValidationError):
				frappe.get_doc({"doctype": "Mietvertrag", "wohnung": flat.name, "von": start}).insert()
		second = frappe.get_doc(
			{"doctype": "Mietvertrag", "wohnung": flat.name, "von": "2026-02-01"}
		).insert()
		self.assertNotEqual(first.kunde, second.kunde)
		second.von = "2026-01-30"
		with self.assertRaises(frappe.ValidationError):
			second.save()

	def test_unmarked_invoice_with_wrong_flat_is_rejected_before_booking(self):
		from hausverwaltung.hausverwaltung.overrides.sales_invoice import (
			validate_mietvertrag_sales_invoice_identity,
		)

		company, cc, _, flat, contract = fixture()
		other = frappe.get_doc(
			{
				"doctype": "Wohnung",
				"name__lage_in_der_immobilie": "Other " + frappe.generate_hash(length=8),
				"gebaeudeteil": "VH",
			}
		).insert()
		invoice = frappe.new_doc("Sales Invoice")
		invoice.update(
			{"customer": contract.kunde, "company": company, "wohnung": other.name, "cost_center": cc}
		)
		invoice.append("items", {"wohnung": other.name, "cost_center": cc})
		with self.assertRaises(frappe.ValidationError):
			validate_mietvertrag_sales_invoice_identity(invoice)
		invoice.wohnung = flat.name
		invoice.items[0].wohnung = flat.name
		validate_mietvertrag_sales_invoice_identity(invoice)
		from hausverwaltung.hausverwaltung.utils.payment_auto_match import _lock_and_validate_invoices

		item = _ensure_item_with_income("Miete", "Miete", company)
		name = _make_sales_invoice(
			contract.kunde,
			"2026-10-04",
			item,
			100,
			company=company,
			cost_center=cc,
			wohnung=flat.name,
			remarks="Legacy invoice safety fixture",
		)
		posted = frappe.get_doc("Sales Invoice", name)
		# Simulate a pre-fix historical invoice; new invoices already fail validate.
		frappe.db.set_value("Sales Invoice Item", posted.items[0].name, "wohnung", other.name)
		with self.assertRaises(frappe.ValidationError):
			_lock_and_validate_invoices(
				invoices=[{"name": name, "allocated_amount": 100}],
				invoice_doctype="Sales Invoice",
				company=company,
				party=contract.kunde,
				company_currency="EUR",
			)
		frappe.db.set_value("Sales Invoice Item", posted.items[0].name, "wohnung", flat.name)
		frappe.db.set_value("Sales Invoice", name, "remarks", "[MV:NONEXISTENT-CONTRACT]")
		with self.assertRaises(frappe.ValidationError):
			_lock_and_validate_invoices(
				invoices=[{"name": name, "allocated_amount": 100}],
				invoice_doctype="Sales Invoice",
				company=company,
				party=contract.kunde,
				company_currency="EUR",
			)
		self.assertEqual(frappe.db.count("Payment Entry", {"party": contract.kunde, "docstatus": 1}), 0)

	def test_empty_hk_head_cannot_submit(self):
		_, _, prop, _, contract = fixture()
		doc = hk_head(prop, generate=False)
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
		self.assertEqual(frappe.db.count("Sales Invoice", {"customer": contract.kunde, "docstatus": 1}), 0)

	def test_incomplete_hk_child_set_cannot_submit(self):
		_, _, prop, _, contract = fixture()
		doc = hk_head(prop)
		flat = frappe.get_doc(
			{
				"doctype": "Wohnung",
				"immobilie": prop.name,
				"name__lage_in_der_immobilie": "Late " + frappe.generate_hash(length=8),
				"gebaeudeteil": "VH",
			}
		).insert()
		frappe.get_doc({"doctype": "Mietvertrag", "wohnung": flat.name, "von": "2025-06-01"}).insert()
		with self.assertRaisesRegex(frappe.ValidationError, "unvollständig"):
			doc.submit()
		self.assertEqual(frappe.db.count("Sales Invoice", {"customer": contract.kunde, "docstatus": 1}), 0)

	def test_zero_hk_requires_explicit_confirmation_and_then_books_real_credit(self):
		company, cc, prop, flat, contract = fixture()
		item = _ensure_item_with_income("Heizkosten", "Heizkosten", company)
		inv = _make_sales_invoice(
			contract.kunde,
			"2026-10-04",
			item,
			1200,
			company=company,
			cost_center=cc,
			wohnung=flat.name,
			wertstellungsdatum="2025-01-01",
			remarks=f"[MV:{contract.name}] Heizkosten 01/2025",
		)
		invoice = frappe.get_doc("Sales Invoice", inv)
		cash = frappe.get_all(
			"Account",
			filters={"company": company, "is_group": 0, "account_type": ["in", ["Bank", "Cash"]]},
			pluck="name",
			limit=1,
		)[0]
		payment = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"company": company,
				"posting_date": "2026-10-04",
				"accounts": [
					{"account": cash, "debit_in_account_currency": 1200, "cost_center": cc},
					{
						"account": invoice.debit_to,
						"party_type": "Customer",
						"party": contract.kunde,
						"reference_type": "Sales Invoice",
						"reference_name": inv,
						"credit_in_account_currency": 1200,
						"cost_center": cc,
					},
				],
			}
		).insert()
		payment.submit()
		doc = hk_head(prop, costs=0)
		with self.assertRaisesRegex(frappe.ValidationError, "ausdrücklich"):
			doc.submit()
		self.assertEqual(
			frappe.db.count("Sales Invoice", {"customer": contract.kunde, "is_return": 1, "docstatus": 1}), 0
		)
		doc.reload()
		doc.run_method("onload")
		doc.nullkosten_bestaetigt = 1
		doc.submit()
		child = frappe.get_doc(
			"Heizkostenabrechnung Mieter", doc.mieter_positionen[0].heizkostenabrechnung_mieter
		)
		credit = frappe.get_doc("Sales Invoice", child.credit_note)
		self.assertEqual(credit.grand_total, -1200)
		self.assertEqual(credit.docstatus, 1)
		ledger = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Sales Invoice", "voucher_no": credit.name, "is_cancelled": 0},
			fields=["debit", "credit"],
		)
		self.assertEqual(sum(Decimal(str(row.debit)) - Decimal(str(row.credit)) for row in ledger), 0)

	def test_changed_hk_period_updates_children_and_recomputes_before_actual_invoice(self):
		_, _, prop, _, _ = fixture()
		doc = hk_head(prop)
		doc.von = "2026-01-01"
		doc.bis = "2026-12-31"
		doc.save()
		# Multiple saves in one API request must not reuse a previous period's flag.
		child_name = doc.mieter_positionen[0].heizkostenabrechnung_mieter
		doc.von, doc.bis = "2027-01-01", "2027-12-31"
		doc.save()
		self.assertEqual(
			str(frappe.db.get_value("Heizkostenabrechnung Mieter", child_name, "von")), "2027-01-01"
		)
		doc.von, doc.bis = "2026-01-01", "2026-12-31"
		doc.save()
		doc.reload()
		doc.run_method("onload")
		child = frappe.get_doc(
			"Heizkostenabrechnung Mieter", doc.mieter_positionen[0].heizkostenabrechnung_mieter
		)
		self.assertEqual(str(child.von), "2026-01-01")
		self.assertEqual(str(child.bis), "2026-12-31")
		self.assertEqual(child.kosten_gesamt, 0)
		self.assertEqual(child.vorauszahlungen, 0)
		doc.mieter_positionen[0].kosten_gesamt = 100
		doc.save()
		doc.submit()
		child.reload()
		invoice = frappe.get_doc("Sales Invoice", child.sales_invoice)
		self.assertEqual(str(invoice.custom_wertstellungsdatum), "2026-12-31")
		self.assertEqual(invoice.grand_total, 100)

	def test_bracketed_automatic_customer_can_book_and_cancel_without_renaming(self):
		_, _, prop, _, _contract = fixture(auto_customer=True, with_contact=True)
		doc = hk_head(prop)
		original = doc.mieter_positionen[0].heizkostenabrechnung_mieter
		self.assertIn("[", original)
		doc.submit()
		child = frappe.get_doc("Heizkostenabrechnung Mieter", original)
		self.assertEqual(child.name, original)
		invoice = frappe.get_doc("Sales Invoice", child.sales_invoice)
		self.assertIn("[HK-SETTLEMENT:HK-ID:", invoice.remarks)
		doc.cancel()
		invoice.reload()
		self.assertEqual(invoice.docstatus, 2)

	def test_bk_overlap_is_blocked_without_second_invoice(self):
		prop, _flat, contract, _flats = bk_fixture()
		annual = bk_head(prop)
		annual.submit()
		halfyear = bk_head(prop, bis="2026-06-30")
		with self.assertRaisesRegex(frappe.ValidationError, "überschneidet"):
			halfyear.submit()
		invoices = frappe.get_all(
			"Sales Invoice", filters={"customer": contract.kunde, "docstatus": 1}, fields=["grand_total"]
		)
		self.assertEqual(len(invoices), 1)
		self.assertEqual(invoices[0].grand_total, 100)

	def test_changed_hk_period_replaces_old_tenant_with_new_contract_child(self):
		_, _, prop, flat, old_contract = fixture()
		old_contract.bis = "2025-12-31"
		old_contract.save()
		next_customer = frappe.get_doc(
			{
				"doctype": "Customer",
				"customer_name": "Next " + frappe.generate_hash(length=10),
				"customer_type": "Individual",
			}
		).insert()
		next_contract = frappe.get_doc(
			{"doctype": "Mietvertrag", "wohnung": flat.name, "kunde": next_customer.name, "von": "2026-01-01"}
		).insert()
		head = hk_head(prop)
		old_child = head.mieter_positionen[0].heizkostenabrechnung_mieter
		head.von = "2026-01-01"
		head.bis = "2026-12-31"
		head.save()
		head.reload()
		head.run_method("onload")
		self.assertFalse(frappe.db.exists("Heizkostenabrechnung Mieter", old_child))
		self.assertEqual(len(head.mieter_positionen), 1)
		self.assertEqual(head.mieter_positionen[0].mietvertrag, next_contract.name)
		self.assertEqual(head.mieter_positionen[0].customer, next_customer.name)
		self.assertEqual(head.mieter_positionen[0].kosten_gesamt, 0)
		head.mieter_positionen[0].kosten_gesamt = 100
		head.save()
		head.submit()
		self.assertEqual(
			frappe.db.count("Sales Invoice", {"customer": old_contract.kunde, "docstatus": 1}), 0
		)
		self.assertEqual(
			frappe.db.count("Sales Invoice", {"customer": next_customer.name, "docstatus": 1}), 1
		)

	def test_bk_vacant_share_remains_with_owner_and_rented_flat_can_book(self):
		prop, flat, contract, _flats = bk_fixture(with_vacancy=True)
		doc = bk_head(prop)
		doc.submit()
		children = frappe.get_all(
			"Betriebskostenabrechnung Mieter",
			filters={"immobilien_abrechnung": doc.name},
			fields=["wohnung", "docstatus"],
		)
		self.assertEqual(len(children), 1)
		self.assertEqual(children[0].wohnung, flat.name)
		invoices = frappe.get_all(
			"Sales Invoice", filters={"customer": contract.kunde, "docstatus": 1}, fields=["grand_total"]
		)
		self.assertEqual(sum(row.grand_total for row in invoices), 50)

	def _supplier_fixture(self):
		from hausverwaltung.hausverwaltung.doctype.bankauszug_import.test_bankauszug_import import (
			TestBankauszugImportDatabaseIntegration,
		)
		from hausverwaltung.hausverwaltung.doctype.zahlungsplan.zahlungsplan import MODUS_ABSCHLAGSPLAN

		f = TestBankauszugImportDatabaseIntegration()
		f.setUp()
		# The fixture tracks files/vouchers; clean up before rolling back our savepoint.
		self.addCleanup(f.tearDown)
		_, _, prop, _, _ = fixture()
		prop.kostenstelle = f.cost_center
		prop.append("bankkonten", {"konto": f.bank_gl_account, "bank_account": f.bank_account})
		prop.save()
		supplier = frappe.get_doc(
			{"doctype": "Supplier", "supplier_name": "Safeguard " + f.suffix, "supplier_type": "Company"}
		).insert()
		cost_type = frappe.get_doc(
			{
				"doctype": "Kostenart nicht umlagefaehig",
				"name1": "Safeguard " + f.suffix,
				"konto": f.expense_account,
			}
		).insert()
		plan = frappe.get_doc(
			{
				"doctype": "Zahlungsplan",
				"bezeichnung": "Safeguard " + f.suffix,
				"modus": MODUS_ABSCHLAGSPLAN,
				"company": f.company,
				"lieferant": supplier.name,
				"immobilie": prop.name,
				"bank_account": f.bank_account,
				"cost_center": f.cost_center,
				"kostenart_typ": "nicht umlegbar",
				"kostenart_nicht_umlagefaehig": cost_type.name,
				"expense_account": f.expense_account,
				"item_code": "Miete",
				"plan": [
					{"faelligkeitsdatum": "2026-05-05", "betrag": 50},
					{"faelligkeitsdatum": "2026-05-06", "betrag": 50},
				],
			}
		).insert()
		return f, supplier, plan

	def test_supplier_advance_only_split_books_one_balanced_payment_and_two_allocations(self):
		import json

		from hausverwaltung.hausverwaltung.doctype.bankauszug_import import bankauszug_import as bi

		f, supplier, plan = self._supplier_fixture()
		doc = f._make_import(
			[f._neutral_row(betrag=100, richtung="Ausgang", party_type="Supplier", party=supplier.name)]
		)
		f._create_transactions_without_auto_match(doc.name)
		doc.reload()
		result = bi.reconcile_split_row(
			doc.name,
			doc.rows[0].name,
			invoice_allocations="[]",
			abschlag_rows=json.dumps([r.name for r in plan.plan]),
		)
		self.assertTrue(result["ok"])
		self.assertEqual(result["invoice_total"], 0)
		self.assertEqual(result["abschlag_total"], 100)
		pe = frappe.get_doc("Payment Entry", result["payment_entry"])
		self.assertEqual(pe.docstatus, 1)
		self.assertEqual(pe.paid_amount, 100)
		self.assertEqual(pe.unallocated_amount, 100)
		self.assertFalse(pe.references)
		plan.reload()
		self.assertEqual(len(plan.zahlungen), 2)
		self.assertEqual(sum(r.allocated_amount for r in plan.zahlungen), 100)
		ledger = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Payment Entry", "voucher_no": pe.name, "is_cancelled": 0},
			fields=["debit", "credit"],
		)
		self.assertEqual(sum(Decimal(str(r.debit)) - Decimal(str(r.credit)) for r in ledger), 0)
		bt = frappe.get_doc("Bank Transaction", doc.rows[0].bank_transaction)
		self.assertEqual(bt.unallocated_amount, 0)

	def test_supplier_wrong_plan_dimensions_are_rejected_and_auto_matching_skips_them(self):
		from hausverwaltung.hausverwaltung.doctype.zahlungsplan import zahlungsplan as zp
		from hausverwaltung.hausverwaltung.utils import payment_auto_match as pam

		f, supplier, plan = self._supplier_fixture()
		bt = frappe.get_doc(
			{
				"doctype": "Bank Transaction",
				"bank_account": f.bank_account,
				"company": f.company,
				"date": "2026-05-05",
				"deposit": 0,
				"withdrawal": 50,
				"currency": "EUR",
				"party_type": "Supplier",
				"party": supplier.name,
				"reference_number": "Safe-" + f.suffix,
			}
		).insert()
		bt.submit()
		pe = pam.create_standalone_payment_entry(bt=bt)
		other_cc = frappe.get_doc(
			{
				"doctype": "Cost Center",
				"cost_center_name": "Wrong " + f.suffix,
				"company": f.company,
				"parent_cost_center": frappe.db.get_value(
					"Cost Center", {"company": f.company, "is_group": 1}, "name"
				),
				"is_group": 0,
			}
		).insert()
		plan.cost_center = other_cc.name
		plan.save()
		with self.assertRaisesRegex(frappe.ValidationError, "Kostenstelle"):
			zp.record_payment_allocation(
				plan_name=plan.name,
				plan_row_name=plan.plan[0].name,
				payment_entry=pe.name,
				allocated_amount=50,
			)
		self.assertIsNone(
			zp.link_payment_entry_to_abschlagsplan_row(
				supplier=supplier.name, posting_date="2026-05-05", amount=50, payment_entry=pe.name
			)
		)
		plan.reload()
		self.assertFalse(plan.zahlungen)
		plan.cost_center = f.cost_center
		plan.save()
		original_bank_gl, original_suffix = f.bank_gl_account, f.suffix
		f.suffix += "-WrongBank"
		f.bank_gl_account = f._make_bank_gl_account()
		other_bank = f._make_company_bank_account()
		other_bank_gl = f.bank_gl_account
		f.bank_gl_account, f.suffix = original_bank_gl, original_suffix
		prop = frappe.get_doc("Immobilie", plan.immobilie)
		prop.append("bankkonten", {"konto": other_bank_gl, "bank_account": other_bank})
		prop.save()
		# Property account-name hooks can rename Bank Accounts and their links.
		plan.reload()
		original_bank = plan.bank_account
		other_bank = frappe.db.get_value(
			"Bank Account", {"bank": "HV Test Bank " + original_suffix + "-WrongBank"}, "name"
		)
		plan.bank_account = other_bank
		plan.save()
		with self.assertRaisesRegex(frappe.ValidationError, "Bankkonto"):
			zp.record_payment_allocation(
				plan_name=plan.name,
				plan_row_name=plan.plan[0].name,
				payment_entry=pe.name,
				allocated_amount=50,
			)
		self.assertIsNone(
			zp.link_payment_entry_to_abschlagsplan_row(
				supplier=supplier.name, posting_date="2026-05-05", amount=50, payment_entry=pe.name
			)
		)
		plan.bank_account = original_bank
		plan.save()
		result = zp.record_payment_allocation(
			plan_name=plan.name, plan_row_name=plan.plan[0].name, payment_entry=pe.name, allocated_amount=50
		)
		self.assertEqual(result["allocated_amount"], 50)
		plan.reload()
		plan.cost_center = other_cc.name
		with self.assertRaisesRegex(frappe.ValidationError, "Kostenstelle"):
			plan.save()

	def test_empty_rule_tables_receive_all_defaults_and_repeated_seed_preserves_user_flags(self):
		from hausverwaltung.hausverwaltung.utils.bankimport_rules import (
			BOOKING_RULE_DOCTYPE,
			DEFAULT_BOOKING_RULES,
			DEFAULT_PARTY_RULES,
			PARTY_RULE_DOCTYPE,
			ensure_default_bankimport_rules,
		)

		for dt in [PARTY_RULE_DOCTYPE, BOOKING_RULE_DOCTYPE]:
			frappe.db.delete(dt, {})
		result = ensure_default_bankimport_rules()
		expected = len(DEFAULT_PARTY_RULES) + len(DEFAULT_BOOKING_RULES)
		self.assertEqual(result["created"], expected)
		name = DEFAULT_PARTY_RULES[0]["rule_key"]
		frappe.db.set_value(PARTY_RULE_DOCTYPE, name, {"enabled": 0, "priority": 999})
		second = ensure_default_bankimport_rules()
		self.assertEqual(second["created"], 0)
		self.assertEqual(frappe.db.get_value(PARTY_RULE_DOCTYPE, name, "enabled"), 0)
		self.assertEqual(frappe.db.get_value(PARTY_RULE_DOCTYPE, name, "priority"), 999)
