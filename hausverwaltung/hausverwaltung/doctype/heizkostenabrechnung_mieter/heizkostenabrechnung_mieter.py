"""DocType ``Heizkostenabrechnung Mieter``.

Erfasst die externe Wärmedienst-Abrechnung (Brunata, Techem, ista, Minol, …)
pro Mieter und erzeugt beim Submit automatisch eine Sales Invoice (Nachzahlung)
oder Credit Note (Guthaben).

Wichtigster Mechanismus: ``vorauszahlungen_ist`` und ``vorauszahlungen_soll``
werden als virtuelle Felder zur Laufzeit aus den existierenden monatlichen
Mietrechnungen berechnet (Item-Code ``Heizkosten``, Filter via
``custom_wertstellungsdatum`` = Leistungszeitraum). Der editierbare Wert
``vorauszahlungen`` startet als Vorschlag = ``vorauszahlungen_ist`` und kann
manuell übersteuert werden, falls der Wärmedienst einen abweichenden Soll-Wert
in seiner Abrechnung ausweist.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List

import frappe
from frappe.model.document import Document
from frappe.utils import cstr, getdate

from hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen import (
	_get_default_company,
)
from hausverwaltung.hausverwaltung.scripts.betriebskosten.operating_cost_prepaiment_calc import (
	calc_hk_vorauszahlungen,
)
from hausverwaltung.hausverwaltung.utils.mieter_name import (
	get_contact_last_name,
	pick_preferred_mieter_contact,
	sanitize_name_part,
)


def _row_value(row: object, fieldname: str) -> Any:
	getter = getattr(row, "get", None)
	return getter(fieldname) if callable(getter) else getattr(row, fieldname, None)


def _get_locked_settlement_allocations(
	invoice_names: Iterable[str],
) -> Dict[str, List[Dict[str, Any]]]:
	"""Lock settlement invoices and all PE/JE reference rows.

	Reference rows of draft vouchers are intentionally included in the locking
	read. Their parents therefore cannot be submitted concurrently between the
	pre-flight and the actual invoice cancellation.
	"""
	names = sorted({cstr(name).strip() for name in invoice_names if cstr(name).strip()})
	if not names:
		return {}

	placeholders = ", ".join(["%s"] * len(names))
	params = tuple(names)
	invoice_rows = frappe.db.sql(
		f"""
		SELECT name, docstatus
		FROM `tabSales Invoice`
		WHERE name IN ({placeholders})
		ORDER BY name
		FOR UPDATE
		""",
		params,
		as_dict=True,
	)
	found = {cstr(_row_value(row, "name")) for row in invoice_rows}
	missing = sorted(set(names) - found)
	if missing:
		frappe.throw(
			"Storno aus Sicherheitsgründen abgebrochen: Die verknüpften "
			f"Sales-Invoice-Belege fehlen: {', '.join(missing)}."
		)

	payment_rows = frappe.db.sql(
		f"""
		SELECT
			per.name AS reference_row,
			per.reference_name AS invoice,
			per.parent AS voucher,
			per.allocated_amount AS allocated_amount,
			pe.docstatus AS voucher_docstatus,
			pe.posting_date AS posting_date
		FROM `tabPayment Entry Reference` per
		INNER JOIN `tabPayment Entry` pe ON pe.name = per.parent
		WHERE per.reference_doctype = 'Sales Invoice'
		  AND per.reference_name IN ({placeholders})
		ORDER BY per.reference_name, per.parent, per.name
		FOR UPDATE
		""",
		params,
		as_dict=True,
	)
	journal_rows = frappe.db.sql(
		f"""
		SELECT
			jea.name AS reference_row,
			jea.reference_name AS invoice,
			jea.parent AS voucher,
			jea.debit_in_account_currency AS debit_amount,
			jea.credit_in_account_currency AS credit_amount,
			je.docstatus AS voucher_docstatus,
			je.posting_date AS posting_date
		FROM `tabJournal Entry Account` jea
		INNER JOIN `tabJournal Entry` je ON je.name = jea.parent
		WHERE jea.reference_type = 'Sales Invoice'
		  AND jea.reference_name IN ({placeholders})
		ORDER BY jea.reference_name, jea.parent, jea.name
		FOR UPDATE
		""",
		params,
		as_dict=True,
	)

	allocations: Dict[str, List[Dict[str, Any]]] = {name: [] for name in names}
	for row in payment_rows:
		if int(_row_value(row, "voucher_docstatus") or 0) != 1:
			continue
		amount = abs(float(_row_value(row, "allocated_amount") or 0))
		if amount <= 0.000001:
			continue
		invoice = cstr(_row_value(row, "invoice")).strip()
		allocations[invoice].append(
			{
				"document_type": "Payment Entry",
				"document": _row_value(row, "voucher"),
				"payment_entry": _row_value(row, "voucher"),
				"allocated_amount": amount,
				"posting_date": _row_value(row, "posting_date"),
			}
		)

	for row in journal_rows:
		if int(_row_value(row, "voucher_docstatus") or 0) != 1:
			continue
		amount = max(
			abs(float(_row_value(row, "debit_amount") or 0)),
			abs(float(_row_value(row, "credit_amount") or 0)),
		)
		if amount <= 0.000001:
			continue
		invoice = cstr(_row_value(row, "invoice")).strip()
		voucher = cstr(_row_value(row, "voucher")).strip()
		allocations[invoice].append(
			{
				"document_type": "Journal Entry",
				"document": voucher,
				"journal_entry": voucher,
				"allocated_amount": amount,
				"posting_date": _row_value(row, "posting_date"),
			}
		)

	return allocations


def _settlement_marker_owners(remarks: Any) -> List[str]:
	return [
		match.strip()
		for match in re.findall(
			r"\[HK-SETTLEMENT:([^\]\r\n]+)\]",
			cstr(remarks or ""),
		)
		if match.strip()
	]


class HeizkostenabrechnungMieter(Document):
	def autoname(self) -> None:
		if getattr(self, "name", None):
			return

		# Falls die UI keine Mieter-Tabelle pflegt, weichen wir auf den Customer aus.
		mieter_contact = pick_preferred_mieter_contact(getattr(self, "mieter", None)) or self.customer or "Mieter"

		# Kompakter Name: Mieter-Last-Name (oder Customer-Anfang) + Wohnung + Periode
		# Wir vermeiden den vollen Customer-String mehrfach, weil der oft schon
		# "G | VH | 4.OG rechts Mieter: Müller" ist (≈ 40 Zeichen).
		last_name = sanitize_name_part(get_contact_last_name(mieter_contact))
		short_mieter = last_name or sanitize_name_part(str(mieter_contact))[:30]

		base_parts = [
			short_mieter,
			sanitize_name_part(str(self.wohnung)) if self.wohnung else "",
			str(self.von) if self.von else "",
			str(self.bis) if self.bis else "",
		]
		base_name = "-".join([p for p in base_parts if p]).strip()
		if not base_name:
			return

		# MySQL `tab*.name` ist VARCHAR(140) — wir lassen Puffer für Suffix.
		MAX_NAME_LEN = 130
		if len(base_name) > MAX_NAME_LEN:
			base_name = base_name[:MAX_NAME_LEN].rstrip("-")

		candidate = base_name
		suffix = 1
		while frappe.db.exists("Heizkostenabrechnung Mieter", candidate, cache=False):
			suffix += 1
			candidate = f"{base_name}-{suffix}"
		self.name = candidate

	def validate(self) -> None:
		if self.von and self.bis and self.von > self.bis:
			frappe.throw("'Von' muss vor oder gleich 'Bis' liegen.")

		# Der Mietvertrag ist die Buchungsidentität und besitzt genau einen
		# Customer. Übergebene Headerwerte dürfen davon niemals abweichen.
		if self.mietvertrag:
			mv = frappe.db.get_value(
				"Mietvertrag", self.mietvertrag, ["kunde", "wohnung"], as_dict=True
			) or {}
			if not mv.get("kunde"):
				frappe.throw(
					f"Mietvertrag {self.mietvertrag} hat keinen Customer; "
					"die Abrechnung kann nicht sicher gebucht werden."
				)
			if self.customer and self.customer != mv.get("kunde"):
				frappe.throw(
					f"Customer {self.customer} passt nicht zum Mietvertrag "
					f"{self.mietvertrag} ({mv.get('kunde')})."
				)
			if self.wohnung and self.wohnung != mv.get("wohnung"):
				frappe.throw(
					f"Wohnung {self.wohnung} passt nicht zum Mietvertrag "
					f"{self.mietvertrag} ({mv.get('wohnung')})."
				)
			self.customer = mv.get("kunde")
			self.wohnung = mv.get("wohnung")
		if self.wohnung and not self.immobilie:
			self.immobilie = frappe.db.get_value("Wohnung", self.wohnung, "immobilie")

		# Vorauszahlungs-Vorschlag setzen wenn leer. 0 ist ein gültiger, bewusst
		# gesetzter Korrekturwert und darf nicht wieder überschrieben werden.
		if self.vorauszahlungen in (None, "") and self.mietvertrag and self.von and self.bis:
			vz = calc_hk_vorauszahlungen(self.mietvertrag, self.von, self.bis)
			self.vorauszahlungen = float(vz.get("actual_total") or 0.0)

		# Differenz + Ausgeglichen-Flag
		try:
			diff = round(float(self.kosten_gesamt or 0) - float(self.vorauszahlungen or 0), 2)
		except (TypeError, ValueError):
			diff = 0.0
		self.abrechnung_ausgeglichen = 1 if abs(diff) < 0.01 else 0

	def onload(self) -> None:
		"""Berechne virtuelle Felder beim Laden im Form."""
		self._recompute_vorauszahlungs_anzeige()
		try:
			self.differenz = round(float(self.kosten_gesamt or 0) - float(self.vorauszahlungen or 0), 2)
		except (TypeError, ValueError):
			self.differenz = 0.0

	def _recompute_vorauszahlungs_anzeige(self) -> None:
		"""Ruft ``calc_hk_vorauszahlungen`` und setzt ``_ist`` + ``_soll`` virtuell."""
		if not (self.mietvertrag and self.von and self.bis):
			self.vorauszahlungen_ist = 0.0
			self.vorauszahlungen_soll = 0.0
			return
		try:
			vz = calc_hk_vorauszahlungen(self.mietvertrag, self.von, self.bis)
		except Exception:
			# Defensiv: Onload soll nie crashen, sonst öffnet sich das Form gar nicht.
			vz = {"expected_total": 0.0, "actual_total": 0.0}
		self.vorauszahlungen_ist = float(vz.get("actual_total") or 0.0)
		self.vorauszahlungen_soll = float(vz.get("expected_total") or 0.0)

	def on_submit(self) -> None:
		"""Erzeugt die Sales Invoice / Credit Note für die Differenz."""
		from hausverwaltung.hausverwaltung.scripts.heizkosten.settlement import (
			create_hk_settlement_documents,
		)
		create_hk_settlement_documents(self.name)

	def before_submit(self) -> None:
		"""Einreichen nur als interner Schritt der Immobilien-Abrechnung erlauben."""
		if not getattr(getattr(self, "flags", object()), "allow_submit_via_head", False):
			frappe.throw(
				"Einzelne Mieter-HK-Abrechnungen können nicht separat eingereicht werden. "
				"Bitte die zugehörige Heizkostenabrechnung Immobilie einreichen."
			)
		if not cstr(getattr(self, "heizkostenabrechnung_immobilie", None) or "").strip():
			frappe.throw(
				"Die HK-Mieterabrechnung ist keiner Heizkostenabrechnung Immobilie "
				"zugeordnet und kann deshalb nicht eingereicht werden."
			)
		prefilled = [
			fieldname
			for fieldname in ("sales_invoice", "credit_note")
			if cstr(self.get(fieldname) or "").strip()
		]
		if prefilled:
			frappe.throw(
				"Die HK-Mieterabrechnung enthält bereits vor dem Einreichen "
				"Ausgleichsbeleg-Links. Der Vorgang wurde aus Sicherheitsgründen "
				"abgebrochen."
			)

	def before_cancel(self) -> None:
		"""Storno nur über Sammelabrechnung bzw. internen Korrekturablauf erlauben."""
		if not getattr(getattr(self, "flags", object()), "allow_cancel_via_head", False):
			frappe.throw(
				"Einzelne Mieter-HK-Abrechnungen können nicht separat storniert werden. "
				"Bitte die zugehörige Heizkostenabrechnung Immobilie stornieren oder dort korrigieren."
			)
		# Der Parent ist beim Kaskaden-Storno noch submittet; dessen Link darf das
		# interne Storno des Child-Dokuments deshalb nicht blockieren.
		self.ignore_linked_doctypes = ["Heizkostenabrechnung Immobilie"]

		# Ownership und Identität aller Belege werden vollständig geprüft, bevor
		# Frappe den Child-Docstatus oder einen verknüpften Beleg verändern darf.
		self.flags._validated_hk_settlement_documents = (
			self._validate_settlement_documents_for_cancel()
		)
		invoices = [
			cstr(self.get(fieldname) or "").strip()
			for fieldname in ("sales_invoice", "credit_note")
		]
		allocations = _get_locked_settlement_allocations(
			name for name in invoices if name
		)
		blocked = {invoice: rows for invoice, rows in allocations.items() if rows}
		if blocked:
			sources = sorted(
				{
					f"{row['document_type']} {row['document']}"
					for rows in blocked.values()
					for row in rows
				}
			)
			frappe.throw(
				"Storno nicht möglich: Mindestens ein HK-Ausgleichsbeleg besitzt "
				"eine aktive Zahlungs- oder Journal-Zuordnung "
				f"({', '.join(sources)}). Bitte zuerst die Zuordnungen auflösen."
			)

	def on_cancel(self) -> None:
		"""Storniert die verknüpften Sales Invoice / Credit Note mit."""
		self._cancel_settlement_documents()

	def _cancel_settlement_documents(self) -> None:
		validated = getattr(
			getattr(self, "flags", object()),
			"_validated_hk_settlement_documents",
			None,
		)
		if validated is None:
			validated = self._validate_settlement_documents_for_cancel()

		# Erst nach erfolgreicher Validierung der gesamten Belegmenge mutieren.
		for _fieldname, linked in validated:
			self._cancel_validated_document(linked)

	def _cancel_linked_document(self, doctype: str, name: str) -> None:
		"""Compatibility wrapper that still performs full ownership validation."""
		if not name:
			return
		if doctype != "Sales Invoice":
			frappe.throw(
				f"Nicht unterstützter HK-Ausgleichsbelegtyp {doctype}; "
				"es wurde nichts storniert."
			)
		matches = [
			fieldname
			for fieldname in ("sales_invoice", "credit_note")
			if cstr(self.get(fieldname) or "").strip() == cstr(name).strip()
		]
		if len(matches) != 1:
			frappe.throw(
				f"Sales Invoice {name} ist der HK-Abrechnung nicht eindeutig "
				"zugeordnet; es wurde nichts storniert."
			)
		linked = self._validate_linked_settlement_document(matches[0], name)
		self._cancel_validated_document(linked)

	def _validate_settlement_documents_for_cancel(self) -> List[tuple[str, object]]:
		sales_invoice = cstr(self.get("sales_invoice") or "").strip()
		credit_note = cstr(self.get("credit_note") or "").strip()
		if sales_invoice and credit_note:
			frappe.throw(
				"Die HK-Abrechnung verweist gleichzeitig auf Nachzahlung und "
				"Gutschrift. Der Storno wurde aus Sicherheitsgründen abgebrochen."
			)

		validated: List[tuple[str, object]] = []
		for fieldname, name in (
			("sales_invoice", sales_invoice),
			("credit_note", credit_note),
		):
			if name:
				validated.append(
					(fieldname, self._validate_linked_settlement_document(fieldname, name))
				)
		return validated

	def _validate_linked_settlement_document(self, fieldname: str, name: str):
		expected_return = 1 if fieldname == "credit_note" else 0
		expected_item = "HK Guthaben" if expected_return else "HK Nachzahlung"
		settlement_name = cstr(getattr(self, "name", None) or "").strip()
		if not settlement_name:
			frappe.throw(
				"Die HK-Abrechnung hat keinen eindeutigen Namen; "
				"es wurde nichts storniert."
			)

		try:
			linked = frappe.get_doc("Sales Invoice", name, for_update=True)
		except frappe.DoesNotExistError:
			frappe.throw(
				f"Verknüpfter HK-Ausgleichsbeleg Sales Invoice {name} fehlt; "
				"es wurde nichts storniert."
			)
		except Exception as exc:
			frappe.throw(
				f"Verknüpfter Beleg konnte nicht geladen werden "
				f"(Sales Invoice {name}): {exc}"
			)

		docstatus = int(_row_value(linked, "docstatus") or 0)
		if docstatus not in (1, 2):
			frappe.throw(
				f"HK-Ausgleichsbeleg {name} ist nicht eingereicht; "
				"es wurde nichts storniert."
			)

		remarks = cstr(_row_value(linked, "remarks") or "")
		marker_owners = _settlement_marker_owners(remarks)
		all_settlement_markers = re.findall(
			r"\[((?:BK|HK)-SETTLEMENT):([^\]\r\n]+)\]",
			remarks,
		)
		expected_marker_owner = settlement_name
		exact_marker = (
			marker_owners == [expected_marker_owner]
			and all_settlement_markers
			== [("HK-SETTLEMENT", expected_marker_owner)]
		)
		has_marker_syntax = bool(
			marker_owners
			or all_settlement_markers
			or "HK-SETTLEMENT" in remarks
			or "BK-SETTLEMENT" in remarks
		)
		if has_marker_syntax and not exact_marker:
			frappe.throw(
				f"Ownership-Marker von HK-Ausgleichsbeleg {name} gehört nicht "
				f"eindeutig zu {settlement_name}; es wurde nichts storniert."
			)
		is_markerless_legacy = not exact_marker

		customer = cstr(_row_value(linked, "customer") or "").strip()
		wohnung = cstr(_row_value(linked, "wohnung") or "").strip()
		company = cstr(_row_value(linked, "company") or "").strip()
		if customer != cstr(getattr(self, "customer", None) or "").strip():
			frappe.throw(
				f"Customer von HK-Ausgleichsbeleg {name} gehört nicht zu "
				f"{settlement_name}; es wurde nichts storniert."
			)
		expected_company = cstr(_get_default_company(self) or "").strip()
		if not expected_company or company != expected_company:
			frappe.throw(
				f"Company von HK-Ausgleichsbeleg {name} gehört nicht zur "
				f"Wohnung der Abrechnung {settlement_name}; "
				"es wurde nichts storniert."
			)
		expected_wohnung = cstr(getattr(self, "wohnung", None) or "").strip()
		legacy_wohnung_proof_required = not wohnung and is_markerless_legacy
		if wohnung != expected_wohnung and not legacy_wohnung_proof_required:
			frappe.throw(
				f"Wohnung von HK-Ausgleichsbeleg {name} gehört nicht zu "
				f"{settlement_name}; es wurde nichts storniert."
			)
		if int(_row_value(linked, "is_return") or 0) != expected_return:
			frappe.throw(
				f"Belegart von HK-Ausgleichsbeleg {name} passt nicht zum Linkfeld "
				f"{fieldname}; es wurde nichts storniert."
			)

		items = list(_row_value(linked, "items") or [])
		item_codes = [cstr(_row_value(item, "item_code") or "").strip() for item in items]
		if item_codes != [expected_item]:
			frappe.throw(
				f"HK-Ausgleichsbeleg {name} enthält nicht exakt das erwartete "
				f"Item {expected_item}; es wurde nichts storniert."
			)

		backlinks = frappe.db.sql(
			"""
			SELECT name, sales_invoice, credit_note
			FROM `tabHeizkostenabrechnung Mieter`
			WHERE sales_invoice = %(voucher)s
			   OR credit_note = %(voucher)s
			ORDER BY name
			FOR UPDATE
			""",
			{"voucher": name},
			as_dict=True,
		)
		if len(backlinks or []) != 1:
			frappe.throw(
				f"HK-Ausgleichsbeleg {name} besitzt keine eindeutige "
				"Child-Rückverknüpfung; es wurde nichts storniert."
			)
		backlink = backlinks[0]
		opposite_field = "credit_note" if fieldname == "sales_invoice" else "sales_invoice"
		if (
			cstr(_row_value(backlink, "name") or "").strip() != settlement_name
			or cstr(_row_value(backlink, fieldname) or "").strip() != name
			or cstr(_row_value(backlink, opposite_field) or "").strip() == name
		):
			frappe.throw(
				f"HK-Ausgleichsbeleg {name} ist nicht bijektiv mit "
				f"{settlement_name} verknüpft; es wurde nichts storniert."
			)

		if is_markerless_legacy:
			self._validate_markerless_legacy_identity(linked, name)
		return linked

	def _validate_markerless_legacy_identity(self, linked: object, name: str) -> None:
		"""Prove apartment and amount for old vouchers without ownership marker."""
		mietvertrag = cstr(getattr(self, "mietvertrag", None) or "").strip()
		if not mietvertrag:
			frappe.throw(
				f"Markerloser HK-Altbeleg {name} kann keinem Mietvertrag "
				"zugeordnet werden; es wurde nichts storniert."
			)
		contract_rows = frappe.db.sql(
			"""
			SELECT name, kunde, wohnung
			FROM `tabMietvertrag`
			WHERE name = %s
			FOR UPDATE
			""",
			(mietvertrag,),
			as_dict=True,
		)
		if len(contract_rows or []) != 1:
			frappe.throw(
				f"Mietvertrag {mietvertrag} von markerlosem HK-Altbeleg {name} "
				"konnte nicht eindeutig gesperrt werden; es wurde nichts storniert."
			)
		contract = contract_rows[0]
		if (
			cstr(_row_value(contract, "kunde") or "").strip()
			!= cstr(getattr(self, "customer", None) or "").strip()
			or cstr(_row_value(contract, "wohnung") or "").strip()
			!= cstr(getattr(self, "wohnung", None) or "").strip()
		):
			frappe.throw(
				f"Mietvertrag von markerlosem HK-Altbeleg {name} bestätigt "
				"Customer und Wohnung nicht; es wurde nichts storniert."
			)

		effective_date = _row_value(linked, "custom_wertstellungsdatum") or _row_value(
			linked,
			"posting_date",
		)
		period_end = getattr(self, "bis", None)
		if (
			not effective_date
			or not period_end
			or getdate(effective_date) != getdate(period_end)
		):
			frappe.throw(
				f"Wertstellungsdatum von markerlosem HK-Altbeleg {name} "
				"passt nicht zum Abrechnungsende; es wurde nichts storniert."
			)

		try:
			actual_amount = abs(
				Decimal(str(_row_value(linked, "grand_total"))).quantize(
					Decimal("0.01")
				)
			)
			expected_amount = abs(
				(
					Decimal(str(getattr(self, "kosten_gesamt", None)))
					- Decimal(str(getattr(self, "vorauszahlungen", None)))
				).quantize(Decimal("0.01"))
			)
		except (InvalidOperation, TypeError, ValueError):
			frappe.throw(
				f"Betrag von markerlosem HK-Altbeleg {name} kann nicht "
				"sicher geprüft werden; es wurde nichts storniert."
			)
		if actual_amount != expected_amount:
			frappe.throw(
				f"Betrag von markerlosem HK-Altbeleg {name} passt nicht zur "
				"HK-Abrechnung; es wurde nichts storniert."
			)

	@staticmethod
	def _cancel_validated_document(linked: object) -> None:
		if int(_row_value(linked, "docstatus") or 0) == 2:
			return
		try:
			linked.flags.ignore_permissions = True
			linked.cancel()
		except Exception as exc:
			frappe.throw(
				"Verknüpfter HK-Ausgleichsbeleg konnte nicht storniert werden "
				f"(Sales Invoice {_row_value(linked, 'name')}): {exc}"
			)

@frappe.whitelist()
def get_vorauszahlung_vorschlag(mietvertrag: str, von: str, bis: str) -> dict[str, Any]:
	"""Frontend-Helper für JS-Form: liefert IST + SOLL Vorauszahlungs-Beträge.

	Nutzt die generische Vorauszahlungs-Logik mit Item-Code ``Heizkosten``,
	gefiltert via Wertstellungsdatum-Logik aus
	``operating_cost_prepaiment_calc``.
	"""
	if not (mietvertrag and von and bis):
		return {"ist": 0.0, "soll": 0.0}
	vz = calc_hk_vorauszahlungen(mietvertrag, von, bis)
	return {
		"ist": float(vz.get("actual_total") or 0.0),
		"soll": float(vz.get("expected_total") or 0.0),
	}
