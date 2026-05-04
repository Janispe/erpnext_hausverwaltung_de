"""DocType ``Heizkostenabrechnung Immobilie`` — Sammel-/Eingang-Container.

Bündelt eine Wärmedienst-Abrechnung für eine ganze Immobilie:
- Periode + Wärmedienst + Original-PDF einmal erfassen
- Per Klick werden für jeden im Zeitraum aktiven Mietvertrag der Immobilie
  ``Heizkostenabrechnung Mieter``-Drafts angelegt, mit Vorauszahlung schon
  vorbefüllt aus den existierenden Mietrechnungen.
- Im Form: editierbare ``mieter_positionen``-Tabelle pro Mieter — HV trägt
  ``kosten_gesamt`` inline ein, ohne durch jeden Mieter-Doc zu klicken.
- Beim Parent-Save werden Tabellen-Edits zurück in die HK-Mieter-Docs
  synchronisiert (nur bei nicht-submitteten Children — submittete sind read-only).
- Beim Parent-Onload wird die Tabelle frisch aus den Mieter-Docs hydriert
  (HK Mieter Doc bleibt Source of Truth).
- Cancel des Parent storniert alle Mieter-Belege (inkl. deren Sales Invoices)
  via ``allow_cancel_via_head``-Flag (Pattern aus BK Immobilie).

Im Gegensatz zu ``Betriebskostenabrechnung Immobilie`` enthält dieser
Container **keine** Verteilungs-Logik (qm/Schlüssel/etc.) — die HK-Verteilung
übernimmt extern der Wärmedienst.
"""

from __future__ import annotations

from typing import Any, Dict, List

import frappe
from frappe.model.document import Document
from frappe.utils import getdate

from hausverwaltung.hausverwaltung.scripts.betriebskosten.operating_cost_prepaiment_calc import (
	calc_hk_vorauszahlungen,
)


