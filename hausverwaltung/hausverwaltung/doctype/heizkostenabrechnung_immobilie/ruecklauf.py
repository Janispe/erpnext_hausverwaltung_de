"""Import the bved 3.10 D record for heating and hot water (cost code 231)."""

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import re

import frappe
from frappe.utils import getdate

from hausverwaltung.hausverwaltung.utils.booking_locks import lock_accounting_scope

from .heizkostenabrechnung_immobilie import (
	_create_mieter_drafts_for_parent,
	_get_owned_mieter_document,
	_lock_hk_property,
	_validate_mieter_period,
)

HEAD = "Heizkostenabrechnung Immobilie"
TENANT = "Heizkostenabrechnung Mieter"
FORMAT = "bved 3.10 D/231"
MAX_BYTES = 5 * 1024 * 1024
DAY = timedelta(days=1)


def _require(condition, message):
	if not condition:
		frappe.throw(message)


def _digest(value):
	return sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def _date(value):
	return date.fromisoformat(value)


def _euros(cents):
	return f"{Decimal(cents) / 100:.2f}"


def _parse(content, property_number, start, end):
	_require(0 < len(content) <= MAX_BYTES, "Die D-Datei muss zwischen 1 Byte und 5 MiB groß sein.")
	_require(re.fullmatch(r"[0-9]{9}", property_number or ""), "Bitte die neunstellige Messdienst-Liegenschaftsnummer eingeben.")
	lines = content.replace(b"\r\n", b"\n").split(b"\n")
	if lines[-1] == b"":
		lines.pop()
	rows = []
	seen = set()
	accounts = set()
	for number, raw in enumerate(lines, 1):
		def check(condition, reason):
			_require(condition, f"D-Datei, Zeile {number}: {reason}")

		line = raw.decode("iso-8859-15")
		check(len(line) == 1024 and line.startswith("D03.10") and line.endswith("D")
			and not line[263:1023].strip(" ") and not re.search(r"[\x00-\x1f\x7f-\x9f]", line), "D-Satz 03.10 mit 1024 Stellen erwartet.")
		account, provider, unit = line[6:16], line[16:18], line[18:31]
		check(re.fullmatch(r"[0-9]{10}", account) and re.fullmatch(r"[0-9]{13}", unit),
			"Kundennummer oder Messdienst-Ordnungsbegriff ungültig.")
		check(unit[:9] == property_number, "Die Messdienst-Liegenschaft stimmt nicht mit der Kontrollangabe überein.")
		accounts.add((account, provider))
		check(len(accounts) == 1, "Die Datei enthält mehrere Messdienstkonten.")
		identifier = line[31:51].rstrip(" ")
		check(identifier and not identifier.startswith(" "), "Auftraggeberkennung fehlt oder ist ungültig.")
		check(line[147:150] == "231" and line[200:203] == "EUR", "Unterstützt werden ausschließlich Kostenschlüssel 231 und EUR.")
		amount = line[57:67]
		check(re.fullmatch(r"(?:[0-9]{10}|-[0-9]{9})", amount), "Bruttokosten in Feld 8 fehlen oder sind ungültig.")
		day = line[51:57]
		try:
			if not re.fullmatch(r"[0-9]{6}", day):
				raise ValueError
			# Resolve the two-digit year within the billing period.
			years = [year for year in range(start.year, end.year + 1) if year % 100 == int(day[4:])]
			if len(years) != 1:
				raise ValueError
			until = datetime.strptime(day[:4] + f"{years[0]:04d}", "%d%m%Y").date()
		except ValueError:
			check(False, "Nutzungsende ist für den Abrechnungszeitraum ungültig.")
		check(start <= until <= end, "Nutzungsende liegt außerhalb des Abrechnungszeitraums.")
		check((unit, until) not in seen, "Für diese Messdienstwohnung und dieses Nutzungsende gibt es mehrere Sätze.")
		seen.add((unit, until))
		rows.append(dict(zeile=number, kennung=identifier, messdienst_wohnung=unit,
			messdienst_konto=account, messdienst_schluessel=provider.strip(),
			bis=until.isoformat(), betrag=_euros(int(amount)), cents=int(amount)))
	return rows


