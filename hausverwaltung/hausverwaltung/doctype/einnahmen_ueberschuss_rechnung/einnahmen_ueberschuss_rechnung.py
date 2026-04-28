import frappe
from frappe.model.document import Document
from frappe.utils import cint, cstr, flt, getdate, strip_html_tags

from hausverwaltung.hausverwaltung.report.euer.euer import get_data


class EinnahmenUeberschussRechnung(Document):
	def validate(self):
		_set_defaults(self)
		self.refresh_from_report()

	@frappe.whitelist()
	def refresh_from_report(self):
		filters = {
			"company": self.company,
			"immobilie": self.immobilie,
			"from_date": self.from_date,
			"to_date": self.to_date,
			"show_details": 0,
			"include_non_euer_accounts": cint(self.include_non_euer_accounts),
			"umlage_method": self.umlage_method or "Kontenstruktur",
			"show_bank_check": cint(self.show_bank_check),
		}
		rows, message = get_data(filters)

		self.report_hinweis = strip_html_tags(message or "")
		self.set("positionen", [])
		for idx, row in enumerate(rows or [], start=1):
			self.append(
				"positionen",
				{
					"idx_in_report": idx,
					"bezeichnung": row.get("account"),
					"einnahmen": _as_optional_currency(row.get("income")),
					"ausgaben": _as_optional_currency(row.get("expense")),
					"saldo": _as_optional_currency(row.get("balance")),
					"indent": cint(row.get("indent")),
					"ist_summe": cint(row.get("bold")),
				},
			)

		self.summe_einnahmen = 0.0
		self.summe_ausgaben = 0.0
		self.ueberschuss = 0.0

		for row in rows or []:
			label = cstr(row.get("account") or "").strip()
			if label == "Summe Einnahmen":
				self.summe_einnahmen = flt(row.get("income"))
			elif label == "Summe Ausgaben":
				self.summe_ausgaben = flt(row.get("expense"))
			elif label == "Überschuss/Verlust":
				self.ueberschuss = flt(row.get("balance"))


def _set_defaults(doc: Document) -> None:
	if not doc.company:
		doc.company = frappe.defaults.get_user_default("Company")
	if not doc.from_date:
		today = getdate()
		doc.from_date = today.replace(month=1, day=1)
	if not doc.to_date:
		today = getdate()
		doc.to_date = today.replace(month=12, day=31)
	if not doc.umlage_method:
		doc.umlage_method = "Kontenstruktur"
	doc.titel = _build_title(doc)


def _build_title(doc: Document) -> str:
	parts = ["EÜR"]
	if doc.immobilie:
		parts.append(cstr(doc.immobilie))
	elif doc.company:
		parts.append(cstr(doc.company))
	if doc.from_date and doc.to_date:
		parts.append(f"{doc.from_date} bis {doc.to_date}")
	return " - ".join(parts)


def _as_optional_currency(value):
	if value in (None, ""):
		return None
	return flt(value)