class HeizkostenabrechnungImmobilie(Document):
	def autoname(self) -> None:
		if getattr(self, "name", None):
			return
		base_parts = [str(p) for p in (self.immobilie, self.von, self.bis) if p]
		base_name = " ".join(base_parts).strip()
		if not base_name:
			return
		# MySQL `tab*.name` ist VARCHAR(140)
		MAX_NAME_LEN = 130
		if len(base_name) > MAX_NAME_LEN:
			base_name = base_name[:MAX_NAME_LEN].rstrip("-").rstrip()
		candidate = base_name
		suffix = 1
		while frappe.db.exists("Heizkostenabrechnung Immobilie", candidate, cache=False):
			suffix += 1
			candidate = f"{base_name}-{suffix}"
		self.name = candidate

	def validate(self) -> None:
		if self.von and self.bis and self.von > self.bis:
			frappe.throw("'Von' muss vor oder gleich 'Bis' liegen.")

	def onload(self) -> None:
		"""Hydriert die Positionen-Tabelle aus den HK-Mieter-Docs (Source of Truth)
		und berechnet Summen + ``can_manual_cancel``-Flag.
		"""
		self._hydrate_positions_from_children()
		self._recompute_summen()
		self.set_onload("can_manual_cancel", self._can_manual_cancel())

	def before_save(self) -> None:
		"""Sync die Tabellen-Werte zurück in die HK-Mieter-Docs.

		- Nur Rows die mit einem existierenden HK Mieter Doc verknüpft sind
		  (``heizkostenabrechnung_mieter`` gesetzt) UND deren Doc noch im
		  Entwurf (docstatus=0) ist, werden zurückgeschrieben.
		- Submittete Rows sind read-only — Edits werden ignoriert (UI sollte
		  das ohnehin verhindern; defensiv prüfen wir hier nochmal).
		"""
		if not self.is_new():
			self._sync_table_to_children()
		# Differenz pro Row neu berechnen für die UI (auch für reine Anzeige)
		for row in self.mieter_positionen or []:
			row.differenz = round(float(row.kosten_gesamt or 0) - float(row.vorauszahlungen or 0), 2)
		self._recompute_summen()

	def before_submit(self) -> None:
		"""Vor dem Submit: stelle sicher dass alle Mieter-Children submittet
		sind. Wenn nicht: submitte sie automatisch (Bulk-Submit-Verhalten).
		Das matcht die BK-Pattern-UX und macht den Workflow „in einem Klick".
		"""
		open_children = self._get_children(status_filter="open")
		if open_children:
			# Auto-Submit der Children: für jeden Draft mit gesetztem kosten_gesamt
			# wird .submit() aufgerufen → erzeugt SI/CN.
			submitted: List[str] = []
			errors: List[str] = []
			for c in open_children:
				if c.get("kosten_gesamt") in (None, ""):
					errors.append(f"{c['name']}: kosten_gesamt nicht gesetzt")
					continue
				try:
					doc = frappe.get_doc("Heizkostenabrechnung Mieter", c["name"])
					doc.submit()
					submitted.append(doc.name)
				except Exception as e:
					errors.append(f"{c['name']}: {str(e)[:200]}")
			if errors:
				frappe.throw(
					f"Es konnten {len(errors)} Mieter-Drafts nicht submittet werden:<br>"
					+ "<br>".join(f"• {e}" for e in errors[:10])
				)

	def on_submit(self) -> None:
		self.db_set("status", "Submittet")

	def on_cancel(self) -> None:
		"""Cascade: storniere/lösche alle Mieter-Belege.

		- Submitted Children → cancel mit ``allow_cancel_via_head``-Flag
		- Draft Children → delete
		"""
		children = frappe.get_all(
			"Heizkostenabrechnung Mieter",
			filters={"heizkostenabrechnung_immobilie": self.name},
			fields=["name", "docstatus"],
		)
		for ch in children:
			try:
				if int(ch.get("docstatus") or 0) == 1:
					doc = frappe.get_doc("Heizkostenabrechnung Mieter", ch["name"])
					doc.flags.allow_cancel_via_head = True
					doc.flags.ignore_permissions = True
					doc.cancel()
				elif int(ch.get("docstatus") or 0) == 0:
					frappe.delete_doc(
						"Heizkostenabrechnung Mieter",
						ch["name"],
						ignore_permissions=True,
						force=1,
					)
			except Exception as e:
				frappe.log_error(
					frappe.get_traceback(),
					f"HK Immobilie cascade cancel fehlgeschlagen für {ch['name']}: {e}",
				)
		self.db_set("status", "Eingang")

	# ------------------------------------------------------------------ helpers

	def _can_manual_cancel(self) -> bool:
		try:
			return bool(frappe.has_permission(doc=self, ptype="cancel"))
		except Exception:
			return False

	def _get_children(self, status_filter: str = "all") -> List[Dict[str, Any]]:
		"""Lade Mieter-Children. status_filter: 'all' / 'open' / 'submitted'."""
		filters: Dict[str, Any] = {"heizkostenabrechnung_immobilie": self.name}
		if status_filter == "open":
			filters["docstatus"] = 0
		elif status_filter == "submitted":
			filters["docstatus"] = 1
		return frappe.get_all(
			"Heizkostenabrechnung Mieter",
			filters=filters,
			fields=[
				"name",
				"docstatus",
				"mietvertrag",
				"customer",
				"wohnung",
				"vorauszahlungen",
				"kosten_gesamt",
				"sales_invoice",
				"credit_note",
			],
			order_by="customer asc",
		)

	def _hydrate_positions_from_children(self) -> None:
		"""Lädt alle HK-Mieter-Children und ersetzt die Positionen-Tabelle damit.

		Die Tabelle wird damit zur reinen View — die Werte in der DB-Tabelle
		(``tabHeizkostenabrechnung Position``) werden bei jedem Form-Open
		überschrieben. Source of Truth bleibt der HK-Mieter-Doc.
		"""
		children = self._get_children()
		# Existierende Tabellen-Rows wegwerfen + neu aufbauen
		self.set("mieter_positionen", [])
		for c in children:
			vor = float(c.get("vorauszahlungen") or 0)
			kos = float(c.get("kosten_gesamt") or 0)
			self.append(
				"mieter_positionen",
				{
					"mietvertrag": c.get("mietvertrag"),
					"customer": c.get("customer"),
					"wohnung": c.get("wohnung"),
					"vorauszahlungen": vor,
					"kosten_gesamt": kos,
					"differenz": round(kos - vor, 2),
					"heizkostenabrechnung_mieter": c.get("name"),
					"child_docstatus": int(c.get("docstatus") or 0),
				},
			)

	def _sync_table_to_children(self) -> None:
		"""Schreibt Tabellen-Edits (kosten_gesamt) zurück in die HK-Mieter-Docs.

		Nur für Rows mit verknüpftem Doc + Doc noch in Draft. Submitted/Cancelled
		Rows werden ignoriert. Wenn ``kosten_gesamt`` sich nicht geändert hat
		(im Vergleich zum aktuellen DB-Wert), kein Save → keine unnötigen Writes.
		"""
		for row in self.mieter_positionen or []:
			doc_name = (row.heizkostenabrechnung_mieter or "").strip()
			if not doc_name:
				continue
			if int(row.child_docstatus or 0) != 0:
				# Submittet oder cancelled — keine Edits erlaubt
				continue
			try:
				doc = frappe.get_doc("Heizkostenabrechnung Mieter", doc_name)
			except frappe.DoesNotExistError:
				continue
			if int(doc.docstatus or 0) != 0:
				# Inzwischen submittet/cancelled (race condition) — skip
				continue
			new_kosten = float(row.kosten_gesamt or 0)
			if abs(float(doc.kosten_gesamt or 0) - new_kosten) < 0.005:
				# Keine Änderung — kein Save nötig
				continue
			doc.kosten_gesamt = new_kosten
			doc.save(ignore_permissions=True)

	def _recompute_summen(self) -> None:
		"""Setzt mieter_count + Summen-Felder als virtuelle Anzeige."""
		count = 0
		kosten = 0.0
		vor = 0.0
		for row in self.mieter_positionen or []:
			count += 1
			kosten += float(row.kosten_gesamt or 0)
			vor += float(row.vorauszahlungen or 0)
		self.mieter_count = count
		self.summe_kosten = round(kosten, 2)
		self.summe_vorauszahlungen = round(vor, 2)
		self.summe_differenz = round(kosten - vor, 2)


