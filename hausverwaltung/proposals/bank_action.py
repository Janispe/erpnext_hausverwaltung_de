"""Bankimport action payloads, projections and execution."""
from contextvars import ContextVar
from decimal import Decimal, InvalidOperation
from uuid import uuid4

import frappe
from frappe.utils import now_datetime

from hausverwaltung.hausverwaltung.doctype.bankauszug_import import bankauszug_import as booking
from hausverwaltung.hausverwaltung.doctype.bankauszug_import.customer_payment_split import customer_payments

from . import domain, frappe_service as core, registry

IMPORT = "Bankauszug Import"
PARTY_ACTION = "hv.bankimport.assign_party/v1"
VOUCHERS = ("Payment Entry", "Journal Entry")
_executing_row = ContextVar("hv_proposal_bank_row", default=None)


def lock_import(name):
	booking._lock_bank_booking_scope(name)


def import_document(name, permission="read", user=None, lock=False):
	doc = frappe.get_doc(IMPORT, name, for_update=lock)
	for right in {"read", permission}:
		if not frappe.has_permission(IMPORT, right, doc=doc, user=user):
			core._deny()
		level = doc.meta.get_field("rows").permlevel or 0
		if level and level not in doc.meta.get_permlevel_access(permission_type=right, user=user):
			core._deny()
	return doc


def row_document(doc, name):
	for row in doc.rows:
		if row.name == name:
			return row
	core._deny()


def fingerprint(row):
	return {"date": str(row.buchungstag), "amount": float(row.betrag), "direction": row.richtung,
		"iban": row.iban or "", "purpose_hash": domain.digest(row.verwendungszweck or "")}


def _amount(value):
	try:
		result = Decimal(str(value))
		if not result.is_finite() or result != result.quantize(Decimal(".01")):
			raise ValueError("Beträge müssen auf Cent genau sein.")
		return int(result * 100)
	except InvalidOperation as exc:
		raise ValueError("Ungültiger Betrag.") from exc


def _items(value, required, optional=()):
	if not isinstance(value, list) or not 1 <= len(value) <= 11:
		raise ValueError("Eine Liste mit bis zu elf Einträgen ist erforderlich.")
	for item in value:
		if not isinstance(item, dict) or not set(required) <= set(item) <= set(required) | set(optional):
			raise ValueError("Ungültige Buchungsaufteilung.")
	return value


def operation(action, payload, doc):
	spec = registry.ACTIONS.get(action)
	if not spec or spec.surface != "bankimport":
		raise ValueError("Unbekannte Bankimport-Aktion.")
	if set(payload) != {"import_name", "row", "fingerprint", "parameters"} or payload["import_name"] != doc.name:
		raise ValueError("Import, Zeile, Fingerabdruck und Parameter sind erforderlich.")
	row = row_document(doc, payload["row"])
	if payload["fingerprint"] != fingerprint(row):
		raise ValueError("Die Importzeile hat sich geändert.")
	params = payload["parameters"]
	if not isinstance(params, dict) or set(params) - set(spec.parameters):
		raise ValueError("Unbekannte Buchungsparameter.")
	required = {"party": ("party", "party_type"), "invoice": ("invoice_names",),
		"abschlag": ("plan_row_name",), "transfer": ("other_bank_account",)}.get(spec.kind, ())
	if any(not params.get(key) for key in required):
		raise ValueError("Buchungsparameter fehlen.")
	if spec.kind == "payment" and ("party_type" in params) != ("party" in params):
		raise ValueError("Partei und Partei-Typ müssen zusammen angegeben werden.")
	if spec.kind == "party" and params["party_type"] != "Customer":
		raise ValueError("Die Parteizuordnung erfordert den Customer eines Mietvertrags.")
	if spec.kind == "kredit" and (
		not params.get("kreditvertrag") or bool(params.get("rate_name")) == bool(params.get("from_statement"))
	):
		raise ValueError("Kreditvertrag mit einer Planrate oder Ableitung aus dem Verwendungszweck erforderlich.")
	if spec.kind == "journal" and bool(params.get("account")) == bool(params.get("splits")):
		raise ValueError("Gegenkonto oder Aufteilung erforderlich.")
	if spec.kind == "split" and not (params.get("invoice_allocations") or params.get("abschlag_rows")):
		raise ValueError("Mindestens eine Rechnung oder Abschlagszeile ist erforderlich.")
	for key, value in params.items():
		if key in {"leftover_as_advance", "from_statement"}:
			if type(value) is not bool:
				raise ValueError("Bestätigungsfelder müssen boolesch sein.")
		elif key in {"invoice_names", "invoice_allocations"}:
			_items(value, ("name", "allocated_amount"), ("reference_doctype",))
			for item in value:
				domain.text(item["name"], "Rechnung", 1, 140)
				if _amount(item["allocated_amount"]) <= 0:
					raise ValueError("Zuordnungsbeträge müssen positiv sein.")
		elif key == "abschlag_rows":
			if not isinstance(value, list) or not 1 <= len(value) <= 11:
				raise ValueError("Ungültige Abschlagszeilen.")
			for name in value:
				domain.text(name, "Abschlagszeile", 1, 140)
		elif key == "splits":
			_items(value, ("account", "amount"), ("cost_center",))
			for item in value:
				domain.text(item["account"], "Konto", 1, 140)
				if _amount(item["amount"]) <= 0:
					raise ValueError("Teilbeträge müssen positiv sein.")
		else:
			domain.text(value, key, 1, 1000 if key == "remarks" else 140)
	return payload | {"target": row.name}


