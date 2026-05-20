"""Kreditvertrag — Annuitätenplan mit Zins/Tilgungs-Split, gebucht beim Bankimport.

Anders als ein Zahlungsplan (eine PI pro Rate gegen ein Aufwandskonto) zerlegt
ein Kreditvertrag jede Rate in Zinsaufwand und Tilgung (Verbindlichkeits-Abbau).
Die Buchung erfolgt als Journal Entry, getriggert vom Bankauszug-Import beim
Match einer offenen Rate gegen die Bank Transaction.

Plan-Mode-Doc: ``.claude/plans/bitte-planen-async-boot.md``.
"""

from __future__ import annotations

import csv
import io
import re
from decimal import Decimal
from typing import Optional

import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import add_months, cint, flt, getdate, now_datetime, nowdate


STATUS_AKTIV = "Aktiv"
STATUS_ABGELOEST = "Abgelöst"
STATUS_VERGANGENHEIT = "Vergangenheit"

RESTSCHULD_EPSILON = 0.01

# Cap für Plan-Generator (50 Jahre monatlich)
MAX_PLAN_ROWS = 600


def _normalize_vertragsnummer(value: str) -> str:
	"""Macht eine Data-Vertragsnummer URL-/Name-fähig.

	Nur ``A-Z a-z 0-9`` erlauben, alles andere → ``-`` zusammengefasst, Trim
	an den Enden. Leerer Input und nur-Sonderzeichen ergeben ``""``.
	"""
	if not value:
		return ""
	return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-")


