"""Korrektur bereits erzeugter (gebuchter) Mietrechnungen.

Anwendungsfall: Es wurde z.B. ein falscher Mietbetrag im Mietvertrag eingetragen
und die Mietrechnungen sind schon erzeugt (und damit submitted/gebucht). Eine
gebuchte Sales Invoice ist in ERPNext unveränderlich — der Betrag lässt sich
nicht editieren. Dieses Modul wählt automatisch den passenden Korrektur-Weg:

    offen + unbezahlt   → Storno der SI, Neu-Erzeugung aus aktueller Staffelmiete
    offen + bezahlt     → Storno der zugeordneten Payment Entries (gibt die Bank
                          Transaction frei) + Storno SI + Neu-Erzeugung +
                          Auto-Match der Bank Transaction auf die korrigierten SIs
    festgeschrieben     → KEIN Storno (GoBD/Unveränderbarkeit): Gutschrift
                          (is_return) im aktuellen offenen Monat + neue korrekte SI

``festgeschrieben`` = das posting_date liegt in einer aktiven ``Accounting Period``,
die ``Sales Invoice`` als geschlossenes Dokument führt (ERPNext blockt dann auch
selbst jedes Storno/Buchen in dem Zeitraum).

WICHTIG: Den korrekten Betrag VORHER im Mietvertrag (Staffelmiete) pflegen —
Generator und Recompute ziehen den Betrag von dort.

Die Neu-Erzeugung läuft über ``generate_mietrechnungen.generate_miet_und_bk_rechnungen``
mit ``mietvertrag``-Filter; der dortige Idempotenz-Guard sorgt dafür, dass nach
einem gezielten Storno nur der stornierte Rechnungs-Typ neu entsteht (BK/HK/UMZ
bleiben unangetastet).
"""

from __future__ import annotations

import re
from datetime import date

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

# Item-Code == Typ-Bezeichnung (so legt der Generator die Rechnungen an).
_TYP_BY_ITEM = {
	"Miete": "Miete",
	"Betriebskosten": "Betriebskosten",
	"Heizkosten": "Heizkosten",
	"Untermietzuschlag": "Untermietzuschlag",
}

_RE_TYPE = re.compile(r"\[TYPE:([^\]]+)\]")
_RE_MV = re.compile(r"\[MV:([^\]]+)\]")
_RE_MONTH = re.compile(r"(\d{2})/(\d{4})")


def _si_context(si) -> dict:
	"""Leitet aus einer Sales Invoice Typ, Mietvertrag und Abrechnungs-Monat ab.

	Reihenfolge der Quellen: Remark-Marker `[TYPE:..] [MV:..] mm/yyyy`, dann
	`mietabrechnung_id` (`<MV>|<mm/yyyy>`), dann Item-Code / posting_date als
	Fallback. Liefert immer ``monat``/``jahr`` (aus posting_date als letzte
	Rückfallebene); ``mietvertrag``/``typ`` können None sein, wenn nicht
	auflösbar — der Aufrufer behandelt das als „keine HV-Mietrechnung".
	"""
	remarks = si.get("remarks") or ""
	typ = None
	mv = None
	monat = None
	jahr = None

	m = _RE_TYPE.search(remarks)
	if m:
		typ = m.group(1).strip()
	m = _RE_MV.search(remarks)
	if m:
		mv = m.group(1).strip()
	m = _RE_MONTH.search(remarks)
	if m:
		monat = int(m.group(1))
		jahr = int(m.group(2))

	mab = si.get("mietabrechnung_id") or ""
	# rpartition: der Monat hängt als `|mm/yyyy` HINTEN dran — der MV-Name selbst
	# kann `|` enthalten (z.B. "G1 | VH | EG links | ab: … - Beganovic").
	if (not mv or monat is None) and "|" in mab:
		mv_part, _, monat_part = mab.rpartition("|")
		if not mv:
			mv = mv_part.strip() or None
		mm = _RE_MONTH.search(monat_part)
		if monat is None and mm:
			monat = int(mm.group(1))
			jahr = int(mm.group(2))

	if not typ:
		for it in si.get("items") or []:
			cand = _TYP_BY_ITEM.get((it.get("item_code") or "").strip())
			if cand:
				typ = cand
				break

	if monat is None or jahr is None:
		d = getdate(si.posting_date)
		monat = monat or d.month
		jahr = jahr or d.year

	return {
		"typ": typ,
		"mietvertrag": mv,
		"monat": int(monat),
		"jahr": int(jahr),
		"monat_str": f"{int(monat):02d}/{int(jahr)}",
	}


