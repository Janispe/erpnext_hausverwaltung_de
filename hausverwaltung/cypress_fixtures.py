"""Test-Fixture-Helfer für Cypress-E2E-Tests.

Nur in ``developer_mode=1`` aufrufbar. Statt Sample-Daten zu seeden (was in
gewachsenen Sites mit eigenen Konten/Betriebskostenarten zu Konflikten führt)
arbeitet ``discover_test_env`` gegen die existierenden Echtdaten der Site:
es sucht eine Immobilie mit gesetzter Kostenstelle und GL-Aktivität im
Zielzeitraum.

Methoden:

* ``hausverwaltung.cypress_fixtures.seed`` (Alias für ``discover_test_env``)
* ``hausverwaltung.cypress_fixtures.get_expected_eur_totals``
* ``hausverwaltung.cypress_fixtures.cleanup_test_eur`` — löscht eine zuvor
  vom Test angelegte ``Einnahmen Ueberschuss Rechnung``.
"""

from __future__ import annotations

from typing import Optional

import frappe
from frappe.utils import flt


def _check_dev_mode() -> None:
	if not int(frappe.conf.get("developer_mode") or 0):
		frappe.throw(
			"hausverwaltung.cypress_fixtures: developer_mode muss aktiv sein "
			"(site_config.json: \"developer_mode\": 1)."
		)


def _resolve_company(explicit: Optional[str] = None) -> str:
	if explicit:
		return explicit
	user_default = frappe.defaults.get_user_default("Company")
	if user_default:
		return user_default
	rows = frappe.get_all("Company", pluck="name", limit=1)
	if rows:
		return rows[0]
	frappe.throw("hausverwaltung.cypress_fixtures: keine Company gefunden.")


def _first_value(doctype: str, filters: dict | list | None, fieldname: str = "name", order_by: str = "name asc"):
	rows = frappe.get_all(doctype, filters=filters or {}, pluck=fieldname, order_by=order_by, limit=1)
	return rows[0] if rows else None


def _ensure_uom() -> str:
	uom = _first_value("UOM", {"enabled": 1}) or _first_value("UOM", {})
	if uom:
		return uom
	doc = frappe.get_doc({"doctype": "UOM", "uom_name": "Nos"}).insert(ignore_permissions=True)
	return doc.name


def _ensure_item_group() -> str:
	group = _first_value("Item Group", {"is_group": 0}) or _first_value("Item Group", {})
	if group:
		return group
	doc = frappe.get_doc({"doctype": "Item Group", "item_group_name": "HV UI Test Items"}).insert(ignore_permissions=True)
	return doc.name


def _ensure_customer_group() -> str:
	group = _first_value("Customer Group", {"is_group": 0}) or _first_value("Customer Group", {})
	if group:
		return group
	doc = frappe.get_doc({"doctype": "Customer Group", "customer_group_name": "HV UI Test Customers"}).insert(ignore_permissions=True)
	return doc.name


def _ensure_territory() -> str:
	territory = _first_value("Territory", {"is_group": 0}) or _first_value("Territory", {})
	if territory:
		return territory
	doc = frappe.get_doc({"doctype": "Territory", "territory_name": "HV UI Test Territory"}).insert(ignore_permissions=True)
	return doc.name


def _leaf_account(company: str, *, account_type: str | None = None, root_type: str | None = None) -> str | None:
	filters = {"company": company, "is_group": 0, "disabled": 0}
	if account_type:
		filters["account_type"] = account_type
	if root_type:
		filters["root_type"] = root_type
	return _first_value("Account", filters)


def _ensure_cost_center(company: str) -> str:
	cost_center = (
		frappe.db.get_value("Company", company, "cost_center")
		or _first_value("Cost Center", {"company": company, "is_group": 0, "disabled": 0})
		or _first_value("Cost Center", {"company": company, "is_group": 0})
	)
	if cost_center:
		return cost_center
	frappe.throw(f"hausverwaltung.cypress_fixtures: keine Kostenstelle für {company} gefunden.")


def _ensure_income_account(company: str) -> str:
	account = frappe.db.get_value("Company", company, "default_income_account") or _leaf_account(company, root_type="Income")
	if account:
		return account
	frappe.throw(f"hausverwaltung.cypress_fixtures: kein Erlöskonto für {company} gefunden.")


