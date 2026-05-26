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
)


def get_context(context):
	"""Page-Bootstrap. Das React-UI rendert clientseitig und holt Daten via RPC."""
	return context


# ───────────────────────────────────────────── Zeilen-Phase / Status-Mapping ──

# Spiegelt das Phasen-Modell aus bankauszug_import._recompute_doc_status:
# Phase hängt an party → bank_transaction → voucher, NICHT an row_status.
def _row_phase(row: dict) -> int:
	if row.get("payment_entry") or row.get("journal_entry"):
		return 4
	if row.get("bank_transaction"):
		return 3
	if row.get("party_type") and row.get("party"):
		return 2
	return 1


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


@frappe.whitelist()
def get_overview(import_name: str) -> dict[str, Any]:
	"""Komplette Übersicht für die Bankimport-UI: importMeta + Zeilen + Phase-Counts."""
	doc = frappe.get_doc("Bankauszug Import", import_name)
	frappe.has_permission("Bankauszug Import", "read", doc=doc, throw=True)

	# Status + Saldo frisch halten (sonst stale nach nachträglichen Buchungen).
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
		rows_out.append(
			{
				"id": row.name,
				"buchungstag": str(row.buchungstag) if row.buchungstag else None,
				"betrag": flt(row.betrag),
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
	for it in items:
		it["modified"] = str(it["modified"]) if it.get("modified") else None
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
	"""Konto-Autocomplete für den Journal-Entry — Wrapper auf die bestehende
	Cockpit-Logik (buchbare Konten aus Betriebskostenart / Kostenart nicht UL)."""
	from hausverwaltung.hausverwaltung.page.buchen_cockpit.buchen_cockpit import (
		autocomplete_konten,
	)

	return {"items": autocomplete_konten(txt=txt or "", typ="alle")}