# ============================================================================
# Whitelisted API
# ============================================================================


@frappe.whitelist()
def create_mieter_drafts(name: str) -> Dict[str, Any]:
	"""Legt für jeden im Zeitraum [von..bis] aktiven Mietvertrag der Immobilie
	einen ``Heizkostenabrechnung Mieter``-Draft an, mit Vorauszahlung schon
	vorbefüllt. Im Anschluss wird die Positionen-Tabelle des Parents neu
	hydriert und gespeichert.

	Idempotent: wenn schon ein HK-Mieter-Doc unter diesem Parent existiert,
	wird es übersprungen.

	Returns: {created: [...], skipped: [...], no_wohnung: [...], parent_status}
	"""
	parent = frappe.get_doc("Heizkostenabrechnung Immobilie", name)
	parent.check_permission("write")

	if not (parent.immobilie and parent.von and parent.bis):
		frappe.throw("Immobilie + Von + Bis müssen gesetzt sein.")
	if int(parent.docstatus or 0) != 0:
		frappe.throw("Mieter-Drafts können nur im Entwurf-Status erzeugt werden.")

	von = getdate(parent.von)
	bis = getdate(parent.bis)

	# Alle Mietverträge die a) Wohnung in dieser Immobilie haben und
	# b) im Zeitraum [von..bis] aktiv sind (Überlappung).
	mvs = frappe.db.sql(
		"""
		SELECT mv.name, mv.kunde, mv.wohnung, mv.von, mv.bis
		FROM `tabMietvertrag` mv
		JOIN `tabWohnung` w ON w.name = mv.wohnung
		WHERE w.immobilie = %(imm)s
		  AND mv.von <= %(bis)s
		  AND (mv.bis IS NULL OR mv.bis >= %(von)s)
		ORDER BY mv.wohnung, mv.von
		""",
		{"imm": parent.immobilie, "von": von, "bis": bis},
		as_dict=True,
	)

	# Existierende HK-Mieter unter diesem Parent (für Idempotenz)
	existing = {
		(r["mietvertrag"], str(r["von"]), str(r["bis"]))
		for r in frappe.get_all(
			"Heizkostenabrechnung Mieter",
			filters={"heizkostenabrechnung_immobilie": parent.name},
			fields=["mietvertrag", "von", "bis"],
		)
	}

	created: List[str] = []
	skipped: List[str] = []
	no_wohnung: List[str] = []
	for mv in mvs:
		if not mv.get("kunde"):
			no_wohnung.append(f"{mv['name']} (kein Customer)")
			continue
		key = (mv["name"], str(von), str(bis))
		if key in existing:
			skipped.append(mv["name"])
			continue

		# Vorauszahlung vorbefüllen
		try:
			vz = calc_hk_vorauszahlungen(mv["name"], von, bis)
			vorauszahlung = float(vz.get("actual_total") or 0.0)
		except Exception:
			vorauszahlung = 0.0

		child = frappe.new_doc("Heizkostenabrechnung Mieter")
		child.mietvertrag = mv["name"]
		child.customer = mv.get("kunde")
		child.wohnung = mv.get("wohnung")
		child.von = von
		child.bis = bis
		child.datum = bis
		child.waermedienst = parent.waermedienst
		child.waermedienst_referenz = parent.waermedienst_referenz
		child.vorauszahlungen = vorauszahlung
		child.kosten_gesamt = 0
		child.heizkostenabrechnung_immobilie = parent.name
		child.insert(ignore_permissions=True)
		created.append(child.name)

	if created:
		parent.db_set("status", "Mieter-Drafts angelegt")
	frappe.db.commit()

	return {
		"created": created,
		"skipped": skipped,
		"no_wohnung": no_wohnung,
		"parent_status": parent.get("status"),
	}


