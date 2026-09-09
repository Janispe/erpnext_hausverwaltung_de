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
	"Mietererstattungsanspruch": ("Journal Entry",),
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
		from hausverwaltung.hausverwaltung.utils.insurance_receivables import validate_case

		validate_case(self)
		self._validate_payment_evidence()
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
			("erstattungsbetrag", _("Erstattungsbetrag")),
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
		# Cancellations stay in the audit trail but never contribute to totals.

		if belegart in {"Mietererstattungsanspruch", "Mietergutschrift", "Mieterauszahlung"} and (
			not self.get("mietvertrag") or not self.get("kunde")
		):
			frappe.throw(
				_(
					"Belegzeile {0}: Ein Mieterbeleg benötigt einen eindeutig zugeordneten Mietvertrag."
				).format(idx)
			)

		if belegart == "Mietererstattungsanspruch":
			journal = frappe.get_doc("Journal Entry", row.get("referenz"))
			parties = [r for r in journal.accounts if r.party_type or r.party]
			if len(parties) != 1 or parties[0].party_type != "Customer" or parties[0].party != self.kunde:
				frappe.throw(_("Der Erstattungsanspruch muss genau zum Debitor des Mietvertrags gehören."))
			leg = parties[0]
			if (
				frappe.db.get_value("Account", leg.account, "account_type") != "Receivable"
				or flt(leg.credit_in_account_currency) <= 0
				or flt(leg.debit_in_account_currency)
			):
				frappe.throw(_("Der Erstattungsanspruch muss ein Guthaben auf dem Debitorenkonto sein."))
			if leg.reference_type or leg.reference_name:
				frappe.throw(_("Eine Rechnungskorrektur ist kein eigenständiger Erstattungsanspruch."))
			if journal.get("custom_versicherungsfall") and journal.custom_versicherungsfall != self.name:
				frappe.throw(_("Der Erstattungsbeleg gehört zu einem anderen Versicherungsfall."))
			values["reference_amount"] = flt(leg.credit_in_account_currency)

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
		maximum = values.get("reference_amount", _reference_amount(row.get("referenz_doctype"), values))
		if flt(row.get("betrag")) > maximum + TOLERANZ:
			frappe.throw(_("Der zugeordnete Betrag übersteigt den Buchungsbeleg."))
		if flt(row.get("betrag")) <= TOLERANZ:
			row.betrag = maximum

	def _calculate_totals(self) -> None:
		totals = {
			"Versicherungsforderung": 0.0,
			"Reparaturrechnung": 0.0,
			"Versicherungseingang": 0.0,
			"Mietergutschrift": 0.0,
			"Mietererstattungsanspruch": 0.0,
			"Mieterauszahlung": 0.0,
		}
		for row in self.get("belege") or []:
			if row.get("referenz_doctype") == "Bank Transaction":
				# Bank statement evidence is never a second accounting voucher.
				continue
			if row.get("belegart") in totals and row.get("belegstatus") == "Eingereicht":
				totals[row.belegart] += flt(row.get("betrag"))

		self.versicherungsforderung_gebucht = totals["Versicherungsforderung"]
		self.versicherungsforderung_offen = max(totals["Versicherungsforderung"] - totals["Versicherungseingang"], 0.0)
		self.reparaturkosten = totals["Reparaturrechnung"]
		self.versicherung_erhalten = totals["Versicherungseingang"]
		self.mietergutschriften = totals["Mietergutschrift"]
		self.mieteranspruch_gebucht = totals["Mietererstattungsanspruch"]
		self.an_mieter_ausgezahlt = totals["Mieterauszahlung"]
		self.offen_versicherung = max(
			flt(self.get("bewilligter_betrag")) - self.versicherung_erhalten,
			0.0,
		)
		self.offen_mieter = max(
			max(flt(self.get("erstattungsbetrag")), self.mieteranspruch_gebucht + self.mietergutschriften)
			- self.an_mieter_ausgezahlt,
			0.0,
		)

	def _validate_completion(self) -> None:
		if self.get("status") != "Abgeschlossen":
			return
		if (
			flt(self.get("erstattungsbetrag"))
			> flt(self.get("mieteranspruch_gebucht")) + flt(self.get("mietergutschriften")) + TOLERANZ
		):
			frappe.throw(_("Der anerkannte Mieteranspruch ist noch nicht vollständig gebucht."))
		if flt(self.get("offen_versicherung")) > TOLERANZ:
			frappe.throw(
				_("Der Versicherungsfall kann mit offenem Versicherungsbetrag nicht abgeschlossen werden.")
			)
		if flt(self.get("offen_mieter")) > TOLERANZ:
			frappe.throw(
				_("Der Versicherungsfall kann mit offenem Mieterguthaben nicht abgeschlossen werden.")
			)
		for row in self.get("belege") or []:
			if row.get("belegstatus") == "Entwurf":
				frappe.throw(_("Zum Abschließen müssen alle verknüpften Buchungsbelege eingereicht sein."))

	def _validate_payment_evidence(self):
		claims = {
			(r.referenz_doctype, r.referenz)
			for r in self.belege
			if r.belegart in {"Mietererstattungsanspruch", "Mietergutschrift"}
		}
		for row in self.belege:
			if (
				row.belegart != "Mieterauszahlung"
				or row.referenz_doctype != "Payment Entry"
				or row.belegstatus == "Storniert"
			):
				continue
			pe = frappe.get_doc("Payment Entry", row.referenz)
			allocated = sum(
				-flt(r.allocated_amount)
				for r in pe.references
				if (r.reference_doctype, r.reference_name) in claims
			)
			if allocated <= 0 or row.betrag > allocated + TOLERANZ:
				frappe.throw(
					_(
						"Die Mieterauszahlung muss den verknüpften Erstattungsanspruch oder die Mietergutschrift ausgleichen."
					)
				)

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


