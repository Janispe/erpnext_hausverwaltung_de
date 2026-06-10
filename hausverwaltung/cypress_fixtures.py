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