class Kreditvertrag(Document):
	def autoname(self):
		"""``KV-{vertragsnummer-norm}-{Auszahlungsjahr}-{####}`` mit graceful fallbacks.

		- voll: ``KV-1-2020-0001``
		- ohne Vertragsnummer: ``KV-2020-0001``
		- ohne Auszahlungsdatum: ``KV-1-0001``
		- ohne beides: ``KV-0001``

		Wichtig: ``laufzeit_start`` ist beim Insert oft noch ein ISO-String
		(Frappe konvertiert Date-Felder erst beim Save). Daher ``getdate()``
		zwingend vor ``.year``.
		"""
		nr = _normalize_vertragsnummer(self.vertragsnummer or "")
		start = getdate(self.laufzeit_start) if self.laufzeit_start else None
		parts = ["KV"]
		if nr:
			parts.append(nr)
		if start:
			parts.append(str(start.year))
		prefix = "-".join(parts)
		self.name = make_autoname(f"{prefix}-.####")

	def validate(self):
		# bezeichnung zuerst auto-fillen, damit nachgelagerte Logik den Wert sieht
		self._auto_fill_bezeichnung()
		self._validate_kontotypen()
		self._validate_zeilen()
		self._validate_keine_doppelverlinkung()
		self._sort_plan_and_reindex()
		self._compute_zeilen_summen()
		self._compute_restschuld_nach()
		self._compute_plausibilitaet()
		self._compute_status()

	def _auto_fill_bezeichnung(self):
		"""Generiert ``bezeichnung`` aus Lieferant + Immobilie + Vertragsnummer + Start.

		Nur wenn das Feld leer ist — manuell gesetzte oder vom Importer
		geschriebene Werte bleiben unangetastet.

		Lieferant-Name: ``Supplier.supplier_name`` (lesbar), Fallback auf
		``self.lieferant`` (Link-Wert).
		"""
		if (self.bezeichnung or "").strip():
			return
		lieferant_name = "Darlehen"
		if self.lieferant:
			supplier_name = frappe.db.get_value("Supplier", self.lieferant, "supplier_name")
			lieferant_name = supplier_name or self.lieferant
		immobilie_label = ""
		if self.immobilie:
			immobilie_label = (
				frappe.db.get_value("Immobilie", self.immobilie, "bezeichnung")
				or self.immobilie
			)
		parts = [f"Darlehen {lieferant_name}"]
		if immobilie_label:
			parts.append(f"– {immobilie_label}")  # noqa: RUF001
		vn = (self.vertragsnummer or "").strip()
		if vn or self.laufzeit_start:
			inner = []
			if vn:
				inner.append(f"Vertrag {vn}")
			if self.laufzeit_start:
				inner.append(f"Auszahlung {getdate(self.laufzeit_start):%d.%m.%Y}")
			parts.append(f"({', '.join(inner)})")
		self.bezeichnung = " ".join(parts)

	# ------------------------------------------------------------------
	# Validation Helpers
	# ------------------------------------------------------------------

	def _validate_kontotypen(self):
		if self.darlehenskonto:
			meta = frappe.db.get_value(
				"Account",
				self.darlehenskonto,
				["root_type", "account_type"],
				as_dict=True,
			)
			if not meta:
				frappe.throw(f"Darlehenskonto '{self.darlehenskonto}' existiert nicht.")
			if meta.root_type != "Liability":
				frappe.throw(
					f"Darlehenskonto '{self.darlehenskonto}' hat root_type '{meta.root_type}', "
					"erwartet 'Liability'. Bitte ein Verbindlichkeits-Konto wählen (z.B. 3300er Bereich)."
				)
			if meta.account_type:
				frappe.throw(
					f"Darlehenskonto '{self.darlehenskonto}' hat account_type '{meta.account_type}'. "
					"Für Kreditverträge muss der account_type LEER sein (insbesondere NICHT 'Payable'), "
					"sonst entstehen Payment Ledger Entries und der Open-Item-Ausgleich greift fälschlich."
				)

		if self.zinsaufwandskonto:
			rt = frappe.db.get_value("Account", self.zinsaufwandskonto, "root_type")
			if not rt:
				frappe.throw(f"Zinsaufwandskonto '{self.zinsaufwandskonto}' existiert nicht.")
			if rt != "Expense":
				frappe.throw(
					f"Zinsaufwandskonto '{self.zinsaufwandskonto}' hat root_type '{rt}', erwartet 'Expense'."
				)

	def _validate_keine_doppelverlinkung(self):
		"""Verhindert dass derselbe JE mehrfach mit Kreditraten verknüpft ist.

		Auf einem geteilten ``darlehenskonto`` (z.B. ``2000 - Darlehenstilgung Jürgen
		Peters - HP``, das alle 3 Wilhelmshavener-Kreditverträge nutzen) würde ein
		doppelt verlinkter JE in ``gl_getilgt`` beider Verträge auftauchen →
		Doppelzählung der Tilgung. Gleiches Risiko gilt für ``journal_entry_zins``
		auf einem geteilten Zinsaufwandskonto.

		Zwei Stufen:
		1. **In-Memory**: Im aktuellen, noch nicht persistierten Doc darf kein JE
		   in zwei verschiedenen Plan-Zeilen referenziert sein (auch nicht über
		   Tilg-Feld + Zins-Feld). Wird vor der SQL-Stufe geprüft, weil DB diese
		   Konflikte noch nicht sieht.
		2. **DB**: kein JE darf in einer Kreditrate eines anderen Vertrags hängen.

		Beide Stufen lösen ``frappe.throw`` aus.
		"""
		# Stufe 1: In-Memory-Konflikte (selbes Doc, selbe Save-Operation)
		seen: dict[str, tuple] = {}
		for row in self.get("plan") or []:
			for field in ("journal_entry", "journal_entry_zins"):
				je_name = row.get(field)
				if not je_name:
					continue
				if je_name in seen:
					prev_idx, prev_field = seen[je_name]
					frappe.throw(
						f"JE '{je_name}' ist mehrfach im selben Vertrag verlinkt: "
						f"Plan-Zeile {prev_idx} ({prev_field}) und Plan-Zeile "
						f"{row.idx} ({field}). Bitte einen der beiden Verweise "
						"entfernen — Doppelzählung würde `gl_getilgt` verfälschen."
					)
				seen[je_name] = (row.idx, field)

		# Stufe 2: Konflikte gegen andere Verträge / persistierte Zeilen
		for row in self.get("plan") or []:
			for field in ("journal_entry", "journal_entry_zins"):
				je_name = row.get(field)
				if not je_name:
					continue
				other = frappe.db.sql(
					"""
					SELECT name, parent
					FROM `tabKreditrate`
					WHERE (journal_entry = %(je)s OR journal_entry_zins = %(je)s)
					  AND (parent != %(parent)s OR name != %(row_name)s)
					LIMIT 1
					""",
					{
						"je": je_name,
						"parent": self.name or "",
						"row_name": row.name or "",
					},
					as_dict=True,
				)
				if other:
					frappe.throw(
						f"Plan-Zeile {row.idx} ({field}): JE '{je_name}' ist bereits in "
						f"Kreditrate '{other[0].name}' (Vertrag '{other[0].parent}') "
						"verknüpft. Doppelverlinkung würde Doppelzählung in `gl_getilgt` "
						"erzeugen — bitte den anderen Verweis vorher entfernen."
					)

	def _validate_zeilen(self):
		seen_dates: set[str] = set()
		for row in self.get("plan") or []:
			if not row.get("faelligkeitsdatum"):
				frappe.throw(f"Plan-Zeile {row.idx}: Fälligkeitsdatum fehlt.")
			for fieldname in ("zinsanteil", "tilgungsanteil", "sondertilgung"):
				v = flt(row.get(fieldname))
				if v < 0:
					frappe.throw(
						f"Plan-Zeile {row.idx}: '{fieldname}' darf nicht negativ sein ({v})."
					)
			key = str(getdate(row.faelligkeitsdatum))
			if key in seen_dates:
				frappe.throw(f"Plan enthält das Fälligkeitsdatum {key} mehrfach.")
			seen_dates.add(key)

	def _sort_plan_and_reindex(self):
		"""Sortiert plan nach faelligkeitsdatum und vergibt idx neu.

		Wichtig: Beim CSV-Import oder Generator können Zeilen in beliebiger
		Reihenfolge ankommen. restschuld_nach hängt vom kumulativen Verlauf
		ab, deshalb muss vorher sortiert werden.
		"""
		rows = list(self.get("plan") or [])
		if not rows:
			return
		rows.sort(key=lambda r: getdate(r.faelligkeitsdatum))
		for new_idx, row in enumerate(rows, start=1):
			row.idx = new_idx
		self.set("plan", rows)

	def _compute_zeilen_summen(self):
		for row in self.get("plan") or []:
			row.gesamtbetrag = flt(row.zinsanteil) + flt(row.tilgungsanteil) + flt(row.sondertilgung)

	def _compute_restschuld_nach(self):
		restschuld = flt(self.anfangs_restschuld)
		for row in self.get("plan") or []:
			restschuld = restschuld - flt(row.tilgungsanteil) - flt(row.sondertilgung)
			row.restschuld_nach = restschuld

	def _compute_plausibilitaet(self):
		"""Plausibilitäts-Felder berechnen.

		Der **Plan** ist die fachliche Quelle (``plan_getilgt`` →
		``aktuelle_restschuld``). Die Buchhaltung wird dagegen geprüft:
		``gl_getilgt`` summiert die Soll-Buchungen auf dem Darlehenskonto
		**nur über die JEs, die via Plan-Zeilen verlinkt sind** — damit ist
		der Check pro Kreditvertrag korrekt, auch wenn mehrere Kredite
		dasselbe GL-Konto teilen.

		``restschuld_abweichung = plan_getilgt − gl_getilgt`` (SOLL ≈ 0).
		Eine Abweichung bedeutet: ein verlinkter JE wurde nach dem Buchen
		verändert oder eine Rate nachträglich editiert.

		``gl_saldo_darlehenskonto`` (Gesamt-Konto-Saldo) bleibt erhalten,
		ist aber nur noch Info — bei geteiltem Konto nicht pro Kredit
		aussagekräftig.
		"""
		# Plan-Seite: Σ(tilgung + sondertilgung) der gebuchten Raten + verlinkte JE-Namen
		plan_getilgt = Decimal("0")
		linked_je_names: list[str] = []
		for row in self.get("plan") or []:
			if row.get("journal_entry"):
				plan_getilgt += Decimal(str(flt(row.tilgungsanteil))) + Decimal(
					str(flt(row.sondertilgung))
				)
				linked_je_names.append(row.journal_entry)

		aktuelle = Decimal(str(flt(self.anfangs_restschuld))) - plan_getilgt
		self.aktuelle_restschuld = float(aktuelle)
		self.plan_getilgt = float(plan_getilgt)

		# GL-Seite: Σ debit auf dem Darlehenskonto — NUR über die verlinkten JEs
		# dieses Kreditvertrags (shared-account-safe).
		gl_getilgt = 0.0
		if self.darlehenskonto and self.company and linked_je_names:
			row = frappe.db.sql(
				"""
				SELECT COALESCE(SUM(debit), 0) AS getilgt
				FROM `tabGL Entry`
				WHERE account = %(account)s
				  AND company = %(company)s
				  AND voucher_type = 'Journal Entry'
				  AND voucher_no IN %(je_names)s
				  AND is_cancelled = 0
				""",
				{
					"account": self.darlehenskonto,
					"company": self.company,
					"je_names": tuple(linked_je_names),
				},
				as_dict=True,
			)
			gl_getilgt = flt(row[0].getilgt) if row else 0.0
		self.gl_getilgt = gl_getilgt
		self.restschuld_abweichung = float(plan_getilgt) - gl_getilgt

		# GL-Saldo des gesamten Darlehenskontos (Liability = credit − debit) — nur Info.
		gl_saldo = 0.0
		if self.darlehenskonto and self.company:
			row = frappe.db.sql(
				"""
				SELECT COALESCE(SUM(credit), 0) - COALESCE(SUM(debit), 0) AS saldo
				FROM `tabGL Entry`
				WHERE account = %(account)s
				  AND company = %(company)s
				  AND is_cancelled = 0
				""",
				{"account": self.darlehenskonto, "company": self.company},
				as_dict=True,
			)
			gl_saldo = flt(row[0].saldo) if row else 0.0
		self.gl_saldo_darlehenskonto = gl_saldo

	def _compute_status(self):
		rows = self.get("plan") or []
		has_open_rates = any(not r.get("journal_entry") for r in rows)
		has_future_rates = any(
			r.get("faelligkeitsdatum") and getdate(r.faelligkeitsdatum) >= getdate(nowdate())
			for r in rows
		)
		aktuelle = flt(self.aktuelle_restschuld)

		# Counter + nächste Fälligkeit (Listen-Felder).
		# `naechste_faelligkeit` umfasst auch überfällige offene Raten — im Alltag
		# ist das genau, was im Listen-View sichtbar sein muss.
		self.offene_raten = sum(1 for r in rows if not r.get("journal_entry"))
		open_dates = sorted(
			getdate(r.faelligkeitsdatum)
			for r in rows
			if not r.get("journal_entry") and r.get("faelligkeitsdatum")
		)
		self.naechste_faelligkeit = open_dates[0] if open_dates else None

		if rows and not has_open_rates and abs(aktuelle) <= RESTSCHULD_EPSILON:
			self.status = STATUS_ABGELOEST
		elif has_open_rates or has_future_rates or aktuelle > RESTSCHULD_EPSILON:
			self.status = STATUS_AKTIV
		else:
			self.status = STATUS_VERGANGENHEIT

	# ------------------------------------------------------------------
	# Whitelist-Methoden: Plan-Vorbelegung & CSV-Import
	# ------------------------------------------------------------------

	@frappe.whitelist()
	def plan_vorbelegen(
		self,
		start: str,
		ende: str,
		zinssatz_p_a: float,
		annuitaet: float,
		replace: int | bool = 0,
	) -> dict:
		"""Generiert Tilgungsplan-Zeilen per Annuitätenformel.

		**Anfangsschuld kommt zwingend aus** ``self.anfangs_restschuld`` — der
		Dialog darf keinen abweichenden Wert mitschicken, weil
		``_compute_restschuld_nach`` beim Save mit ``self.anfangs_restschuld``
		rechnet. Würden Generator und Compute mit unterschiedlichen Werten
		starten, driften die ``restschuld_nach``-Werte sofort auseinander.

		Pro Monat:
		  zins = restschuld * (zinssatz_p_a / 100 / 12)
		  tilgung = min(annuitaet - zins, restschuld)
		  restschuld -= tilgung
		"""
		self.check_permission("write")

		start_d = getdate(start)
		ende_d = getdate(ende)
		if ende_d < start_d:
			frappe.throw("'Ende' darf nicht vor 'Start' liegen.")
		anfangsschuld = flt(self.anfangs_restschuld)
		zinssatz = flt(zinssatz_p_a)
		annuitaet_betrag = flt(annuitaet)
		if anfangsschuld <= 0:
			frappe.throw(
				"Anfangs-Restschuld am Kreditvertrag muss positiv sein, bevor der Plan "
				"generiert werden kann. Bitte das Feld 'Anfangs-Restschuld' setzen."
			)
		if annuitaet_betrag <= 0:
			frappe.throw("Annuität muss positiv sein.")

		monthly_rate = zinssatz / 100.0 / 12.0

		if cint(replace):
			self.set("plan", [])

		existing = {
			str(getdate(r.faelligkeitsdatum))
			for r in (self.get("plan") or [])
			if r.get("faelligkeitsdatum")
		}

		restschuld = anfangsschuld
		current = start_d
		added = 0
		skipped = 0
		while current <= ende_d and (added + skipped) < MAX_PLAN_ROWS and restschuld > RESTSCHULD_EPSILON:
			key = str(current)
			zins = round(restschuld * monthly_rate, 2)
			tilgung = round(min(annuitaet_betrag - zins, restschuld), 2)
			if tilgung < 0:
				# Annuität deckt nicht mal den Zins — kann nicht sauber tilgen
				frappe.throw(
					f"Annuität {annuitaet_betrag:.2f} EUR ist kleiner als die monatliche "
					f"Zinslast {zins:.2f} EUR bei Restschuld {restschuld:.2f} EUR — "
					"Plan kann nicht aufgebaut werden."
				)

			if key not in existing:
				self.append(
					"plan",
					{
						"faelligkeitsdatum": current,
						"zinsanteil": zins,
						"tilgungsanteil": tilgung,
						"sondertilgung": 0,
					},
				)
				existing.add(key)
				added += 1
			else:
				skipped += 1

			restschuld = round(restschuld - tilgung, 2)
			current = getdate(add_months(current, 1))

		self.save(ignore_permissions=True)
		return {"added": added, "skipped": skipped, "total_rows": len(self.get("plan") or [])}

	@frappe.whitelist()
	def plan_csv_import(self, file_url: str, mode: str = "extend") -> dict:
		"""Importiert einen Tilgungsplan aus einer hochgeladenen CSV-Datei.

		Spalten (case-insensitive): datum, zinsanteil, tilgungsanteil,
		optional sondertilgung, optional restschuld (zur Cross-Validation).
		Delimiter ; oder , wird automatisch erkannt. Beträge mit Punkt oder Komma.
		"""
		self.check_permission("write")

		if mode not in ("extend", "replace"):
			frappe.throw(f"Ungültiger mode: {mode!r} (erwartet 'extend' oder 'replace').")

		if not file_url:
			frappe.throw("Keine Datei angegeben.")

		# Explizites Two-Step-Lookup: erst Name via Filter holen, dann Doc laden.
		# ``frappe.get_doc("File", {"file_url": ...})`` interpretiert das Dict als
		# Name-Lookup (nicht als Filter) und scheitert.
		file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
		if not file_name:
			frappe.throw(f"Datei mit file_url={file_url!r} nicht gefunden.")
		file_doc = frappe.get_doc("File", file_name)
		# Permission-Check für private Files
		file_doc.check_permission("read")
		content_bytes = file_doc.get_content()
		if isinstance(content_bytes, bytes):
			try:
				content = content_bytes.decode("utf-8-sig")
			except UnicodeDecodeError:
				content = content_bytes.decode("latin-1")
		else:
			content = content_bytes

		# Delimiter auto-detect
		first_line = content.splitlines()[0] if content else ""
		if first_line.count(";") > first_line.count(","):
			delimiter = ";"
		else:
			delimiter = ","

		reader = csv.DictReader(io.StringIO(content), delimiter=delimiter)
		if not reader.fieldnames:
			frappe.throw("CSV ohne Header — bitte Spaltennamen in der ersten Zeile angeben.")

		# Header-Mapping (case-insensitive, akzeptiere alternative Namen)
		header_map: dict[str, str] = {}
		for h in reader.fieldnames:
			key = (h or "").strip().lower()
			if key in ("datum", "date", "faelligkeit", "fälligkeit"):
				header_map["datum"] = h
			elif key in ("zins", "zinsanteil", "interest"):
				header_map["zinsanteil"] = h
			elif key in ("tilgung", "tilgungsanteil", "principal"):
				header_map["tilgungsanteil"] = h
			elif key in ("sondertilgung", "extra"):
				header_map["sondertilgung"] = h
			elif key in ("restschuld", "balance", "saldo"):
				header_map["restschuld"] = h

		for required in ("datum", "zinsanteil", "tilgungsanteil"):
			if required not in header_map:
				frappe.throw(
					f"Pflicht-Spalte '{required}' fehlt im CSV (gefundene: {reader.fieldnames!r})."
				)

		if mode == "replace":
			self.set("plan", [])

		existing_dates = {
			str(getdate(r.faelligkeitsdatum))
			for r in (self.get("plan") or [])
			if r.get("faelligkeitsdatum")
		}

		added = 0
		skipped = 0
		errors: list[str] = []
		balance_warnings: list[str] = []

		for line_no, raw in enumerate(reader, start=2):
			try:
				datum_str = (raw.get(header_map["datum"]) or "").strip()
				if not datum_str:
					skipped += 1
					continue
				datum = getdate(datum_str)
				zins = _parse_amount(raw.get(header_map["zinsanteil"]))
				tilgung = _parse_amount(raw.get(header_map["tilgungsanteil"]))
				sondertilgung = 0.0
				if "sondertilgung" in header_map:
					sondertilgung = _parse_amount(raw.get(header_map["sondertilgung"]))
				csv_restschuld = None
				if "restschuld" in header_map:
					csv_restschuld = _parse_amount(raw.get(header_map["restschuld"]), allow_empty=True)
			except Exception as exc:
				errors.append(f"Zeile {line_no}: {exc}")
				continue

			key = str(datum)
			if key in existing_dates:
				skipped += 1
				continue

			self.append(
				"plan",
				{
					"faelligkeitsdatum": datum,
					"zinsanteil": zins,
					"tilgungsanteil": tilgung,
					"sondertilgung": sondertilgung,
				},
			)
			existing_dates.add(key)
			added += 1

			if csv_restschuld is not None:
				# Cross-Validation: nach validate() wird restschuld_nach gesetzt; hier
				# tracken wir nur die CSV-Erwartung pro Datum, der Vergleich passiert
				# nach save() unten.
				balance_warnings.append(f"__expect__:{key}:{csv_restschuld}")

		if errors:
			frappe.throw("CSV-Fehler:\n" + "\n".join(errors))

		self.save(ignore_permissions=True)

		# Cross-Validation gegen restschuld_nach (das jetzt berechnet ist)
		mismatches: list[dict] = []
		if balance_warnings:
			expected_map: dict[str, float] = {}
			for w in balance_warnings:
				_, key, val = w.split(":", 2)
				expected_map[key] = float(val)
			for row in self.get("plan") or []:
				if not row.get("faelligkeitsdatum"):
					continue
				key = str(getdate(row.faelligkeitsdatum))
				if key in expected_map:
					expected = expected_map[key]
					actual = flt(row.restschuld_nach)
					if abs(expected - actual) > RESTSCHULD_EPSILON:
						mismatches.append(
							{
								"datum": key,
								"erwartet": expected,
								"berechnet": actual,
								"differenz": round(expected - actual, 2),
							}
						)

		return {
			"added": added,
			"skipped": skipped,
			"total_rows": len(self.get("plan") or []),
			"restschuld_mismatches": mismatches,
		}