def _resolve_mietvertrag(si, ctx: dict) -> str | None:
	"""Echten Mietvertrag-Docnamen bestimmen.

	Der Marker-Wert aus Remark/``mietabrechnung_id`` kann vom Docnamen abweichen
	(Alt-Importe haben Tabs statt Leerzeichen im Namen), darum: erst prüfen, ob
	der Marker als Docname existiert, sonst über Wohnung + Zeitraum (+ Kunde)
	auflösen — wie ``resolve_mietabrechnung_id``.
	"""
	marker = ctx.get("mietvertrag")
	if marker and frappe.db.exists("Mietvertrag", marker):
		return marker

	anchor = date(ctx["jahr"], ctx["monat"], 1)
	base: dict = {"von": ["<=", anchor]}
	or_f = [["bis", "is", "not set"], ["bis", ">=", anchor]]
	if si.get("wohnung"):
		base["wohnung"] = si.get("wohnung")

	# Erst mit Kunde (disambiguiert parallele Verträge), dann ohne.
	for extra in ({"kunde": si.customer}, {}):
		matches = frappe.get_all(
			"Mietvertrag",
			filters={**base, **extra},
			or_filters=or_f,
			pluck="name",
			limit=2,
		)
		if len(matches) == 1:
			return matches[0]
	return marker  # Rückfall (evtl. nicht existent) — Aufrufer prüft Existenz


def _is_frozen(posting_date, company: str | None = None) -> bool:
	"""True, wenn das Datum in einer aktiven Accounting Period liegt, die
	'Sales Invoice' als geschlossenes Dokument führt.

	Das ist der Perioden-Sperr-Mechanismus dieser ERPNext-Version (das ältere
	``acc_frozen_upto`` existiert hier nicht). ERPNext selbst blockt in so einem
	Zeitraum jedes Storno/Buchen (ClosedAccountingPeriod) — wir entscheiden
	deshalb vorab auf den Gutschrift-Pfad statt in den Fehler zu laufen.
	"""
	d = getdate(posting_date)
	periods = frappe.get_all(
		"Accounting Period",
		filters={"start_date": ["<=", d], "end_date": [">=", d], "disabled": 0},
		fields=["name", "company"],
	)
	for p in periods:
		if company and p.company and p.company != company:
			continue
		if frappe.get_all(
			"Closed Document",
			filters={"parent": p.name, "document_type": "Sales Invoice", "closed": 1},
			limit=1,
		):
			return True
	return False


def _payment_entries_for_si(si_name: str) -> list[str]:
	"""Submittete Payment Entries, die diese SI referenzieren."""
	parents = frappe.get_all(
		"Payment Entry Reference",
		filters={"reference_doctype": "Sales Invoice", "reference_name": si_name},
		pluck="parent",
	)
	if not parents:
		return []
	return frappe.get_all(
		"Payment Entry",
		filters={"name": ["in", list(set(parents))], "docstatus": 1},
		pluck="name",
	)


def _journal_entries_for_si(si_name: str) -> list[str]:
	"""Submittete Journal Entries, die diese SI referenzieren (z.B. BK-Verrechnung)."""
	parents = frappe.get_all(
		"Journal Entry Account",
		filters={"reference_type": "Sales Invoice", "reference_name": si_name},
		pluck="parent",
	)
	if not parents:
		return []
	return frappe.get_all(
		"Journal Entry",
		filters={"name": ["in", list(set(parents))], "docstatus": 1},
		pluck="name",
	)


def _bank_transactions_for_pe(pe_name: str) -> list[str]:
	return frappe.get_all(
		"Bank Transaction Payments",
		filters={"payment_document": "Payment Entry", "payment_entry": pe_name},
		pluck="parent",
	)


def _find_invoice(remark_marker: str, *, is_return: int = 0) -> str | None:
	"""Neueste submittete SI mit passendem Remark-Marker."""
	names = frappe.get_all(
		"Sales Invoice",
		filters={
			"remarks": ["like", f"%{remark_marker}%"],
			"docstatus": 1,
			"is_return": is_return,
		},
		order_by="creation desc",
		pluck="name",
		limit=1,
	)
	return names[0] if names else None


def _recompute_betrag(ctx: dict) -> float:
	"""Korrekter Betrag für (Mietvertrag, Monat, Typ) aus der aktuellen Staffelmiete."""
	from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import (
		_miete_betrag_fuer_monat,
		_staffelbetrag,
	)

	anchor = date(ctx["jahr"], ctx["monat"], 1)
	mv_name = ctx["mietvertrag"]
	typ = ctx["typ"]

	if typ == "Miete":
		mv_row = frappe.db.get_value("Mietvertrag", mv_name, ["name", "von", "bis"], as_dict=True)
		return _miete_betrag_fuer_monat(mv_row, anchor)
	parentfield = {
		"Betriebskosten": "betriebskosten",
		"Heizkosten": "heizkosten",
		"Untermietzuschlag": "untermietzuschlag",
	}.get(typ)
	if not parentfield:
		return 0.0
	return _staffelbetrag(mv_name, parentfield, anchor)


