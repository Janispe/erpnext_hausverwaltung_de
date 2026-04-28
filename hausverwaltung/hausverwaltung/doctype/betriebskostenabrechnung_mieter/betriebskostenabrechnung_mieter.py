from typing import Any, Dict, List

import frappe
from frappe.model.document import Document

from hausverwaltung.hausverwaltung.utils.mieter_name import (
	get_contact_last_name,
	pick_preferred_mieter_contact,
	sanitize_name_part,
)


class BetriebskostenabrechnungMieter(Document):
	def autoname(self) -> None:
		if getattr(self, "name", None):
			return

		mieter_contact = pick_preferred_mieter_contact(getattr(self, "mieter", None))
		base_parts = [
			mieter_contact or "Mieter",
			self.wohnung,
			self.von,
			self.bis,
		]
		base_parts = [sanitize_name_part(str(p)) for p in base_parts if p]
		base_name = "-".join([p for p in base_parts if p]).strip()
		if not base_name:
			return

		last_name = sanitize_name_part(get_contact_last_name(mieter_contact))
		if last_name:
			base_name = f"{base_name} - {last_name}"

		candidate = base_name
		suffix = 1
		while frappe.db.exists("Betriebskostenabrechnung Mieter", candidate, cache=False):
			suffix += 1
			candidate = f"{base_name}-{suffix}"
		self.name = candidate

	def _cancel_linked_document(self, doctype: str, name: str) -> None:
		if not name:
			return
		try:
			linked = frappe.get_doc(doctype, name)
		except Exception:
			# Falls verknüpfter Beleg gelöscht wurde o.ä.: nicht blockieren
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

	def _cancel_settlement_documents(self) -> None:
		"""Storniert automatisch erzeugte Ausgleichsbelege (Nachzahlung/Guthaben/Konsolidierung)."""
		self._cancel_linked_document("Journal Entry", (self.get("consolidation_journal_entry") or "").strip())
		self._cancel_linked_document("Sales Invoice", (self.get("sales_invoice") or "").strip())
		self._cancel_linked_document("Sales Invoice", (self.get("credit_note") or "").strip())

	def _can_manual_cancel(self) -> bool:
		"""Prüft, ob der aktuelle Nutzer das Dokument direkt stornieren darf."""
		try:
			return bool(frappe.has_permission(doc=self, ptype="cancel"))
		except Exception:
			return False

	def _sum_abrechnung(self) -> float:
		"""Summe der Abrechnungsposten (Float)."""
		total = 0.0
		for r in getattr(self, "abrechnung", []) or []:
			try:
				total += float(r.get("betrag") or 0)
			except Exception:
				continue
		return round(total, 2)

	def onload(self):
		# Virtuelle Felder setzen
		self.gesamtkosten = self._sum_abrechnung()
		try:
			self.differenz = round(float(self.gesamtkosten or 0) - float(self.vorrauszahlungen or 0), 2)
		except Exception:
			self.differenz = 0.0
		self.set_onload("can_manual_cancel", self._can_manual_cancel())

	def validate(self):
		# Rechne bei Änderungen neu
		self.onload()
		# Optional: Markiere ausgeglichen, wenn Differenz ~ 0
		try:
			self.abrechnung_ausgeglichen = 1 if abs(float(self.differenz or 0)) < 0.01 else 0
		except Exception:
			self.abrechnung_ausgeglichen = 0

	def after_insert(self):
		"""Erstellt automatisch die Ausgleichsrechnung (Nachzahlung/Guthaben) direkt nach dem Anlegen.

		Wirft einen Fehler, wenn die Erstellung nicht möglich ist, damit sofort Feedback im UI erscheint.
		"""
		# Falls ein Aufrufer die automatische Erstellung selbst übernimmt, hier überspringen
		if getattr(getattr(self, "flags", object()), "skip_auto_settle", False):
			return
		from hausverwaltung.hausverwaltung.scripts.betriebskosten.abrechnung_erstellen import (
			create_bk_settlement_documents,
		)
		res = create_bk_settlement_documents(self.name, consolidate_unpaid=True)
		# Wenn weder Nachzahlung noch Gutschrift erstellt wurde und keine Ausgleichsnotiz vorhanden ist, Fehler werfen
		if isinstance(res, dict):
			created = res.get("created") or {}
			if not (created.get("sales_invoice") or created.get("credit_note") or created.get("note")):
				raise frappe.ValidationError("Ausgleichsbeleg konnte nicht erstellt werden.")

	def before_insert(self):
		"""Manuelle Erstellung verhindern: Abrechnungen dürfen nur über das Immobilien-Abrechnungsobjekt entstehen."""
		if not getattr(getattr(self, "flags", object()), "allow_manual_create", False):
			raise frappe.ValidationError(
				"Manuelle Erstellung nicht erlaubt. Bitte erzeugen Sie Abrechnungen über 'Betriebskostenabrechnung Immobilie'."
			)

	def before_cancel(self):
		# Wenn Storno über berechtigten Nutzer oder Kopf ausgelöst wird, Links zum Kopf ignorieren,
		# damit die Abrechnung auch bei verknüpftem, eingereichtem Kopf storniert werden kann.
		if getattr(getattr(self, "flags", object()), "allow_cancel_via_head", False) or self._can_manual_cancel():
			self.flags.ignore_links = True
			self.flags.ignore_linked_doctypes = ["Betriebskostenabrechnung Immobilie"]

	def on_cancel(self):
		allowed = bool(
			getattr(getattr(self, "flags", object()), "allow_cancel_via_head", False) or self._can_manual_cancel()
		)
		if not allowed:
			raise frappe.ValidationError(
				"Abbrechen ist nicht erlaubt. Nutzen Sie das Immobilien-Abrechnungsobjekt für Korrekturen."
			)
		self._cancel_settlement_documents()

	def before_delete(self):
		if not getattr(getattr(self, "flags", object()), "allow_cancel_via_head", False):
			raise frappe.ValidationError("Löschen ist nicht erlaubt. Nutzen Sie das Immobilien-Abrechnungsobjekt für Korrekturen.")

	def get_kostenmatrix_rows(self) -> List[Dict[str, object]]:
		"""Kombiniert Immobilien- und Wohnungsanteile je Betriebskostenart für Druck und Export."""
		combined: Dict[str, Dict[str, object]] = {}

		def accumulate(items, column: str) -> None:
			for row in items or []:
				art = row.get("betriebskostenart")
				if not art:
					continue
				try:
					amount = round(float(row.get("betrag") or 0), 2)
				except Exception:
					amount = 0.0
				entry = combined.setdefault(art, {
					"betriebskostenart": art,
					"immobilie": 0.0,
					"wohnung": 0.0,
				})
				entry[column] = round(float(entry.get(column) or 0) + amount, 2)

		immobilien_items = []
		if getattr(self, "immobilien_abrechnung", None):
			try:
				head = frappe.get_doc("Betriebskostenabrechnung Immobilie", self.immobilien_abrechnung)
				immobilien_items = head.get("kosten_pro_art") or []
			except Exception:
				immobilien_items = []
		elif getattr(self, "immobilien_kosten", None):
			immobilien_items = self.immobilien_kosten

		accumulate(immobilien_items, "immobilie")
		accumulate(getattr(self, "abrechnung", []) or [], "wohnung")

		return [combined[key] for key in sorted(combined)]