# ----------------------------------------------------------------------
# Module-level Scheduler & Utility-Funktionen
# ----------------------------------------------------------------------


def update_statuses_for_list():
	"""Daily Scheduler: Status für alle Kreditverträge neu berechnen.

	Notwendig, weil sonst nach Datum-Übergang `status=Aktiv` bleibt, bis das
	Doc das nächste Mal manuell gespeichert wird.
	"""
	for name in frappe.get_all("Kreditvertrag", pluck="name"):
		try:
			doc = frappe.get_doc("Kreditvertrag", name)
			old_status = doc.status
			doc._compute_plausibilitaet()
			doc._compute_status()
			if doc.status != old_status:
				doc.db_set("status", doc.status, update_modified=False)
			# Plausibilitäts-Felder aktualisieren (für Dashboard-Indicator)
			doc.db_set("aktuelle_restschuld", doc.aktuelle_restschuld, update_modified=False)
			doc.db_set("plan_getilgt", doc.plan_getilgt, update_modified=False)
			doc.db_set("gl_getilgt", doc.gl_getilgt, update_modified=False)
			doc.db_set("gl_saldo_darlehenskonto", doc.gl_saldo_darlehenskonto, update_modified=False)
			doc.db_set("restschuld_abweichung", doc.restschuld_abweichung, update_modified=False)
			# Listen-Felder: Counter + nächste Fälligkeit
			doc.db_set("offene_raten", doc.offene_raten, update_modified=False)
			doc.db_set("naechste_faelligkeit", doc.naechste_faelligkeit, update_modified=False)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"Kreditvertrag Status-Update fehlgeschlagen: {name}",
			)