@frappe.whitelist()
def korrigiere_mietrechnung(sales_invoice: str, dry_run: int | str = 0) -> dict:
	"""Korrigiert eine bereits gebuchte Mietrechnung (siehe Modul-Docstring).

	Args:
	    sales_invoice: Name der fehlerhaften Sales Invoice.
	    dry_run: Wenn truthy, wird nur der geplante Weg zurückgegeben, nichts gebucht.

	Returns: Plan-/Ergebnis-Dict mit ``path``, ``frozen``, ``paid`` und (bei
	    Ausführung) den erzeugten/stornierten Belegen.
	"""
	dry = bool(int(dry_run or 0))
	si = frappe.get_doc("Sales Invoice", sales_invoice)

	if si.docstatus != 1:
		frappe.throw(_("Nur eine gebuchte Rechnung kann korrigiert werden (docstatus=1)."))
	if int(si.get("is_return") or 0):
		frappe.throw(_("Eine Gutschrift/Storno-Rechnung kann nicht korrigiert werden."))

	ctx = _si_context(si)
	if not ctx["typ"]:
		frappe.throw(
			_(
				"Das ist keine erkennbare Hausverwaltungs-Mietrechnung "
				"(kein Rechnungs-Typ aus Remark oder Item ableitbar)."
			)
		)
	# Marker-MV kann vom echten Docnamen abweichen → robust auflösen.
	ctx["mietvertrag"] = _resolve_mietvertrag(si, ctx)
	if not ctx["mietvertrag"] or not frappe.db.exists("Mietvertrag", ctx["mietvertrag"]):
		frappe.throw(
			_("Der zugehörige Mietvertrag konnte nicht eindeutig aufgelöst werden (Wohnung/Zeitraum prüfen).")
		)
	if not frappe.has_permission("Sales Invoice", "cancel", doc=si.name):
		frappe.throw(_("Keine Berechtigung, Rechnungen zu stornieren."), frappe.PermissionError)

	frozen = _is_frozen(si.posting_date, si.company)
	pes = _payment_entries_for_si(si.name)
	jes = _journal_entries_for_si(si.name)
	paid = bool(pes) or flt(si.outstanding_amount) < flt(si.grand_total) - 0.01

	neu_betrag = _recompute_betrag(ctx)

	plan = {
		"sales_invoice": si.name,
		"context": ctx,
		"frozen": frozen,
		"paid": paid,
		"payment_entries": pes,
		"journal_entries": jes,
		"alter_betrag": flt(si.grand_total),
		"neuer_betrag": flt(neu_betrag),
		"path": "gutschrift" if frozen else "storno",
		"dry_run": dry,
	}

	# Journal-Entry-Verknüpfungen automatisch zu stornieren ist riskant (in dieser
	# App z.B. BK-Verrechnungsbuchungen). Im Storno-Pfad daher abbrechen.
	if not frozen and jes:
		frappe.throw(
			_("Rechnung ist über Journal Entry(s) {0} verknüpft — bitte manuell behandeln.").format(
				", ".join(jes)
			)
		)

	if dry:
		return plan

	if frozen:
		result = _korrektur_gutschrift(si, ctx, neu_betrag)
	else:
		result = _korrektur_storno(si, ctx, pes)

	plan.update(result)
	return plan


def _korrektur_storno(si, ctx: dict, pes: list[str]) -> dict:
	"""Offene Periode: PEs + SI stornieren, neu erzeugen, Bank-Zahlung neu zuordnen."""
	from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import (
		generate_miet_und_bk_rechnungen,
	)
	from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
		auto_match_bank_transaction,
	)

	# 1) Betroffene Bank Transactions merken (vor dem PE-Storno), dann PEs stornieren.
	bank_transactions: list[str] = []
	for pe_name in pes:
		bank_transactions.extend(_bank_transactions_for_pe(pe_name))
		pe = frappe.get_doc("Payment Entry", pe_name)
		pe.cancel()
	bank_transactions = list(dict.fromkeys(bank_transactions))  # dedupe, Reihenfolge erhalten

	# 2) Fehlerhafte SI stornieren.
	si.cancel()

	# 3) Korrigierte Rechnung neu erzeugen (nur dieser Vertrag/Monat; Guard erzeugt
	#    ausschließlich den stornierten Typ neu, da BK/HK/UMZ noch existieren).
	gen = generate_miet_und_bk_rechnungen(
		monat=ctx["monat"], jahr=ctx["jahr"], company=si.company, mietvertrag=ctx["mietvertrag"]
	)

	neue_si = _find_invoice(f"[TYPE:{ctx['typ']}] [MV:{ctx['mietvertrag']}] {ctx['monat_str']}")

	# 4) Freigewordene Bank-Zahlung(en) erneut auto-matchen (best effort).
	rematch = []
	for bt in bank_transactions:
		try:
			rematch.append({"bank_transaction": bt, "result": auto_match_bank_transaction(bt)})
		except Exception as e:  # Re-Match darf die Korrektur nicht kippen
			frappe.log_error(frappe.get_traceback(), f"Korrektur Re-Match {bt}")
			rematch.append({"bank_transaction": bt, "error": str(e)})

	return {
		"stornierte_si": si.name,
		"stornierte_payment_entries": pes,
		"neue_si": neue_si,
		"rematch": rematch,
		"generator": {"created": gen.get("created"), "durchlauf": gen.get("durchlauf")},
	}


