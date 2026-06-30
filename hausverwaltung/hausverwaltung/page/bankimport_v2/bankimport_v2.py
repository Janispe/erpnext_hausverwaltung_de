# Bankimport v2 — Page-Controller + dünne Adapter-Endpunkte.
#
# Die React-UI (iframe, public/bankimport_v2) ruft fast alle Aktionen direkt
# gegen die bestehende, erprobte API in
#   hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import
# auf (gemappt über die RPC-Allowlist in bankimport_v2.js). Hier leben nur die
# wenigen Helfer, die es dort noch nicht gibt:
#
#   - get_overview()    Doc + Zeilen in die UI-Shape (rows/importMeta/phaseCounts)
#   - list_imports()    Import-Auswahl, wenn die Page ohne ?import= geöffnet wird
#   - search_parties()  Autocomplete für die Phase-1-Zuordnung
#   - search_accounts()  Konto-Autocomplete für den Journal-Entry (Wrapper auf
#                        buchen_cockpit.autocomplete_konten)
#
# Es wird KEINE Buchungslogik dupliziert — nur gelesen und gemappt.

from __future__ import annotations

import base64
import binascii
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils.file_manager import save_file

from hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import import (
	SKIPPED_ROW_STATUSES,
	_cancel_voucher_for_row,
	_linked_voucher_for_row,
	_recompute_doc_status,
	_refresh_saldo_fields,
	_persist_saldo_fields,
	parse_csv,
	sync_cancelled_journal_entry_links,
	sync_cancelled_payment_entry_links,
)
from hausverwaltung.hausverwaltung.utils.bankimport_rules import (
	BOOKING_RULE_DOCTYPE,
	PARTY_RULE_DOCTYPE,
	RULE_SCOPE_DOCTYPE,
	ensure_default_bankimport_rules,
	normalize_iban,
)


def get_context(context):
	"""Page-Bootstrap. Das React-UI rendert clientseitig und holt Daten via RPC."""
	return context


# ───────────────────────────────────────────── Zeilen-Phase / Status-Mapping ──

# Spiegelt das Phasen-Modell aus bankauszug_import._recompute_doc_status:
# Sobald eine Bank Transaction existiert, kann die Zeile gebucht werden, auch
# wenn sie keine Party hat (z.B. Bankgebühren als Journal Entry).
def _row_phase(row: dict) -> int:
	rs = (row.get("row_status") or "").lower()
	if row.get("error") or rs == "failed":
		return 3
	if rs in {"schon vorhanden", "vor start-datum"}:
		return 4
	if row.get("payment_entry") or row.get("journal_entry"):
		return 4
	if row.get("bank_transaction"):
		return 3
	if not (row.get("party_type") and row.get("party")):
		return 1
	return 2


def _row_status(row: dict, phase: int) -> str:
	rs = (row.get("row_status") or "").lower()
	if row.get("error") or rs == "failed":
		return "error"
	if rs == "schon vorhanden":
		return "existing"
	if rs == "vor start-datum":
		return "skipped"
	if phase == 4:
		return "done"
	if phase == 2:
		return "phase2-no-bt"
	if phase == 1:
		return "phase1-no-party"
	# Phase 3: Bank-Tx da, aber kein Beleg — row_status-Feld überlagert nur die
	# Sonderfälle (Auto-Match-Misserfolg).
	if rs == "needs_review":
		return "needs_review"
	return "phase3-open"


def _bank_account_iban(bank_account: str | None) -> str | None:
	if not bank_account:
		return None
	try:
		if frappe.get_meta("Bank Account").has_field("iban"):
			return frappe.db.get_value("Bank Account", bank_account, "iban")
	except Exception:
		pass
	return None


def _doc_audit(doctype: str | None, name: str | None) -> dict[str, Any] | None:
	"""Liefert Standard-Metadaten eines verlinkten Dokuments für die UI.

	Die Bankimport-Übersicht soll nie an fehlenden/stornierten Links scheitern;
	darum gibt der Helper bei fehlenden Rechten/Docs still ``None`` zurück.
	"""
	if not doctype or not name:
		return None
	try:
		values = frappe.db.get_value(
			doctype,
			name,
			["owner", "creation", "modified_by", "modified"],
			as_dict=True,
		)
	except Exception:
		return None
	if not values:
		return None
	return {
		"doctype": doctype,
		"name": name,
		"createdBy": values.get("owner"),
		"createdAt": str(values.get("creation")) if values.get("creation") else None,
		"modifiedBy": values.get("modified_by"),
		"modifiedAt": str(values.get("modified")) if values.get("modified") else None,
	}