# ----------------------------------------------------------------------
# Journal-Entry-Erzeugung & Match-Helper für Bankimport
# ----------------------------------------------------------------------


def _create_journal_entry_for_rate(
	doc: "Kreditvertrag",
	row: Document,
	posting_date,
	cheque_no: Optional[str] = None,
) -> Document:
	"""Erzeugt einen submitted Journal Entry für eine Kreditrate.

	Buchungssatz (im Beispiel: Auszahlung der Rate):
	  Cr.  Bankkonto                                 gesamtbetrag
	  Dr.  Zinsaufwandskonto                          zinsanteil       (entfällt wenn 0)
	  Dr.  Darlehenskonto (Liability, party=Bank)     tilgung+sondertilgung  (entfällt wenn 0)

	``voucher_type = "Bank Entry"`` erfordert in ERPNext zwingend ``cheque_no``
	+ ``cheque_date``. ``cheque_no`` Default: Bank-Transaction-Name aus dem
	Aufrufer (falls vorhanden) oder eine ableitbare Kennung aus dem Kreditvertrag.

	Wir setzen ``custom_remark = 1`` plus ``remark = user_remark``, damit
	Journal Entry.create_remarks() unseren Verwendungszweck nicht überschreibt
	(vgl. payment_auto_match.create_journal_entry_for_bt).
	"""
	if not doc.bank_account:
		frappe.throw("Kreditvertrag ohne Bankkonto kann nicht gebucht werden.")
	if not doc.darlehenskonto:
		frappe.throw("Kreditvertrag ohne Darlehenskonto kann nicht gebucht werden.")
	if not doc.zinsaufwandskonto:
		frappe.throw("Kreditvertrag ohne Zinsaufwandskonto kann nicht gebucht werden.")

	bank_acc_gl = frappe.get_cached_value("Bank Account", doc.bank_account, "account")
	if not bank_acc_gl:
		frappe.throw(f"Bank Account '{doc.bank_account}' hat kein GL-Konto hinterlegt.")

	gesamt = flt(row.gesamtbetrag)
	if gesamt <= 0:
		frappe.throw(
			f"Plan-Zeile {row.idx}: Gesamtbetrag muss positiv sein "
			"(zinsanteil + tilgungsanteil + sondertilgung)."
		)

	user_remark = f"Kredit {doc.bezeichnung} – Rate vom {row.faelligkeitsdatum}"

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Bank Entry"
	je.company = doc.company
	je.posting_date = getdate(posting_date)
	# Bank Entry verlangt cheque_no + cheque_date (sonst validate_cheque_info Throw)
	je.cheque_no = cheque_no or f"{doc.name}-R{row.idx}"
	je.cheque_date = getdate(posting_date)
	# custom_wertstellungsdatum existiert als Custom Field auf Journal Entry
	# (apps/hausverwaltung/hausverwaltung/custom/journal_entry.json)
	if frappe.get_meta("Journal Entry").get_field("custom_wertstellungsdatum"):
		je.custom_wertstellungsdatum = row.faelligkeitsdatum
	je.user_remark = user_remark
	je.remark = user_remark
	je.custom_remark = 1

	# Cr. Bankkonto (Asset)
	je.append(
		"accounts",
		{
			"account": bank_acc_gl,
			"credit_in_account_currency": gesamt,
			"cost_center": doc.cost_center,
		},
	)

	# Dr. Zinsaufwand — Null-Zeile vermeiden
	zins = flt(row.zinsanteil)
	if zins > 0:
		je.append(
			"accounts",
			{
				"account": doc.zinsaufwandskonto,
				"debit_in_account_currency": zins,
				"cost_center": doc.cost_center,
			},
		)

	# Dr. Darlehenskonto (Liability, Party=Bank-Supplier)
	tilgung_total = flt(row.tilgungsanteil) + flt(row.sondertilgung)
	if tilgung_total > 0:
		je.append(
			"accounts",
			{
				"account": doc.darlehenskonto,
				"party_type": "Supplier",
				"party": doc.lieferant,
				"debit_in_account_currency": tilgung_total,
				"cost_center": doc.cost_center,
			},
		)

	je.insert(ignore_permissions=True)
	je.submit()
	return je


