import frappe
from frappe import _
from frappe.model.document import Document


class BetriebskostenFestbetrag(Document):
	def validate(self) -> None:
		self._validate_reference_or_label()
		self._validate_free_label_not_cost_type()
		self._validate_dates()
		self._validate_no_overlap_in_parent()

	def _validate_reference_or_label(self) -> None:
		betriebskostenart = (getattr(self, "betriebskostenart", None) or "").strip()
		bezeichnung = (getattr(self, "bezeichnung", None) or "").strip()
		self.betriebskostenart = betriebskostenart or None
		self.bezeichnung = bezeichnung or None
		if bool(betriebskostenart) == bool(bezeichnung):
			frappe.throw(_("Bitte entweder eine Kostenart oder eine freie Bezeichnung angeben."))

	def _validate_free_label_not_cost_type(self) -> None:
		bezeichnung = (getattr(self, "bezeichnung", None) or "").strip()
		if not bezeichnung:
			return

		if frappe.db.exists("Betriebskostenart", bezeichnung):
			frappe.throw(
				_(
					"Die freie Bezeichnung '{0}' entspricht einer vorhandenen Betriebskostenart. "
					"Bitte wählen Sie diese als Kostenart aus oder verwenden Sie eine andere freie Bezeichnung."
				).format(bezeichnung)
			)

	def _identity(self):
		betriebskostenart = (getattr(self, "betriebskostenart", None) or "").strip()
		if betriebskostenart:
			return ("betriebskostenart", betriebskostenart)
		return ("bezeichnung", (getattr(self, "bezeichnung", None) or "").strip().casefold())

	def _validate_dates(self) -> None:
		if not self.gueltig_von or not self.gueltig_bis:
			return
		if self.gueltig_von > self.gueltig_bis:
			frappe.throw(_("Gültig von darf nicht nach Gültig bis liegen."))

	def _validate_no_overlap_in_parent(self) -> None:
		"""Prüfe Überlappung anhand der Geschwister-Rows im selben Mietvertrag."""
		if not (self.parent and self._identity()[1] and self.gueltig_von and self.gueltig_bis):
			return
		identity = self._identity()
		try:
			parent_doc = frappe.get_doc(self.parenttype or "Mietvertrag", self.parent)
		except Exception:
			return
		for sibling in parent_doc.get(self.parentfield or "festbetraege") or []:
			if sibling.name == self.name:
				continue
			sibling_art = (getattr(sibling, "betriebskostenart", None) or "").strip()
			sibling_identity = (
				("betriebskostenart", sibling_art)
				if sibling_art
				else ("bezeichnung", (getattr(sibling, "bezeichnung", None) or "").strip().casefold())
			)
			if sibling_identity != identity:
				continue
			if not (sibling.gueltig_von and sibling.gueltig_bis):
				continue
			if sibling.gueltig_von <= self.gueltig_bis and sibling.gueltig_bis >= self.gueltig_von:
				frappe.throw(
					_("Für diesen Mietvertrag und diesen Festbetrag existiert bereits ein überlappender Festbetrag-Zeitraum.")
				)