@frappe.whitelist()
def create_tenant_claim(name, posting_date):
	"""Create a reviewable JE draft; never submit or initiate a bank transfer."""
	from erpnext.accounts.party import get_party_account

	from hausverwaltung.hausverwaltung.utils.tenant_refunds import tenant_contract

	case = frappe.get_doc("Versicherungsfall", name, for_update=True)
	case.check_permission("write")
	case._apply_scope()
	if not case.kunde or not case.mietvertrag:
		frappe.throw(_("Bitte den Mietvertrag des Erstattungsempfängers auswählen."))
	if tenant_contract(case.kunde, for_update=True).name != case.mietvertrag:
		frappe.throw(_("Der Customer gehört nicht eindeutig zum Mietvertrag."))
	if case.status in ABSCHLUSS_STATUS:
		frappe.throw(_("Ein abgeschlossener Fall muss vor einer neuen Buchung wieder geöffnet werden."))
	if not posting_date or not case.erstattungsbegruendung or flt(case.erstattungsbetrag) <= 0:
		frappe.throw(_("Bitte Buchungsdatum, anerkannten Erstattungsbetrag und Begründung erfassen."))
	for row in case.belege:
		if row.belegart in {"Mietererstattungsanspruch", "Mietergutschrift"}:
			if frappe.db.get_value(row.referenz_doctype, row.referenz, "docstatus") != 2:
				frappe.throw(
					_("Ein Mieteranspruch ist bereits verknüpft. Bitte den bestehenden Beleg verwenden.")
				)
		if row.belegart == "Reparaturrechnung" and case.erstattungsart == "Auslagenersatz Gebäudereparatur":
			frappe.throw(
				_(
					"Die Reparaturrechnung ist bereits erfasst. Bitte deren Zahlung durch den Mieter gegen die Lieferantenverbindlichkeit buchen und den Erstattungs-Journal-Entry verknüpfen; keinen zweiten Aufwand erzeugen."
				)
			)
	account = frappe.get_doc("Account", case.erstattungskonto)
	allowed_roots = {
		"Auslagenersatz Gebäudereparatur": {"Expense"},
		"Weiterleitung Versicherungsleistung": {"Asset", "Liability"},
	}
	if (
		account.company != case.company
		or account.is_group
		or account.disabled
		or account.account_type in {"Bank", "Cash", "Receivable", "Payable"}
		or account.root_type not in allowed_roots.get(case.erstattungsart, set())
	):
		frappe.throw(
			_(
				"Bitte ein passendes aktives Aufwands- beziehungsweise Verrechnungskonto dieser Company auswählen."
			)
		)
	currency = frappe.db.get_value("Company", case.company, "default_currency")
	party_account = get_party_account("Customer", case.kunde, case.company)
	for acc in (account.name, party_account):
		if frappe.db.get_value("Account", acc, "account_currency") != currency:
			frappe.throw(_("Erstattungsbuchungen werden nur in Company-Währung unterstützt."))
	cc = frappe.db.get_value("Immobilie", case.immobilie, "kostenstelle")
	if not cc or frappe.db.get_value("Cost Center", cc, "company") != case.company:
		frappe.throw(_("Die Immobilie benötigt eine Kostenstelle dieser Company."))
	remark = f"Erstattungsanspruch {case.name}: {case.erstattungsbegruendung}"
	je = frappe.get_doc(
		dict(
			doctype="Journal Entry",
			voucher_type="Journal Entry",
			company=case.company,
			posting_date=getdate(posting_date),
			user_remark=remark,
			custom_remark=1,
			remark=remark,
			custom_mieterkonto_kategorie=case.mieterkonto_kategorie or "Sonstig",
			custom_versicherungsfall=case.name,
			accounts=[
				dict(account=account.name, debit_in_account_currency=case.erstattungsbetrag, cost_center=cc),
				dict(
					account=party_account,
					party_type="Customer",
					party=case.kunde,
					credit_in_account_currency=case.erstattungsbetrag,
					cost_center=cc,
				),
			],
		)
	)
	je.insert()
	case.append(
		"belege",
		dict(belegart="Mietererstattungsanspruch", referenz_doctype="Journal Entry", referenz=je.name),
	)
	case.save()
	return {"doctype": "Journal Entry", "name": je.name}


