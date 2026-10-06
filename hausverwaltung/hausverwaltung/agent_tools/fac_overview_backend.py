"""Permission-checked Frappe access for compact business overviews."""

from hausverwaltung.hausverwaltung.agent_tools.fac_overview import OverviewError


class OverviewBackend:
	def __init__(self):
		import frappe

		from hausverwaltung.hausverwaltung.services import assistant

		self.frappe = frappe
		self.assistant = assistant

	def today(self):
		from frappe.utils import nowdate

		return nowdate()

	def timestamp(self):
		from frappe.utils import now_datetime

		return now_datetime().isoformat()

	def _require_finance_permissions(self):
		self.assistant._require_finance_permissions()

	def _can_read_doc(self, doctype, name):
		return self.assistant._can_read_doc(doctype, name)

	def _get_mietvertrag_row(self, identifier):
		row = self.assistant._get_mietvertrag_row(identifier)
		if not row or not self._can_read_doc("Mietvertrag", row.get("mietvertrag")):
			return None
		# Project fields through the generic field-permission checks, rather than
		# returning labels from the exact resolver's unfiltered SQL joins.
		doc = self.read_doc(
			"Mietvertrag",
			row["mietvertrag"],
			["name", "kunde", "wohnung", "immobilie", "von", "bis", "status"],
		)
		customer = self.read_doc("Customer", doc["kunde"], ["name", "customer_name"])
		return {
			"mietvertrag": doc["name"],
			"customer": doc["kunde"],
			"customer_name": customer.get("customer_name"),
			**{key: doc.get(key) for key in ("wohnung", "immobilie", "von", "bis", "status")},
		}

	def get_mieterkonto_summary(self, *args, **kwargs):
		from hausverwaltung.hausverwaltung.report.mieterkonto import mieterkonto

		identity = self._get_mietvertrag_row(args[0])
		terms = self.rental_terms(identity["mietvertrag"])
		start, end = self.assistant._resolve_date_range(kwargs.get("from_date"), kwargs.get("to_date"))
		result = mieterkonto.execute(
			{
				"company": terms["company"],
				"customer": identity["customer"],
				"from_date": start,
				"to_date": end,
				"show_kategorien": 1,
				"gruppieren_pro_monat": 1,
				"offene_betraege_basis": "Gesamt",
			}
		)
		return {
			"match": identity,
			"summary": self.assistant._compact_report_summary(result[4] if len(result) > 4 else []),
			"recent_rows": self.assistant._compact_mieterkonto_rows(result[1]),
			"from_date": start,
			"to_date": end,
			"company": terms["company"],
		}

	def hv_query_view(self, **kwargs):
		# Only the exact-customer OP query used by the overview. Resolve company
		# from the contract rather than the user's default company.
		from decimal import Decimal

		from hausverwaltung.hausverwaltung.agent_tools.fac_overview import (
			INVOICE_FIELDS,
			INVOICE_ITEM_FIELDS,
			_invoice_identity,
		)

		customer = kwargs["filters"]["customer"]
		identity = self._get_mietvertrag_row(customer)
		terms = self.rental_terms(identity["mietvertrag"])
		invoices = self.related(
			"Sales Invoice",
			{
				"customer": customer,
				"company": terms["company"],
				"docstatus": 1,
				"is_return": 0,
				"grand_total": [">", 0],
				"outstanding_amount": [">", 0.01],
				"status": [
					"not in",
					["Paid", "Credit Note Issued", "Written Off", "Partly Paid and Written Off"],
				],
			},
			INVOICE_FIELDS,
			order_by="due_date asc, name asc",
		)
		for invoice in invoices:
			detailed = self.read_doc(
				"Sales Invoice", invoice["name"], INVOICE_FIELDS, children={"items": INVOICE_ITEM_FIELDS}
			)
			_invoice_identity(self, detailed, detailed.get("items", []))
			if invoice["currency"] != terms["currency"]:
				raise OverviewError(
					"CURRENCY_CONFLICT", "Forderungen verschiedener Währungen dürfen nicht addiert werden."
				)
		limit = kwargs["limit"]
		rows = [
			{
				"invoice": invoice["name"],
				**{key: invoice.get(key) for key in ("due_date", "outstanding_amount", "currency")},
			}
			for invoice in invoices[:limit]
		]
		return {
			"rows": rows,
			"aggregate": {
				"op": "sum",
				"field": "outstanding_amount",
				"value": float(
					sum((Decimal(str(invoice["outstanding_amount"])) for invoice in invoices), Decimal(0))
				),
				"currency": terms["currency"],
			},
			"total_count": len(invoices),
			"has_more": len(invoices) > limit,
			"next_offset": limit if len(invoices) > limit else None,
			"truncated": False,
		}

	def _fields(self, doctype, fields, parenttype=None):
		from hausverwaltung.hausverwaltung.agent_tools import read_api

		read_api._ensure_agent_api_access()
		if not parenttype:
			read_api._ensure_doctype_readable(doctype)
		meta = self.frappe.get_meta(doctype)
		present = [
			field for field in fields if field in {"name", "docstatus", "modified"} or meta.has_field(field)
		]
		if not present:
			return []
		if parenttype:
			from frappe.model import get_permitted_fields

			from hausverwaltung.hausverwaltung.agent_tools.contracts import is_sensitive_field

			permitted = set(
				get_permitted_fields(
					doctype, parenttype=parenttype, user=self.frappe.session.user, permission_type="read"
				)
			)
			safe = [
				field
				for field in present
				if field in permitted
				and not is_sensitive_field(field)
				and not (meta.get_field(field) and meta.get_field(field).hidden)
			]
		else:
			safe, _ = read_api._sanitize_fieldnames(doctype, present)
		if set(safe) != set(present):
			raise OverviewError(
				"FIELD_PERMISSION_DENIED", "Nicht alle für die Übersicht benötigten Felder sind lesbar."
			)
		return safe

	def read_doc(self, doctype, name, fields, children=None):
		safe = self._fields(doctype, fields)
		if not name or not self.frappe.db.exists(doctype, name):
			raise OverviewError("NOT_FOUND", "Exakter Datensatz wurde nicht gefunden.")
		doc = self.frappe.get_doc(doctype, name)
		if not self.frappe.has_permission(doctype, "read", doc=doc):
			raise OverviewError("PERMISSION_DENIED", "Der angeforderte Datensatz ist nicht lesbar.")
		result = {field: doc.get(field) for field in safe}
		if children:
			# get_permitted_fields intentionally excludes Table fields. Use the
			# parent's readable permission levels for table access instead.
			permitted_levels = set(doc.meta.get_permlevel_access("read", user=self.frappe.session.user))
			for field, columns in children.items():
				df = doc.meta.get_field(field)
				if not df:
					continue
				if (df.permlevel or 0) not in permitted_levels or df.hidden:
					raise OverviewError("FIELD_PERMISSION_DENIED", "Benötigte Kindtabelle ist nicht lesbar.")
				columns = self._fields(df.options, columns, parenttype=doctype)
				result[field] = [
					{column: row.get(column) for column in columns} for row in (doc.get(field) or [])
				]
		return result

	def related(self, doctype, filters, fields, cap=1000, order_by="name asc"):
		# Discover names only, then check each document and field. Hidden related
		# contracts must never make a unit appear vacant or a sum appear complete.
		self._fields(doctype, [*fields, *filters])
		names = self.frappe.get_all(
			doctype, filters=filters, pluck="name", limit_page_length=cap + 1, order_by=order_by
		)
		if len(names) > cap:
			raise OverviewError(
				"LIMIT_EXCEEDED", "Zu viele verknüpfte Datensätze; allgemeine Abfrage aus Code verwenden."
			)
		if any(not self._can_read_doc(doctype, name) for name in names):
			raise OverviewError(
				"PERMISSION_INCOMPLETE",
				"Verknüpfte Daten sind nicht vollständig lesbar; keine vollständige Übersicht möglich.",
			)
		return [self.read_doc(doctype, name, fields) for name in names]

	def rental_terms(self, name):
		fields = [
			"name",
			"kunde",
			"wohnung",
			"von",
			"bis",
			"aktuelle_nettokaltmiete",
			"aktuelle_betriebskostenregelung",
			"aktuelle_betriebskosten",
			"aktuelle_heizkosten",
			"bruttomiete",
			"bevorzugter_versandweg",
		]
		data = self.read_doc(
			"Mietvertrag", name, fields, children={"mieter": ["mieter", "rolle", "eingezogen", "ausgezogen"]}
		)
		doc = self.frappe.get_doc("Mietvertrag", name)
		# Read actual controller properties, which incorporate BK rule changes and
		# bound the effective date to the contract's start/end.
		for field in fields:
			if field.startswith("aktuelle_") or field == "bruttomiete":
				data[field] = getattr(doc, field)
		from frappe.utils import getdate

		effective = doc._bruttomiete_stichtag()
		kinds = {}
		for field in ("miete", "betriebskosten", "heizkosten", "untermietzuschlag"):
			rows = [row for row in (doc.get(field) or []) if row.von and getdate(row.von) <= effective]
			current = max(rows, key=lambda row: getdate(row.von)) if rows else None
			kinds[field] = (current.art or "Monatlich") if current else "Monatlich"
		from hausverwaltung.hausverwaltung.scripts.generate_mietrechnungen import _company_via_wohnung

		company = _company_via_wohnung(data["wohnung"])
		currency = self.read_doc("Company", company, ["default_currency"])["default_currency"]
		return {
			"effective_date": str(doc._bruttomiete_stichtag()),
			"company": company,
			"currency": currency,
			"net_rent": data["aktuelle_nettokaltmiete"],
			"operating_cost_rule": data["aktuelle_betriebskostenregelung"],
			"operating_costs": data["aktuelle_betriebskosten"],
			"heating_costs": data["aktuelle_heizkosten"],
			"gross_rent": data["bruttomiete"],
			"preferred_delivery": data.get("bevorzugter_versandweg"),
			"contract_partners": data.get("mieter", []),
			"billing_kinds": kinds,
			"monthly_amounts_available": all(kind == "Monatlich" for kind in kinds.values()),
			"amount_basis": "controller_values_at_effective_date_not_invoice_amounts",
		}

	def invoice_reference(self, invoice):
		from hausverwaltung.hausverwaltung.overrides.sales_invoice import _contract_reference

		try:
			return _contract_reference(
				mietabrechnung_id=invoice.get("mietabrechnung_id"),
				remarks=invoice.get("remarks"),
				document_label="Rechnung",
			).mietvertrag
		except self.frappe.ValidationError:
			raise OverviewError(
				"IDENTITY_CONFLICT",
				"Rechnung enthält ungültige oder widersprüchliche Mietvertragsreferenzen.",
			)

	def invoice_allocations(self, invoice):
		# Payment ledger reflects later reconciliation; PE child references alone
		# can be stale after allocations have been moved.
		rows = self.related(
			"Payment Ledger Entry",
			{
				"against_voucher_type": "Sales Invoice",
				"against_voucher_no": invoice["name"],
				"delinked": 0,
				"company": invoice["company"],
			},
			[
				"name",
				"posting_date",
				"voucher_type",
				"voucher_no",
				"party_type",
				"party",
				"amount",
				"account_currency",
				"amount_in_account_currency",
				"account",
			],
			order_by="posting_date asc, name asc",
		)
		result = []
		for row in rows:
			if row["voucher_type"] == "Sales Invoice" and row["voucher_no"] == invoice["name"]:
				continue
			if row.get("party_type") != "Customer" or row.get("party") != invoice["customer"]:
				raise OverviewError(
					"IDENTITY_CONFLICT", "Zahlungszuordnung widerspricht dem Rechnungs-Customer."
				)
			identity = self._get_mietvertrag_row(invoice["customer"])
			self._validate_ledger_voucher(
				row["voucher_type"], row["voucher_no"], identity, invoice["company"], row["account"]
			)
			result.append(row)
		return result

	def _validate_ledger_voucher(self, doctype, name, identity, company, account):
		from hausverwaltung.hausverwaltung.agent_tools.fac_overview import (
			INVOICE_FIELDS,
			INVOICE_ITEM_FIELDS,
			_invoice_identity,
		)

		if not self._can_read_doc(doctype, name):
			raise OverviewError("PERMISSION_INCOMPLETE", "Zugeordneter Buchungsbeleg ist nicht lesbar.")
		if doctype == "Payment Entry":
			doc = self.read_doc(doctype, name, ["company", "party_type", "party"])
			valid = (
				doc.get("company") == company
				and doc.get("party_type") == "Customer"
				and doc.get("party") == identity["customer"]
			)
		elif doctype == "Sales Invoice":
			doc = self.read_doc(doctype, name, INVOICE_FIELDS, children={"items": INVOICE_ITEM_FIELDS})
			matched = _invoice_identity(self, doc, doc.get("items", []))
			valid = matched["mietvertrag"] == identity["mietvertrag"] and doc["company"] == company
		elif doctype == "Journal Entry":
			doc = self.read_doc(
				doctype,
				name,
				["company"],
				children={
					"accounts": ["account", "party_type", "party", "wohnung", "immobilie", "mietvertrag"]
				},
			)
			matched = [
				row
				for row in doc.get("accounts", [])
				if row.get("account") == account
				and row.get("party_type") == "Customer"
				and row.get("party") == identity["customer"]
			]
			valid = doc["company"] == company and bool(matched)
			for row in matched:
				for field, expected in (
					("wohnung", identity["wohnung"]),
					("immobilie", identity.get("immobilie")),
					("mietvertrag", identity["mietvertrag"]),
				):
					valid = valid and (not row.get(field) or row[field] == expected)
		else:
			raise OverviewError(
				"UNSUPPORTED_REFERENCE",
				"Zahlungsreferenz kann nicht fachlich geprüft werden; Code-Abfrage verwenden.",
			)
		if not valid:
			raise OverviewError(
				"IDENTITY_CONFLICT", "Ledger-Zuordnung widerspricht dem zugeordneten Buchungsbeleg."
			)

	def search(self, query, doctype, limit, offset):
		from hausverwaltung.hausverwaltung.agent_tools import read_api

		return read_api.search_docs(doctype=doctype, query=query, limit=limit, offset=offset)

	def can_read_type(self, doctype):
		return bool(self.frappe.has_permission(doctype, "read"))

	def available_tools(self):
		from frappe_assistant_core.core.tool_registry import get_tool_registry

		return get_tool_registry().get_available_tools(user=self.frappe.session.user)

	def _linked_parents(self, child_type, filters, parent_type, fields, children=None):
		# Link discovery does not return child data. Every parent (and its needed
		# fields) must be readable before exposing a relation or claiming completeness.
		names = self.frappe.get_all(
			child_type, filters=filters, pluck="parent", limit_page_length=1001, order_by="parent asc"
		)
		if len(names) > 1000:
			raise OverviewError("LIMIT_EXCEEDED", "Zu viele verknüpfte Datensätze; Code-Abfrage verwenden.")
		return [self.read_doc(parent_type, name, fields, children=children) for name in sorted(set(names))]

	def contact_contracts(self, contact):
		from hausverwaltung.hausverwaltung.agent_tools.fac_overview import CONTRACT_FIELDS

		return self._linked_parents(
			"Vertragspartner",
			{"parenttype": "Mietvertrag", "parentfield": "mieter", "mieter": contact},
			"Mietvertrag",
			CONTRACT_FIELDS,
			children={"mieter": ["mieter", "rolle"]},
		)

	def contact_addresses(self, contact):
		return self._linked_parents(
			"Dynamic Link",
			{"parenttype": "Address", "link_doctype": "Contact", "link_name": contact},
			"Address",
			[
				"name",
				"address_title",
				"address_type",
				"address_line1",
				"address_line2",
				"pincode",
				"city",
				"country",
			],
			children={"links": ["link_doctype", "link_name"]},
		)

	def payment_allocations(self, payment, identity):
		from hausverwaltung.hausverwaltung.agent_tools.fac_overview import (
			INVOICE_FIELDS,
			INVOICE_ITEM_FIELDS,
			_invoice_identity,
		)

		rows = self.related(
			"Payment Ledger Entry",
			{
				"voucher_type": "Payment Entry",
				"voucher_no": payment["name"],
				"delinked": 0,
				"company": payment["company"],
			},
			[
				"name",
				"posting_date",
				"party_type",
				"party",
				"against_voucher_type",
				"against_voucher_no",
				"amount",
				"account_currency",
				"amount_in_account_currency",
				"account",
			],
			order_by="posting_date asc, name asc",
		)
		allocations = []
		for row in rows:
			if row["party_type"] != "Customer" or row["party"] != identity["customer"]:
				raise OverviewError("IDENTITY_CONFLICT", "Zahlungszuordnung widerspricht dem Customer.")
			doctype, name = row["against_voucher_type"], row["against_voucher_no"]
			if doctype == "Payment Entry" and name == payment["name"]:
				continue
			self._validate_ledger_voucher(doctype, name, identity, payment["company"], row["account"])
			allocations.append(row)
		return allocations