@frappe.whitelist()
def submit_all_pending(name: str) -> Dict[str, Any]:
	"""Submittet alle noch nicht-submitteten Mieter-Children einzeln.

	Praktisch nur als „letzter Klick" vor dem Parent-Submit nutzbar — beim
	Parent-Submit selbst werden ohnehin alle Children automatisch submittet
	(siehe ``before_submit``).

	Returns: {submitted: [...], skipped: [...], errors: [...]}
	"""
	parent = frappe.get_doc("Heizkostenabrechnung Immobilie", name)
	parent.check_permission("submit")

	open_children = frappe.get_all(
		"Heizkostenabrechnung Mieter",
		filters={"heizkostenabrechnung_immobilie": parent.name, "docstatus": 0},
		fields=["name", "kosten_gesamt"],
	)
	submitted: List[str] = []
	skipped: List[Dict[str, Any]] = []
	errors: List[Dict[str, Any]] = []

	for ch in open_children:
		if ch.get("kosten_gesamt") in (None, ""):
			skipped.append({"name": ch["name"], "reason": "kosten_gesamt nicht gesetzt"})
			continue
		try:
			doc = frappe.get_doc("Heizkostenabrechnung Mieter", ch["name"])
			doc.submit()
			submitted.append(doc.name)
		except Exception as e:
			errors.append({"name": ch["name"], "error": str(e)[:300]})

	if submitted and not errors:
		frappe.db.commit()
	return {"submitted": submitted, "skipped": skipped, "errors": errors}