@frappe.whitelist()
def get_immobilien_kosten(name: str) -> List[Dict[str, object]]:
	"""Liefert die Kosten aus der verknüpften Immobilienabrechnung."""
	if not name:
		return []
	try:
		doc = frappe.get_doc("Betriebskostenabrechnung Mieter", name)
		doc.check_permission("read")
	except Exception:
		return []
	head_name = doc.get("immobilien_abrechnung")
	if not head_name:
		return []
	try:
		head = frappe.get_doc("Betriebskostenabrechnung Immobilie", head_name)
	except Exception:
		# falls Berechtigung/Fehler: lieber leer zurückgeben statt Frontend zu blockieren
		return []
	rows: List[Dict[str, object]] = []
	for row in head.get("kosten_pro_art") or []:
		try:
			amount = round(float(row.get("betrag") or 0), 2)
		except Exception:
			amount = 0.0
		rows.append({
			"betriebskostenart": row.get("betriebskostenart"),
			"betrag": amount,
		})
	return rows


@frappe.whitelist()
def get_immobilien_basis(name: str) -> Dict[str, Any]:
	"""Liefert Basis-Summen für die Immobilie inkl. Schlüsselwerte."""
	if not name:
		return {"total_qm": 0.0, "total_bewohner": 0.0, "schluessel_totals": {}, "wohnung_schluesselwerte": {}}
	try:
		doc = frappe.get_doc("Betriebskostenabrechnung Mieter", name)
		doc.check_permission("read")
	except Exception:
		return {"total_qm": 0.0, "total_bewohner": 0.0, "schluessel_totals": {}, "wohnung_schluesselwerte": {}}

	head_name = doc.get("immobilien_abrechnung")
	if not head_name:
		return {"total_qm": 0.0, "total_bewohner": 0.0, "schluessel_totals": {}, "wohnung_schluesselwerte": {}}

	try:
		head = frappe.get_doc("Betriebskostenabrechnung Immobilie", head_name)
	except Exception:
		return {"total_qm": 0.0, "total_bewohner": 0.0, "schluessel_totals": {}, "wohnung_schluesselwerte": {}}

	from hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen import (
		_wohnungen_in_haus,
		_flaeche_qm,
	)
	from hausverwaltung.hausverwaltung.doctype.zustandsschluessel.zustandsschluessel import (
		get_effective_zustandsschluessel_value,
	)

	stichtag = head.get("stichtag") or head.get("bis")
	wohnungen = _wohnungen_in_haus(immobilie=head.get("immobilie"))
	total_qm = 0.0
	for wohnung in wohnungen:
		try:
			total_qm += float(_flaeche_qm(wohnung, stichtag) or 0)
		except Exception:
			continue
	total_qm = round(total_qm, 2)

	children = frappe.get_all(
		"Betriebskostenabrechnung Mieter",
		filters={"immobilien_abrechnung": head_name},
		fields=["name"],
	)

	parent_names = [r.get("name") for r in children if r.get("name")]
	if not parent_names:
		return {"total_qm": total_qm, "total_bewohner": 0.0}

	total_bewohner = 0.0
	try:
		result = frappe.db.sql(
			"""
			select count(*) as cnt
			from `tabVertragspartner`
			where parenttype = 'Betriebskostenabrechnung Mieter'
			  and parent in %(parents)s
			""",
			{"parents": tuple(parent_names)},
			as_dict=True,
		)
		if result:
			total_bewohner = float(result[0].get("cnt") or 0)
	except Exception:
		total_bewohner = 0.0

	schluessel_totals: Dict[str, float] = {}
	wohnung_schluesselwerte: Dict[str, float] = {}
	try:
		arts = frappe.get_all(
			"Betriebskostenart",
			filters={"verteilung": "Schlüssel"},
			fields=["name", "schlüssel"],
			limit_page_length=0,
		)
		schluessel_names = sorted({(row.get("schlüssel") or "").strip() for row in arts or [] if row.get("schlüssel")})
		for schluessel in schluessel_names:
			total = 0.0
			for wohnung in wohnungen:
				try:
					total += float(get_effective_zustandsschluessel_value(wohnung, stichtag, schluessel) or 0)
				except Exception:
					continue
			schluessel_totals[schluessel] = round(total, 2)
			try:
				wohnung_schluesselwerte[schluessel] = round(
					float(get_effective_zustandsschluessel_value(doc.get("wohnung"), stichtag, schluessel) or 0), 2
				)
			except Exception:
				wohnung_schluesselwerte[schluessel] = 0.0
	except Exception:
		schluessel_totals = {}
		wohnung_schluesselwerte = {}

	return {
		"total_qm": total_qm,
		"total_bewohner": total_bewohner,
		"schluessel_totals": schluessel_totals,
		"wohnung_schluesselwerte": wohnung_schluesselwerte,
	}