def _ensure_receivable_account(company: str) -> str:
	account = (
		frappe.db.get_value("Company", company, "default_receivable_account")
		or _leaf_account(company, account_type="Receivable")
		or _leaf_account(company, root_type="Asset")
	)
	if account:
		return account
	frappe.throw(f"hausverwaltung.cypress_fixtures: kein Debitorenkonto für {company} gefunden.")


def _ensure_test_item(company: str, income_account: str) -> str:
	item_code = "HV UI Mahnwesen Testleistung"
	if frappe.db.exists("Item", item_code):
		return item_code
	doc = frappe.get_doc(
		{
			"doctype": "Item",
			"item_code": item_code,
			"item_name": item_code,
			"item_group": _ensure_item_group(),
			"stock_uom": _ensure_uom(),
			"is_stock_item": 0,
			"disabled": 0,
			"include_item_in_manufacturing": 0,
		}
	).insert(ignore_permissions=True)
	return doc.name


def _ensure_test_customer(run_id: str) -> str:
	customer_name = f"HV UI Mahnwesen Real {run_id}"
	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": customer_name,
			"customer_type": "Individual",
			"customer_group": _ensure_customer_group(),
			"territory": _ensure_territory(),
		}
	).insert(ignore_permissions=True)
	return doc.name


def _ensure_serienbrief_category() -> str | None:
	if not frappe.db.exists("DocType", "Serienbrief Kategorie"):
		return None
	existing = frappe.db.exists("Serienbrief Kategorie", "HV UI Tests")
	if existing:
		return "HV UI Tests"
	doc = frappe.get_doc({"doctype": "Serienbrief Kategorie", "title": "HV UI Tests"}).insert(ignore_permissions=True)
	return doc.name


