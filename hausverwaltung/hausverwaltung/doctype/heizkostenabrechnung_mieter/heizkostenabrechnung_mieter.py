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

from typing import Any

import frappe
from frappe.model.document import Document

from hausverwaltung.hausverwaltung.scripts.betriebskosten.operating_cost_prepaiment_calc import (
	calc_hk_vorauszahlungen,
)
from hausverwaltung.hausverwaltung.utils.mieter_name import (
	get_contact_last_name,
	pick_preferred_mieter_contact,
	sanitize_name_part,
)


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

		# Derived fields aus Mietvertrag — auch wenn fetch_from gesetzt ist,
		# stellen wir hier noch defensiv sicher, dass alle drei gefüllt sind
		# (z.B. bei programmatischer Anlage ohne UI-Fetch-Trigger).
		if self.mietvertrag and (not self.customer or not self.wohnung):
			mv = frappe.db.get_value(
				"Mietvertrag", self.mietvertrag, ["kunde", "wohnung"], as_dict=True
			) or {}
			if not self.customer:
				self.customer = mv.get("kunde")
			if not self.wohnung:
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
		self.set_onload("can_manual_cancel", self._can_manual_cancel())

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

	def before_cancel(self) -> None:
		"""Wenn der Cancel über die Sammel-Abrechnung (Parent) ausgelöst wird,
		den Link zur Sammel-Abrechnung beim Cancel ignorieren — sonst blockiert
		Frappe das Cancel der Children, weil der Parent noch submittet ist.
		"""
		if getattr(getattr(self, "flags", object()), "allow_cancel_via_head", False):
			self.flags.ignore_links = True
			self.flags.ignore_linked_doctypes = ["Heizkostenabrechnung Immobilie"]

	def on_cancel(self) -> None:
		"""Storniert die verknüpften Sales Invoice / Credit Note mit."""
		self._cancel_linked_document("Sales Invoice", (self.get("sales_invoice") or "").strip())
		self._cancel_linked_document("Sales Invoice", (self.get("credit_note") or "").strip())

	def _cancel_linked_document(self, doctype: str, name: str) -> None:
		if not name:
			return
		try:
			linked = frappe.get_doc(doctype, name)
		except Exception:
			# Falls verknüpfter Beleg gelöscht wurde: nicht blockieren
			return
		if getattr(linked, "docstatus", None) == 2:
			return
		try:
			linked.flags.ignore_permissions = True
			linked.flags.ignore_links = True
			if getattr(linked, "docstatus", None) == 0:
				frappe.delete_doc(doctype, name, ignore_permissions=True, force=1)
			else:
				linked.cancel()
		except Exception as e:
			frappe.throw(f"Verknüpfter Beleg konnte nicht storniert werden ({doctype} {name}): {e}")

	def _can_manual_cancel(self) -> bool:
		try:
			return bool(frappe.has_permission(doc=self, ptype="cancel"))
		except Exception:
			return False


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