def _row_audit(row) -> dict[str, Any]:
	payment_document_type = row.payment_document_type
	payment_document = row.payment_document
	if not payment_document and row.payment_entry:
		payment_document_type = "Payment Entry"
		payment_document = row.payment_entry
	elif not payment_document and row.journal_entry:
		payment_document_type = "Journal Entry"
		payment_document = row.journal_entry

	message = row.auto_match_message or ""
	message_lc = message.lower()
	if "auto" in message_lc or "automatisch" in message_lc:
		assignment_source = "Automatisch"
	elif (
		"manuell" in message_lc
		or message_lc.startswith("buchungssatz:")
		or message_lc.startswith("abschlag zugeordnet")
	):
		assignment_source = "Manuell"
	else:
		assignment_source = None

	return {
		"row": {
			"createdBy": getattr(row, "owner", None),
			"createdAt": str(getattr(row, "creation", None)) if getattr(row, "creation", None) else None,
			"modifiedBy": getattr(row, "modified_by", None),
			"modifiedAt": str(getattr(row, "modified", None)) if getattr(row, "modified", None) else None,
		},
		"assignment": {
			"source": assignment_source,
			"by": getattr(row, "modified_by", None),
			"at": str(getattr(row, "modified", None)) if getattr(row, "modified", None) else None,
			"message": message or None,
		},
		"party": _doc_audit(row.party_type, row.party),
		"bankTransaction": _doc_audit("Bank Transaction", row.bank_transaction),
		"paymentDocument": _doc_audit(payment_document_type, payment_document),
	}


def _suggest_invoice_for_row(bt_name: str) -> dict[str, Any] | None:
	"""Dry-Run: schlägt für eine Phase-3-Zeile eine offene Rechnung vor, wenn
	exakt EINE Rechnung der Party den Bank-Betrag trifft.

	Im Gegensatz zu ``auto_match_bank_transaction`` Strategy 1 — die beim
	ersten Treffer bucht — gibt der Suggester bei mehreren gleichbetraglichen
	Rechnungen bewusst ``None`` zurück. Eine UI-Empfehlung soll eindeutig
	sein; bei Ambiguität wählt der User die richtige selber im Rechnungs-Tab.

	Die Strategien 2/3 (Monats-/Alle-Summe) erzeugen ohnehin Sets, die nicht
	in eine Single-ID-Empfehlung passen.

	Returns ``{ "rechnungId": "...", "reason": "..." }`` oder ``None``.
	"""
	from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
		_TOLERANCE,
		prepare_invoice_match,
	)

	try:
		bt = frappe.get_doc("Bank Transaction", bt_name)
	except frappe.DoesNotExistError:
		return None
	prep = prepare_invoice_match(bt)
	if not prep["ok"]:
		return None

	target = prep["target_amount"]
	exact = [
		inv for inv in prep["candidates"]
		if abs(flt(inv.outstanding_amount) - target) < _TOLERANCE
	]
	if len(exact) != 1:
		return None
	return {
		"rechnungId": exact[0].name,
		"reason": "Offener Beleg dieser Höhe gefunden",
	}


