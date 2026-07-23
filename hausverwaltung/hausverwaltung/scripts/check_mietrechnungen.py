"""Sollstellungs-Prüfung — vergleicht eingefrorene Sales-Invoice-Werte gegen
die aktuell gültigen Werte aus dem Mietvertrag.

Read-only: ändert weder Belege noch Mietverträge. Liefert drei Klassen von
Befunden:
- fehlend:      Soll-Position laut Vertrag, aber keine Sales Invoice.
- ueberfluessig: Sales Invoice existiert, aber Vertrag sieht 0 € vor.
- abweichungen: SI vorhanden, aber Betrag oder Stammdaten weichen ab.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import frappe
from frappe import _
from frappe.utils import get_first_day, getdate

from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import (
	_cost_center_via_wohnung,
	_kunde_des_vertrags,
	_miete_betrag_fuer_monat,
	_month_window,
	_overlap,
	_resolve_company,
	_staffelbetrag,
)
from hausverwaltung.hausverwaltung.utils.income_accounts import get_hv_income_accounts

TYP_PARENTFIELD = {
	"Miete": "miete",
	"Betriebskosten": "betriebskosten",
	"Heizkosten": "heizkosten",
	"Untermietzuschlag": "untermietzuschlag",
}


def _expected_betrag(mv_row, typ: str, anker: date) -> float:
	if typ == "Miete":
		return _miete_betrag_fuer_monat(mv_row, anker)
	parentfield = TYP_PARENTFIELD[typ]
	return _staffelbetrag(mv_row.name, parentfield, anker)


def _load_si_data(si_name: str | None, typ: str | None = None) -> dict | None:
	"""Lädt SI-Header + die zum ``typ`` gehörende Item-Zeile.

	Legacy-/Migrations-SIs kombinieren oft Miete und Betriebskosten in EINER SI
	mit zwei Item-Zeilen. ``typ`` filtert auf das passende Item (item_code), so
	dass Betragsvergleich, cost_center und income_account die richtige Position
	abgreifen. Ohne ``typ`` wird die erste Zeile genommen (Notnagel).
	"""
	if not si_name:
		return None
	si = frappe.db.get_value(
		"Sales Invoice",
		si_name,
		["name", "docstatus", "customer", "wohnung"],
		as_dict=True,
	)
	if not si:
		return None
	item_filters: dict = {"parent": si_name}
	if typ:
		item_filters["item_code"] = typ
	item = frappe.db.get_value(
		"Sales Invoice Item",
		item_filters,
		["rate", "cost_center", "income_account"],
		as_dict=True,
		order_by="idx asc",
	)
	return {
		"sales_invoice": si.name,
		"docstatus": si.docstatus,
		"customer": si.customer,
		"wohnung": si.get("wohnung"),
		"rate": float(item.rate) if item and item.rate else 0.0,
		"cost_center": item.cost_center if item else None,
		"income_account": item.income_account if item else None,
	}


def _find_existing_invoice(
	customer: str | None,
	monat: date,
	mv_name: str,
	typ: str,
	wohnung: str | None = None,
) -> str | None:
	"""Findet die zur Kombination (Kunde, Monat, Typ) passende Sales Invoice.

	Frappe normalisiert Whitespace im ``remarks``-Feld (Tabs, Truncation),
	daher ist ein Marker-Match nicht zuverlässig. Stattdessen Suche über
	Kunde + posting_date-Monat + Item-Code aus dem Sales-Invoice-Item.

	Wenn ``wohnung`` gegeben ist, wird zuerst exakt darauf gefiltert; nur
	wenn kein Treffer (typisch für Legacy-Importe ohne Wohnung-Custom-Feld)
	wird ohne Wohnung-Filter erneut gesucht.

	Priorität: aktive (docstatus 0/1) vor stornierter (docstatus 2).
	"""
	if not customer:
		return None
	from frappe.utils import get_last_day

	posting_range = [get_first_day(monat), get_last_day(monat)]
	base_filters = {
		"customer": customer,
		"posting_date": ("between", posting_range),
	}

	def _search(filters: dict) -> str | None:
		for docstatus_filter in (("in", [0, 1]), ("=", 2)):
			f = dict(filters, docstatus=docstatus_filter)
			try:
				parent_names = frappe.get_all("Sales Invoice", filters=f, pluck="name")
			except Exception:
				return None
			if not parent_names:
				continue
			match = frappe.get_all(
				"Sales Invoice Item",
				filters={"parent": ("in", parent_names), "item_code": typ},
				fields=["parent"],
				limit=1,
				order_by="creation desc",
			)
			if match:
				return match[0].parent
		return None

	if wohnung:
		hit = _search(dict(base_filters, wohnung=wohnung))
		if hit:
			return hit
	return _search(base_filters)


def _diff_si_against_expected(
	si: dict,
	*,
	expected_betrag: float,
	expected_kunde: str | None,
	expected_wohnung: str | None,
	expected_cost_center: str | None,
	expected_income_account: str | None,
	mietvertrag: str,
	typ: str,
	monat: str,
) -> list[dict]:
	diffs: list[dict] = []

	def _add(feld: str, erwartet, aktuell):
		diffs.append(
			{
				"feld": feld,
				"erwartet": erwartet,
				"aktuell": aktuell,
				"sales_invoice": si["sales_invoice"],
				"mietvertrag": mietvertrag,
				"typ": typ,
				"monat": monat,
			}
		)

	# Betrag: immer vergleichen
	if abs(round(si["rate"], 2) - round(expected_betrag, 2)) >= 0.01:
		_add("betrag", round(expected_betrag, 2), round(si["rate"], 2))

	# Stammdaten: nur flaggen, wenn sowohl erwartet als auch aktuell gesetzt
	# sind und sich unterscheiden — unterdrückt Migrations-Lärm, bei dem die
	# Custom-Felder auf alten SIs schlicht leer sind.
	if expected_kunde and si["customer"] and si["customer"] != expected_kunde:
		_add("kunde", expected_kunde, si["customer"])
	if expected_wohnung and si["wohnung"] and si["wohnung"] != expected_wohnung:
		_add("wohnung", expected_wohnung, si["wohnung"])
	if expected_cost_center and si["cost_center"] and si["cost_center"] != expected_cost_center:
		_add("cost_center", expected_cost_center, si["cost_center"])
	if expected_income_account and si["income_account"] and si["income_account"] != expected_income_account:
		_add("income_account", expected_income_account, si["income_account"])
	return diffs


def _diff_for_mv_monat(
	mv_row,
	anker: date,
	company: str | None,
	*,
	durchlauf_rechnungen: list[dict] | None = None,
	durchlauf_skips: list[dict] | None = None,
) -> dict:
	"""Diff für genau (Mietvertrag, Anker-Monat).

	Wenn ``durchlauf_rechnungen`` übergeben wird, wird die Soll-Suche auf diesen
	Durchlauf eingeschränkt; sonst per Marker-Search im gesamten SI-Bestand.
	"""
	fehlend: list[dict] = []
	abweichungen: list[dict] = []
	ueberfluessig: list[dict] = []
	ok = 0

	try:
		income_accounts = get_hv_income_accounts(company) if company else {}
	except Exception:
		income_accounts = {}

	expected_kunde = _kunde_des_vertrags(mv_row)
	expected_wohnung = mv_row.wohnung
	expected_cost_center = _cost_center_via_wohnung(mv_row.wohnung)

	monat_str = anker.strftime("%m/%Y")

	for typ in ("Miete", "Betriebskosten", "Heizkosten", "Untermietzuschlag"):
		expected_betrag = round(float(_expected_betrag(mv_row, typ, anker)), 2)
		expected_account = income_accounts.get(typ)

		si_data = None
		intentional_skip = False

		if durchlauf_rechnungen is not None:
			row = next(
				(
					r
					for r in durchlauf_rechnungen
					if r.get("mietvertrag") == mv_row.name and r.get("typ") == typ
				),
				None,
			)
			if row:
				si_data = _load_si_data(row.get("sales_invoice"), typ=typ)
			elif durchlauf_skips:
				intentional_skip = any(
					s.get("mietvertrag") == mv_row.name
					and s.get("typ") == typ
					and s.get("reason") == "rechnung_existiert"
					for s in durchlauf_skips
				)
				if intentional_skip:
					si_name = _find_existing_invoice(
						expected_kunde, anker, mv_row.name, typ, wohnung=expected_wohnung
					)
					si_data = _load_si_data(si_name, typ=typ)
		else:
			si_name = _find_existing_invoice(
				expected_kunde, anker, mv_row.name, typ, wohnung=expected_wohnung
			)
			si_data = _load_si_data(si_name, typ=typ)

		if expected_betrag > 0:
			if si_data is None:
				fehlend.append(
					{
						"mietvertrag": mv_row.name,
						"wohnung": mv_row.wohnung,
						"kunde": expected_kunde,
						"typ": typ,
						"monat": monat_str,
						"erwartet_betrag": expected_betrag,
					}
				)
				continue
			if si_data["docstatus"] == 2:
				fehlend.append(
					{
						"mietvertrag": mv_row.name,
						"wohnung": mv_row.wohnung,
						"kunde": expected_kunde,
						"typ": typ,
						"monat": monat_str,
						"erwartet_betrag": expected_betrag,
						"hinweis": f"Sales Invoice {si_data['sales_invoice']} ist storniert",
					}
				)
				continue
			row_diffs = _diff_si_against_expected(
				si_data,
				expected_betrag=expected_betrag,
				expected_kunde=expected_kunde,
				expected_wohnung=expected_wohnung,
				expected_cost_center=expected_cost_center,
				expected_income_account=expected_account,
				mietvertrag=mv_row.name,
				typ=typ,
				monat=monat_str,
			)
			if row_diffs:
				abweichungen.extend(row_diffs)
			else:
				ok += 1
		else:
			if si_data is not None and si_data["docstatus"] != 2:
				ueberfluessig.append(
					{
						"mietvertrag": mv_row.name,
						"wohnung": mv_row.wohnung,
						"kunde": expected_kunde,
						"typ": typ,
						"monat": monat_str,
						"aktuell_betrag": si_data["rate"],
						"sales_invoice": si_data["sales_invoice"],
					}
				)

	return {
		"fehlend": fehlend,
		"abweichungen": abweichungen,
		"ueberfluessig": ueberfluessig,
		"ok": ok,
	}


@frappe.whitelist()
def pruefe_durchlauf(durchlauf: str) -> dict:
	if not durchlauf:
		frappe.throw(_("Durchlauf-Name fehlt."))
	doc = frappe.get_doc("Mietrechnungen Durchlauf", durchlauf)
	anker = date(int(doc.jahr), int(doc.monat), 1)
	company = doc.company

	rechnungen_rows = [r.as_dict() for r in (doc.get("rechnungen") or [])]
	skips_rows = [r.as_dict() for r in (doc.get("skips") or [])]

	vertrage = frappe.get_all(
		"Mietvertrag",
		filters={},
		fields=["name", "kunde", "wohnung", "von", "bis"],
	)

	fehlend: list[dict] = []
	abweichungen: list[dict] = []
	ueberfluessig: list[dict] = []
	ok = 0

	month_start, month_end_excl, _days = _month_window(anker)
	for v in vertrage:
		c_start = v.von or date(1900, 1, 1)
		c_end_excl = (v.bis + timedelta(days=1)) if v.bis else date(9999, 12, 31)
		_, _, ov_days = _overlap(month_start, month_end_excl, c_start, c_end_excl)
		if ov_days == 0:
			continue
		result = _diff_for_mv_monat(
			v,
			anker,
			company,
			durchlauf_rechnungen=rechnungen_rows,
			durchlauf_skips=skips_rows,
		)
		fehlend.extend(result["fehlend"])
		abweichungen.extend(result["abweichungen"])
		ueberfluessig.extend(result["ueberfluessig"])
		ok += result["ok"]

	return {
		"durchlauf": durchlauf,
		"monat": anker.strftime("%Y-%m"),
		"company": company,
		"fehlend": fehlend,
		"abweichungen": abweichungen,
		"ueberfluessig": ueberfluessig,
		"ok_count": ok,
	}


def _aktivitaets_monate_fuer_mv(
	mv_name: str, expected_kunde: str | None, mv_wohnung: str | None
) -> set[tuple[int, int]]:
	"""Sammelt (jahr, monat)-Tupel, in denen es überhaupt eine Sollstellungs-
	Aktivität für diesen MV gab — entweder eine Durchlauf-Zeile oder eine
	Sales Invoice des Kunden.

	Damit wird verhindert, dass `pruefe_mietvertrag` über Jahrzehnte hinweg
	historische Monate ohne jegliche SI-Aktivität als „fehlend" flaggt.

	Wir filtern bewusst nicht nach Wohnung — Legacy-/Migrations-SIs haben
	das Custom-Feld oft nicht gesetzt, würden also fehlen.
	"""
	monate: set[tuple[int, int]] = set()

	# 1) Durchlauf-Zeilen (auch wenn der zugehörige Durchlauf gelöscht/storniert wurde)
	rows = frappe.get_all(
		"Mietrechnungen Durchlauf Rechnung",
		filters={"mietvertrag": mv_name},
		fields=["posting_date", "parent"],
	)
	parent_keys = {r.parent for r in rows if r.parent}
	parent_meta: dict[str, tuple[int, int]] = {}
	if parent_keys:
		for d in frappe.get_all(
			"Mietrechnungen Durchlauf",
			filters={"name": ("in", list(parent_keys))},
			fields=["name", "monat", "jahr"],
		):
			try:
				parent_meta[d.name] = (int(d.jahr), int(d.monat))
			except Exception:
				continue
	for r in rows:
		key = parent_meta.get(r.parent)
		if key:
			monate.add(key)
		elif r.posting_date:
			d = getdate(r.posting_date)
			monate.add((d.year, d.month))

	# 2) Alle Sales Invoices des Kunden — ohne Wohnung-Filter, weil Legacy-SIs
	#    diesen Custom-Field oft nicht haben. Risiko: wenn ein Kunde mehrere
	#    Mietverträge an unterschiedlichen Wohnungen hat, werden auch deren
	#    Monate in den Scope aufgenommen — das diff erkennt das später korrekt.
	if expected_kunde:
		sis = frappe.get_all(
			"Sales Invoice",
			filters={"customer": expected_kunde, "docstatus": ("in", [0, 1, 2])},
			fields=["posting_date"],
		)
		for si in sis:
			if si.posting_date:
				d = getdate(si.posting_date)
				monate.add((d.year, d.month))

	return monate


@frappe.whitelist()
def pruefe_mietvertrag(mietvertrag: str) -> dict:
	if not mietvertrag:
		frappe.throw(_("Mietvertrag-Name fehlt."))
	mv = frappe.get_doc("Mietvertrag", mietvertrag)

	try:
		company = _resolve_company(None)
	except Exception:
		company = None

	mv_dict = mv.as_dict()
	expected_kunde = _kunde_des_vertrags(mv_dict)

	aktivitaet = _aktivitaets_monate_fuer_mv(mv.name, expected_kunde, mv_dict.get("wohnung"))

	monate: list[dict] = []
	for jahr, monat_nr in sorted(aktivitaet):
		anker = date(jahr, monat_nr, 1)
		# Kontrakt muss diesen Monat noch überschneiden — sonst macht eine
		# Soll-Berechnung keinen Sinn (z.B. Vertrag endete 2023 aber alte SI von 2020).
		c_start = mv.von or date(1900, 1, 1)
		c_end_excl = (mv.bis + timedelta(days=1)) if mv.bis else date(9999, 12, 31)
		month_start, month_end_excl, _days = _month_window(anker)
		_, _, ov_days = _overlap(month_start, month_end_excl, c_start, c_end_excl)
		if ov_days == 0:
			continue
		result = _diff_for_mv_monat(mv_dict, anker, company)
		if result["fehlend"] or result["abweichungen"] or result["ueberfluessig"]:
			monate.append(
				{
					"monat": anker.strftime("%m/%Y"),
					"fehlend": result["fehlend"],
					"abweichungen": result["abweichungen"],
					"ueberfluessig": result["ueberfluessig"],
					"ok": result["ok"],
				}
			)

	return {
		"mietvertrag": mietvertrag,
		"monate": monate,
		"von": str(mv.von) if mv.von else None,
		"bis": str(mv.bis) if mv.bis else None,
		"aktivitaets_monate_geprueft": len(aktivitaet),
	}


@frappe.whitelist()
def get_korrigierbare_sollstellungen_fuer_mietvertrag(
	mietvertrag: str, scope: str | dict | None = None
) -> dict:
	"""Liefert gebuchte Sollstellungen, die nach einer Staffeländerung abweichen.

	``scope`` ordnet den geänderten Rechnungstyp dem frühesten betroffenen Monat
	zu, z.B. ``{"Miete": "2026-06-01"}``. So bietet der Mietvertrag nur die
	durch die konkrete Änderung betroffenen Rechnungsarten und Monate an und
	nicht zufällig vorhandene ältere Abweichungen anderer Staffeln.
	"""
	if isinstance(scope, str):
		try:
			scope = json.loads(scope)
		except (TypeError, ValueError):
			frappe.throw(_("Ungültiger Änderungsumfang für die Sollstellungsprüfung."))
	scope = scope or {}
	if not isinstance(scope, dict):
		frappe.throw(_("Ungültiger Änderungsumfang für die Sollstellungsprüfung."))

	normalized_scope: dict[str, date] = {}
	for typ, start in scope.items():
		if typ not in TYP_PARENTFIELD or not start:
			continue
		d = getdate(start)
		normalized_scope[typ] = date(d.year, d.month, 1)

	result = pruefe_mietvertrag(mietvertrag)
	candidates: list[dict] = []
	for month_result in result.get("monate") or []:
		for row in month_result.get("abweichungen") or []:
			if row.get("feld") != "betrag":
				continue
			candidates.append(row)
		for row in month_result.get("ueberfluessig") or []:
			candidates.append(row)

	filtered: list[dict] = []
	for row in candidates:
		invoice = row.get("sales_invoice")
		month_label = row.get("monat")
		if not invoice or not month_label:
			continue
		typ = row.get("typ")
		if normalized_scope and typ not in normalized_scope:
			continue
		month, year = (int(value) for value in month_label.split("/", 1))
		if typ in normalized_scope and date(year, month, 1) < normalized_scope[typ]:
			continue
		filtered.append(row)

	invoice_names = list(dict.fromkeys(row["sales_invoice"] for row in filtered))
	if invoice_names:
		submitted = set(
			frappe.get_all(
				"Sales Invoice",
				filters={"name": ("in", invoice_names), "docstatus": 1, "is_return": 0},
				pluck="name",
			)
		)
		invoice_names = [name for name in invoice_names if name in submitted]

	invoice_set = set(invoice_names)
	filtered = [row for row in filtered if row["sales_invoice"] in invoice_set]
	months = list(dict.fromkeys(row["monat"] for row in filtered))
	changes = [
		{
			"sales_invoice": row["sales_invoice"],
			"monat": row["monat"],
			"typ": row.get("typ"),
			"aktuell": row.get("aktuell", row.get("aktuell_betrag", 0)),
			"erwartet": row.get("erwartet", 0),
		}
		for row in filtered
	]
	return {
		"mietvertrag": mietvertrag,
		"sales_invoices": invoice_names,
		"monate": months,
		"anzahl": len(invoice_names),
		"aenderungen": changes,
	}