def _read(doctype, name, user=None, lock=False):
	doc = frappe.get_doc(doctype, name, for_update=lock)
	if not frappe.has_permission(doctype, "read", doc=doc, user=user):
		core._deny()
	return doc


def _party(action, params, row):
	if action == PARTY_ACTION:
		return params["party_type"], params["party"]
	return params.get("party_type", row.party_type), params.get("party", row.party)


def _state(row, lock=False):
	bt_name = booking._get_row_bank_transaction_name(row)
	bt = frappe.get_doc("Bank Transaction", bt_name, for_update=lock) if bt_name else None
	voucher = booking._linked_voucher_for_row(row)
	return {"fingerprint": fingerprint(row), "party_type": row.party_type or None, "party": row.party or None,
		"transaction": bt_name, "transaction_party": [bt.party_type, bt.party] if bt else None,
		"transaction_vouchers": sorted([p.payment_document or "", p.payment_entry or "", float(p.allocated_amount)]
			for p in (bt.get("payment_entries") or [])) if bt else [],
		"voucher": list(voucher) if voucher[1] else [],
		"customer_payments": customer_payments(row)}


def _references(action, params, party_type, user=None, lock=False):
	references = []
	invoice_type = {"Customer": "Sales Invoice", "Supplier": "Purchase Invoice"}.get(party_type)
	for item in params.get("invoice_names", params.get("invoice_allocations", [])):
		picked = item.get("reference_doctype")
		if not invoice_type or picked not in {None, invoice_type}:
			raise ValueError("Rechnungsart passt nicht zur Partei.")
		invoice = _read(invoice_type, item["name"], user=user, lock=lock)
		references.append({"doctype": invoice_type, "name": invoice.name,
			"remaining": float(invoice.outstanding_amount), "status": int(invoice.docstatus)})
	plan_rows = params.get("abschlag_rows", [])
	if params.get("plan_row_name"):
		plan_rows = [params["plan_row_name"]]
	if plan_rows:
		from hausverwaltung.hausverwaltung.doctype.zahlungsplan.zahlungsplan import _active_allocation_amounts

		for name in plan_rows:
			parent = frappe.db.get_value("Zahlungsplan Zeile", name, "parent", for_update=lock)
			plan = _read("Zahlungsplan", parent, user=user, lock=lock)
			line = next((line for line in plan.plan if line.name == name), None)
			if not line or params.get("plan_name", plan.name) != plan.name:
				raise ValueError("Abschlagszeile passt nicht zum Zahlungsplan.")
			_, allocations = _active_allocation_amounts(plan)
			references.append({"doctype": "Zahlungsplan", "name": plan.name,
				"remaining": float(line.betrag) - float(allocations.get(name, 0)), "status": plan.status})
	return references