def _read_file(parent, name, *, lock):
	file = frappe.get_doc("File", name, for_update=lock)
	file.check_permission("read")
	_require(
		file.is_private and file.attached_to_doctype == HEAD and file.attached_to_name == parent.name
		and re.fullmatch(r"/private/files/[^/\\]+[.]dat", file.file_url or "", re.IGNORECASE),
		"Bitte eine private lokale DAT-Datei an dieser Heizkostenabrechnung anhängen.",
	)
	# Bound the read independently of the File metadata.
	with open(file.get_full_path(), "rb") as handle:
		return handle.read(MAX_BYTES + 1)


def _occupancy(parent, *, lock):
	contracts = frappe.db.sql(
		"""SELECT mv.name, mv.kunde, mv.wohnung, mv.von, mv.bis
		FROM `tabMietvertrag` mv JOIN `tabWohnung` w ON w.name = mv.wohnung
		WHERE w.immobilie = %(imm)s AND mv.docstatus < 2
		AND mv.von <= %(bis)s AND (mv.bis IS NULL OR mv.bis >= %(von)s)
		ORDER BY mv.name""" + (" FOR UPDATE" if lock else ""),
		{"imm": parent.immobilie, "von": parent.von, "bis": parent.bis}, as_dict=True,
	)
	start, end = getdate(parent.von), getdate(parent.bis)
	for contract in contracts:
		contract.von = max(start, getdate(contract.von))
		contract.bis = min(end, getdate(contract.bis)) if contract.bis else end
	return {contract.name: contract for contract in contracts}


def _vacancy(until, contracts, start, end):
	if any(contract.von <= until <= contract.bis for contract in contracts):
		return None
	next_start = min((contract.von for contract in contracts if contract.von > until), default=None)
	if until != (next_start - DAY if next_start else end):
		return None
	previous_end = max((contract.bis for contract in contracts if contract.bis < until), default=None)
	return previous_end + DAY if previous_end else start


def _map_rows(parent, rows, contracts, overrides, *, lock):
	_require(isinstance(overrides, dict) and set(overrides) <= {str(row["zeile"]) for row in rows},
		"Manuelle Zuordnungen müssen sich auf Zeilen dieser Datei beziehen.")
	by_unit = defaultdict(list)
	for contract in contracts.values():
		by_unit[contract.wohnung].append(contract)
	start, end = getdate(parent.von), getdate(parent.bis)
	by_contract = defaultdict(list)
	by_external_unit = defaultdict(list)
	by_local_unit = defaultdict(list)
	for row in rows:
		manual = overrides.get(str(row["zeile"]), {})
		_require(isinstance(manual, dict) and set(manual) <= {"mietvertrag", "leerstand"}
			and all(isinstance(value, str) and value for value in manual.values()) and len(manual) <= 1,
			"Pro Zeile ist genau ein manuelles Zuordnungsziel möglich.")
		until = _date(row["bis"])
		row.update(von=None, mietvertrag=None, wohnung=None, typ=None, grund=None, manuell=bool(manual))
		if unit := manual.get("leerstand"):
			property_name = frappe.db.get_value("Wohnung", unit, "immobilie", for_update=lock)
			since = _vacancy(until, by_unit[unit], start, end) if property_name == parent.immobilie else None
			if since is None:
				row["grund"] = "Die Wohnung liegt außerhalb der Immobilie oder das Nutzungsende passt zu keinem Leerstand."
				continue
			row.update(von=since.isoformat(), wohnung=unit, typ="Leerstand")
		else:
			contract = contracts.get(manual.get("mietvertrag", row["kennung"]))
			if not contract or contract.bis != until or not contract.kunde:
				row["grund"] = "Kein eindeutiger Mietvertrag dieser Immobilie mit passendem Nutzungsende und eigenem Customer."
				continue
			row.update(von=contract.von.isoformat(), wohnung=contract.wohnung, typ="Mietvertrag", mietvertrag=contract.name)
			by_contract[contract.name].append(row)
		by_external_unit[row["messdienst_wohnung"]].append(row)
		by_local_unit[row["wohnung"]].append(row)

	for mapped in by_contract.values():
		if len(mapped) > 1:
			for row in mapped:
				row["grund"] = "Der Mietvertrag ist mehreren Sätzen zugeordnet."
	for groups, field in ((by_external_unit, "wohnung"), (by_local_unit, "messdienst_wohnung")):
		for mapped in groups.values():
			if len({row[field] for row in mapped}) > 1:
				for row in mapped:
					row["grund"] = "Messdienstwohnung und ERP-Wohnung sind nicht eindeutig zugeordnet."
			sorted_rows = sorted(mapped, key=lambda row: row["von"])
			for first, second in zip(sorted_rows, sorted_rows[1:]):
				if first["bis"] >= second["von"]:
					first["grund"] = second["grund"] = "Die Nutzungszeiträume überschneiden sich."