def _ensure_serienbrief_vorlage(run_id: str) -> str | None:
	if not frappe.db.exists("DocType", "Serienbrief Vorlage"):
		return None
	name = f"HV UI Mahnung Real {run_id}"
	if frappe.db.exists("Serienbrief Vorlage", name):
		return name
	doc = frappe.new_doc("Serienbrief Vorlage")
	doc.update(
		{
			"title": name,
			"haupt_verteil_objekt": "Dunning",
			"content_type": "Textbaustein (Rich Text)",
			"content": "<p>Mahnung {{ ansprechpartner }}</p>",
			"description": "Playwright real DB test fixture",
		}
	)
	category = _ensure_serienbrief_category()
	if category:
		doc.kategorie = category
	doc.append(
		"variables",
		{
			"variable": "ansprechpartner",
			"label": "Ansprechpartner",
			"variable_type": "String",
			"optional": 0,
		},
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_dunning_type(company: str, income_account: str, cost_center: str, template: str | None) -> str:
	name = "Zahlungserinnerung - HP"
	if frappe.db.exists("Dunning Type", name):
		doc = frappe.get_doc("Dunning Type", name)
	else:
		doc = frappe.get_doc(
			{
				"doctype": "Dunning Type",
				"dunning_type": name,
				"company": company,
				"dunning_fee": 0,
				"rate_of_interest": 0,
				"income_account": income_account,
				"cost_center": cost_center,
			}
		).insert(ignore_permissions=True)
		return doc.name
	changed = False
	for fieldname, value in {
		"company": company,
		"income_account": income_account,
		"cost_center": cost_center,
	}.items():
		if getattr(doc, fieldname, None) != value:
			setattr(doc, fieldname, value)
			changed = True
	if template and frappe.get_meta("Dunning Type").get_field("hv_serienbrief_vorlage"):
		if getattr(doc, "hv_serienbrief_vorlage", None) != template:
			doc.hv_serienbrief_vorlage = template
			changed = True
	if changed:
		doc.save(ignore_permissions=True)
	return doc.name


@frappe.whitelist()
def ensure_bankimport_bank_account(company: Optional[str] = None) -> dict:
	"""Ensure the Bankimport UI has at least one selectable company bank account.

	Fresh Docker sites can have a Company and chart of accounts but no ``Bank
	Account`` doctype row yet. The real Bankimport UI filters for active company
	bank accounts, so seed one narrow test-safe row when needed.
	"""
	_check_dev_mode()
	company = _resolve_company(company)

	def is_active_account(account: str | None) -> bool:
		if not account:
			return True
		return not bool(frappe.db.get_value("Account", account, "disabled"))

	existing = frappe.get_all(
		"Bank Account",
		filters={"is_company_account": 1},
		fields=["name", "account"],
		order_by="name asc",
		limit=50,
	)
	for row in existing:
		if is_active_account(row.get("account")):
			return {"bank_account": row["name"], "created": False, "company": company}

	from hausverwaltung.hausverwaltung.data_import.sample.sample_data import (
		_ensure_bank_cash_defaults,
		_ensure_default_bank,
	)

	gl_account = (
		frappe.db.get_value("Company", company, "default_bank_account")
		or _ensure_bank_cash_defaults(company)
	)
	if not gl_account:
		frappe.throw("hausverwaltung.cypress_fixtures: kein Bank-/Kasse-Sachkonto gefunden.")

	bank = _ensure_default_bank()
	payload = {
		"doctype": "Bank Account",
		"account_name": "HV UI Test Bankkonto",
		"bank": bank,
		"is_company_account": 1,
		"company": company,
		"account": gl_account,
	}
	if frappe.get_meta("Bank Account").has_field("iban"):
		payload["iban"] = "DE89370400440532013000"
	if frappe.get_meta("Bank Account").has_field("disabled"):
		payload["disabled"] = 0

	doc = frappe.get_doc(payload).insert(ignore_permissions=True)
	frappe.db.commit()
	return {"bank_account": doc.name, "created": True, "company": company, "account": gl_account}


@frappe.whitelist()
def seed_real_op_dunning(run_id: str, company: Optional[str] = None) -> dict:
	"""Create a real overdue Sales Invoice for OP/Mahnwesen Playwright tests.

	The created Sales Invoice is submitted and therefore visible to
	``get_mahnkandidaten``. The test is expected to create a real Dunning draft
	through the UI and then call ``cleanup_real_op_dunning``.
	"""
	_check_dev_mode()
	run_id = str(run_id or "").strip()
	if not run_id:
		frappe.throw("hausverwaltung.cypress_fixtures: run_id fehlt.")

	company = _resolve_company(company)
	income_account = _ensure_income_account(company)
	receivable_account = _ensure_receivable_account(company)
	cost_center = _ensure_cost_center(company)
	item_code = _ensure_test_item(company, income_account)
	customer = _ensure_test_customer(run_id)
	template = _ensure_serienbrief_vorlage(run_id)
	dunning_type = _ensure_dunning_type(company, income_account, cost_center, template)

	si = frappe.new_doc("Sales Invoice")
	si.update(
		{
			"company": company,
			"customer": customer,
			"posting_date": "2026-05-01",
			"due_date": "2026-05-15",
			"debit_to": receivable_account,
			"currency": frappe.db.get_value("Company", company, "default_currency") or "EUR",
			"ignore_default_payment_terms_template": 1,
			"remarks": f"HV UI Mahnwesen Real {run_id}",
			"items": [
				{
					"item_code": item_code,
					"item_name": item_code,
					"description": f"HV UI Mahnwesen Real {run_id}",
					"qty": 1,
					"rate": 123.45,
					"income_account": income_account,
					"cost_center": cost_center,
				}
			],
		}
	)
	si.set("payment_terms_template", None)
	si.set("payment_schedule", [])
	if frappe.get_meta("Sales Invoice").get_field("mietabrechnung_id"):
		si.mietabrechnung_id = f"HV-UI-MAHN-{run_id}"
	si.insert(ignore_permissions=True)
	si.submit()
	frappe.db.commit()

	return {
		"company": company,
		"customer": customer,
		"customer_name": frappe.db.get_value("Customer", customer, "customer_name") or customer,
		"sales_invoice": si.name,
		"dunning_type": dunning_type,
		"serienbrief_vorlage": template,
		"outstanding_amount": flt(si.outstanding_amount),
		"run_id": run_id,
	}


@frappe.whitelist()
def cleanup_real_op_dunning(run_id: str, sales_invoice: Optional[str] = None, customer: Optional[str] = None, template: Optional[str] = None) -> dict:
	"""Best-effort cleanup for ``seed_real_op_dunning``."""
	_check_dev_mode()
	run_id = str(run_id or "").strip()
	deleted: dict[str, list[str]] = {"Dunning": [], "Sales Invoice": [], "Customer": [], "Serienbrief Vorlage": []}

	def delete_doc(doctype: str, name: str | None) -> None:
		if not name or not frappe.db.exists(doctype, name):
			return
		try:
			doc = frappe.get_doc(doctype, name)
			if getattr(doc, "docstatus", 0) == 1:
				doc.cancel()
			frappe.delete_doc(doctype, name, force=True, ignore_permissions=True)
			deleted.setdefault(doctype, []).append(name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), f"cleanup_real_op_dunning failed for {doctype} {name}")

	if sales_invoice:
		dunning_names = [
			row.parent
			for row in frappe.get_all(
				"Overdue Payment",
				filters={"sales_invoice": sales_invoice, "parenttype": "Dunning"},
				fields=["parent"],
				limit_page_length=0,
			)
		]
	else:
		dunning_names = frappe.get_all(
			"Dunning",
			filters={"customer": customer} if customer else {},
			pluck="name",
			limit=20,
			order_by="creation desc",
		)
		if run_id:
			dunning_names = [
				name for name in dunning_names
				if run_id in str(frappe.db.get_value("Dunning", name, "customer") or "")
				or bool(
					frappe.db.exists(
						"Sales Invoice",
						{
							"name": frappe.db.get_value("Dunning", name, "sales_invoice"),
							"remarks": ("like", f"%{run_id}%"),
						},
					)
				)
			]
	for name in dunning_names:
		delete_doc("Dunning", name)

	if not sales_invoice and run_id:
		sales_invoice = frappe.db.get_value("Sales Invoice", {"remarks": ("like", f"%{run_id}%")}, "name")
	delete_doc("Sales Invoice", sales_invoice)

	if customer:
		delete_doc("Customer", customer)

	if template:
		delete_doc("Serienbrief Vorlage", template)

	frappe.db.commit()
	return {"deleted": deleted}