@frappe.whitelist()
def get_overview(import_name: str) -> dict[str, Any]:
	"""Komplette Übersicht für die Bankimport-UI: importMeta + Zeilen + Phase-Counts."""
	doc = frappe.get_doc("Bankauszug Import", import_name)
	frappe.has_permission("Bankauszug Import", "read", doc=doc, throw=True)

	# Status + Saldo frisch halten (sonst stale nach nachträglichen Buchungen).
	try:
		sync_cancelled_payment_entry_links(import_name=doc.name)
		sync_cancelled_journal_entry_links(import_name=doc.name)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"Bankimport v2: Storno-Sync fehlgeschlagen ({doc.name})",
		)
		frappe.clear_last_message()

	try:
		_recompute_doc_status(doc.name)
		_refresh_saldo_fields(doc)
		_persist_saldo_fields(doc)
		doc.reload()
	except Exception:
		frappe.clear_last_message()

	rows_out: list[dict] = []
	counts = {1: 0, 2: 0, 3: 0, 4: 0}
	for row in doc.rows:
		rd = row.as_dict()
		phase = _row_phase(rd)
		counts[phase] += 1
		# betrag ist im Child-Row immer positiv gespeichert; das Vorzeichen steckt
		# in `richtung`. Die UI leitet Ein-/Ausgang aus dem Vorzeichen ab, daher
		# hier signed ausliefern (Ausgang negativ).
		betrag = flt(row.betrag)
		if row.richtung == "Ausgang":
			betrag = -abs(betrag)
		elif row.richtung == "Eingang":
			betrag = abs(betrag)
		# Rechnungs-Empfehlung (Dry-Run) nur für Phase-3-Zeilen mit Party und BT.
		# Strikt opportunistisch: jede Exception schluckt das Feld zu ``None``,
		# damit der Overview-Endpoint nie wegen eines Suggester-Fehlers wackelt.
		auto_match = None
		if phase == 3 and row.party and row.bank_transaction:
			try:
				auto_match = _suggest_invoice_for_row(row.bank_transaction)
			except Exception:
				auto_match = None

		rows_out.append(
			{
				"id": row.name,
				"buchungstag": str(row.buchungstag) if row.buchungstag else None,
				"betrag": betrag,
				"richtung": row.richtung,
				"iban": row.iban,
				"auftraggeber": row.auftraggeber,
				"verwendungszweck": row.verwendungszweck,
				"error": row.error,
				"partyTyp": row.party_type,
				"party": row.party,
				"bankTransaction": row.bank_transaction,
				"paymentEntry": row.payment_entry,
				"journalEntry": row.journal_entry,
				"paymentDocument": row.payment_document,
				"paymentDocumentType": row.payment_document_type,
				"rowStatus": _row_status(rd, phase),
				"phase": phase,
				"autoMatchMessage": row.auto_match_message,
				"autoMatch": auto_match,
				"audit": _row_audit(row),
			}
		)

	return {
		"import": {
			"name": doc.name,
			"title": doc.title,
			"bankAccount": doc._bank_account_label(),
			"bankAccountName": doc.bank_account,
			"iban": _bank_account_iban(doc.bank_account),
			"csvFile": doc.csv_file,
			"saldoLautBank": flt(doc.get("saldo_laut_csv")),
			"saldoLautERP": flt(doc.get("saldo_laut_erp")),
			"saldoDifferenz": flt(doc.get("saldo_differenz")),
			"saldoStichtag": str(doc.get("saldo_datum")) if doc.get("saldo_datum") else None,
			"status": doc.status,
			"offeneBuchungen": doc.get("offene_buchungen"),
		},
		"rows": rows_out,
		"phaseCounts": counts,
	}


@frappe.whitelist()
def list_imports(limit: int = 30) -> dict[str, Any]:
	"""Verfügbare Bankauszug-Importe für den Picker (wenn ?import= fehlt)."""
	items = frappe.get_list(
		"Bankauszug Import",
		fields=["name", "title", "status", "offene_buchungen", "modified"],
		order_by="modified desc",
		limit=limit,
	)
	row_counts = {
		r.parent: r.total_rows
		for r in frappe.get_all(
			"Bankauszug Import Row",
			filters={"parent": ["in", [it.name for it in items] or [""]]},
			fields=["parent", {"COUNT": "name", "as": "total_rows"}],
			group_by="parent",
		)
	}
	for it in items:
		it["modified"] = str(it["modified"]) if it.get("modified") else None
		it["total_rows"] = row_counts.get(it.name, 0)
	return {"items": items}


@frappe.whitelist()
def list_bank_accounts(txt: str = "") -> dict[str, Any]:
	"""Firmen-Bankkonten für den Neu-Import-Dialog."""
	txt = (txt or "").strip()
	meta = frappe.get_meta("Bank Account")
	fields = ["name", "bank", "account"]
	if meta.has_field("iban"):
		fields.append("iban")

	filters: dict[str, Any] = {"is_company_account": 1}
	if meta.has_field("disabled"):
		filters["disabled"] = 0
	or_filters = None
	if txt:
		or_filters = [["name", "like", f"%{txt}%"], ["bank", "like", f"%{txt}%"]]

	rows = frappe.get_list(
		"Bank Account",
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		order_by="name asc",
		limit=80,
	)

	items = []
	for row in rows:
		if row.get("account") and frappe.db.get_value("Account", row.account, "disabled"):
			continue
		account_number = None
		if row.get("account"):
			account_number = frappe.db.get_value("Account", row.account, "account_number")
		short = (row.name or "").split(" - ", 1)[0].strip() or row.name
		label = f"{short} ({account_number})" if account_number else short
		description = row.get("iban") or row.get("bank") or row.get("account")
		items.append(
			{
				"value": row.name,
				"label": label,
				"description": description,
			}
		)

	return {"items": items}


