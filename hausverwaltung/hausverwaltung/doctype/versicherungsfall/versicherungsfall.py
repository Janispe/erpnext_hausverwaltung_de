from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import flt, getdate, nowdate

BELEG_DOCTYPES: dict[str, tuple[str, ...]] = {
	"Reparaturrechnung": ("Purchase Invoice",),
	"Versicherungsforderung": ("Journal Entry",),
	"Versicherungseingang": ("Journal Entry", "Bank Transaction"),
	"Mietergutschrift": ("Sales Invoice",),
	"Mieterauszahlung": ("Payment Entry", "Bank Transaction"),
	"Sonstiger Buchungsbeleg": (
		"Journal Entry",
		"Sales Invoice",
		"Purchase Invoice",
		"Payment Entry",
		"Bank Transaction",
	),
}

BELEG_FIELDS: dict[str, tuple[str, ...]] = {
	"Journal Entry": ("company", "docstatus", "posting_date", "total_debit"),
	"Sales Invoice": (
		"company",
		"docstatus",
		"posting_date",
		"grand_total",
		"customer",
		"is_return",
	),
	"Purchase Invoice": ("company", "docstatus", "posting_date", "grand_total"),
	"Payment Entry": (
		"company",
		"docstatus",
		"posting_date",
		"paid_amount",
		"party_type",
		"party",
		"payment_type",
	),
	"Bank Transaction": (
		"company",
		"docstatus",
		"date",
		"deposit",
		"withdrawal",
		"party_type",
		"party",
	),
}

STATUS_LABELS = {0: "Entwurf", 1: "Eingereicht", 2: "Storniert"}
ABSCHLUSS_STATUS = {"Abgeschlossen", "Abgelehnt"}
TOLERANZ = 0.01