def _children(parent, *, lock):
	return frappe.db.sql(
		"""SELECT name, mietvertrag, customer, wohnung, immobilie, von, bis, modified, docstatus,
		sales_invoice, credit_note
		FROM `tabHeizkostenabrechnung Mieter`
		WHERE heizkostenabrechnung_immobilie = %s AND docstatus < 2 ORDER BY name"""
		+ (" FOR UPDATE" if lock else ""), (parent.name,), as_dict=True,
	)


def _preview(parent, datei, liegenschaft, kontrollsumme, kontrollbeleg, zuordnungen, *, lock):
	_require(parent.immobilie and parent.von and parent.bis, "Bitte zuerst Immobilie und Abrechnungszeitraum speichern.")
	_require(re.fullmatch(r"-?[0-9]{1,14}(?:[.,][0-9]{1,2})?", str(kontrollsumme if kontrollsumme is not None else "")),
		"Bitte die unabhängige Bruttokontrollsumme in Euro mit höchstens zwei Nachkommastellen eingeben.")
	kontrollbeleg = (kontrollbeleg or "").strip()
	_require(0 < len(kontrollbeleg) <= 250, "Bitte die Quelle der Kontrollsumme angeben (höchstens 250 Zeichen).")
	control = int(Decimal(str(kontrollsumme).replace(",", ".")) * 100)
	content = _read_file(parent, datei, lock=lock)
	rows = _parse(content, liegenschaft, getdate(parent.von), getdate(parent.bis))
	contracts = _occupancy(parent, lock=lock)
	overrides = frappe.parse_json(zuordnungen) if isinstance(zuordnungen, str) else zuordnungen
	_map_rows(parent, rows, contracts, {} if overrides is None else overrides, lock=lock)
	children = _children(parent, lock=lock)
	errors = []
	total = sum(row["cents"] for row in rows)
	if total != control:
		errors.append("Die Summe der D-Sätze einschließlich Leerstand weicht von der Kontrollsumme ab.")
	if any(row["grund"] for row in rows):
		errors.append("Bitte alle offenen Zuordnungen klären.")
	mapped = {row["mietvertrag"] for row in rows if row["mietvertrag"] and not row["grund"]}
	if set(contracts) - mapped:
		errors.append("Für mindestens einen Mietvertrag im Abrechnungszeitraum fehlt ein eindeutig zugeordneter D-Satz.")
	if any(child.docstatus != 0 or child.sales_invoice or child.credit_note for child in children):
		errors.append("Mindestens eine Mieterabrechnung ist bereits eingereicht oder enthält einen Buchungsverweis.")
	if len({child.mietvertrag for child in children}) != len(children) or any(
		not (contract := contracts.get(child.mietvertrag)) or child.customer != contract.kunde
		or child.wohnung != contract.wohnung or child.immobilie != parent.immobilie
		or getdate(child.von) != getdate(parent.von) or getdate(child.bis) != getdate(parent.bis)
		for child in children
	):
		errors.append("Vorhandene Mieterentwürfe enthalten doppelte oder abweichende Stammdaten.")
	data = dict(format=FORMAT, datei=datei, sha256=sha256(content).hexdigest(),
		liegenschaft=liegenschaft, kontrollbeleg=kontrollbeleg, kontrollsumme=_euros(control),
		summe=_euros(total), leerstand_summe=_euros(sum(row["cents"] for row in rows if row["typ"] == "Leerstand")),
		zeilen=rows, fehler=errors)
	data["freigabe_id"] = _digest([parent.name, parent.modified, frappe.session.user, data, children])
	return data