@frappe.whitelist()
def get_dunnings_for_sales_invoice(sales_invoice: str) -> list[dict]:
	"""Return Dunning docs linked through the ERPNext Overdue Payment child table."""
	_check_dev_mode()
	if not sales_invoice:
		return []
	rows = frappe.db.sql(
		"""
		SELECT
			d.name,
			d.docstatus,
			op.sales_invoice,
			d.customer,
			d.dunning_type,
			d.posting_date,
			op.outstanding AS outstanding_amount,
			d.hv_serienbrief_vorlage
		FROM `tabDunning` d
		INNER JOIN `tabOverdue Payment` op ON op.parent = d.name
		WHERE op.parenttype = 'Dunning'
		  AND op.sales_invoice = %s
		ORDER BY d.creation DESC
		""",
		(sales_invoice,),
		as_dict=True,
	)
	return [dict(row) for row in rows]


@frappe.whitelist()
def seed(company: Optional[str] = None) -> dict:
	"""Liefert eine Immobilie + Zeitraum mit existierender GL-Aktivität.

	Sucht eine Immobilie mit gesetzter Kostenstelle, deren Cost Center im
	letzten vollständigen Geschäftsjahr GL-Entries auf Income- oder
	Expense-Konten hat. Liefert ``None``-Werte falls keine geeignete Immobilie
	gefunden — Tests skippen sich dann via ``this.skip()``.

	(Heißt ``seed`` aus historischen Gründen; legt KEINE Sample-Daten an.)
	"""
	_check_dev_mode()
	company = _resolve_company(company)

	immobilien = frappe.get_all(
		"Immobilie",
		filters={"kostenstelle": ("is", "set")},
		fields=["name", "kostenstelle"],
		limit=200,
	)

	if not immobilien:
		return {
			"company": company,
			"immobilie": None,
			"kostenstelle": None,
			"von": None,
			"bis": None,
			"from_year": None,
			"reason": "Keine Immobilie mit Kostenstelle gefunden.",
		}

	last_full_year = frappe.utils.getdate(frappe.utils.today()).year - 1

	for immo in immobilien:
		row = frappe.db.sql(
			"""
			SELECT COUNT(*) AS cnt
			FROM `tabGL Entry` gle
			INNER JOIN `tabAccount` a ON a.name = gle.account
			WHERE gle.cost_center = %s
			  AND gle.company = %s
			  AND gle.is_cancelled = 0
			  AND a.root_type IN ('Income', 'Expense')
			  AND YEAR(gle.posting_date) = %s
			""",
			(immo["kostenstelle"], company, last_full_year),
			as_dict=True,
		)
		if row and row[0]["cnt"] > 0:
			return {
				"company": company,
				"immobilie": immo["name"],
				"kostenstelle": immo["kostenstelle"],
				"von": f"{last_full_year}-01-01",
				"bis": f"{last_full_year}-12-31",
				"from_year": last_full_year,
				"gl_entry_count": int(row[0]["cnt"]),
			}

	return {
		"company": company,
		"immobilie": immobilien[0]["name"],
		"kostenstelle": immobilien[0]["kostenstelle"],
		"von": f"{last_full_year}-01-01",
		"bis": f"{last_full_year}-12-31",
		"from_year": last_full_year,
		"gl_entry_count": 0,
		"reason": "Keine GL-Entries im Zielzeitraum, Test wird Werte = 0 erwarten.",
	}