def _credit_details(params, doc, row, user=None, lock=False):
	from hausverwaltung.hausverwaltung.doctype.kreditvertrag import kreditvertrag as credit

	contract = _read("Kreditvertrag", params["kreditvertrag"], user=user, lock=lock)
	if contract.bank_account != doc.bank_account:
		raise ValueError("Kreditvertrag passt nicht zum Bankkonto.")
	if params.get("from_statement"):
		hints = credit._extract_loan_match_hints(row.verwendungszweck)
		if not credit._loan_hints_are_complete(hints):
			raise ValueError("Tilgung und Zinsen fehlen im Verwendungszweck.")
		contracts = credit._find_kreditvertraege_for_statement(bank_account=doc.bank_account,
			vertragsnummer=hints["vertragsnummer"], supplier=row.party if row.party_type == "Supplier" else None)
		if len(contracts) != 1 or contracts[0].name != contract.name:
			raise ValueError("Der Verwendungszweck bezeichnet keinen eindeutigen Kreditvertrag.")
		interest, principal, rounding = hints["zinsanteil"], hints["tilgungsanteil"], 0
		state = {"statement": hints}
	else:
		line = next((rate for rate in contract.plan if rate.name == params.get("rate_name")), None)
		if not line:
			raise ValueError("Eine konkrete Kreditrate ist erforderlich.")
		interest = line.zinsanteil or 0
		principal = (line.tilgungsanteil or 0) + (line.sondertilgung or 0)
		rounding = line.get("rundungsdifferenz") or 0
		state = {"remaining": float(line.gesamtbetrag), "voucher": line.journal_entry}
	parts = [(contract.zinsaufwandskonto, interest, contract.cost_center),
		(contract.darlehenskonto, principal, contract.cost_center)]
	if rounding:
		account, cost_center = frappe.db.get_value("Company", contract.company, ["round_off_account", "round_off_cost_center"])
		parts.append((account, rounding, cost_center or contract.cost_center))
	return parts, {"doctype": "Kreditvertrag", "name": contract.name, **state}


def authorize(action, payload, permission="read", user=None, lock=False):
	doc = import_document(payload["import_name"], permission, user=user, lock=lock)
	row = row_document(doc, payload["row"])
	params = payload["parameters"]
	party_type, party = _party(action, params, row)
	if params.get("party"):
		if party_type not in {"Customer", "Supplier"}:
			core._deny()
		_read(party_type, party, user=user)
	if params.get("other_bank_account"):
		_read("Bank Account", params["other_bank_account"], user=user)
	if params.get("kreditvertrag"):
		_read("Kreditvertrag", params["kreditvertrag"], user=user)
	return doc, row


def authorize_sources(sources, user=None):
	for source in sources:
		if source.get("doctype"):
			_read(source["doctype"], source["name"], user=user)


def authorize_preview(body, user=None):
	preview = body["preview"]
	authorize_sources(body.get("sources", []), user)
	authorize_sources(preview["before"]["references"], user)
	for posting in preview["postings"]:
		_read("Account", posting["account"], user=user)
		if posting.get("cost_center"):
			_read("Cost Center", posting["cost_center"], user=user)


def can_accept(user=None):
	roles = core.roles_of(user)
	return core.REVIEWER in roles and core.AGENT not in roles and all(
		frappe.has_permission(doctype, right, user=user) for doctype in VOUCHERS for right in ("create", "submit")
	)


def require_reviewer(body):
	core._actor(human=True)
	if not can_accept():
		core._deny()
	_, row = authorize(body["action"], body["payload"], "write")
	if not booking._get_row_bank_transaction_name(row):
		if not all(frappe.has_permission("Bank Transaction", permission) for permission in ("create", "submit")):
			core._deny()


def _postings(bank, parts, amount, incoming, user=None):
	entries = [(bank, amount, None)] + [(account, -_amount(value), center)
		for account, value, center in parts if _amount(value)]
	if len(entries) > 12 or sum(value for _, value, _ in entries):
		raise ValueError("Der Buchungssatz muss ausgeglichen sein.")
	result = []
	for account, value, center in entries:
		if not account:
			raise ValueError("Buchungskonto fehlt.")
		account_doc = _read("Account", account, user=user)
		if center:
			_read("Cost Center", center, user=user)
		signed = value if incoming else -value
		result.append({"account": account, "label": account_doc.account_name or account,
			"debit": max(signed, 0) / 100, "credit": max(-signed, 0) / 100,
			**({"cost_center": center} if center else {})})
	return result


