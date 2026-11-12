"""Frappe adapter: use effective installed metadata and parent field permissions."""

import frappe
from frappe.model import get_permitted_fields
from frappe.utils import cint

from hausverwaltung.hausverwaltung.agent_tools import read_api
from hausverwaltung.hausverwaltung.agent_tools.contracts import AgentToolError, is_sensitive_field
from hausverwaltung.hausverwaltung.agent_tools.form_metadata import (
	LAYOUT_TYPES,
	TABLE_TYPES,
	FormMetadataError,
)


class FormMetadataBackend:
	def load(self, doctype, language):
		try:
			read_api._ensure_agent_api_access()
			read_api._ensure_doctype_readable(doctype)
			meta = frappe.get_meta(doctype)
			if meta.istable:
				raise FormMetadataError(
					"INVALID_ARGUMENT",
					"Child-Felder über den lesbaren Eltern-DocType und table_field abrufen.",
				)
			rows = self._fields(meta, language)
			tables = {}
			for row in rows:
				if row["fieldtype"] not in TABLE_TYPES or not row.get("options"):
					continue
				child_doctype = row["options"]
				if child_doctype in read_api.SENSITIVE_DOCTYPES:
					continue
				child = frappe.get_meta(child_doctype)
				if not child.istable:
					continue
				tables[row["fieldname"]] = self._fields(child, language, parent=meta, table=row)
				row["child_field_count"] = len(tables[row["fieldname"]])
				row["read_via_parent"] = 1
			return {
				"doctype": meta.name,
				"module": meta.module,
				"istable": cint(meta.istable),
				"title_field": meta.title_field or "name",
				"search_fields": meta.search_fields or "",
				"fields": rows,
				"tables": tables,
			}
		except AgentToolError as exc:
			raise FormMetadataError(exc.code, str(exc)) from exc

	def _label(self, label, language):
		return frappe._(label, lang=language) if label else ""

	def _fields(self, meta, language, parent=None, table=None):
		parenttype = parent.name if parent else None
		permitted = set(
			get_permitted_fields(
				meta.name,
				parenttype=parenttype,
				user=frappe.session.user,
				permission_type="read",
				ignore_virtual=False,
			)
		)
		levels = set(
			meta.get_permlevel_access(permission_type="read", parenttype=parenttype, user=frappe.session.user)
		)
		if frappe.session.user == "Administrator":
			levels.update(cint(df.permlevel) for df in meta.fields)
		rows, tab, section = [], None, None
		for df in meta.fields:
			if df.fieldtype == "Tab Break":
				tab = self._layout(df, language)
				section = None
				continue
			if df.fieldtype == "Section Break":
				section = self._layout(df, language)
				continue
			if (
				not df.fieldname
				or df.fieldtype in LAYOUT_TYPES
				or is_sensitive_field(df.fieldname, df.fieldtype)
			):
				continue
			if df.fieldname not in permitted and not (
				df.fieldtype in TABLE_TYPES and cint(df.permlevel) in levels
			):
				continue
			label = df.label or df.fieldname
			row = {
				"fieldname": df.fieldname,
				"label": self._label(label, language),
				"label_original": label,
				"fieldtype": df.fieldtype,
				"reqd": cint(df.reqd),
				"read_only": cint(df.read_only),
				"hidden": cint(df.hidden),
				"allow_on_submit": cint(df.allow_on_submit),
				"is_virtual": cint(df.get("is_virtual")),
			}
			for key in ("options", "depends_on", "mandatory_depends_on", "read_only_depends_on"):
				if df.get(key):
					row[key] = df.get(key)
			path = [part for part in (tab, section) if part]
			if table:
				path = [
					*table["form_path"],
					{
						"fieldname": table["fieldname"],
						"label": table["label"],
						"fieldtype": table["fieldtype"],
						**{key: table[key] for key in ("hidden", "depends_on") if table.get(key)},
					},
					*path,
				]
				row["table_field"] = table["fieldname"]
			row["form_path"] = path
			rows.append(row)
		return rows

	def _layout(self, df, language):
		layout = {
			"fieldname": df.fieldname,
			"label": self._label(df.label or "", language),
			"fieldtype": df.fieldtype,
		}
		for key in ("hidden", "depends_on"):
			if df.get(key):
				layout[key] = df.get(key)
		return layout