class Versicherungsfall(Document):
	def autoname(self) -> None:
		self.name = make_autoname("VF-.YYYY.-.#####")

	def validate(self) -> None:
		self._apply_scope()
		self._validate_dates()
		self._validate_amounts()
		self._validate_claim_number()
		self._validate_and_enrich_belege()
		self._calculate_totals()
		self._validate_completion()
		self._set_bezeichnung()

	def _apply_scope(self) -> None:
		"""Make Mietvertrag the authoritative source for Customer and Wohnung."""
		if self.get("mietvertrag"):
			contract = frappe.db.get_value(
				"Mietvertrag",
				self.mietvertrag,
				["name", "kunde", "wohnung", "immobilie"],
				as_dict=True,
			)
			if not contract:
				frappe.throw(_("Der ausgewählte Mietvertrag wurde nicht gefunden."))
			if not contract.get("kunde"):
				frappe.throw(_("Mietvertrag {0} hat keinen eigenen Customer.").format(self.mietvertrag))
			if not contract.get("wohnung"):
				frappe.throw(_("Mietvertrag {0} hat keine Wohnung.").format(self.mietvertrag))

			wohnung_immobilie = frappe.db.get_value("Wohnung", contract.get("wohnung"), "immobilie")
			immobilie = wohnung_immobilie or contract.get("immobilie")
			if not immobilie:
				frappe.throw(
					_("Die Wohnung von Mietvertrag {0} hat keine Immobilie.").format(self.mietvertrag)
				)

			# Deliberately overwrite payload values. A caller may never attach a
			# different Customer or Wohnung to the selected contract.
			self.kunde = contract.get("kunde")
			self.wohnung = contract.get("wohnung")
			self.immobilie = immobilie
		else:
			self.kunde = None
			if self.get("beguenstigter") == "Mieter":
				frappe.throw(_("Für einen Mieterfall muss ein Mietvertrag ausgewählt werden."))
			if self.get("wohnung"):
				immobilie = frappe.db.get_value("Wohnung", self.wohnung, "immobilie")
				if not immobilie:
					frappe.throw(_("Die ausgewählte Wohnung hat keine Immobilie."))
				self.immobilie = immobilie

		if not self.get("immobilie"):
			frappe.throw(_("Bitte eine Immobilie oder einen Mietvertrag auswählen."))

	def _validate_dates(self) -> None:
		if self.get("meldedatum") and self.get("schadendatum"):
			if getdate(self.meldedatum) < getdate(self.schadendatum):
				frappe.throw(_("Das Meldedatum darf nicht vor dem Schadendatum liegen."))

		if self.get("status") in ABSCHLUSS_STATUS and not self.get("abgeschlossen_am"):
			self.abgeschlossen_am = nowdate()
		elif self.get("status") not in ABSCHLUSS_STATUS:
			self.abgeschlossen_am = None

	def _validate_amounts(self) -> None:
		for fieldname, label in (
			("beantragter_betrag", _("Beantragter Betrag")),
			("bewilligter_betrag", _("Bewilligter Betrag")),
			("selbstbeteiligung", _("Selbstbeteiligung")),
		):
			if flt(self.get(fieldname)) < 0:
				frappe.throw(_("{0} darf nicht negativ sein.").format(label))

	def _validate_claim_number(self) -> None:
		if not self.get("versicherer") or not (self.get("schadennummer") or "").strip():
			return
		existing = frappe.db.get_value(
			"Versicherungsfall",
			{
				"versicherer": self.versicherer,
				"schadennummer": self.schadennummer.strip(),
				"name": ("!=", self.name or ""),
			},
			"name",
		)
		if existing:
			frappe.throw(
				_("Schadennummer {0} ist für diesen Versicherer bereits in {1} erfasst.").format(
					self.schadennummer, existing
				)
			)

	def _validate_and_enrich_belege(self) -> None:
		seen: set[tuple[str, str]] = set()
		for idx, row in enumerate(self.get("belege") or [], start=1):
			belegart = (row.get("belegart") or "").strip()
			doctype = (row.get("referenz_doctype") or "").strip()
			referenz = (row.get("referenz") or "").strip()
			allowed = BELEG_DOCTYPES.get(belegart)
			if not allowed:
				frappe.throw(_("Belegzeile {0}: unbekannte Rolle.").format(idx))
			if doctype not in allowed:
				frappe.throw(
					_("Belegzeile {0}: {1} ist für die Rolle {2} nicht zulässig.").format(
						idx, doctype or _("Kein Belegtyp"), belegart
					)
				)
			if not referenz:
				frappe.throw(_("Belegzeile {0}: Bitte einen Beleg auswählen.").format(idx))

			key = (doctype, referenz)
			if key in seen:
				frappe.throw(
					_("Beleg {0} {1} ist in diesem Versicherungsfall mehrfach verknüpft.").format(
						doctype, referenz
					)
				)
			seen.add(key)

			other_case = frappe.db.get_value(
				"Versicherungsfall Beleg",
				{
					"referenz_doctype": doctype,
					"referenz": referenz,
					"parent": ("!=", self.name or ""),
				},
				"parent",
			)
			if other_case:
				frappe.throw(
					_("Beleg {0} {1} gehört bereits zu Versicherungsfall {2}.").format(
						doctype, referenz, other_case
					)
				)

			values = frappe.db.get_value(
				doctype,
				referenz,
				list(BELEG_FIELDS[doctype]),
				as_dict=True,
			)
			if not values:
				frappe.throw(
					_("Belegzeile {0}: {1} {2} wurde nicht gefunden.").format(idx, doctype, referenz)
				)
			self._validate_beleg_values(idx, row, values)
			self._enrich_beleg(row, values)

	def _validate_beleg_values(self, idx: int, row, values: dict[str, Any]) -> None:
		doctype = row.get("referenz_doctype")
		belegart = row.get("belegart")
		if values.get("company") and self.get("company") and values.get("company") != self.company:
			frappe.throw(_("Belegzeile {0}: Der Beleg gehört zu einer anderen Company.").format(idx))
		if int(values.get("docstatus") or 0) == 2:
			frappe.throw(_("Belegzeile {0}: Ein stornierter Beleg darf nicht verknüpft werden.").format(idx))

		if belegart in {"Mietergutschrift", "Mieterauszahlung"} and (
			not self.get("mietvertrag") or not self.get("kunde")
		):
			frappe.throw(
				_(
					"Belegzeile {0}: Ein Mieterbeleg benötigt einen eindeutig zugeordneten Mietvertrag."
				).format(idx)
			)

		if belegart == "Mietergutschrift":
			if int(values.get("is_return") or 0) != 1:
				frappe.throw(_("Belegzeile {0}: Die Sales Invoice ist keine Credit Note.").format(idx))
			if values.get("customer") != self.kunde:
				frappe.throw(
					_("Belegzeile {0}: Die Credit Note gehört nicht zum Customer des Mietvertrags.").format(
						idx
					)
				)

		if belegart == "Mieterauszahlung" and doctype == "Payment Entry":
			if values.get("party_type") != "Customer" or values.get("party") != self.get("kunde"):
				frappe.throw(
					_("Belegzeile {0}: Die Auszahlung gehört nicht zum Customer des Mietvertrags.").format(
						idx
					)
				)
			if values.get("payment_type") != "Pay":
				frappe.throw(_("Belegzeile {0}: Der Payment Entry ist keine Auszahlung.").format(idx))

		if belegart == "Mieterauszahlung" and doctype == "Bank Transaction":
			if flt(values.get("withdrawal")) <= TOLERANZ:
				frappe.throw(_("Belegzeile {0}: Die Bank Transaction ist kein Ausgang.").format(idx))
			if values.get("party") and (
				values.get("party_type") != "Customer" or values.get("party") != self.get("kunde")
			):
				frappe.throw(
					_("Belegzeile {0}: Die Bank Transaction ist einem anderen Mieter zugeordnet.").format(idx)
				)

		if belegart == "Versicherungseingang" and doctype == "Bank Transaction":
			if flt(values.get("deposit")) <= TOLERANZ:
				frappe.throw(_("Belegzeile {0}: Die Bank Transaction ist kein Eingang.").format(idx))

	def _enrich_beleg(self, row, values: dict[str, Any]) -> None:
		docstatus = int(values.get("docstatus") or 0)
		row.belegstatus = STATUS_LABELS.get(docstatus, "Entwurf")
		row.belegdatum = values.get("posting_date") or values.get("date")
		if flt(row.get("betrag")) < 0:
			frappe.throw(_("Der zugeordnete Belegbetrag darf nicht negativ sein."))
		if flt(row.get("betrag")) <= TOLERANZ:
			row.betrag = _reference_amount(row.get("referenz_doctype"), values)

	def _calculate_totals(self) -> None:
		totals = {
			"Reparaturrechnung": 0.0,
			"Versicherungseingang": 0.0,
			"Mietergutschrift": 0.0,
			"Mieterauszahlung": 0.0,
		}
		for row in self.get("belege") or []:
			if row.get("belegart") in totals:
				totals[row.belegart] += flt(row.get("betrag"))

		self.reparaturkosten = totals["Reparaturrechnung"]
		self.versicherung_erhalten = totals["Versicherungseingang"]
		self.mietergutschriften = totals["Mietergutschrift"]
		self.an_mieter_ausgezahlt = totals["Mieterauszahlung"]
		self.offen_versicherung = max(
			flt(self.get("bewilligter_betrag")) - self.versicherung_erhalten,
			0.0,
		)
		self.offen_mieter = max(self.mietergutschriften - self.an_mieter_ausgezahlt, 0.0)

	def _validate_completion(self) -> None:
		if self.get("status") != "Abgeschlossen":
			return
		if flt(self.get("offen_versicherung")) > TOLERANZ:
			frappe.throw(
				_("Der Versicherungsfall kann mit offenem Versicherungsbetrag nicht abgeschlossen werden.")
			)
		if flt(self.get("offen_mieter")) > TOLERANZ:
			frappe.throw(
				_("Der Versicherungsfall kann mit offenem Mieterguthaben nicht abgeschlossen werden.")
			)
		for row in self.get("belege") or []:
			if row.get("belegstatus") != "Eingereicht":
				frappe.throw(_("Zum Abschließen müssen alle verknüpften Buchungsbelege eingereicht sein."))

	def _set_bezeichnung(self) -> None:
		parts = [self.get("schadensart") or _("Versicherungsfall"), self.get("immobilie")]
		if self.get("wohnung"):
			parts.append(self.wohnung)
		if self.get("schadennummer"):
			parts.append(self.schadennummer)
		self.bezeichnung = " · ".join(str(part) for part in parts if part)


def _reference_amount(doctype: str, values: dict[str, Any]) -> float:
	if doctype == "Journal Entry":
		return abs(flt(values.get("total_debit")))
	if doctype in {"Sales Invoice", "Purchase Invoice"}:
		return abs(flt(values.get("grand_total")))
	if doctype == "Payment Entry":
		return abs(flt(values.get("paid_amount")))
	if doctype == "Bank Transaction":
		return abs(flt(values.get("deposit")) or flt(values.get("withdrawal")))
	return 0.0
