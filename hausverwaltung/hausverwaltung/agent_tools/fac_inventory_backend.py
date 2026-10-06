"""Permission-preserving inventory reads, reusing the overview identity checks."""

from hausverwaltung.hausverwaltung.agent_tools.fac_overview import OverviewError
from hausverwaltung.hausverwaltung.agent_tools.fac_overview_backend import OverviewBackend


class InventoryBackend(OverviewBackend):
	def _fields(self, *args, **kwargs):
		from hausverwaltung.hausverwaltung.agent_tools.contracts import AgentToolError

		try:
			return super()._fields(*args, **kwargs)
		except AgentToolError as exc:
			raise OverviewError(exc.code, exc.message)

	def visible_rows(self, doctype, filters, fields, limit, offset):
		from hausverwaltung.hausverwaltung.agent_tools import read_api
		from hausverwaltung.hausverwaltung.agent_tools.contracts import AgentToolError

		try:
			read_api._ensure_agent_api_access()
			read_api._ensure_doctype_readable(doctype)
			safe = self._fields(doctype, fields)
			filter_fields = [item[0] for item in filters]
			if filter_fields:
				self._fields(doctype, filter_fields)
			rows = self.frappe.get_list(
				doctype,
				filters=filters,
				fields=safe,
				order_by="name asc",
				limit_start=offset,
				limit_page_length=limit,
			)
			# Custom has_permission hooks can be stricter than get_list's SQL
			# conditions. Never return rows/counts from such an incomplete page.
			if any(not self._can_read_doc(doctype, row["name"]) for row in rows):
				raise OverviewError(
					"PERMISSION_INCOMPLETE",
					"Datensatzberechtigungen erlauben keine vollständige Seite; keine ungeprüften Daten oder Zählung.",
				)
			return rows
		except AgentToolError as exc:
			raise OverviewError(exc.code, exc.message)