@frappe.whitelist()
def get_expected_eur_totals(
	immobilie: str,
	from_date: str,
	to_date: str,
	company: str,
	umlage_method: str = "Kontenstruktur",
	include_non_euer_accounts: int = 1,
) -> dict:
	"""Liefert die EXAKTEN Soll-Summen für den EÜR-Test.

	Ruft denselben Report-Code (``hausverwaltung.report.euer.get_data``) auf,
	den auch der ``Einnahmen Ueberschuss Rechnung``-Doc in seinem
	``refresh_from_report``-Hook nutzt. Aggregiert die Summen-Zeilen exakt wie
	``EinnahmenUeberschussRechnung.refresh_from_report`` in
	[einnahmen_ueberschuss_rechnung.py:43-54].

	Damit ist der Vergleich Doc ↔ Soll exakt: beide Seiten lesen aus der
	gleichen Quelle. Der Test verifiziert, dass die Doc-Lifecycle-Mechanik
	(validate-Hook → positionen-Tabelle → summe_*-Felder) korrekt funktioniert.
	"""
	_check_dev_mode()

	from frappe.utils import cstr

	from hausverwaltung.hausverwaltung.report.euer.euer import get_data

	kostenstelle = frappe.db.get_value("Immobilie", immobilie, "kostenstelle")
	if not kostenstelle:
		frappe.throw(f"Immobilie {immobilie} hat keine Kostenstelle gesetzt.")

	filters = {
		"company": company,
		"immobilie": immobilie,
		"from_date": from_date,
		"to_date": to_date,
		"show_details": 0,
		"include_non_euer_accounts": int(include_non_euer_accounts),
		"umlage_method": umlage_method,
		"show_bank_check": 0,
	}
	rows, _message = get_data(filters)

	totals = {"einnahmen": 0.0, "ausgaben": 0.0, "ueberschuss": 0.0}
	for row in rows or []:
		label = cstr(row.get("account") or "").strip()
		if label == "Summe Einnahmen":
			totals["einnahmen"] = flt(row.get("income"))
		elif label == "Summe Ausgaben":
			totals["ausgaben"] = flt(row.get("expense"))
		elif label == "Überschuss/Verlust":
			totals["ueberschuss"] = flt(row.get("balance"))

	totals["kostenstelle"] = kostenstelle
	totals["positionen_count"] = len(rows or [])
	return totals


@frappe.whitelist()
def cleanup_test_eur(name: str) -> dict:
	"""Löscht ein vom Test angelegtes EÜR-Dokument (Draft).

	Best-effort: ignoriert Fehler, damit Cypress-after-Hooks nicht hart blocken.
	"""
	_check_dev_mode()
	if not name:
		return {"deleted": False, "reason": "no name"}
	try:
		if frappe.db.exists("Einnahmen Ueberschuss Rechnung", name):
			doc = frappe.get_doc("Einnahmen Ueberschuss Rechnung", name)
			if doc.docstatus == 1:
				doc.cancel()
			frappe.delete_doc(
				"Einnahmen Ueberschuss Rechnung",
				name,
				force=True,
				ignore_permissions=True,
			)
			return {"deleted": True, "name": name}
		return {"deleted": False, "reason": "not found"}
	except Exception as exc:
		return {"deleted": False, "reason": str(exc)}