RULE_CONFIG = {
	PARTY_RULE_DOCTYPE: {
		"group": "party",
		"label": "Party Matching",
		"fields": [
			"name",
			"rule_key",
			"enabled",
			"is_system_rule",
			"priority",
			"matcher_function",
			"stop_on_match",
			"requires_review",
			"parameters_json",
			"description",
			"modified",
		],
	},
	BOOKING_RULE_DOCTYPE: {
		"group": "booking",
		"label": "Buchungs-Matching",
		"fields": [
			"name",
			"rule_key",
			"enabled",
			"is_system_rule",
			"priority",
			"matcher_function",
			"auto_apply",
			"stop_on_match",
			"requires_review",
			"parameters_json",
			"description",
			"modified",
		],
	},
}


@frappe.whitelist()
def list_bankimport_rules() -> dict[str, Any]:
	"""Rule-Übersicht für die Bankimport-UI."""
	ensure_default_bankimport_rules()
	groups = {}
	for doctype, config in RULE_CONFIG.items():
		frappe.has_permission(doctype, "read", throw=True)
		rows = frappe.get_all(
			doctype,
			fields=config["fields"],
			order_by="priority asc, creation asc",
			limit=0,
		)
		scope_by_parent = _rule_scope_by_parent(doctype, [row.name for row in rows])
		items = [
			_format_rule_row(doctype, row, scope_by_parent.get(row.name, []))
			for row in rows
		]
		groups[config["group"]] = {
			"doctype": doctype,
			"label": config["label"],
			"items": items,
			"counts": {
				"total": len(items),
				"enabled": sum(1 for item in items if item["enabled"]),
				"disabled": sum(1 for item in items if not item["enabled"]),
				"system": sum(1 for item in items if item["isSystemRule"]),
			},
		}
	return {"groups": groups}


@frappe.whitelist()
def set_bankimport_rule_enabled(doctype: str, name: str, enabled: int) -> dict[str, Any]:
	"""Aktiv/Inaktiv-Schalter aus dem Regelpanel."""
	if doctype not in RULE_CONFIG:
		frappe.throw(_("Unbekannter Regeltyp."))
	if not name:
		frappe.throw(_("Bitte eine Regel auswählen."))
	frappe.has_permission(doctype, "write", throw=True)
	if not frappe.db.exists(doctype, name):
		frappe.throw(_("Regel {0} wurde nicht gefunden.").format(name))
	value = 1 if bool(int(enabled or 0)) else 0
	frappe.db.set_value(doctype, name, "enabled", value)
	return {"ok": True, "doctype": doctype, "name": name, "enabled": value}


def _rule_scope_by_parent(doctype: str, names: list[str]) -> dict[str, list[dict[str, Any]]]:
	if not names:
		return {}
	rows = frappe.get_all(
		RULE_SCOPE_DOCTYPE,
		filters={
			"parenttype": doctype,
			"parent": ["in", names],
			"enabled": 1,
		},
		fields=["parent", "mode", "scope_type", "iban", "party_type", "party", "description"],
		order_by="parent asc, idx asc",
		limit=0,
	)
	out: dict[str, list[dict[str, Any]]] = {}
	for row in rows:
		out.setdefault(row.parent, []).append(_format_rule_scope(row))
	return out


def _format_rule_row(doctype: str, row, scope_rows: list[dict[str, Any]]) -> dict[str, Any]:
	modified = row.get("modified")
	return {
		"doctype": doctype,
		"name": row.name,
		"ruleKey": row.get("rule_key"),
		"enabled": bool(row.get("enabled")),
		"isSystemRule": bool(row.get("is_system_rule")),
		"priority": row.get("priority"),
		"matcherFunction": row.get("matcher_function"),
		"autoApply": bool(row.get("auto_apply")) if doctype == BOOKING_RULE_DOCTYPE else None,
		"stopOnMatch": bool(row.get("stop_on_match")),
		"requiresReview": bool(row.get("requires_review")),
		"parametersJson": row.get("parameters_json") or "",
		"description": row.get("description") or "",
		"scope": scope_rows,
		"scopeCount": len(scope_rows),
		"modified": str(modified) if modified else None,
	}