def _get_parent(name, *, lock=False):
	parent = frappe.get_doc(HEAD, name, for_update=lock)
	parent.check_permission("read")
	parent.check_permission("write")
	_require(parent.docstatus == 0, "Ein Rücklauf kann nur in einen Abrechnungsentwurf übernommen werden.")
	return parent


@frappe.whitelist(methods=["POST"])
def vorschau(name, datei, liegenschaft, kontrollsumme, kontrollbeleg, zuordnungen=None):
	parent = _get_parent(name)
	_require(not parent.ruecklauf_import, "Dieser Entwurf hat bereits einen bestätigten Rücklauf.")
	return _preview(parent, datei, liegenschaft, kontrollsumme, kontrollbeleg, zuordnungen, lock=False)


@frappe.whitelist(methods=["POST"])
def uebernehmen(name, datei, liegenschaft, kontrollsumme, kontrollbeleg, freigabe_id, zuordnungen=None):
	# Match the lock order used by the existing draft creation and submission.
	lock_accounting_scope()
	_lock_hk_property(frappe.db.get_value(HEAD, name, "immobilie"))
	parent = _get_parent(name, lock=True)
	if parent.ruecklauf_import:
		previous = json.loads(parent.ruecklauf_import)
		_require(previous["freigabe_id"] == freigabe_id, "Dieser Entwurf hat bereits einen bestätigten Rücklauf.")
		return {"wiederholung": True}

	others = frappe.db.sql(
		"""SELECT name FROM `tabHeizkostenabrechnung Immobilie`
		WHERE immobilie = %(imm)s AND docstatus < 2 AND name != %(name)s
		AND von <= %(bis)s AND bis >= %(von)s
		AND (docstatus = 1 OR COALESCE(ruecklauf_import, '') != '') FOR UPDATE""",
		{"imm": parent.immobilie, "name": parent.name, "von": parent.von, "bis": parent.bis},
	)
	_require(not others, "Für einen überschneidenden Zeitraum besteht bereits ein bestätigter Rücklauf oder eine eingereichte Abrechnung.")
	data = _preview(parent, datei, liegenschaft, kontrollsumme, kontrollbeleg, zuordnungen, lock=True)
	_require(not data["fehler"], " ".join(data["fehler"]))
	_require(data["freigabe_id"] == freigabe_id, "Datei, Zuordnungen oder Entwurfsstand haben sich geändert. Bitte die Vorschau erneut prüfen.")

	point = "hk_ruecklauf_" + frappe.generate_hash(length=10)
	frappe.db.savepoint(point)
	try:
		_create_mieter_drafts_for_parent(parent)
		by_contract = {row["mietvertrag"]: row for row in data["zeilen"] if row["mietvertrag"]}
		for entry in _children(parent, lock=True):
			child = _get_owned_mieter_document(parent, entry.name)
			_validate_mieter_period(parent, child)
			_require(child.docstatus == 0, "Eine eingereichte Mieterabrechnung kann nicht überschrieben werden.")
			row = by_contract.pop(child.mietvertrag)
			child.kosten_gesamt = Decimal(row["betrag"])
			child.save()
			row["entwurf"] = child.name
		_require(not by_contract, "Mindestens ein erforderlicher Mieterentwurf fehlt.")
		parent._hydrate_positions_from_children()
		data.update(freigegeben_von=frappe.session.user, freigegeben_am=frappe.utils.now())
		parent.ruecklauf_import = json.dumps(data, ensure_ascii=False, indent=2)
		parent.flags.hk_ruecklauf_import = True
		parent.save()
	except Exception:
		frappe.db.rollback(save_point=point)
		raise
	return {"wiederholung": False}