def _candidate_rates(
	bank_account: str,
	amount: float,
	posting_date,
	tolerance_amount: float = 0.01,
	supplier: Optional[str] = None,
	reference_text: Optional[str] = None,
) -> list[dict]:
	"""Sucht offene, betrags- und datumsnahe Kreditraten.

	Status wird bewusst NICHT als Hard-Filter verwendet (kann stale sein) — die
	echte Wahrheit ist ``journal_entry IS NULL``. ``supplier`` ist ein **Soft-
	Filter**: Alle KVs am Bankkonto werden geprüft; matchen ausschließlich
	Kandidaten von einem anderen Supplier, gewinnen die trotzdem (z.B. wenn
	der Supplier auf der Bankzeile falsch erkannt wurde). Wenn aber Kandidaten
	mit passendem Supplier existieren, werden NUR diese zurückgegeben —
	der Supplier-Hint wird als Disambiguierung genutzt, nicht als Ausschluss.
	"""
	if not bank_account or amount is None:
		return []

	target_amount = abs(flt(amount))
	target_date = getdate(posting_date) if posting_date else None
	hints = _extract_loan_match_hints(reference_text)

	# Immer alle Kreditverträge am Bankkonto laden — Supplier ist Soft-Filter.
	kv_names = frappe.get_all(
		"Kreditvertrag",
		filters={"bank_account": bank_account},
		pluck="name",
	)

	candidates: list[dict] = []
	for kv_name in kv_names:
		kv = frappe.get_doc("Kreditvertrag", kv_name)
		tolerance_days = cint(kv.match_tolerance_days) or 7
		for row in kv.get("plan") or []:
			if row.get("journal_entry"):
				continue
			if not row.get("faelligkeitsdatum"):
				continue
			row_amount = abs(flt(row.gesamtbetrag))
			if abs(row_amount - target_amount) > tolerance_amount:
				continue
			if target_date:
				delta = abs((getdate(row.faelligkeitsdatum) - target_date).days)
				if delta > tolerance_days:
					continue
			else:
				delta = 9999
			candidates.append(
				{
					"kreditvertrag": kv_name,
					"row_name": row.name,
					"row_idx": row.idx,
					"faelligkeitsdatum": row.faelligkeitsdatum,
					"gesamtbetrag": flt(row.gesamtbetrag),
					"zinsanteil": flt(row.zinsanteil),
					"tilgungsanteil": flt(row.tilgungsanteil),
					"sondertilgung": flt(row.sondertilgung),
					"delta_days": delta,
					"supplier_match": bool(supplier and kv.lieferant == supplier),
					"vertragsnummer_match": bool(
						hints.get("vertragsnummer")
						and _normalize_match_token(kv.get("vertragsnummer"))
						== hints["vertragsnummer"]
					),
					"split_match": _loan_split_matches(row, hints, tolerance_amount),
					"_kv_doc": kv,
					"_row_doc": row,
				}
			)

	if hints.get("vertragsnummer"):
		contract_matches = [c for c in candidates if c["vertragsnummer_match"]]
		if contract_matches:
			candidates = contract_matches

	if hints.get("zinsanteil") is not None or hints.get("tilgungsanteil") is not None:
		split_matches = [c for c in candidates if c["split_match"]]
		if split_matches:
			candidates = split_matches

	# Soft-Filter: wenn Supplier auf der Bankzeile erkannt UND mindestens ein
	# Kandidat mit passendem Supplier existiert, schließen wir die anderen aus.
	# Wenn KEIN Kandidat zum erkannten Supplier passt, behalten wir alle
	# (der erkannte Supplier war wahrscheinlich falsch).
	if supplier:
		supplier_matches = [c for c in candidates if c["supplier_match"]]
		if supplier_matches:
			candidates = supplier_matches

	candidates.sort(key=lambda c: c["delta_days"])
	return candidates


def link_bank_transaction_to_kreditvertrag_rate(
	*,
	bank_account: str,
	posting_date,
	amount: float,
	bank_transaction: str,
	supplier: Optional[str] = None,
	reference_text: Optional[str] = None,
) -> Optional[dict]:
	"""Auto-Match-Hook für Bankauszug Import.

	**Konservative Auto-Buchung:** Nur bei **genau einem** passenden Kandidaten
	wird gebucht. Bei 0 oder ≥2 Treffern wird die Kandidatenliste zurück­
	gegeben — der Nutzer entscheidet manuell via Dialog.
	"""
	candidates = _candidate_rates(
		bank_account=bank_account,
		amount=amount,
		posting_date=posting_date,
		supplier=supplier,
		reference_text=reference_text,
	)

	def _serialize(cs):
		return [
			{
				"kreditvertrag": c["kreditvertrag"],
				"row_name": c["row_name"],
				"row_idx": c["row_idx"],
				"faelligkeitsdatum": str(c["faelligkeitsdatum"]),
				"gesamtbetrag": c["gesamtbetrag"],
				"delta_days": c["delta_days"],
				"vertragsnummer_match": c.get("vertragsnummer_match"),
				"split_match": c.get("split_match"),
			}
			for c in cs
		]

	if len(candidates) != 1:
		statement_result = _create_or_book_rate_from_statement(
			bank_account=bank_account,
			posting_date=posting_date,
			amount=amount,
			bank_transaction=bank_transaction,
			supplier=supplier,
			reference_text=reference_text,
		)
		if statement_result:
			return statement_result
		return {"match_count": len(candidates), "candidates": _serialize(candidates)}

	best = candidates[0]
	kv: Kreditvertrag = best["_kv_doc"]
	rate_row: Document = best["_row_doc"]

	result = _book_rate_row_and_reconcile(
		kv=kv,
		rate_row=rate_row,
		posting_date=posting_date,
		amount=amount,
		bank_transaction=bank_transaction,
		savepoint_name="kv_match",
	)
	result.update(
		{
			"match_count": 1,
			"kreditvertrag": kv.name,
			"row_name": rate_row.name,
			"row_idx": rate_row.idx,
			"faelligkeitsdatum": str(rate_row.faelligkeitsdatum),
			"gesamtbetrag": flt(rate_row.gesamtbetrag),
			"created_from_statement": False,
		}
	)
	return result


