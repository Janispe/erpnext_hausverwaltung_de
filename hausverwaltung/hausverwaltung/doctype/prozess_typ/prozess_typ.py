from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class ProzessTyp(Document):
	def validate(self) -> None:
		self._validate_trigger_uniqueness()
		self._validate_plugin_keys_unique()

	def _validate_trigger_uniqueness(self) -> None:
		seen: set[tuple[str, str]] = set()
		for t in self.get("triggers") or []:
			key = (t.source_doctype or "").strip()
			tkey = (t.key or "").strip()
			if not key or not tkey:
				continue
			pair = (key, tkey)
			if pair in seen:
				frappe.throw(
					_("Doppelter Trigger '{0}' auf Quell-Doctype '{1}'.").format(tkey, key)
				)
			seen.add(pair)

	def _validate_plugin_keys_unique(self) -> None:
		for field in ("validators", "update_hooks", "completion_blockers", "custom_task_handlers"):
			seen: set[str] = set()
			for row in self.get(field) or []:
				key = (row.plugin_key or "").strip()
				if not key:
					continue
				if key in seen:
					frappe.throw(
						_("Doppelter Plugin-Key '{0}' im Feld {1}.").format(key, field)
					)
				seen.add(key)
