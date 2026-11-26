"""The booking-inbox entry points for one exact, human-reviewed cash receipt."""

from datetime import date

import frappe
from frappe.utils import flt

from hausverwaltung.hausverwaltung.page.buchen_cockpit import buchen_cockpit as cockpit
from hausverwaltung.hausverwaltung.services import receipt_batch
from hausverwaltung.hausverwaltung.services import receipt_pilot as pilot

from . import domain, frappe_service as engine, registry
from .frappe_guards import service_scope

ACTION = "hv.cash_receipt.book/v1"
POLICY = registry.ACTIONS[ACTION].policy
ACCOUNTING_ROLES = {"Accounts User", "Accounts Manager"}
BOOKING_TEXT = ("lieferant", "rechnungsname", "remarks", "zahlungsbemerkung")
ROW_TEXT = ("kostenart", "umlagefaehig", "wohnung")


def _accountant(user):
	roles = set(frappe.get_roles(user))
	info = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
	return (
		info and info.enabled and info.user_type == "System User"
		and (user == "Administrator" or (
			bool(roles & ACCOUNTING_ROLES) and not roles & {pilot.AGENT_ROLE, receipt_batch.AGENT_ROLE, engine.AGENT}
		))
	)


def _human():
	pilot._require_enabled()
	user = frappe.session.user
	request = getattr(frappe.local, "request", None)
	manager = getattr(frappe.local, "login_manager", None)
	sid = frappe.session.get("sid")
	if (
		user == "Guest" or not _accountant(user) or not request or not manager
		or manager.user != user or not sid or request.cookies.get("sid") != sid
		or request.headers.get("Authorization")
	):
		frappe.throw("Die Barauslagen-Freigabe benötigt eine angemeldete Buchhaltungssitzung.", frappe.PermissionError)


def _receipt(name):
	_human()
	doc = frappe.get_doc(pilot.PROPOSAL, name, for_update=True)
	doc.check_permission("read")
	doc.check_permission("write")
	if not doc.receipt_digest:
		frappe.throw("Bon nicht verfügbar.", frappe.PermissionError)
	cockpit._require_document_permissions("Purchase Invoice", submit=True)
	cockpit._require_document_permissions("Journal Entry", submit=True)
	return doc


def _key(receipt):
	return domain.digest([ACTION, receipt.receipt_digest])


def _proposal(receipt, lock=False):
	name = frappe.db.get_value(engine.PROPOSAL, {"request_id": _key(receipt)}, "name", for_update=lock)
	if not name:
		return None, None
	doc = frappe.get_doc(engine.PROPOSAL, name, for_update=lock)
	body = engine._body(doc, lock=lock)
	if doc.target != receipt.name or doc.action != ACTION or body["action"] != ACTION:
		frappe.throw("Der Bon ist bereits mit einem anderen Vorschlag verknüpft.")
	return doc, body


def _source(receipt):
	# The modification timestamp also invalidates a change followed by a revert.
	return domain.digest([
		receipt.name, receipt.receipt_digest, receipt.file_url, receipt.status,
		receipt.linked_purchase_invoice, str(receipt.modified),
		receipt.receipt_context, receipt.extracted_data,
	])


def _binding(doc):
	return {"id": doc.name, "revision": doc.current_revision, "hash": doc.revision_hash}


def _final(receipt):
	return receipt.status in {"Booked", "Cancelled"} or bool(receipt.linked_purchase_invoice)


def review_state(receipt):
	"""Used after the Inbox has checked read permission on the source."""
	if not pilot.enabled() or not _accountant(frappe.session.user):
		return None
	source = _source(receipt)
	if receipt.status == "Cancelled":
		return {"source": source, "status": "Cancelled"}
	doc, body = _proposal(receipt)
	if not doc:
		return {"source": source, "status": "Succeeded" if _final(receipt) else "Pending"}
	status = doc.status
	if status == "Approved" and body["preview"]["source"] != source:
		status = "Stale"
	return {
		"source": source, "status": status, "binding": _binding(doc),
		"booking": body["payload"]["booking"],
	}


def review_versions(receipt_names):
	"""Version only the receipt rows the Inbox already authorized for reading."""
	if not receipt_names:
		return {}
	return dict(frappe.get_all(engine.PROPOSAL,
		filters={"action": ACTION, "target": ["in", receipt_names]},
		fields=["target", "modified"], as_list=True, limit_page_length=0))