def _book_rate_row_and_reconcile(
	*,
	kv: "Kreditvertrag",
	rate_row: Document,
	posting_date,
	amount: float,
	bank_transaction: str,
	savepoint_name: str,
	create_savepoint: bool = True,
) -> dict:
	# Savepoint um JE+Reconcile+Link: wenn nach JE-Submit etwas fehlschlägt,
	# rollen wir auf den Savepoint zurück und cancel'n den JE. So bleiben
	# keine verwaisten Buchungen liegen.
	if create_savepoint:
		frappe.db.savepoint(savepoint_name)
	je = None
	try:
		# Beim Auto-Match ist die Bank Transaction der natürliche cheque_no
		je = _create_journal_entry_for_rate(
			kv, rate_row, posting_date=posting_date, cheque_no=bank_transaction
		)

		from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
			reconcile_voucher_with_bt,
		)

		bt = frappe.get_doc("Bank Transaction", bank_transaction)
		reconcile_voucher_with_bt(bt, "Journal Entry", je.name, abs(flt(amount)))

		rate_row.db_set("journal_entry", je.name, update_modified=False)
		rate_row.db_set("bank_transaction", bank_transaction, update_modified=False)
		rate_row.db_set("gebucht_am", getdate(posting_date), update_modified=False)
	except Exception:
		# JE submitted? Dann stornieren, sonst bleibt verwaiste Buchung hängen.
		frappe.db.rollback(save_point=savepoint_name)
		if je and je.name and frappe.db.exists("Journal Entry", je.name):
			try:
				je_doc = frappe.get_doc("Journal Entry", je.name)
				if je_doc.docstatus == 1:
					je_doc.cancel()
			except Exception:
				frappe.log_error(
					frappe.get_traceback(),
					f"Kredit-Match: konnte verwaisten JE {je.name} nicht stornieren",
				)
		raise

	# Parent-Plausibilitäts-Felder + Status nachziehen (sonst stale bis nächster Save)
	_recompute_parent_plausibilitaet(kv.name)

	return {
		"journal_entry": je.name,
	}


def _create_or_book_rate_from_statement(
	*,
	bank_account: str,
	posting_date,
	amount: float,
	bank_transaction: str,
	supplier: Optional[str] = None,
	reference_text: Optional[str] = None,
	tolerance_amount: float = 0.01,
) -> Optional[dict]:
	hints = _extract_loan_match_hints(reference_text)
	if not _loan_hints_are_complete(hints):
		return None

	contracts = _find_kreditvertraege_for_statement(
		bank_account=bank_account,
		vertragsnummer=hints["vertragsnummer"],
		supplier=supplier,
	)
	if len(contracts) != 1:
		return None

	target_amount = abs(flt(amount))
	if abs((flt(hints["zinsanteil"]) + flt(hints["tilgungsanteil"])) - target_amount) > tolerance_amount:
		return {
			"match_count": 0,
			"blocked": True,
			"reason": "statement_split_amount_mismatch",
			"message": (
				"Zins-/Tilgungs-Split aus dem Kontoauszug passt nicht zum Bankbetrag "
				f"({flt(hints['zinsanteil']) + flt(hints['tilgungsanteil']):.2f} != "
				f"{target_amount:.2f})."
			),
		}

	kv: Kreditvertrag = contracts[0]
	target_date = getdate(posting_date)
	open_period_rows = [
		row
		for row in kv.get("plan") or []
		if not row.get("journal_entry") and _same_month(row.get("faelligkeitsdatum"), target_date)
	]
	exact_period_rows = [
		row
		for row in open_period_rows
		if _loan_split_matches(row, hints, tolerance_amount)
		and abs(abs(flt(row.gesamtbetrag)) - target_amount) <= tolerance_amount
	]

	if len(exact_period_rows) == 1:
		rate_row = exact_period_rows[0]
		result = _book_rate_row_and_reconcile(
			kv=kv,
			rate_row=rate_row,
			posting_date=posting_date,
			amount=amount,
			bank_transaction=bank_transaction,
			savepoint_name="kv_statement_existing",
		)
		result.update(
			{
				"match_count": 1,
				"kreditvertrag": kv.name,
				"row_name": rate_row.name,
				"row_idx": rate_row.idx,
				"faelligkeitsdatum": str(rate_row.faelligkeitsdatum),
				"gesamtbetrag": flt(rate_row.gesamtbetrag),
				"created_from_statement": False,
			}
		)
		return result

	if len(exact_period_rows) > 1:
		return {
			"match_count": 0,
			"blocked": True,
			"reason": "multiple_period_rates",
			"kreditvertrag": kv.name,
			"message": "Mehrere passende Kreditraten im Zeitraum - bitte manuell prüfen.",
		}

	if open_period_rows:
		return {
			"match_count": 0,
			"blocked": True,
			"reason": "period_rate_mismatch",
			"kreditvertrag": kv.name,
			"message": (
				"Offene Kreditrate im Zeitraum vorhanden, aber Betrag/Split weicht "
				"vom Kontoauszug ab - bitte Kreditvertrag prüfen."
			),
		}

	if any(
		not row.get("journal_entry")
		and row.get("faelligkeitsdatum")
		and getdate(row.get("faelligkeitsdatum")) > target_date
		for row in kv.get("plan") or []
	):
		return {
			"match_count": 0,
			"blocked": True,
			"reason": "future_plan_rows",
			"kreditvertrag": kv.name,
			"message": (
				"Kreditrate nicht automatisch angelegt, weil zukünftige Planzeilen "
				"vorhanden sind - bitte Kreditvertrag prüfen."
			),
		}

	if any(
		row.get("faelligkeitsdatum") and getdate(row.get("faelligkeitsdatum")) == target_date
		for row in kv.get("plan") or []
	):
		return {
			"match_count": 0,
			"blocked": True,
			"reason": "date_rate_exists",
			"kreditvertrag": kv.name,
			"message": (
				"Kreditrate am Buchungstag ist bereits im Vertrag vorhanden - "
				"bitte Kreditvertrag prüfen."
			),
		}

	savepoint_name = "kv_statement_create"
	frappe.db.savepoint(savepoint_name)
	try:
		rate_row = kv.append(
			"plan",
			{
				"faelligkeitsdatum": target_date,
				"zinsanteil": flt(hints["zinsanteil"]),
				"tilgungsanteil": flt(hints["tilgungsanteil"]),
				"sondertilgung": 0,
			},
		)
		kv.save(ignore_permissions=True)
		result = _book_rate_row_and_reconcile(
			kv=kv,
			rate_row=rate_row,
			posting_date=posting_date,
			amount=amount,
			bank_transaction=bank_transaction,
			savepoint_name=savepoint_name,
			create_savepoint=False,
		)
	except Exception:
		frappe.db.rollback(save_point=savepoint_name)
		raise

	result.update(
		{
			"match_count": 1,
			"kreditvertrag": kv.name,
			"row_name": rate_row.name,
			"row_idx": rate_row.idx,
			"faelligkeitsdatum": str(rate_row.faelligkeitsdatum),
			"gesamtbetrag": flt(rate_row.gesamtbetrag),
			"created_from_statement": True,
		}
	)
	return result