def validate_insurance_journal(doc, method=None):
	for row in doc.accounts:
		if row.reference_type == "Journal Entry" and row.reference_name:
			if frappe.db.get_value("Journal Entry", row.reference_name, "custom_versicherungsbuchung") == "Versicherungsforderung" and doc.get("custom_versicherungsbuchung") != "Versicherungseingang":
				frappe.throw(_("Die Versicherungsforderung bitte über die Zuordnung eines Versicherungseingangs ausgleichen."))
	if doc.get("custom_versicherungsbuchung"):
		from hausverwaltung.hausverwaltung.utils.insurance_receivables import validate_journal

		return validate_journal(doc)
	if not doc.get("custom_versicherungsfall"):
		return
	from hausverwaltung.hausverwaltung.utils.tenant_refunds import tenant_contract

	case = frappe.get_doc("Versicherungsfall", doc.custom_versicherungsfall)
	case._apply_scope()
	if tenant_contract(case.kunde).name != case.mietvertrag or doc.company != case.company:
		frappe.throw(_("Erstattungsbuchung und Versicherungsfall haben unterschiedliche Zuordnungen."))
	cc = frappe.db.get_value("Immobilie", case.immobilie, "kostenstelle")
	if len(doc.accounts) != 2:
		frappe.throw(
			_("Der erzeugte Erstattungsbeleg muss aus Aufwand/Verrechnung und Mieterdebitor bestehen.")
		)
	debit, credit = doc.accounts
	if (
		debit.account != case.erstattungskonto
		or debit.party
		or credit.party_type != "Customer"
		or credit.party != case.kunde
		or flt(debit.debit_in_account_currency) != flt(case.erstattungsbetrag)
		or flt(credit.credit_in_account_currency) != flt(case.erstattungsbetrag)
		or debit.cost_center != cc
		or credit.cost_center != cc
		or doc.get("custom_mieterkonto_kategorie") != case.mieterkonto_kategorie
	):
		frappe.throw(
			_(
				"Der Erstattungsbeleg stimmt nicht mit Betrag, Mieter, Gegenkonto, Kostenstelle oder Kategorie des Versicherungsfalls überein."
			)
		)


def sync_insurance_voucher(doc, method=None):
	"""Keep claim/payment status current on submit and cancellation."""
	links = frappe.get_all(
		"Versicherungsfall Beleg",
		filters={
			"referenz_doctype": doc.doctype,
			"referenz": doc.name,
		},
		fields=["parent"],
	)
	names = {r.parent for r in links}
	if doc.doctype == "Journal Entry" and doc.get("custom_versicherungsfall"):
		names.add(doc.custom_versicherungsfall)
	if doc.doctype == "Payment Entry" and doc.party_type == "Customer" and doc.payment_type == "Pay":
		for ref in doc.references:
			if ref.reference_doctype == "Journal Entry":
				name = frappe.db.get_value("Journal Entry", ref.reference_name, "custom_versicherungsfall")
				if name:
					names.add(name)
	for name in sorted(names):
		case = frappe.get_doc("Versicherungsfall", name, for_update=True)
		if doc.doctype == "Journal Entry" and doc.get("custom_versicherungsbuchung") and doc.docstatus == 1:
			if not any(r.referenz_doctype == doc.doctype and r.referenz == doc.name for r in case.belege):
				case.append("belege", dict(belegart=doc.custom_versicherungsbuchung, referenz_doctype=doc.doctype, referenz=doc.name))
		if (
			doc.doctype == "Payment Entry"
			and doc.docstatus == 1
			and not any(r.referenz_doctype == doc.doctype and r.referenz == doc.name for r in case.belege)
		):
			claim_names = {r.referenz for r in case.belege if r.belegart == "Mietererstattungsanspruch"}
			amount = sum(
				-flt(r.allocated_amount)
				for r in doc.references
				if r.reference_doctype == "Journal Entry" and r.reference_name in claim_names
			)
			if amount > TOLERANZ:
				case.append(
					"belege",
					dict(
						belegart="Mieterauszahlung",
						referenz_doctype=doc.doctype,
						referenz=doc.name,
						betrag=amount,
					),
				)
		if doc.docstatus == 2 and case.status in ABSCHLUSS_STATUS:
			case.status = "Teilweise reguliert"
		case.save(ignore_permissions=True)