def on_settlement_cancel(journal, method=None):
	invoices = {line.reference_name for line in journal.accounts
		if line.reference_type == "Purchase Invoice" and line.reference_name}
	for invoice in sorted(invoices):
		name = frappe.db.get_value(pilot.PROPOSAL, {
			"linked_purchase_invoice": invoice, "status": "Booked", "receipt_digest": ["is", "set"],
		}, "name", for_update=True)
		if not name:
			continue
		receipt = frappe.get_doc(pilot.PROPOSAL, name, for_update=True)
		proposal, _ = _proposal(receipt, lock=True)
		if (proposal and proposal.status == "Succeeded"
			and frappe.parse_json(proposal.result)["settlement_journal_entry"] == journal.name):
			frappe.db.set_value(pilot.PROPOSAL, name, "status", "Cancelled")


def _text(values, key):
	value = values.get(key)
	if value is None:
		return ""
	if not isinstance(value, str):
		frappe.throw(f"Ungültiger Wert für {key}.")
	return value.strip()


def _date(values, key, required=False):
	value = _text(values, key)
	if not value and not required:
		return ""
	try:
		return date.fromisoformat(value).isoformat()
	except ValueError:
		frappe.throw(f"Bitte ein gültiges Datum für {key} erfassen.")


def _booking(values):
	values = engine._json(values, dict)
	rows = engine._json(values.get("positionen"), list)
	total = pilot._amount(values.get("beleg_brutto_bestaetigt"))
	if total is None or total <= 0:
		frappe.throw("Bitte den Brutto-Endbetrag auf dem Originalbeleg bestätigen.")
	positions = []
	for index, row in enumerate(rows, 1):
		row = engine._json(row, dict)
		if any(row.get(key) for key in ("konto", "betriebskostenart", "kostenart_nicht_ul")):
			frappe.throw(f"Bitte in Bonposition {index} eine Kostenart auswählen.")
		positions.append({
			**{key: _text(row, key) for key in ROW_TEXT},
			"betrag": cockpit._validated_booking_amount(row.get("betrag"), index=index),
		})
	return {
		**{key: _text(values, key) for key in BOOKING_TEXT},
		"rechnungsdatum": _date(values, "rechnungsdatum", required=True),
		"wertstellungsdatum": _date(values, "wertstellungsdatum"),
		"beleg_brutto_bestaetigt": str(total),
		"beleg_eur_bestaetigt": cockpit._as_bool(values.get("beleg_eur_bestaetigt")),
		"positionen": positions,
	}


def _plan(receipt, booking):
	"""Resolve the booking inputs without inserting or submitting an ERPNext voucher."""
	receipt_batch.require_bookable(receipt)
	context = pilot.review_context(receipt)
	if context["fragen"]:
		frappe.throw(context["fragen"][0])
	try:
		original, _ = pilot.verified_original(receipt, for_update=True)
	except (OSError, ValueError, frappe.DoesNotExistError):
		frappe.throw("Der private Originalbeleg fehlt oder wurde verändert.")
	original.check_permission("read")

	params = booking | {
		"vorschlag_name": receipt.name, "submit_doc": True, "zahlung_sofort": True,
		"zahlungsart": context["zahlungsart"], "zahlungskonto": context["zahlungskonto"],
		"positionen": [row | {"kostenstelle": context["kostenstelle"]} for row in booking["positionen"]],
	}
	if context["zahlungsquelle"] == "Privat vorgestreckt":
		note = f"Privat vorgestreckt von {context['person']}"
		params["zahlungsbemerkung"] = "\n".join(filter(None, (note, booking["zahlungsbemerkung"])))
	request = cockpit._purchase_invoice_request_context(params, receipt=receipt)
	pilot.validate_booking_confirmation(receipt, request["rows"], eur_confirmed=booking["beleg_eur_bestaetigt"])
	pi = cockpit._prepare_cockpit_purchase_invoice(request, params, receipt=True)
	pi.set_missing_values(for_validate=True)
	pi.set_taxes_and_charges()
	pi.calculate_taxes_and_totals()
	cockpit._validate_receipt_total(pi, flt(booking["beleg_brutto_bestaetigt"]))
	cockpit._validate_settlement_account(
		params["zahlungskonto"], company=pi.company, payable_account=pi.credit_to,
		zahlungsart=params["zahlungsart"],
	)
	preview = {
		"source": _source(receipt), "original": original.name,
		"invoice": cockpit._receipt_invoice_effect(pi),
		"settlement_account": params["zahlungskonto"], "payment_type": params["zahlungsart"],
		"payment_note": params["zahlungsbemerkung"],
	}
	return preview, pi, request, params, original


def _expect(doc, binding):
	if binding is None or engine._binding(binding) != _binding(doc):
		frappe.throw("Die Bon-Fassung hat sich geändert. Bitte die Buchungs-Inbox neu laden.")


def _response(doc):
	return {"status": doc.status, "binding": _binding(doc)}


