"""Korrektur bereits erzeugter (gebuchter) Mietrechnungen.

Anwendungsfall: Es wurde z.B. ein falscher Mietbetrag im Mietvertrag eingetragen
und die Mietrechnungen sind schon erzeugt (und damit submitted/gebucht). Eine
gebuchte Sales Invoice ist in ERPNext unveränderlich — der Betrag lässt sich
nicht editieren. Dieses Modul wählt automatisch den passenden Korrektur-Weg:

    offen + unbezahlt   → Storno der SI, Neu-Erzeugung aus aktueller Staffelmiete
    offen + bezahlt     → Storno der SI; ERPNext löst dabei automatisch nur
                          deren Rechnungsreferenz aus den bestehenden Payment
                          Entries. Optional dieselben PEs direkt der neuen SI
                          zuordnen.
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

import json
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
def korrigiere_mietrechnung(
	sales_invoice: str, dry_run: int | str = 0, rebook_payments: int | str = 0
) -> dict:
	"""Korrigiert eine bereits gebuchte Mietrechnung (siehe Modul-Docstring).

	Args:
	    sales_invoice: Name der fehlerhaften Sales Invoice.
	    dry_run: Wenn truthy, wird nur der geplante Weg zurückgegeben, nichts gebucht.
	    rebook_payments: Wenn truthy, werden die bestehenden Payment Entries direkt
	        der neuen Sollstellung zugeordnet; Differenzen bleiben als Guthaben
	        bzw. offener Rechnungsbetrag bestehen. Die Payment Entries selbst und
	        ihre Banktransaktions-Verknüpfungen bleiben unverändert bestehen.

	Returns: Plan-/Ergebnis-Dict mit ``path``, ``frozen``, ``paid`` und (bei
	    Ausführung) den erzeugten/stornierten Belegen.
	"""
	dry = bool(int(dry_run or 0))
	rebook = bool(int(rebook_payments or 0))
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
		"rebook_payments": rebook,
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
		result = _korrektur_storno(si, ctx, pes, rebook_payments=rebook)

	plan.update(result)
	return plan


@frappe.whitelist()
def korrigiere_mietrechnungen_bulk(sales_invoices, rebook_payments: int | str = 0) -> dict:
	"""Korrigiert mehrere Mietrechnungen nacheinander.

	Jede SI wird in einem eigenen Savepoint verarbeitet — ein Fehler bei einer
	Rechnung (z.B. festgeschrieben + Journal-Entry-Verknüpfung) kippt die anderen
	nicht. ``sales_invoices`` ist eine Liste oder ein JSON-String von SI-Namen.
	"""
	if isinstance(sales_invoices, str):
		sales_invoices = json.loads(sales_invoices)
	rebook = bool(int(rebook_payments or 0))
	names = list(dict.fromkeys(str(n).strip() for n in (sales_invoices or []) if str(n).strip()))

	ergebnisse: list[dict] = []
	ok = 0
	for idx, name in enumerate(names):
		sp = f"korr_bulk_{idx}"
		frappe.db.savepoint(sp)
		try:
			# Bei einer Sammelkorrektur erst alle alten Referenzen lösen und alle
			# Ersatz-Sollstellungen erzeugen. Die gemeinsame Zuordnung danach kann
			# Minderungen und Erhöhungen desselben Mieters miteinander ausgleichen.
			res = korrigiere_mietrechnung(name, dry_run=0, rebook_payments=0)
			ok += 1
			ergebnisse.append(
				{
					"sales_invoice": name,
					"ok": True,
					"path": res.get("path"),
					"alter_betrag": res.get("alter_betrag"),
					"neuer_betrag": res.get("neuer_betrag"),
					"neue_si": res.get("neue_si"),
					"beibehaltene_payment_entries": res.get("beibehaltene_payment_entries") or [],
					"zahlungsuebernahmen": [],
				}
			)
		except Exception as e:
			frappe.db.rollback(save_point=sp)
			ergebnisse.append({"sales_invoice": name, "ok": False, "error": str(e)})

	zahlungsfehler = []
	if rebook:
		zahlungsfehler = _reconcile_bulk_payment_pool(ergebnisse)

	return {
		"total": len(names),
		"ok": ok,
		"fehler": len(names) - ok,
		"ergebnisse": ergebnisse,
		"zahlungsfehler": zahlungsfehler,
	}


def _reconcile_bulk_payment_pool(ergebnisse: list[dict]) -> list[dict]:
	"""Ordnet erhaltene PEs erst ihrem Ersatz und dann offenen Ersatz-SIs zu.

	Die erste Runde wahrt die bisherige fachliche Zuordnung. Die zweite Runde
	verwendet verbleibende Guthaben desselben Kunden/Kontos zum Ausgleich anderer
	korrigierter Sollstellungen. Dadurch gleichen sich z.B. eine Mietminderung
	und eine gleich hohe BK-Erhöhung unabhängig von der Reihenfolge aus.
	"""
	candidates = [
		row
		for row in ergebnisse
		if row.get("ok")
		and row.get("path") == "storno"
		and row.get("neue_si")
		and row.get("beibehaltene_payment_entries")
	]
	# Minderungen zuerst: so steht ihr Überschuss bereits für Erhöhungen bereit.
	candidates.sort(key=lambda row: flt(row.get("neuer_betrag")) - flt(row.get("alter_betrag")))
	all_payment_entries = list(
		dict.fromkeys(pe for row in candidates for pe in row["beibehaltene_payment_entries"])
	)
	errors: list[dict] = []
	failed_pairs: set[tuple[str, str]] = set()

	def assign(row: dict, pe_name: str) -> bool:
		pair = (pe_name, row["neue_si"])
		if pair in failed_pairs:
			return False
		if not _payment_can_reconcile_invoice(pe_name, row["neue_si"]):
			return False
		try:
			result = _reconcile_existing_payment(pe_name, row["neue_si"])
		except Exception as exc:
			failed_pairs.add(pair)
			frappe.log_error(frappe.get_traceback(), f"Korrektur Zahlungszuordnung {pe_name}")
			errors.append(
				{
					"payment_entry": pe_name,
					"sales_invoice": row["neue_si"],
					"error": str(exc),
				}
			)
			return False
		# Frühere Teilzuordnungen desselben PE bzw. derselben SI auf den jetzt
		# finaleren Reststand aktualisieren. Die Ergebnisanzeige darf Zwischenstände
		# nicht mehrfach oder in Eingangsreihenfolge addieren.
		for candidate in candidates:
			for previous in candidate["zahlungsuebernahmen"]:
				if previous.get("payment_entry") == result.get("payment_entry"):
					previous["zahlung_offen"] = result.get("zahlung_offen")
				if previous.get("neue_sollstellung") == result.get("neue_sollstellung"):
					previous["rechnung_offen"] = result.get("rechnung_offen")
		row["zahlungsuebernahmen"].append(result)
		return flt(result.get("zugeordnet")) > 0.01

	# 1) Die zuvor auf der jeweiligen alten SI geführten PEs zuerst auf deren
	#    direkte Ersatz-SI buchen.
	for row in candidates:
		for pe_name in row["beibehaltene_payment_entries"]:
			assign(row, pe_name)

	# 2) Noch offene Ersatz-SIs mit Restguthaben anderer PEs desselben
	#    Kunden/Receivable-Kontos aus dieser Sammelkorrektur ausgleichen.
	for row in candidates:
		for pe_name in all_payment_entries:
			if not _payment_can_reconcile_invoice(pe_name, row["neue_si"]):
				continue
			assign(row, pe_name)

	return errors


def _payment_can_reconcile_invoice(payment_entry: str, sales_invoice: str) -> bool:
	"""Sicherer Vorabcheck für eine Zuordnung innerhalb desselben Kundenkontos."""
	pe = frappe.get_doc("Payment Entry", payment_entry)
	invoice = frappe.get_doc("Sales Invoice", sales_invoice)
	party_account = pe.paid_from if pe.payment_type == "Receive" else pe.paid_to
	return bool(
		pe.docstatus == 1
		and invoice.docstatus == 1
		and pe.party_type == "Customer"
		and pe.party == invoice.customer
		and pe.company == invoice.company
		and party_account == invoice.debit_to
		and flt(pe.unallocated_amount) > 0.01
		and flt(invoice.outstanding_amount) > 0.01
	)


def _korrektur_storno(si, ctx: dict, pes: list[str], *, rebook_payments: bool = False) -> dict:
	"""Offene Periode: PE-Zuordnung lösen, SI ersetzen, optional neu zuordnen."""
	from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import (
		generate_miet_und_bk_rechnungen,
	)

	# 1) Fehlerhafte SI stornieren. Bei aktivierter ERPNext-Einstellung
	#    "unlink_payment_on_cancellation_of_invoice" löst ERPNext dabei selbst
	#    ausschließlich die Referenz zur SI. Die Payment Entries bleiben gebucht,
	#    behalten ihre Belegnummern und bleiben mit Banktransaktionen verknüpft.
	if pes and not frappe.db.get_single_value(
		"Accounts Settings", "unlink_payment_on_cancellation_of_invoice"
	):
		frappe.throw(
			_(
				"Die ERPNext-Einstellung zum Lösen von Zahlungen beim Rechnungsstorno ist deaktiviert. "
				"Die Korrektur wurde sicherheitshalber abgebrochen; Zahlungsbuchungen werden nicht storniert."
			)
		)
	if pes:
		# Das Submitten/Zuordnen eines PE aktualisiert die SI in der Datenbank.
		# Neu laden verhindert einen TimestampMismatch beim anschließenden Storno.
		si.reload()
	si.cancel()

	# 2) Korrigierte Rechnung neu erzeugen. Der Korrekturpfad erzeugt gezielt nur
	#    den betroffenen Typ; Draft-Dubletten dürfen den Ersatz für die stornierte
	#    gebuchte Rechnung nicht blockieren.
	gen = generate_miet_und_bk_rechnungen(
		monat=ctx["monat"],
		jahr=ctx["jahr"],
		company=si.company,
		mietvertrag=ctx["mietvertrag"],
		rechnungstyp=ctx["typ"],
		include_drafts_in_guard=0,
	)

	neue_si = _find_invoice(f"[TYPE:{ctx['typ']}] [MV:{ctx['mietvertrag']}] {ctx['monat_str']}")

	# 3) Optional dieselben Payment Entries über die ERPNext-Zahlungsabstimmung
	#    der neuen SI zuordnen. Kein Zahlungsbeleg und keine Banktransaktion wird
	#    storniert, kopiert oder neu verknüpft. Ohne Häkchen bleibt der gelöste
	#    Betrag als unallocated credit für "Zahlungen zuordnen" verfügbar.
	zahlungsuebernahmen = []
	if rebook_payments:
		for pe_name in pes:
			zahlungsuebernahmen.append(_reconcile_existing_payment(pe_name, neue_si))

	return {
		"stornierte_si": si.name,
		"stornierte_payment_entries": [],
		"beibehaltene_payment_entries": pes,
		"neue_si": neue_si,
		"zahlungsuebernahmen": zahlungsuebernahmen,
		"generator": {"created": gen.get("created"), "durchlauf": gen.get("durchlauf")},
	}


def _reconcile_existing_payment(payment_entry: str, new_si: str | None) -> dict:
	"""Ordnet denselben PE per ERPNext Payment Reconciliation einer neuen SI zu."""
	if not new_si:
		frappe.throw(_("Die neue Sollstellung wurde nicht gefunden."))

	pe = frappe.get_doc("Payment Entry", payment_entry)
	invoice = frappe.get_doc("Sales Invoice", new_si)
	account = pe.paid_from if pe.payment_type == "Receive" else pe.paid_to
	pr = frappe.get_doc(
		{
			"doctype": "Payment Reconciliation",
			"company": pe.company,
			"party_type": pe.party_type,
			"party": pe.party,
			"receivable_payable_account": account,
			"payment_name": pe.name,
			"invoice_name": invoice.name,
		}
	)
	pr.get_unreconciled_entries()
	payment_rows = [
		row for row in pr.payments if row.reference_type == "Payment Entry" and row.reference_name == pe.name
	]
	invoice_rows = [
		row
		for row in pr.invoices
		if row.invoice_type == "Sales Invoice" and row.invoice_number == invoice.name
	]
	if not payment_rows:
		frappe.throw(_("Payment Entry {0} hat keinen offenen Betrag.").format(pe.name))
	if not invoice_rows:
		frappe.throw(_("Sollstellung {0} hat keinen offenen Betrag.").format(invoice.name))

	available = flt(payment_rows[0].amount)
	invoice_open = flt(invoice_rows[0].outstanding_amount)
	allocated = min(available, invoice_open)
	pr.allocate_entries(
		frappe._dict(
			{
				"payments": [payment_rows[0].as_dict()],
				"invoices": [invoice_rows[0].as_dict()],
			}
		)
	)
	pr.validate_allocation()
	pr.reconcile_allocations()

	pe.reload()
	invoice.reload()
	return {
		"payment_entry": pe.name,
		"neue_sollstellung": invoice.name,
		"zugeordnet": allocated,
		"zahlung_offen": flt(pe.unallocated_amount),
		"rechnung_offen": flt(invoice.outstanding_amount),
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
