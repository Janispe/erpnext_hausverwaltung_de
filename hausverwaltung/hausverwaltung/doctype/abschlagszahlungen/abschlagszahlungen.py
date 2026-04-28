from __future__ import annotations

import frappe
from frappe.model.document import Document
from frappe.utils import cstr


class Abschlagszahlungen(Document):
	@frappe.whitelist()
	def create_or_update_abschlaege(self):
		"""Create/update linked Abschlagszahlung docs from table rows. Optionally pre-fill plan."""
		self.check_permission("write")

		rows = list(self.get("abschlaege") or [])
		if not rows:
			frappe.throw("Bitte mindestens eine Zeile erfassen.")

		created = 0
		updated = 0
		failed = 0

		for row in rows:
			try:
				is_existing = bool(row.get("abschlagszahlung")) and frappe.db.exists("Zahlungsplan", row.abschlagszahlung)
				az = _upsert_abschlagszahlung_from_row(self, row)
				row.abschlagszahlung = az.name
				row.last_error = None

				rhythmus = self.get("default_plan_rhythmus")
				von = self.get("default_plan_von")
				bis = self.get("default_plan_bis")
				if rhythmus and von and bis and float(row.get("betrag") or 0) > 0:
					az.plan_vorbelegen(rhythmus=rhythmus, von=von, bis=bis, betrag=float(row.betrag))

				if is_existing:
					updated += 1
				else:
					created += 1
			except Exception:
				failed += 1
				row.last_error = cstr(frappe.get_traceback())

		self.save(ignore_permissions=True)
		frappe.msgprint(f"Fertig: erstellt/aktualisiert={created + updated}, Fehler={failed}", alert=True)
		return {"ok": True, "updated": updated, "created": created, "failed": failed}


def _upsert_abschlagszahlung_from_row(parent: Abschlagszahlungen, row: Document):
	if not parent.get("company"):
		frappe.throw("Bitte eine Company auswählen.")

	payload = {
		"doctype": "Zahlungsplan",
		"company": parent.company,
		"bezeichnung": row.get("bezeichnung"),
		"lieferant": row.get("lieferant"),
		"vertragsnummer": row.get("vertragsnummer"),
		"immobilie": row.get("immobilie"),
		"wohnung": row.get("wohnung"),
		"bemerkung": row.get("bemerkung"),
		"betrag": row.get("betrag"),
		"bank_account": row.get("bank_account") or parent.get("bank_account"),
		"reference_no": row.get("reference_no"),
		"kostenart": row.get("kostenart"),
		"kostenart_nicht_umlagefaehig": row.get("kostenart_nicht_umlagefaehig"),
	}

	if row.get("abschlagszahlung") and frappe.db.exists("Zahlungsplan", row.abschlagszahlung):
		az = frappe.get_doc("Zahlungsplan", row.abschlagszahlung)
		az.update(payload)
		az.save(ignore_permissions=True)
		return az

	az = frappe.get_doc(payload)
	az.insert(ignore_permissions=True)
	return az
