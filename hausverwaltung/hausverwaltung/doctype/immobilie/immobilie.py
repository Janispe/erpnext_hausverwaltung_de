import frappe
from frappe.model.document import Document
from hausverwaltung.hausverwaltung.doctype.wohnung.wohnung import STATUS_INAKTIV
from hausverwaltung.hausverwaltung.utils.immobilie_accounts import get_immobilie_account_map


class Immobilie(Document):
	def validate(self):
		if not self.adresse:
			self.adresse_titel = None
		else:
			self.adresse_titel = frappe.db.get_value("Address", self.adresse, "address_title")

		_validate_account_rows(self, "bankkonten", "Bankkonto")
		_validate_account_rows(self, "kassenkonten", "Kassenkonto")

	@property
	def gesamtwohnflaeche(self) -> float:
		"""Aktuelle Gesamtwohnfläche der Wohnungen (ohne inaktive)."""
		if not self.name:
			return 0.0
		return _sum_gesamtwohnflaeche(self.name)


def _sum_gesamtwohnflaeche(immobilie: str) -> float:
	query = """
		SELECT COALESCE(SUM(z.`gr\u00f6\u00dfe`), 0)
		FROM `tabWohnung` w
		LEFT JOIN `tabWohnungszustand` z
		  ON z.name = (
			SELECT z2.name
			FROM `tabWohnungszustand` z2
			WHERE z2.wohnung = w.name
			  AND z2.ab <= CURDATE()
			  AND z2.docstatus != 2
			ORDER BY z2.ab DESC
			LIMIT 1
		  )
		WHERE w.immobilie = %s
		  AND w.docstatus != 2
		  AND COALESCE(w.status, '') != %s
	"""
	try:
		total = frappe.db.sql(query, (immobilie, STATUS_INAKTIV))[0][0]
	except Exception:
		return 0.0
	return float(total or 0.0)


def _validate_account_rows(doc: Document, fieldname: str, label: str) -> None:
	rows = doc.get(fieldname) or []
	seen: set[str] = set()
	primary_accounts: list[str] = []

	for row in rows:
		konto = (row.get("konto") or "").strip()
		if not konto:
			continue
		if konto in seen:
			frappe.throw(f"{label} '{konto}' ist mehrfach hinterlegt.")
		seen.add(konto)
		if row.get("ist_hauptkonto"):
			primary_accounts.append(konto)

	if len(primary_accounts) > 1:
		frappe.throw(f"Es darf nur ein Haupt-{label.lower()} gesetzt sein.")


def get_immobilie_bank_accounts(immobilie: str) -> list[str]:
	return list(get_immobilie_account_map([immobilie]).get(immobilie, {}).get("bank_accounts") or [])


def get_immobilie_cash_accounts(immobilie: str) -> list[str]:
	return list(get_immobilie_account_map([immobilie]).get(immobilie, {}).get("cash_accounts") or [])


def get_immobilie_primary_bank_account(immobilie: str) -> str | None:
	return get_immobilie_account_map([immobilie]).get(immobilie, {}).get("primary_bank_account")


def get_immobilie_primary_cash_account(immobilie: str) -> str | None:
	return get_immobilie_account_map([immobilie]).get(immobilie, {}).get("primary_cash_account")