def _format_rule_scope(row) -> dict[str, Any]:
	return {
		"mode": row.get("mode"),
		"scopeType": row.get("scope_type"),
		"iban": normalize_iban(row.get("iban")),
		"partyType": row.get("party_type"),
		"party": row.get("party"),
		"description": row.get("description") or "",
	}


@frappe.whitelist()
def create_import(bank_account: str, filename: str, file_data: str) -> dict[str, Any]:
	"""Legt einen Bankauszug-Import aus dem React-Dialog an und parst die CSV."""
	frappe.has_permission("Bankauszug Import", "create", throw=True)
	if not bank_account:
		frappe.throw(_("Bitte ein Bankkonto auswählen."))
	if not filename:
		filename = "bankauszug.csv"
	if not file_data:
		frappe.throw(_("Bitte eine CSV-Datei auswählen."))

	if not frappe.db.exists("Bank Account", bank_account):
		frappe.throw(_("Bankkonto {0} wurde nicht gefunden.").format(bank_account))
	bank_account_doc = frappe.get_doc("Bank Account", bank_account)
	frappe.has_permission("Bank Account", "read", doc=bank_account_doc, throw=True)
	if bank_account_doc.get("is_company_account") != 1:
		frappe.throw(_("Bitte ein Firmen-Bankkonto auswählen."))
	if frappe.get_meta("Bank Account").has_field("disabled") and bank_account_doc.get("disabled"):
		frappe.throw(_("Bitte ein aktives Bankkonto auswählen."))
	if bank_account_doc.get("account") and frappe.db.get_value("Account", bank_account_doc.account, "disabled"):
		frappe.throw(_("Das verknüpfte Sachkonto ist deaktiviert. Bitte ein aktives Bankkonto auswählen."))

	raw_data = file_data.split(",", 1)[1] if "," in file_data and file_data.startswith("data:") else file_data
	try:
		content = base64.b64decode(raw_data, validate=True)
	except (binascii.Error, ValueError):
		frappe.throw(_("Die CSV-Datei konnte nicht gelesen werden."))
	if not content:
		frappe.throw(_("Die CSV-Datei ist leer."))
	if len(content) > 10 * 1024 * 1024:
		frappe.throw(_("Die CSV-Datei ist zu groß. Maximal erlaubt sind 10 MB."))

	file_doc = save_file(filename, content, "", "", is_private=1)
	doc = frappe.get_doc(
		{
			"doctype": "Bankauszug Import",
			"bank_account": bank_account,
			"csv_file": file_doc.file_url,
			"delimiter": ";",
			"encoding": "auto",
		}
	)
	doc.insert()

	file_doc.db_set("attached_to_doctype", "Bankauszug Import")
	file_doc.db_set("attached_to_name", doc.name)
	if frappe.get_meta("File").has_field("attached_to_field"):
		file_doc.db_set("attached_to_field", "csv_file")

	parse_result = parse_csv(doc.name)
	doc.reload()

	return {
		"name": doc.name,
		"title": doc.title,
		"parse": parse_result,
	}


@frappe.whitelist()
def get_delete_impact(import_name: str) -> dict[str, Any]:
	"""Ermittelt vor dem Löschen, welche Folgebelege zurückgenommen würden."""
	if not import_name:
		frappe.throw(_("Bitte einen Bankimport auswählen."))
	doc = frappe.get_doc("Bankauszug Import", import_name)
	frappe.has_permission("Bankauszug Import", "delete", doc=doc, throw=True)
	return _delete_impact_for_doc(doc)


def _status_key(value: Any) -> str:
	return str(value or "").strip().lower()


def _row_value(row: Any, fieldname: str, default: Any = None) -> Any:
	if hasattr(row, "get"):
		return row.get(fieldname, default)
	return getattr(row, fieldname, default)


def _docstatus(doctype: str, name: str) -> int | None:
	value = frappe.db.get_value(doctype, name, "docstatus")
	if value is None:
		return None
	try:
		return int(value)
	except Exception:
		return value


def _docstatus_label(docstatus: int | None) -> str:
	if docstatus is None:
		return "missing"
	if docstatus == 0:
		return "draft"
	if docstatus == 1:
		return "submitted"
	if docstatus == 2:
		return "cancelled"
	return str(docstatus)