def _invalidate(doc, cause):
	doc.status, doc.decision_by, doc.decision_at = "Stale", None, None
	engine._event(doc, "Stale", {"cause": cause})


@frappe.whitelist(methods=["POST"])
def approve(name, source, booking, binding=None, context=None):
	receipt = _receipt(name)
	doc, body = _proposal(receipt, lock=True)
	if doc and doc.status == "Succeeded":
		_expect(doc, binding)
		if receipt.status == "Cancelled":
			return _response(doc) | {"status": "Cancelled"}
		return _response(doc)
	if source != _source(receipt) or _final(receipt):
		frappe.throw("Der Bon hat sich geändert. Bitte den Originalbeleg und die Buchungsdaten erneut prüfen.")

	booking = _booking(booking)
	if context is not None:
		pilot.set_context(receipt, context)
	preview, *_ = _plan(receipt, booking)
	operation = {"target": receipt.name, "booking": booking}
	with service_scope():
		if doc:
			if (
				doc.status == "Approved" and body["policy"] == POLICY
				and body["payload"] == operation and body["preview"] == preview
			):
				return _response(doc)
			_expect(doc, binding)
			if doc.status == "Approved":
				_invalidate(doc, "booking_data_changed")
			doc.current_revision += 1
			doc.status = "Pending"
			event = "Revised"
		else:
			if binding is not None:
				frappe.throw("Die Bon-Fassung hat sich geändert. Bitte die Buchungs-Inbox neu laden.")
			key = _key(receipt)
		if receipt.receipt_upload:
			package = domain.receipt_upload_package(receipt.receipt_upload)
			package_meta = domain.receipt_upload_package_meta(receipt.receipt_upload)
		else:
			package = domain.RECEIPT_PACKAGE_PREFIX + key
			package_meta = {"title": f"Barauslage {receipt.name}", "reference_doctype": pilot.PROPOSAL,
				"reference_name": receipt.name}
		engine._lock_package(package, create=True, package_meta=package_meta)
			doc = engine._create_proposal(ACTION, receipt.name, package, key, domain.digest(operation))
			event = "Created"
		engine._revision(doc, operation, [], {}, policy=POLICY, preview=preview)
		engine._event(doc, event)
		engine._approve(doc)
		return _response(doc)


@frappe.whitelist(methods=["POST"])
def reopen(name, binding):
	receipt = _receipt(name)
	doc, _ = _proposal(receipt, lock=True)
	if not doc or _final(receipt) or doc.status not in {"Approved", "Stale"}:
		frappe.throw("Die Freigabe kann nicht mehr zurückgezogen werden.")
	_expect(doc, binding)
	if doc.status == "Approved":
		with service_scope():
			_invalidate(doc, "correction_requested")
	return _response(doc)


@frappe.whitelist(methods=["POST"])
def execute(name, binding):
	receipt = _receipt(name)
	doc, body = _proposal(receipt, lock=True)
	if not doc:
		frappe.throw("Bitte zuerst die geprüfte Bon-Fassung freigeben.")
	_expect(doc, binding)
	if doc.status == "Succeeded":
		if receipt.status == "Cancelled":
			return _response(doc) | {"status": "Cancelled"}
		return _response(doc) | {"result": frappe.parse_json(doc.result)}
	if doc.status == "Stale":
		return _response(doc)
	if doc.status != "Approved" or not doc.decision_by or not _accountant(doc.decision_by):
		frappe.throw("Bitte zuerst die geprüfte Bon-Fassung freigeben.")
	for doctype, permission, target in (
		(pilot.PROPOSAL, "write", receipt), ("Purchase Invoice", "create", None),
		("Purchase Invoice", "submit", None), ("Journal Entry", "create", None),
		("Journal Entry", "submit", None),
	):
		frappe.has_permission(doctype, permission, doc=target, user=doc.decision_by, throw=True)

	with service_scope():
		if body["policy"] != POLICY or _source(receipt) != body["preview"]["source"]:
			_invalidate(doc, "source_changed")
			return _response(doc)
		booking = body["payload"]["booking"]
		messages = list(frappe.local.message_log)
		try:
			preview, pi, request, params, original = _plan(receipt, booking)
		except frappe.ValidationError:
			frappe.local.message_log = messages
			_invalidate(doc, "booking_data_changed")
			return _response(doc)
		if preview != body["preview"]:
			_invalidate(doc, "booking_data_changed")
			return _response(doc)
		result = cockpit._post_cockpit_purchase_invoice(
			pi, request, params, receipt_file=original, receipt_total=flt(booking["beleg_brutto_bestaetigt"]),
			receipt_effect=preview["invoice"],
		)
		engine._succeed(doc, result)
	return _response(doc) | {"result": result}
