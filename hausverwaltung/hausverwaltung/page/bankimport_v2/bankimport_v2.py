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

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt

from hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import import (
	_recompute_doc_status,
	_refresh_saldo_fields,
	_persist_saldo_fields,
	sync_cancelled_payment_entry_links,
)


def get_context(context):
	"""Page-Bootstrap. Das React-UI rendert clientseitig und holt Daten via RPC."""
	return context


# ───────────────────────────────────────────── Zeilen-Phase / Status-Mapping ──

# Spiegelt das Phasen-Modell aus bankauszug_import._recompute_doc_status:
# Sobald eine Bank Transaction existiert, kann die Zeile gebucht werden, auch
# wenn sie keine Party hat (z.B. Bankgebühren als Journal Entry).
def _row_phase(row: dict) -> int:
	if row.get("payment_entry") or row.get("journal_entry"):
		return 4
	if row.get("bank_transaction"):
		return 3
	if not (row.get("party_type") and row.get("party")):
		return 1
	return 2


def _row_status(row: dict, phase: int) -> str:
	if phase == 4:
		return "done"
	if phase == 2:
		return "phase2-no-bt"
	if phase == 1:
		return "phase1-no-party"
	# Phase 3: Bank-Tx da, aber kein Beleg — row_status-Feld überlagert nur die
	# Sonderfälle (Auto-Match-Misserfolg).
	rs = (row.get("row_status") or "").lower()
	if rs == "failed":
		return "error"
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
def search_parties(party_type: str, txt: str = "") -> dict[str, Any]:
	"""Autocomplete für Customer/Supplier (Phase-1-Zuordnung)."""
	if party_type not in ("Customer", "Supplier"):
		frappe.throw(_("Party-Typ muss Customer oder Supplier sein."))

	title_field = "customer_name" if party_type == "Customer" else "supplier_name"
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