def _import_owns_bank_transaction(row: Any) -> bool:
	"""Nur Bank-Transactions zurücknehmen, die dieser Import erzeugt hat."""
	if not (_row_value(row, "bank_transaction") or _row_value(row, "reference")):
		return False
	return _status_key(_row_value(row, "row_status")) not in SKIPPED_ROW_STATUSES


def _delete_impact_for_doc(doc) -> dict[str, Any]:
	vouchers: dict[tuple[str, str], dict[str, Any]] = {}
	bank_transactions_to_reverse: dict[str, dict[str, Any]] = {}
	bank_transactions_kept: dict[str, dict[str, Any]] = {}

	for row in doc.get("rows") or []:
		row_name = _row_value(row, "name")
		voucher_type, voucher_name = _linked_voucher_for_row(row)
		if voucher_type and voucher_name:
			key = (voucher_type, voucher_name)
			if key not in vouchers:
				status = _docstatus(voucher_type, voucher_name)
				vouchers[key] = {
					"type": voucher_type,
					"name": voucher_name,
					"docstatus": status,
					"status": _docstatus_label(status),
					"rows": [],
				}
			vouchers[key]["rows"].append(row_name)

		bt_name = _row_value(row, "bank_transaction") or _row_value(row, "reference")
		if not bt_name:
			continue
		target = bank_transactions_to_reverse if _import_owns_bank_transaction(row) else bank_transactions_kept
		if bt_name not in target:
			status = _docstatus("Bank Transaction", bt_name)
			target[bt_name] = {
				"name": bt_name,
				"docstatus": status,
				"status": _docstatus_label(status),
				"rows": [],
				"reason": "import-owned" if target is bank_transactions_to_reverse else "already-existing",
			}
		target[bt_name]["rows"].append(row_name)

	impact = {
		"import": doc.name,
		"title": doc.get("title"),
		"rows": len(doc.get("rows") or []),
		"vouchers": list(vouchers.values()),
		"bankTransactionsToReverse": list(bank_transactions_to_reverse.values()),
		"bankTransactionsKept": list(bank_transactions_kept.values()),
	}
	impact["counts"] = {
		"vouchers": len(impact["vouchers"]),
		"paymentEntries": sum(1 for item in impact["vouchers"] if item["type"] == "Payment Entry"),
		"journalEntries": sum(1 for item in impact["vouchers"] if item["type"] == "Journal Entry"),
		"bankTransactionsToReverse": len(impact["bankTransactionsToReverse"]),
		"bankTransactionsKept": len(impact["bankTransactionsKept"]),
	}
	impact["requiresCascade"] = bool(impact["vouchers"] or impact["bankTransactionsToReverse"])
	return impact


def _cleanup_bank_transaction_for_import_delete(bank_transaction: str) -> dict[str, Any]:
	docstatus = _docstatus("Bank Transaction", bank_transaction)
	if docstatus is None:
		return {"bank_transaction": bank_transaction, "status": "missing"}

	bt = frappe.get_doc("Bank Transaction", bank_transaction)
	if docstatus == 2:
		return {"bank_transaction": bank_transaction, "status": "already_cancelled"}
	if docstatus == 1:
		if not getattr(bt, "flags", None):
			bt.flags = frappe._dict()
		bt.flags.ignore_permissions = True
		bt.cancel()
		return {"bank_transaction": bank_transaction, "status": "cancelled"}

	bt.delete(ignore_permissions=True)
	return {"bank_transaction": bank_transaction, "status": "deleted_draft"}


def _cascade_delete_import(doc, impact: dict[str, Any]) -> dict[str, Any]:
	from hausverwaltung.hausverwaltung.utils.bank_transaction_links import (
		remove_bank_transaction_payment_links,
	)

	savepoint = "bankimport_delete_cascade"
	frappe.db.savepoint(savepoint)
	try:
		voucher_results = []
		for voucher in impact["vouchers"]:
			cancel = _cancel_voucher_for_row(voucher["type"], voucher["name"])
			delinked = remove_bank_transaction_payment_links(voucher["type"], voucher["name"])
			voucher_results.append({**voucher, "cancel": cancel, "delinkedBankTransactions": delinked})

		bank_transaction_results = [
			_cleanup_bank_transaction_for_import_delete(item["name"])
			for item in impact["bankTransactionsToReverse"]
		]

		frappe.delete_doc("Bankauszug Import", doc.name)
	except Exception:
		frappe.db.rollback(save_point=savepoint)
		raise

	return {
		"vouchers": voucher_results,
		"bankTransactions": bank_transaction_results,
		"keptBankTransactions": impact["bankTransactionsKept"],
	}