def get_open_rates_for_match(
	bank_account: str,
	posting_date,
	amount: float,
	supplier: Optional[str] = None,
	reference_text: Optional[str] = None,
) -> list[dict]:
	"""Liefert eine Kandidatenliste für den manuellen Match-Dialog.

	Im Gegensatz zu link_bank_transaction_to_kreditvertrag_rate gibt das hier
	auch >1 Kandidaten zurück (damit der Nutzer wählen kann) und enthält
	keine Doc-Referenzen.
	"""
	candidates = _candidate_rates(
		bank_account=bank_account,
		amount=amount,
		posting_date=posting_date,
		supplier=supplier,
		reference_text=reference_text,
	)
	return [
		{
			"kreditvertrag": c["kreditvertrag"],
			"row_name": c["row_name"],
			"row_idx": c["row_idx"],
			"faelligkeitsdatum": str(c["faelligkeitsdatum"]),
			"gesamtbetrag": c["gesamtbetrag"],
			"delta_days": c["delta_days"],
			"vertragsnummer_match": c.get("vertragsnummer_match"),
			"split_match": c.get("split_match"),
		}
		for c in candidates
	]


def assign_kreditrate(
	*,
	kreditvertrag: str,
	rate_name: str,
	bank_account: str,
	posting_date,
	amount: float,
	bank_transaction: str,
) -> dict:
	"""Manueller Match: erzeugt JE für eine vom Nutzer ausgewählte Rate.

	Wird vom Bankimport-Dialog aufgerufen — Server holt sich die echten
	Parameter aus Row/Bank Transaction. Validiert Konsistenz (Bankkonto,
	Betrag-im-Toleranzfenster), aber das Datum darf weiter abweichen als
	match_tolerance_days, damit der Nutzer auch nachträglich zuordnen kann.
	"""
	kv = frappe.get_doc("Kreditvertrag", kreditvertrag)
	if kv.bank_account != bank_account:
		frappe.throw(
			f"Bankkonto der Bankzeile ({bank_account}) passt nicht zum Kreditvertrag "
			f"({kv.bank_account})."
		)

	rate_row = None
	for r in kv.get("plan") or []:
		if r.name == rate_name:
			rate_row = r
			break
	if rate_row is None:
		frappe.throw(f"Rate {rate_name} nicht im Kreditvertrag {kreditvertrag} gefunden.")

	if rate_row.get("journal_entry"):
		frappe.throw(
			f"Rate {rate_row.idx} ist bereits gebucht ({rate_row.journal_entry})."
		)

	if abs(abs(flt(rate_row.gesamtbetrag)) - abs(flt(amount))) > 0.01:
		frappe.throw(
			f"Betrag der Bankzeile ({abs(flt(amount)):.2f} EUR) passt nicht zur Rate "
			f"({flt(rate_row.gesamtbetrag):.2f} EUR)."
		)

	# Savepoint-Bracket: JE+Reconcile+Link rollen gemeinsam zurück, falls
	# nach Submit etwas schiefgeht.
	savepoint_name = "kv_assign"
	frappe.db.savepoint(savepoint_name)
	je = None
	try:
		je = _create_journal_entry_for_rate(
			kv, rate_row, posting_date=posting_date, cheque_no=bank_transaction
		)

		from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
			reconcile_voucher_with_bt,
		)

		bt = frappe.get_doc("Bank Transaction", bank_transaction)
		reconcile_voucher_with_bt(bt, "Journal Entry", je.name, abs(flt(amount)))

		rate_row.db_set("journal_entry", je.name, update_modified=False)
		rate_row.db_set("bank_transaction", bank_transaction, update_modified=False)
		rate_row.db_set("gebucht_am", getdate(posting_date), update_modified=False)
	except Exception:
		frappe.db.rollback(save_point=savepoint_name)
		if je and je.name and frappe.db.exists("Journal Entry", je.name):
			try:
				je_doc = frappe.get_doc("Journal Entry", je.name)
				if je_doc.docstatus == 1:
					je_doc.cancel()
			except Exception:
				frappe.log_error(
					frappe.get_traceback(),
					f"Kredit-Assign: konnte verwaisten JE {je.name} nicht stornieren",
				)
		raise

	_recompute_parent_plausibilitaet(kv.name)

	return {
		"kreditvertrag": kv.name,
		"row_name": rate_row.name,
		"row_idx": rate_row.idx,
		"journal_entry": je.name,
	}


def _recompute_parent_plausibilitaet(kreditvertrag_name: str) -> None:
	"""Lädt den Kreditvertrag neu und persistiert die Plausibilitäts-Felder + Status.

	Wird nach Buchen/Storno aufgerufen, damit aktuelle_restschuld,
	plan_getilgt, gl_getilgt, gl_saldo_darlehenskonto, restschuld_abweichung
	und status nicht bis zum nächsten Save oder Scheduler-Lauf stale bleiben.
	"""
	try:
		kv = frappe.get_doc("Kreditvertrag", kreditvertrag_name)
		kv._compute_plausibilitaet()
		kv._compute_status()
		kv.db_set("aktuelle_restschuld", kv.aktuelle_restschuld, update_modified=False)
		kv.db_set("plan_getilgt", kv.plan_getilgt, update_modified=False)
		kv.db_set("gl_getilgt", kv.gl_getilgt, update_modified=False)
		kv.db_set("gl_saldo_darlehenskonto", kv.gl_saldo_darlehenskonto, update_modified=False)
		kv.db_set("restschuld_abweichung", kv.restschuld_abweichung, update_modified=False)
		kv.db_set("status", kv.status, update_modified=False)
		# Listen-Felder: nach BT-Match/Storno sofort sichtbar machen
		kv.db_set("offene_raten", kv.offene_raten, update_modified=False)
		kv.db_set("naechste_faelligkeit", kv.naechste_faelligkeit, update_modified=False)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"Kreditvertrag Plausibilitäts-Recompute fehlgeschlagen: {kreditvertrag_name}",
		)


# ----------------------------------------------------------------------
# Storno-Hook: ruft auf, wenn ein Journal Entry storniert wird
# ----------------------------------------------------------------------


def on_journal_entry_cancel(doc, method=None):
	"""Bei JE-Cancel: zugehörige Kreditrate zurücksetzen, BT-Verknüpfung entkoppeln.

	Wird über hooks.py als doc_events["Journal Entry"]["on_cancel"] verdrahtet.
	"""
	if not doc or doc.doctype != "Journal Entry":
		return

	rate_rows = frappe.get_all(
		"Kreditrate",
		filters={"journal_entry": doc.name},
		fields=["name", "parent"],
	)
	if not rate_rows:
		return

	affected_parents: set[str] = set()
	for r in rate_rows:
		try:
			rate = frappe.get_doc("Kreditrate", r.name)
			rate.db_set("journal_entry", None, update_modified=False)
			rate.db_set("bank_transaction", None, update_modified=False)
			rate.db_set("gebucht_am", None, update_modified=False)
			if r.parent:
				affected_parents.add(r.parent)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"Kreditrate Reset nach JE-Cancel fehlgeschlagen ({doc.name} / {r.name})",
			)

	# Bank-Transaction-Reconciliation aktiv entkoppeln, falls ERPNext es nicht
	# selbst tut. Wir gehen über Meta-Discovery statt hardcoded Feldnamen, weil
	# die Bank-Transaction-Payments-Tabelle versionsabhängig heißt.
	try:
		_cleanup_bank_transaction_link(doc.name)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"Bank Transaction Cleanup nach JE-Cancel fehlgeschlagen ({doc.name})",
		)

	# Plausibilitäts-Felder + Status pro betroffenem Kreditvertrag neu rechnen
	for kv_name in affected_parents:
		_recompute_parent_plausibilitaet(kv_name)


