"""Case-owned claim booking and date correction, in one database transaction."""

from __future__ import annotations

import frappe
from frappe.utils import flt, getdate

INSURANCE = "Versicherungsforderung"
TENANT = "Mietererstattungsanspruch"
ROLES = (INSURANCE, TENANT)


def _active_claims(case):
	claims = {}
	# Include both links and generated documents so missing links cannot cause duplicates.
	candidates = {
		r.referenz for r in case.belege if r.belegart in ROLES and r.referenz_doctype == "Journal Entry"
	}
	candidates.update(
		frappe.get_all(
			"Journal Entry",
			filters={"custom_versicherungsfall": case.name, "docstatus": ["!=", 2]},
			pluck="name",
		)
	)
	for name in sorted(candidates):
		doc = frappe.get_doc("Journal Entry", name, for_update=True)
		if doc.docstatus == 2:
			continue
		role = doc.get("custom_versicherungsbuchung") or TENANT
		if role not in ROLES:
			continue
		doc.check_permission("read")
		if doc.get("custom_versicherungsfall") != case.name:
			frappe.throw(
				"Der verknüpfte Anspruch wurde außerhalb dieses Versicherungsfalls erstellt. Bitte dessen Zuordnung zuerst prüfen."
			)
		if role in claims:
			frappe.throw(f"Mehrere aktive Belege für {role}. Bitte zuerst die bestehenden Buchungen prüfen.")
		claims[role] = doc
	return claims


def _assert_unsettled(doc):
	# Check references, not only a zero/net balance: offsetting allocations also
	# must not disappear when an original claim is replaced.
	linked = frappe.db.sql(
		"""
		SELECT j.name FROM `tabJournal Entry Account` a
		JOIN `tabJournal Entry` j ON j.name=a.parent
		WHERE j.docstatus=1 AND a.reference_type='Journal Entry' AND a.reference_name=%s
		UNION ALL
		SELECT pe.name FROM `tabPayment Entry Reference` r
		JOIN `tabPayment Entry` pe ON pe.name=r.parent
		WHERE pe.docstatus=1 AND r.reference_doctype='Journal Entry' AND r.reference_name=%s
		UNION ALL
		SELECT voucher_no FROM `tabPayment Ledger Entry`
		WHERE delinked=0 AND against_voucher_type='Journal Entry' AND against_voucher_no=%s
		AND NOT (voucher_type='Journal Entry' AND voucher_no=%s)
		LIMIT 1
	""",
		(doc.name, doc.name, doc.name, doc.name),
	)
	if linked:
		frappe.throw(
			f"Anspruch {doc.name} ist bereits mit {linked[0][0]} ausgeglichen. Die Datumskorrektur wurde nicht ausgeführt. Zuerst die zugehörige Zahlungsbuchung über 'Beleg lösen' im Bankimport aufheben."
		)


@frappe.whitelist()
def book_claims(name, insurance_date=None, tenant_date=None, expected_modified=None, correction_reason=None):
	"""Reuse drafts, submit claims together, or replace only changed unpaid claims.

	Never commit here. Savepoint rollback also protects callers that catch errors;
	normal Frappe request rollback remains the outer transaction boundary.
	"""
	from hausverwaltung.hausverwaltung.doctype.versicherungsfall.versicherungsfall import (
		create_tenant_claim,
		validate_insurance_journal,
	)
	from hausverwaltung.hausverwaltung.utils.insurance_receivables import create_insurance_claim

	case = frappe.get_doc("Versicherungsfall", name, for_update=True)
	case.check_permission("write")
	if not expected_modified or str(case.modified) != str(expected_modified):
		frappe.throw(
			"Der Versicherungsfall wurde zwischenzeitlich geändert. Bitte neu laden und die Angaben erneut prüfen."
		)
	if case.status in {"Abgeschlossen", "Abgelehnt"}:
		frappe.throw("Bitte den Versicherungsfall vor einer Buchung oder Korrektur wieder öffnen.")
	case._apply_scope()
	claims = _active_claims(case)
	amounts = {INSURANCE: flt(case.bewilligter_betrag), TENANT: flt(case.erstattungsbetrag)}
	requested = {INSURANCE: insurance_date, TENANT: tenant_date}
	roles = [r for r in ROLES if amounts[r] > 0 or r in claims]
	if not roles:
		frappe.throw(
			"Bitte zuerst den bewilligten Versicherungsbetrag beziehungsweise den anerkannten Mietererstattungsbetrag erfassen."
		)
	dates = {}
	replacements = {}
	for role in roles:
		if not requested[role]:
			frappe.throw(
				f"Bitte das Buchungsdatum für {role} angeben. Maßgeblich ist das Datum des Anspruchs, nicht der Tag der Dateneingabe."
			)
		dates[role] = getdate(requested[role])
		if case.schadendatum and dates[role] < getdate(case.schadendatum):
			frappe.throw(f"Das Buchungsdatum für {role} darf nicht vor dem Schadendatum liegen.")
		doc = claims.get(role)
		if doc:
			validate_insurance_journal(doc)
			if doc.docstatus == 1 and getdate(doc.posting_date) != dates[role]:
				if not (correction_reason or "").strip():
					frappe.throw("Bitte einen Grund für die Datumskorrektur angeben.")
				doc.check_permission("cancel")
				_assert_unsettled(doc)
				replacements[role] = doc.name
			elif doc.docstatus == 0:
				doc.check_permission("write")
				doc.check_permission("submit")

	frappe.db.savepoint("insurance_case_claims")
	try:
		result = []
		for role in roles:
			doc = claims.get(role)
			old_name = replacements.get(role)
			if old_name:
				doc.cancel()
				doc = None
			if not doc:
				creator = create_insurance_claim if role == INSURANCE else create_tenant_claim
				created = creator(case.name, str(dates[role]))
				doc = frappe.get_doc("Journal Entry", created["name"])
				if old_name:
					# ERPNext's amendment link plus explicit case links retain provenance.
					doc.amended_from = old_name
					doc.save()
			if doc.docstatus == 0:
				if getdate(doc.posting_date) != dates[role]:
					doc.posting_date = dates[role]
					if doc.meta.has_field("custom_wertstellungsdatum"):
						doc.custom_wertstellungsdatum = dates[role]
					doc.save()
				doc.submit()
			result.append(
				dict(role=role, name=doc.name, posting_date=str(doc.posting_date), replaces=old_name)
			)
		case.reload()
		if replacements:
			from frappe.utils import escape_html

			case.add_comment(
				"Comment",
				text="Datumskorrektur: "
				+ escape_html(correction_reason.strip())
				+ "<br>"
				+ "<br>".join(
					f"{escape_html(r['replaces'])} → {escape_html(r['name'])}, {r['posting_date']}"
					for r in result
					if r["replaces"]
				),
			)
		return {"ok": True, "claims": result}
	except Exception:
		frappe.db.rollback(save_point="insurance_case_claims")
		raise