def _korrektur_gutschrift(si, ctx: dict, neu_betrag: float) -> dict:
	"""Festgeschriebene Periode: Original bleibt, Gutschrift + neue SI im aktuellen Monat."""
	from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import (
		_cost_center_via_wohnung,
	)
	from hausverwaltung.hausverwaltung.utils.income_accounts import get_hv_income_accounts

	post = getdate(today())
	if _is_frozen(post, si.company):
		frappe.throw(
			_(
				"Auch das aktuelle Datum liegt in einer geschlossenen Accounting Period. "
				"Korrektur nicht möglich — bitte zuerst eine offene Periode bereitstellen."
			)
		)

	wohnung = si.get("wohnung")
	cost_center = _cost_center_via_wohnung(wohnung)
	income_account = get_hv_income_accounts(si.company).get(ctx["typ"])
	item_code = ctx["typ"]
	orig_betrag = flt(si.grand_total)

	# 1) Gutschrift über den vollen Original-Betrag (return_against verknüpft mit Original).
	gutschrift = _build_si(
		si.customer,
		post,
		item_code,
		f"Korrektur-Gutschrift {ctx['monat_str']} (zu {si.name})",
		orig_betrag,
		income_account,
		cost_center,
		f"[KORREKTUR-STORNO] [TYPE:{ctx['typ']}] [MV:{ctx['mietvertrag']}] {ctx['monat_str']}",
		wohnung,
		si.company,
		is_return=1,
		return_against=si.name,
	)

	# 2) Neue korrekte Rechnung über den Recompute-Betrag (im aktuellen Monat).
	neue_si = ""
	if flt(neu_betrag) > 0:
		neue_si = _build_si(
			si.customer,
			post,
			item_code,
			f"Korrektur {ctx['monat_str']} {ctx['typ']} Wohnung {wohnung}",
			flt(neu_betrag),
			income_account,
			cost_center,
			f"[KORREKTUR] [TYPE:{ctx['typ']}] [MV:{ctx['mietvertrag']}] {ctx['monat_str']}",
			wohnung,
			si.company,
			mietabrechnung_id=si.get("mietabrechnung_id"),
		)

	return {
		"original_si": si.name,
		"gutschrift": gutschrift,
		"neue_si": neue_si,
		"hinweis": _(
			"Festgeschriebene Periode: Original blieb erhalten. Gutschrift {0}"
			" und neue Rechnung {1} im aktuellen Monat gebucht. Zahlungs-/Guthaben-"
			"Ausgleich ggf. über Zahlungsabgleich nachziehen."
		).format(gutschrift, neue_si or "—"),
	}


def _build_si(
	customer: str,
	posting: date,
	item_code: str,
	beschreibung: str,
	betrag: float,
	income_account: str | None,
	cost_center: str | None,
	remark: str,
	wohnung: str | None,
	company: str,
	*,
	is_return: int = 0,
	return_against: str | None = None,
	mietabrechnung_id: str | None = None,
) -> str:
	"""Baut + bucht eine Sales Invoice (oder Gutschrift). Posting im aktuellen Monat."""
	if not income_account:
		frappe.throw(
			_("Kein Erlöskonto für {0} hinterlegt (Hausverwaltung Einstellungen).").format(item_code)
		)
	qty = -1 if is_return else 1
	rate = abs(flt(betrag))
	si = frappe.get_doc(
		{
			"doctype": "Sales Invoice",
			"company": company,
			"customer": customer,
			"posting_date": posting,
			"set_posting_time": 1,
			"due_date": posting,
			"is_return": is_return,
			"return_against": return_against,
			"remarks": remark,
			"items": [
				{
					"item_code": item_code,
					"item_name": item_code,
					"description": beschreibung,
					"qty": qty,
					"rate": rate,
					"income_account": income_account,
					"cost_center": cost_center,
				}
			],
		}
	)
	if wohnung:
		si.set("wohnung", wohnung)
		for it in si.items:
			it.set("wohnung", wohnung)
	if mietabrechnung_id:
		si.set("mietabrechnung_id", mietabrechnung_id)
	si.insert()
	si.submit()
	return si.name
