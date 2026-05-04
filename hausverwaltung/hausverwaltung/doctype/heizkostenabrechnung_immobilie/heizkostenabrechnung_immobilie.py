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
		"""Save eines Draft-Parents (docstatus=0): Tabellen-Werte in die
		verlinkten HK-Mieter-Drafts zurück synchronisieren.

		Für submittete Parents wird stattdessen ``before_update_after_submit``
		aufgerufen (Frappe-Lifecycle), das die Diff-only Korrektur fährt.
		"""
		if self.is_new():
			return
		# Korrektur-Summary für Frontend-Toast initialisieren
		self.flags._correction_summary = {"unchanged": 0, "replaced": [], "errors": []}
		self._sync_table_to_children()
		# Differenz pro Row + Summen neu berechnen
		for row in self.mieter_positionen or []:
			row.differenz = round(float(row.kosten_gesamt or 0) - float(row.vorauszahlungen or 0), 2)
		self._recompute_summen()

	def before_update_after_submit(self) -> None:
		"""Save eines submitteten Parents: Diff-only Korrektur.

		Für jede Tabellen-Row, deren ``kosten_gesamt`` sich vom verlinkten
		HK-Mieter-Doc unterscheidet, wird die alte Mieter-Abrechnung
		storniert (= alte SI cancel) und eine neue erstellt + submittet
		(= neue SI). Unveränderte Rows bleiben unangetastet.

		Wird von Frappe automatisch beim ``save()`` eines Docs mit
		``docstatus=1`` aufgerufen — Voraussetzung: das geänderte Feld hat
		``allow_on_submit=1`` (siehe ``mieter_positionen.kosten_gesamt``).
		"""
		# Korrektur-Summary für Frontend-Toast initialisieren
		self.flags._correction_summary = {"unchanged": 0, "replaced": [], "errors": []}
		self._apply_corrections_from_table()
		# Differenz pro Row + Summen neu berechnen
		for row in self.mieter_positionen or []:
			row.differenz = round(float(row.kosten_gesamt or 0) - float(row.vorauszahlungen or 0), 2)
		self._recompute_summen()

	def _apply_corrections_from_table(self) -> None:
		"""Diff-only Korrektur-Workflow für submittete Parents.

		Pro Tabellen-Row:
		1. Lade aktuelle Mieter-Abrechnung (verlinkt via ``row.heizkostenabrechnung_mieter``)
		2. Vergleiche ``row.kosten_gesamt`` mit dem Wert im Mieter-Doc
		3. Wenn unverändert → Skip (alte SI bleibt)
		4. Wenn geändert:
		   - **Pre-flight**: prüft ob die alte SI/CN schon eine Payment-
		     Allokation hat — wenn ja, wird die ganze Korrektur abgebrochen
		     (atomar) mit klarer Liste der betroffenen Mieter und Hinweis auf
		     manuelles Vorgehen.
		   - Alte Mieter-Abrechnung canceln (storniert alte SI via on_cancel)
		   - Neue Mieter-Abrechnung mit identischen Stammdaten + neuem
		     ``kosten_gesamt`` anlegen + submitten (= neue SI via on_submit)
		   - Tabellen-Link auf die neue Mieter-Abrechnung umbiegen

		Ergebnis-Counter werden in ``self.flags._correction_summary`` abgelegt
		— das JS liest sie nach dem Save und zeigt einen Toast.
		"""
		summary = self.flags._correction_summary

		# 1) Pass 1 — Diff identifizieren + Pre-flight Payment-Check
		to_correct: list[dict] = []  # geänderte Rows die korrigiert werden müssen
		paid_blockers: list[dict] = []  # Rows mit bereits bezahlter SI

		for row in self.mieter_positionen or []:
			old_name = (row.heizkostenabrechnung_mieter or "").strip()
			if not old_name:
				continue
			try:
				old_doc = frappe.get_doc("Heizkostenabrechnung Mieter", old_name)
			except frappe.DoesNotExistError:
				continue
			# Nur submittete Mieter-Docs werden hier verarbeitet
			if int(old_doc.docstatus or 0) != 1:
				continue

			new_kosten = float(row.kosten_gesamt or 0)
			old_kosten = float(old_doc.kosten_gesamt or 0)
			if abs(new_kosten - old_kosten) < 0.005:
				summary["unchanged"] += 1
				continue

			# Diff erkannt → Payment-Check für die zugehörige(n) SI/CN
			si_name = (old_doc.get("sales_invoice") or "").strip()
			cn_name = (old_doc.get("credit_note") or "").strip()
			paid_refs: list[dict] = []
			for ref_name in (si_name, cn_name):
				if not ref_name:
					continue
				allocations = _get_payment_allocations(ref_name)
				if allocations:
					paid_refs.extend(allocations)

			if paid_refs:
				paid_blockers.append(
					{
						"row": row,
						"old_doc": old_doc,
						"customer": old_doc.customer,
						"old_kosten": old_kosten,
						"new_kosten": new_kosten,
						"si": si_name,
						"cn": cn_name,
						"allocations": paid_refs,
					}
				)
			else:
				to_correct.append(
					{
						"row": row,
						"old_doc": old_doc,
						"old_kosten": old_kosten,
						"new_kosten": new_kosten,
					}
				)

		# 2) Wenn irgendein paid blocker → throw, ganze Korrektur abbrechen
		if paid_blockers:
			lines = [
				"<strong>Korrektur nicht möglich — folgende Mieter haben bereits Zahlungen verbucht:</strong><br>"
			]
			for b in paid_blockers:
				alloc_sum = sum(a["allocated_amount"] for a in b["allocations"])
				pe_names = ", ".join(sorted({a["payment_entry"] for a in b["allocations"]}))
				lines.append(
					f"• <strong>{frappe.utils.escape_html(b['customer'])}</strong>: "
					f"alte Rechnung <code>{b['si'] or b['cn']}</code> "
					f"hat {alloc_sum:.2f} € allokiert "
					f"(Payment Entry: {frappe.utils.escape_html(pe_names)}). "
					f"Änderung {b['old_kosten']:.2f} → {b['new_kosten']:.2f} € blockiert."
				)
			lines.append(
				"<br><br><em>So beheben:</em> Im jeweiligen Payment Entry die Zuordnung zu dieser "
				"Sales Invoice rausnehmen (oder Payment Entry stornieren), dann die Korrektur "
				"erneut speichern."
			)
			frappe.throw(
				msg="<br>".join(lines),
				title="Korrektur blockiert: Zahlungen vorhanden",
			)

		# 3) Pass 2 — keine Blocker, jetzt die geänderten Rows wirklich korrigieren
		for entry in to_correct:
			row = entry["row"]
			old_doc = entry["old_doc"]
			old_kosten = entry["old_kosten"]
			new_kosten = entry["new_kosten"]
			old_name = old_doc.name
			try:
				old_doc.flags.allow_cancel_via_head = True
				old_doc.flags.ignore_permissions = True
				old_doc.cancel()  # storniert old SI/CN via on_cancel

				new_doc = frappe.new_doc("Heizkostenabrechnung Mieter")
				new_doc.mietvertrag = old_doc.mietvertrag
				new_doc.customer = old_doc.customer
				new_doc.wohnung = old_doc.wohnung
				new_doc.immobilie = old_doc.immobilie
				new_doc.von = old_doc.von
				new_doc.bis = old_doc.bis
				new_doc.datum = old_doc.datum
				new_doc.waermedienst = old_doc.waermedienst
				new_doc.waermedienst_referenz = old_doc.waermedienst_referenz
				new_doc.vorauszahlungen = old_doc.vorauszahlungen  # bleibt
				new_doc.kosten_gesamt = new_kosten  # NEU
				new_doc.heizkostenabrechnung_immobilie = self.name
				new_doc.insert(ignore_permissions=True)
				new_doc.submit()  # erzeugt neue SI/CN via on_submit

				# Tabellen-Link umbiegen auf den neuen Doc
				row.heizkostenabrechnung_mieter = new_doc.name
				row.child_docstatus = 1
				summary["replaced"].append(
					{
						"old": old_name,
						"new": new_doc.name,
						"customer": old_doc.customer,
						"old_kosten": old_kosten,
						"new_kosten": new_kosten,
					}
				)
			except Exception as e:
				summary["errors"].append({"row": old_name, "error": str(e)[:300]})

	def on_update_after_submit(self) -> None:
		"""Wird nach Save eines submitteten Docs aufgerufen — wir nutzen das,
		um dem Frontend per ``msgprint`` ein Korrektur-Summary anzuzeigen.
		"""
		summary = getattr(self.flags, "_correction_summary", None)
		if not summary:
			return
		replaced = summary.get("replaced") or []
		errors = summary.get("errors") or []
		if not replaced and not errors:
			return  # Nichts geändert → kein Toast
		lines = []
		if replaced:
			lines.append(
				f"<strong>{len(replaced)} Mieter neu fakturiert:</strong>"
			)
			for r in replaced[:20]:
				delta = r["new_kosten"] - r["old_kosten"]
				sign = "+" if delta > 0 else ""
				lines.append(
					f"• {r['customer']}: {r['old_kosten']:.2f} € → {r['new_kosten']:.2f} € "
					f"({sign}{delta:.2f} €) "
					f"[alt: {r['old']} canceled, neu: {r['new']}]"
				)
			if len(replaced) > 20:
				lines.append(f"… und {len(replaced) - 20} weitere")
		if errors:
			lines.append(f"<br><strong style='color:red'>{len(errors)} Fehler:</strong>")
			for e in errors[:10]:
				lines.append(f"• {e['row']}: {e['error']}")
		frappe.msgprint(
			msg="<br>".join(lines),
			title="Korrektur angewandt",
			indicator="orange" if errors else "green",
		)

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
		"""Lade Mieter-Children. status_filter: 'all' / 'open' / 'submitted'.

		Gecancelte Children (docstatus=2) werden grundsätzlich ausgeblendet —
		bei Korrekturen werden alte Docs storniert und neue submitted, die
		Tabelle soll immer nur den aktuellen Stand zeigen.
		"""
		filters: Dict[str, Any] = {"heizkostenabrechnung_immobilie": self.name}
		if status_filter == "open":
			filters["docstatus"] = 0
		elif status_filter == "submitted":
			filters["docstatus"] = 1
		else:
			# "all" → 0 oder 1, NICHT 2
			filters["docstatus"] = ["!=", 2]
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
# Module-level helpers
# ============================================================================


def _get_payment_allocations(sales_invoice_name: str) -> List[Dict[str, Any]]:
	"""Liefert alle submittete Payment-Entry-Allokationen für eine Sales Invoice.

	Wird vom Pre-flight-Check der Korrektur-Logik genutzt: wenn diese Funktion
	Rows liefert, kann die SI nicht ohne weiteres canceled werden — der HV
	muss erst die Allokation manuell auflösen.
	"""
	if not sales_invoice_name:
		return []
	rows = frappe.db.sql(
		"""
		SELECT
			pe.name AS payment_entry,
			per.allocated_amount AS allocated_amount,
			pe.posting_date AS posting_date
		FROM `tabPayment Entry Reference` per
		JOIN `tabPayment Entry` pe ON pe.name = per.parent
		WHERE per.reference_doctype = 'Sales Invoice'
		  AND per.reference_name = %(name)s
		  AND pe.docstatus = 1
		""",
		{"name": sales_invoice_name},
		as_dict=True,
	)
	return [
		{
			"payment_entry": r["payment_entry"],
			"allocated_amount": float(r["allocated_amount"] or 0),
			"posting_date": r["posting_date"],
		}
		for r in rows
		if float(r["allocated_amount"] or 0) > 0.005
	]


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
