"""Report: Bankkonten / IBANs mit mehreren Parteien.

Findet alle `Bank Account`-Records, deren (normalisierte) IBAN auf mehr als
eine distinkte `(party_type, party)`-Kombination zeigt. Das ist genau der Fall,
den der Bankimport in `bankauszug_import._get_party_by_iban` defensiv als
"nicht eindeutig" behandelt (Row bleibt in Phase 1 manuell zuzuordnen) —
hier wird er als Liste sichtbar gemacht.

Es werden ALLE Party-Types berücksichtigt (Customer, Supplier, …). Zu jeder
betroffenen IBAN werden sämtliche Bank-Account-Records angezeigt — auch solche
ohne Party oder mit `is_company_account`, damit Kollisionen (z.B. IBAN an Firma
UND Customer) sofort erkennbar sind.
"""

import frappe

from hausverwaltung.hausverwaltung.utils.report_helpers import enrich_link_titles

# SQL-Ausdruck zum Normalisieren der IBAN, identisch zu
# bankauszug_import._normalize_iban (Leerzeichen raus, upper-case).
IBAN_NORM = "UPPER(REPLACE(ba.iban, ' ', ''))"


def execute(filters=None):
	filters = filters or {}

	conditions = ["COALESCE(ba.iban, '') != ''"]
	values = {}

	party_type = filters.get("party_type")
	if party_type:
		# Nur IBANs anzeigen, an denen (auch) dieser Party-Type hängt — die
		# Gruppen-Logik bleibt aber über alle Party-Types hinweg.
		conditions.append(
			f"""{IBAN_NORM} IN (
				SELECT UPPER(REPLACE(iban, ' ', ''))
				FROM `tabBank Account`
				WHERE COALESCE(iban, '') != '' AND party_type = %(party_type)s
			)"""
		)
		values["party_type"] = party_type

	data = frappe.db.sql(
		f"""
		SELECT
			{IBAN_NORM} AS iban_norm,
			ba.iban AS iban,
			ba.name AS bank_account,
			ba.account_name AS account_name,
			ba.bank AS bank,
			ba.party_type AS party_type,
			ba.party AS party,
			ba.is_company_account AS is_company_account
		FROM
			`tabBank Account` ba
		WHERE
			{" AND ".join(conditions)}
			AND {IBAN_NORM} IN (
				SELECT iban_norm FROM (
					SELECT UPPER(REPLACE(iban, ' ', '')) AS iban_norm
					FROM `tabBank Account`
					WHERE
						COALESCE(iban, '') != ''
						AND COALESCE(party, '') != ''
						AND COALESCE(party_type, '') != ''
					GROUP BY iban_norm
					HAVING COUNT(DISTINCT CONCAT(party_type, '||', party)) > 1
				) sub
			)
		ORDER BY
			iban_norm, ba.party_type, ba.party, ba.name
		""",
		values=values,
		as_dict=True,
	)

	# Anzahl distinkter Parteien pro IBAN für eine Übersichtsspalte berechnen.
	parteien_pro_iban = {}
	for row in data:
		key = row.get("iban_norm")
		if row.get("party") and row.get("party_type"):
			parteien_pro_iban.setdefault(key, set()).add(
				(row["party_type"], row["party"])
			)
	for row in data:
		row["anzahl_parteien"] = len(parteien_pro_iban.get(row.get("iban_norm"), set()))

	columns = [
		{
			"fieldname": "iban",
			"fieldtype": "Data",
			"label": "IBAN",
			"width": 220,
		},
		{
			"fieldname": "anzahl_parteien",
			"fieldtype": "Int",
			"label": "# Parteien",
			"width": 90,
		},
		{
			"fieldname": "bank_account",
			"fieldtype": "Link",
			"label": "Bankkonto",
			"options": "Bank Account",
			"width": 260,
		},
		{
			"fieldname": "party_type",
			"fieldtype": "Data",
			"label": "Party-Type",
			"width": 110,
		},
		{
			"fieldname": "party",
			"fieldtype": "Dynamic Link",
			"label": "Partei",
			"options": "party_type",
			"width": 260,
		},
		{
			"fieldname": "is_company_account",
			"fieldtype": "Check",
			"label": "Firmenkonto",
			"width": 100,
		},
		{
			"fieldname": "bank",
			"fieldtype": "Link",
			"label": "Bank",
			"options": "Bank",
			"width": 160,
		},
		{
			"fieldname": "account_name",
			"fieldtype": "Data",
			"label": "Kontobezeichnung",
			"width": 220,
		},
	]

	enrich_link_titles(data, columns)
	return columns, data