@frappe.whitelist()
def delete_import(import_name: str, cascade: int = 0) -> dict[str, Any]:
	"""Löscht einen Bankauszug-Import und nimmt import-eigene Folgebelege zurück."""
	if not import_name:
		frappe.throw(_("Bitte einen Bankimport auswählen."))
	doc = frappe.get_doc("Bankauszug Import", import_name)
	frappe.has_permission("Bankauszug Import", "delete", doc=doc, throw=True)
	impact = _delete_impact_for_doc(doc)

	if impact["requiresCascade"] and not bool(int(cascade or 0)):
		frappe.throw(
			_("Dieser Import enthält Bank-Transaktionen oder Zahlungsbelege. Bitte Löschfolgen bestätigen.")
		)

	cleanup = _cascade_delete_import(doc, impact) if impact["requiresCascade"] else {}
	if not impact["requiresCascade"]:
		frappe.delete_doc("Bankauszug Import", import_name)

	return {"ok": True, "name": import_name, "impact": impact, "cleanup": cleanup}


@frappe.whitelist()
def search_parties(party_type: str, txt: str = "") -> dict[str, Any]:
	"""Autocomplete für Customer/Supplier/Eigentuemer (Phase-1-Zuordnung)."""
	title_fields = {
		"Customer": "customer_name",
		"Supplier": "supplier_name",
		"Eigentuemer": "eigentuemer_name",
	}
	if party_type not in title_fields:
		frappe.throw(_("Party-Typ muss Customer, Supplier oder Eigentuemer sein."))

	title_field = title_fields[party_type]
	txt = (txt or "").strip()
	or_filters = None
	if txt:
		or_filters = [["name", "like", f"%{txt}%"], [title_field, "like", f"%{txt}%"]]

	rows = frappe.get_list(
		party_type,
		or_filters=or_filters,
		fields=["name", f"{title_field} as title"],
		order_by="modified desc",
		limit=20,
	)
	items = [
		{
			"value": r["name"],
			"label": r.get("title") or r["name"],
			"description": r["name"] if r.get("title") and r["title"] != r["name"] else None,
		}
		for r in rows
	]
	return {"items": items}


@frappe.whitelist()
def search_accounts(txt: str = "") -> dict[str, Any]:
	"""Konto-Autocomplete für den Journal-Entry.

	Die Cockpit-Logik liefert nur Kostenarten-Konten. Für freie Bankimport-
	Buchungssätze müssen zusätzlich alle aktiven Blattkonten auffindbar sein.
	"""
	from hausverwaltung.hausverwaltung.page.buchen_cockpit.buchen_cockpit import (
		autocomplete_konten,
	)

	txt = (txt or "").strip()
	items_by_value: dict[str, dict[str, Any]] = {}

	for item in autocomplete_konten(txt=txt, typ="alle") or []:
		if item.get("value"):
			items_by_value[item["value"]] = item

	like = f"%{txt}%"
	conditions = ["is_group = 0", "ifnull(disabled, 0) = 0"]
	values: list[Any] = []
	if txt:
		conditions.append("(name LIKE %s OR account_name LIKE %s OR account_number LIKE %s)")
		values.extend([like, like, like])

	accounts = frappe.db.sql(
		f"""
		SELECT name, account_number, account_name, root_type, report_type
		FROM `tabAccount`
		WHERE {" AND ".join(conditions)}
		ORDER BY ifnull(account_number, ''), name
		LIMIT 80
		""",
		values,
		as_dict=True,
	) or []

	for account in accounts:
		name = account.get("name")
		if not name or name in items_by_value:
			continue
		account_number = account.get("account_number")
		account_name = account.get("account_name")
		label = f"{account_number} {account_name}" if account_number and account_name else name
		parts = [p for p in (account.get("root_type"), account.get("report_type")) if p]
		items_by_value[name] = {
			"value": name,
			"label": label,
			"description": " / ".join(parts) if parts else None,
		}

	return {"items": list(items_by_value.values())[:80]}
