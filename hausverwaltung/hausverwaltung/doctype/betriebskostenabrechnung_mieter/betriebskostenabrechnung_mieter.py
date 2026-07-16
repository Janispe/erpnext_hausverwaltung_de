from typing import Any, Dict, List

import frappe
from frappe.contacts.doctype.address.address import get_default_address
from frappe.model.document import Document
from frappe.utils import cstr

from hausverwaltung.hausverwaltung.utils.mieter_name import (
	get_contact_last_name,
	get_hauptmieter_display_name,
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
		combined: Dict[tuple[str, str], Dict[str, object]] = {}

		def accumulate(items, column: str) -> None:
			for row in items or []:
				betriebskostenart = row.get("betriebskostenart")
				bezeichnung = row.get("bezeichnung")
				label = betriebskostenart or bezeichnung
				if not label:
					continue
				try:
					amount = round(float(row.get("betrag") or 0), 2)
				except Exception:
					amount = 0.0
				# Freie Bezeichnungen sind keine Links auf Betriebskostenart. Der
				# Typ ist Teil des Schlüssels, damit eine freie Position nicht mit
				# einer gleichnamigen verlinkten Kostenart zusammenfällt.
				key = (
					("betriebskostenart", betriebskostenart)
					if betriebskostenart
					else ("bezeichnung", bezeichnung)
				)
				entry = combined.setdefault(
					key,
					{
						"betriebskostenart": betriebskostenart,
						"bezeichnung": None if betriebskostenart else bezeichnung,
						"immobilie": 0.0,
						"wohnung": 0.0,
					},
				)
				entry[column] = round(float(entry.get(column) or 0) + amount, 2)

		immobilien_items = []
		if getattr(self, "immobilien_abrechnung", None):
			immobilien_items = _get_abrechnungsposten_rows(
				"Betriebskostenabrechnung Immobilie",
				self.immobilien_abrechnung,
				"kosten_pro_art",
			)
		elif getattr(self, "immobilien_kosten", None):
			immobilien_items = self.immobilien_kosten

		accumulate(immobilien_items, "immobilie")
		accumulate(getattr(self, "abrechnung", []) or [], "wohnung")

		from hausverwaltung.hausverwaltung.utils.bk_sort import sort_key

		return sorted(
			combined.values(),
			key=lambda row: sort_key(row.get("betriebskostenart") or row.get("bezeichnung")),
		)

	def get_immobilien_basis(self) -> Dict[str, Any]:
		"""Basis-Summen für die Drucktabelle."""
		return _get_immobilien_basis_for_doc(self)

	def get_print_context(self) -> Dict[str, object]:
		"""Kontext für freie BK-Print-Formate.

		Serienbrief-Vorlagen erwarten historisch
		``objekt``, ``empfaenger`` und ``datum``. Ein Frappe Print Format bekommt
		standardmäßig nur ``doc``; diese Methode stellt die fehlenden Werte
		für beliebige BK-Mieter-Layouts bereit.
		"""
		address = self._get_print_recipient_address()
		display_name = self._get_print_recipient_name()
		return frappe._dict(
			objekt=self,
			datum=frappe.utils.formatdate(self.get("datum") or frappe.utils.today(), "dd.MM.yyyy"),
			empfaenger=frappe._dict(
				name=self.get("customer") or self.name,
				anzeigename=display_name,
				mieter_name=display_name,
				strasse=address.get("street", ""),
				plz=address.get("zip", ""),
				ort=address.get("city", ""),
				plz_ort=address.get("plz_ort", ""),
				adresse=address.get("display", ""),
			),
		)

	def _get_print_recipient_name(self) -> str:
		name = get_hauptmieter_display_name(getattr(self, "mieter", None))
		if name:
			return name

		customer = cstr(self.get("customer")).strip()
		if customer:
			customer_name = cstr(frappe.db.get_value("Customer", customer, "customer_name")).strip()
			if customer_name:
				return customer_name
			return customer

		return cstr(self.name).strip()

	def _get_print_recipient_address(self) -> Dict[str, str]:
		customer = cstr(self.get("customer")).strip()
		if customer:
			address = self._get_print_address_for_link("Customer", customer)
			if address:
				return address

		wohnung = cstr(self.get("wohnung")).strip()
		if wohnung:
			try:
				immobilie = cstr(frappe.db.get_value("Wohnung", wohnung, "immobilie")).strip()
			except Exception:
				immobilie = ""
			if immobilie:
				try:
					linked_address = cstr(frappe.db.get_value("Immobilie", immobilie, "adresse")).strip()
				except Exception:
					linked_address = ""
				address = self._print_address_dict_from_name(linked_address)
				if address:
					return address
				address = self._get_print_address_for_link("Immobilie", immobilie)
				if address:
					return address

		return {}

	def _get_print_address_for_link(self, link_doctype: str, link_name: str) -> Dict[str, str]:
		try:
			address_name = get_default_address(link_doctype, link_name)
		except Exception:
			address_name = None
		return self._print_address_dict_from_name(address_name)

	def _print_address_dict_from_name(self, address_name: str | None) -> Dict[str, str]:
		address_name = cstr(address_name).strip()
		if not address_name:
			return {}
		try:
			address = frappe.get_cached_doc("Address", address_name)
		except Exception:
			return {}

		street = ", ".join(
			filter(
				None,
				[
					cstr(getattr(address, "address_line1", "")).strip(),
					cstr(getattr(address, "address_line2", "")).strip(),
				],
			)
		)
		zip_code = cstr(getattr(address, "pincode", None) or getattr(address, "zip", None)).strip()
		city = cstr(getattr(address, "city", "")).strip()
		plz_ort = " ".join(p for p in (zip_code, city) if p).strip()
		return {
			"street": street,
			"zip": zip_code,
			"city": city,
			"plz_ort": plz_ort,
			"display": "\n".join(filter(None, [street, plz_ort])),
		}


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
			"bezeichnung": row.get("bezeichnung"),
			"betrag": amount,
		})
	# Auch hier gruppiert sortieren — wirkt rückwirkend für bestehende BKs,
	# bei denen kosten_pro_art noch alphabetisch persistiert wurde.
	from hausverwaltung.hausverwaltung.utils.bk_sort import sort_key

	rows.sort(key=lambda r: sort_key(r.get("betriebskostenart") or r.get("bezeichnung")))
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

	return _get_immobilien_basis_for_doc(doc)


def _get_immobilien_basis_for_doc(doc) -> Dict[str, Any]:
	"""Liefert Basis-Summen für die Immobilie inkl. Schlüsselwerte."""
	head_name = doc.get("immobilien_abrechnung")
	if not head_name:
		return {"total_qm": 0.0, "total_bewohner": 0.0, "schluessel_totals": {}, "wohnung_schluesselwerte": {}}

	try:
		head = frappe.db.get_value(
			"Betriebskostenabrechnung Immobilie",
			head_name,
			["immobilie", "stichtag", "bis"],
			as_dict=True,
		)
	except Exception:
		return {"total_qm": 0.0, "total_bewohner": 0.0, "schluessel_totals": {}, "wohnung_schluesselwerte": {}}
	if not head:
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


def _get_abrechnungsposten_rows(parenttype: str, parent: str, parentfield: str) -> List[Dict[str, object]]:
	if not parent:
		return []
	return frappe.get_all(
		"Abrechnungsposten",
		filters={
			"parenttype": parenttype,
			"parent": parent,
			"parentfield": parentfield,
		},
		fields=["betriebskostenart", "bezeichnung", "betrag"],
		order_by="idx asc",
		limit_page_length=0,
	)