def preview(action, payload, dependencies, package, own_id=None, user=None, lock=False,
		expected_row=None):
	spec = registry.ACTIONS[action]
	doc, row = authorize(action, payload, user=user, lock=lock)
	params = payload["parameters"]
	read_state = _state(row, lock)
	baseline = read_state
	party_type, party = _party(action, params, row)
	modes = []
	if dependencies:
		if spec.kind == "party" or len(dependencies) != 1:
			raise ValueError("Nur eine Parteizuordnung kann einer Buchung vorausgehen.")
		ref = domain.binding(dependencies[0])
		parent, previous = core._exact(ref)
		if (parent.name == own_id or parent.package != package or parent.action != PARTY_ACTION
			or parent.target != row.name or previous["payload"]["import_name"] != doc.name
			or parent.status not in {"Pending", "Approved", "Succeeded"}):
			raise ValueError("Vorgänger muss die Partei derselben Importzeile zuordnen.")
		parent_params = previous["payload"]["parameters"]
		if parent.status == "Succeeded":
			saved = frappe.parse_json(parent.result)
			if saved["state"] != read_state:
				raise ValueError("Parteizuordnung hat sich geändert.")
			baseline = previous["preview"]["before"]["row"]
		bound_party = parent_params["party_type"], parent_params["party"]
		if spec.kind == "payment" and params.get("party") and (party_type, party) != bound_party:
			raise ValueError("Die Partei der Vorauszahlung weicht von der gebundenen Parteizuordnung ab.")
		party_type, party = bound_party
		modes.append(ref | {"mode": "real" if parent.status == "Succeeded" else "projected"})
	if expected_row is not None and baseline != expected_row:
		raise ValueError("Die Importzeile hat sich geändert.")
	if payload["fingerprint"] != read_state["fingerprint"] or read_state["voucher"] or read_state["customer_payments"] or read_state["transaction_vouchers"]:
		raise ValueError("Die Importzeile hat sich geändert oder wurde bereits gebucht.")
	if party and spec.kind not in {"journal", "transfer", "kredit"}:
		if party_type not in {"Customer", "Supplier"}:
			raise ValueError("Nur Customer und Supplier werden unterstützt.")
		_read(party_type, party, user=user)
	if spec.kind == "party":
		contracts = frappe.get_all("Mietvertrag", filters={"kunde": party}, pluck="name", limit_page_length=2)
		if len(contracts) != 1:
			raise ValueError("Der Customer muss genau einem Mietvertrag zugeordnet sein.")
		contract = _read("Mietvertrag", contracts[0], user=user, lock=lock)
		if not contract.wohnung:
			raise ValueError("Der Mietvertrag hat keine Wohnung.")
		references = [{"doctype": "Mietvertrag", "name": contract.name, "unit": contract.wohnung}]
		postings = []
	else:
		from erpnext.accounts.party import get_party_account

		bank = _read("Bank Account", doc.bank_account, user=user)
		amount = _amount(row.betrag)
		references = _references(action, params, party_type, user, lock)
		if spec.kind == "journal":
			parts = [(item["account"], item["amount"], item.get("cost_center"))
				for item in params.get("splits", [{"account": params.get("account"), "amount": row.betrag,
					"cost_center": params.get("cost_center")}])]
		elif spec.kind == "transfer":
			other = _read("Bank Account", params["other_bank_account"], user=user)
			parts = [(other.account, row.betrag, None)]
		elif spec.kind == "kredit":
			parts, credit_state = _credit_details(params, doc, row, user, lock)
			references.append(credit_state)
		else:
			if not party:
				raise ValueError("Für die Buchung muss eine Partei zugeordnet sein.")
			parts = [(get_party_account(party_type, party, bank.company), row.betrag, None)]
		postings = _postings(bank.account, parts, amount, row.richtung == "Eingang", user)
	before = {"row": baseline, "references": references}
	after = {"party_type": party_type, "party": party} if spec.kind == "party" else {"booked": True}
	changes = [{"field": "party", "label": "Partei", "before": baseline["party"], "after": party, "kind": "value"}] if spec.kind == "party" else [
		{"field": "booking", "label": "Bankzeile", "before": "Offen", "after": "Gebucht", "kind": "value"}]
	return {"before": before, "after": after, "postings": postings, "changes": changes, "effects": [f"bankimport_{spec.kind}"],
		"dependencies": modes, "projection_version": action, "limits": []}


def fresh(doc, body):
	try:
		current = preview(doc.action, body["payload"], body["dependencies"], doc.package, doc.name,
			lock=core._writing.get(), expected_row=body["preview"]["before"]["row"])
	except frappe.DoesNotExistError as exc:
		raise ValueError("Buchungsgrundlage fehlt.") from exc
	for key in ("before", "after", "postings", "projection_version"):
		if current[key] != body["preview"][key]:
			raise ValueError("Buchungsgrundlage hat sich geändert.")
	return current


def _journal_postings(voucher):
	return sorted((line.account, _amount(line.debit_in_account_currency or 0), _amount(line.credit_in_account_currency or 0))
		for line in voucher.accounts)