def _cleanup_bank_transaction_link(journal_entry_name: str) -> None:
	"""Entfernt JE-Verknüpfungen aus Bank Transactions via ERPNext-API.

	Nutzt ``BankTransaction.remove_payment_entry``, das ``delink_payment_entry``
	+ ``self.remove(row)`` macht und damit Clearance/Allocations sauber
	zurücksetzt — direktes ``frappe.db.delete`` der Child-Row würde diese
	Folgelogik überspringen und kann Status/Clearance inkonsistent lassen.

	Match-Kriterium: ``payment_document == "Journal Entry"`` UND
	``payment_entry == journal_entry_name`` (statt nur nach Name zu suchen,
	um Namens-Kollisionen mit anderen Doctypes zu vermeiden).
	"""
	# Bank Transactions finden, die diesen JE als Payment führen
	bt_names = frappe.get_all(
		"Bank Transaction Payments",
		filters={
			"payment_document": "Journal Entry",
			"payment_entry": journal_entry_name,
		},
		fields=["parent"],
		distinct=True,
	)
	for r in bt_names:
		if not r.get("parent"):
			continue
		try:
			bt = frappe.get_doc("Bank Transaction", r.parent)
			# Alle matching-Rows entfernen (theoretisch nur eine pro BT, aber defensiv)
			targets = [
				pe
				for pe in bt.payment_entries
				if pe.payment_document == "Journal Entry"
				and pe.payment_entry == journal_entry_name
			]
			if not targets:
				continue
			for pe in targets:
				bt.remove_payment_entry(pe)
			bt.save(ignore_permissions=True)
		except Exception:
			frappe.log_error(
				frappe.get_traceback(),
				f"Bank Transaction {r.parent} delink fehlgeschlagen (JE {journal_entry_name})",
			)


# ----------------------------------------------------------------------
# Form-Defaults (für kreditvertrag.js)
# ----------------------------------------------------------------------


@frappe.whitelist()
def get_defaults_for_immobilie(immobilie: Optional[str] = None) -> dict:
	"""Liefert Form-Defaults bei Immobilien-Wechsel (cost_center)."""
	if not immobilie:
		return {}
	try:
		cost_center = frappe.get_cached_value("Immobilie", immobilie, "kostenstelle")
	except Exception:
		cost_center = None
	return {"cost_center": cost_center}


# ----------------------------------------------------------------------
# Internal helpers
# ----------------------------------------------------------------------


def _parse_amount(raw, allow_empty: bool = False) -> float:
	"""Parst einen Geldbetrag mit deutschem (1.234,56) oder US-Format (1234.56)."""
	if raw is None:
		if allow_empty:
			return None
		return 0.0
	s = str(raw).strip()
	if not s:
		if allow_empty:
			return None
		return 0.0
	# Tausenderpunkte raus, dann Komma → Punkt
	# Heuristik: wenn sowohl . als auch , vorkommen, gilt der hintere als Dezimaltrenner
	if "," in s and "." in s:
		if s.rfind(",") > s.rfind("."):
			s = s.replace(".", "").replace(",", ".")
		else:
			s = s.replace(",", "")
	elif "," in s:
		s = s.replace(".", "").replace(",", ".")
	# Vorzeichen behalten (Minus, EUR-Symbol entfernen)
	s = s.replace("€", "").replace("EUR", "").replace(" ", "").strip()
	return float(s)


def _normalize_match_token(value: Optional[str]) -> str:
	return re.sub(r"[^0-9A-Za-z]+", "", str(value or "")).upper()


def _extract_loan_match_hints(reference_text: Optional[str]) -> dict:
	"""Extrahiert stabile Kredit-Hinweise aus Bank-Verwendungszwecken.

	Beispiel Postbank/Commerzbank:
	``AZ 7626440021, IN EUR: Tilgung 6786,82 Zinsen 3858,29``
	"""
	text = str(reference_text or "")
	if not text.strip():
		return {}

	hints: dict = {}
	az_match = re.search(
		r"\b(?:AZ|Aktenzeichen|Darlehen(?:s)?nr\.?|Vertrag(?:s)?nr\.?)"
		r"\s*[:#-]?\s*([0-9A-Za-z][0-9A-Za-z./_-]*)",
		text,
		re.IGNORECASE,
	)
	if az_match:
		token = _normalize_match_token(az_match.group(1).split(",")[0])
		if token:
			hints["vertragsnummer"] = token

	for key, fieldname in (("zins(?:en)?", "zinsanteil"), ("tilgung", "tilgungsanteil")):
		match = re.search(
			rf"\b{key}\b\s*[:=]?\s*"
			rf"([-+]?\d{{1,3}}(?:[.\s]\d{{3}})*(?:,\d{{2}})|[-+]?\d+(?:[,.]\d{{2}})?)",
			text,
			re.IGNORECASE,
		)
		if match:
			try:
				hints[fieldname] = _parse_amount(match.group(1), allow_empty=True)
			except Exception:
				pass

	return hints


def _loan_split_matches(row: Document, hints: dict, tolerance_amount: float) -> bool:
	if hints.get("zinsanteil") is not None and abs(
		flt(row.zinsanteil) - flt(hints["zinsanteil"])
	) > tolerance_amount:
		return False
	if hints.get("tilgungsanteil") is not None and abs(
		(flt(row.tilgungsanteil) + flt(row.sondertilgung)) - flt(hints["tilgungsanteil"])
	) > tolerance_amount:
		return False
	return True


def _loan_hints_are_complete(hints: dict) -> bool:
	return bool(
		hints.get("vertragsnummer")
		and hints.get("zinsanteil") is not None
		and hints.get("tilgungsanteil") is not None
	)


def _same_month(value, target_date) -> bool:
	if not value or not target_date:
		return False
	left = getdate(value)
	right = getdate(target_date)
	return left.year == right.year and left.month == right.month


def _find_kreditvertraege_for_statement(
	*,
	bank_account: str,
	vertragsnummer: str,
	supplier: Optional[str] = None,
) -> list["Kreditvertrag"]:
	if not bank_account or not vertragsnummer:
		return []

	target = _normalize_match_token(vertragsnummer)
	kv_names = frappe.get_all(
		"Kreditvertrag",
		filters={"bank_account": bank_account},
		pluck="name",
	)
	matches = []
	for kv_name in kv_names:
		kv = frappe.get_doc("Kreditvertrag", kv_name)
		if _normalize_match_token(kv.get("vertragsnummer")) == target:
			matches.append(kv)

	if supplier:
		supplier_matches = [kv for kv in matches if kv.get("lieferant") == supplier]
		if supplier_matches:
			return supplier_matches
	return matches
