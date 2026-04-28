import frappe
from frappe import _
from frappe.model.document import Document


class BetriebskostenFestbetrag(Document):
	def validate(self) -> None:
		self._validate_dates()
		self._validate_no_overlap_in_parent()

	def _validate_dates(self) -> None:
		if not self.gueltig_von or not self.gueltig_bis:
			return
		if self.gueltig_von > self.gueltig_bis:
			frappe.throw(_("Gültig von darf nicht nach Gültig bis liegen."))

	def _validate_no_overlap_in_parent(self) -> None:
		"""Prüfe Überlappung anhand der Geschwister-Rows im selben Mietvertrag."""
		if not (self.parent and self.betriebskostenart and self.gueltig_von and self.gueltig_bis):
			return
		try:
			parent_doc = frappe.get_doc(self.parenttype or "Mietvertrag", self.parent)
		except Exception:
			return
		for sibling in parent_doc.get(self.parentfield or "festbetraege") or []:
			if sibling.name == self.name:
				continue
			if sibling.betriebskostenart != self.betriebskostenart:
				continue
			if not (sibling.gueltig_von and sibling.gueltig_bis):
				continue
			if sibling.gueltig_von <= self.gueltig_bis and sibling.gueltig_bis >= self.gueltig_von:
				frappe.throw(
					_("Für diesen Mietvertrag und diese Betriebskostenart existiert bereits ein überlappender Festbetrag.")
				)