def _preview_postings(body):
	return sorted((line["account"], _amount(line["debit"]), _amount(line["credit"]))
		for line in body["preview"]["postings"])


def execute_approved(doc, body):
	require_reviewer(body)
	if doc.status == "Succeeded":
		core._event(doc, "ResultReused")
		return core._response(doc, body)
	checked = core._checked(doc, body)
	if checked["status"] == "Stale":
		return checked
	if doc.status != "Approved":
		frappe.throw("Eine gebundene Freigabe ist erforderlich.")
	approver = frappe.db.get_value("User", doc.decision_by, ["enabled", "user_type"], as_dict=True)
	if not approver or not approver.enabled or approver.user_type != "System User" or not can_accept(doc.decision_by):
		core._deny()
	authorize(doc.action, body["payload"], "write", user=doc.decision_by)
	core._read_graph(body, doc.decision_by)
	if any(dep["mode"] != "real" for dep in fresh(doc, body)["dependencies"]):
		frappe.throw("Zuerst die gebundene Parteizuordnung ausführen.")

	action, payload = doc.action, body["payload"]
	import_name, row_name = payload["import_name"], payload["row"]
	params = payload["parameters"].copy()
	method = registry.ACTIONS[action].method
	if action == PARTY_ACTION:
		params["only_row"] = 1
	if params.pop("from_statement", False):
		params["expected_contract"] = params.pop("kreditvertrag")
		params.pop("rate_name", None)
		method = "book_kreditrate_from_statement_for_row"
	for key in {"invoice_names", "invoice_allocations", "abschlag_rows"} & params.keys():
		params[key] = domain.encode(params[key])
	savepoint = f"hv_bank_step_{uuid4().hex}"
	frappe.db.savepoint(savepoint)
	messages = list(frappe.local.message_log)
	token = _executing_row.set(row_name)
	try:
		result = getattr(booking, method)(import_name, row_name, **params)
		if not result or result.get("ok") is False or result.get("errors"):
			raise ValueError("Die Aktion konnte nicht ausgeführt werden.")
		if action == PARTY_ACTION:
			result = booking.create_bank_transaction_for_row(import_name, row_name, skip_auto_match=1)
			if result.get("errors"):
				raise ValueError("Die Banktransaktion konnte nicht angelegt werden.")
		row = row_document(import_document(import_name, lock=True), row_name)
		state = _state(row, lock=True)
		if action == PARTY_ACTION:
			expected_party = [params["party_type"], params["party"]]
			if (not state["transaction"] or [state["party_type"], state["party"]] != expected_party
				or state["transaction_party"] != expected_party):
				raise ValueError("Parteizuordnung entspricht nicht dem Vorschlag.")
			doctype, name = "Bank Transaction", state["transaction"]
		else:
			if not state["voucher"]:
				raise ValueError("Die Buchung wurde nicht ausgeführt.")
			doctype, name = state["voucher"]
			voucher = frappe.get_doc(doctype, name, for_update=True)
			if registry.ACTIONS[action].kind == "kredit":
				if (result.get("kreditvertrag") != payload["parameters"]["kreditvertrag"]
					or doctype != "Journal Entry" or _journal_postings(voucher) != _preview_postings(body)):
					raise ValueError("Kreditbuchung entspricht nicht der freigegebenen Vorschau.")
			if not all(frappe.has_permission(doctype, right, doc=voucher, user=user)
				for right in ("create", "submit") for user in {frappe.session.user, doc.decision_by}):
				core._deny()
		result = {"doctype": doctype, "name": name, "id": name, "by": frappe.session.user, "at": str(now_datetime())}
		core._succeed(doc, result | {"state": state}, audit_result=result)
	except (frappe.QueryDeadlockError, core.ConcurrentRevisionRetry):
		raise
	except (frappe.ValidationError, frappe.PermissionError, frappe.DoesNotExistError, ValueError):
		frappe.db.rollback(save_point=savepoint)
		frappe.local.message_log = messages
		doc.reload()
		error = "Buchung fehlgeschlagen. Bitte Ausgangslage prüfen oder über „Anpassen“ buchen."
		core._event(doc, "ExecutionFailed", {"error": error, "surface": "bankimport"})
		return core._response(doc, body) | {"error": error}
	finally:
		_executing_row.reset(token)
	return core._response(doc, body)


def revise(doc, old, payload, dependencies, meta):
	from . import bank_packages

	return bank_packages.revise(doc, old, payload, dependencies, meta)
