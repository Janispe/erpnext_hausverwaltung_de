"""Read-only ERPNext accounting evidence for a caller-authorised scope."""

from dataclasses import dataclass

import frappe

from hausverwaltung.hausverwaltung.agent_tools import fac_routing

MAX_SOURCE_LINES = 80
MAX_ACCOUNTS = 240
MAX_CANDIDATES = 3
MAX_REFERENCES = 3


@dataclass(frozen=True)
class AccountingAccess:
	"""ERPNext principal and explicitly authorised scope of one comparison."""

	user: str
	company: str | None
	cost_center: str | None
	has_object: bool = False


def _readable(access, doctype, name):
	return bool(name and frappe.has_permission(doctype, "read", doc=name, user=access.user))


SUPPLIER_QUESTION = "Welcher aktive Lieferant ist diesem Händler eindeutig zugeordnet?"


def supplier(access, merchant, *, lock=False):
	if not merchant:
		return {"match": None, "question": "Welcher Händler steht auf dem Bon?"}
	rows = frappe.db.sql(
		"""SELECT name, supplier_name FROM `tabSupplier`
		WHERE disabled = 0 AND (name = %s OR supplier_name = %s)
		ORDER BY name LIMIT 2""" + (" FOR UPDATE" if lock else ""),
		(merchant, merchant), as_dict=True,
	)
	if len(rows) == 1 and _readable(access, "Supplier", rows[0].name):
		return {"match": rows[0], "question": ""}
	return {"match": None, "question": SUPPLIER_QUESTION, "missing": not rows}


def prior_receipts(access, merchant):
	match = supplier(access, merchant)["match"]
	company, center = access.company, access.cost_center
	if not match or not company or not center:
		return {"positions": [], "has_object": access.has_object, "truncated": False}
	rows = frappe.db.sql(
		"""SELECT item.name AS position, bill.name AS receipt, bill.posting_date AS date,
			item.expense_account AS account, LEFT(item.item_name, 120) AS description,
			CASE WHEN item.cost_center = %s THEN 1 ELSE 0 END AS same_object
		FROM `tabPurchase Invoice` bill
		JOIN `tabPurchase Invoice Item` item ON item.parent = bill.name
		WHERE bill.docstatus = 1 AND bill.is_return = 0 AND bill.company = %s AND bill.supplier = %s
			AND item.cost_center = %s AND item.expense_account IS NOT NULL AND item.expense_account <> ''
		ORDER BY same_object DESC, bill.posting_date DESC, bill.name DESC, item.idx ASC
		LIMIT %s""",
		(center if access.has_object else None, company, match["name"], center, MAX_SOURCE_LINES + 1), as_dict=True,
	)
	permission = {name: _readable(access, "Purchase Invoice", name) for name in {row.receipt for row in rows}}
	positions = []
	for row in rows[:MAX_SOURCE_LINES]:
		if permission[row.receipt]:
			row.date = str(row.date)
			row.same_object = bool(row.same_object)
			positions.append(row)
	return {"positions": positions, "has_object": access.has_object, "truncated": len(rows) > MAX_SOURCE_LINES}


def allowed_accounts(access):
	company = access.company
	if not company:
		return {"accounts": [], "truncated": False}
	currency = frappe.db.get_value("Company", company, "default_currency")
	rows = frappe.db.sql(
		"""SELECT account.name AS account, account.account_name AS label,
			category.name AS category, category.category_type
		FROM `tabAccount` account
		JOIN (
			SELECT name, konto, 'Betriebskostenart' AS category_type FROM `tabBetriebskostenart`
			WHERE artikel IS NOT NULL AND artikel <> ''
			UNION ALL
			SELECT name, konto, 'Kostenart nicht umlagefaehig' FROM `tabKostenart nicht umlagefaehig`
			WHERE artikel IS NOT NULL AND artikel <> ''
		) category ON category.konto = account.name
		WHERE account.company = %s AND account.account_currency = %s AND account.disabled = 0
			AND account.is_group = 0 AND COALESCE(account.account_type, '') NOT IN ('Receivable', 'Payable')
		ORDER BY account.name, category.category_type, category.name LIMIT %s""",
		(company, currency, MAX_ACCOUNTS + 1), as_dict=True,
	)
	permission = {name: _readable(access, "Account", name) for name in {row.account for row in rows}}
	return {"accounts": [row for row in rows[:MAX_ACCOUNTS] if permission[row.account]], "truncated": len(rows) > MAX_ACCOUNTS}


def verify(access, merchant, shortlist):
	if not isinstance(shortlist, list) or len(shortlist) > MAX_CANDIDATES:
		frappe.throw("Bitte höchstens drei belegte Konten vorschlagen.")
	identity = supplier(access, merchant)
	history = prior_receipts(access, merchant)
	catalogue = allowed_accounts(access)
	allowed = {row["account"]: row for row in catalogue["accounts"]}
	positions = {row["position"]: row for row in history["positions"]}
	selected = {}
	for item in shortlist:
		if not isinstance(item, dict) or set(item) != {"account", "positions"}:
			frappe.throw("Kontenvorschlag muss ein Konto und seine Quellen enthalten.")
		account, keys = item["account"], item["positions"]
		if not isinstance(account, str) or account not in allowed or account in selected:
			frappe.throw("Das Sachkonto ist für diesen Bon nicht zulässig.")
		if (not isinstance(keys, list) or not 1 <= len(keys) <= MAX_REFERENCES
			or any(not isinstance(key, str) or positions.get(key, {}).get("account") != account for key in keys)
			or len(set(keys)) != len(keys)):
			frappe.throw("Eine Quelle gehört nicht zu historischen Positionen dieses Kontos und Lieferanten.")
		selected[account] = dict(allowed[account], sources=[
			{key: positions[position][key] for key in ("position", "receipt", "date", "same_object")}
			for position in keys
		])
	questions = [identity["question"]] if identity["question"] else []
	if not history["has_object"]:
		questions.append("Welchem Objekt ist der Bon für einen objektbezogenen Vergleich zuzuordnen?")
	elif not any(source["same_object"] for item in selected.values() for source in item["sources"]):
		questions.append("Welche Kontierung gilt für dieses Objekt? Die Kurzliste enthält keinen Beleg desselben Objekts.")
	if not selected:
		questions.append("Welches Sachkonto ist zu wählen? Es liegt kein belegter Kontenvorschlag vor.")
	elif len(selected) > 1:
		questions.append("Welches der durch frühere Belege gestützten Sachkonten passt zu diesem Bon?")
	if history["truncated"] or catalogue["truncated"]:
		questions.append("Der Vergleich umfasst eine begrenzte Auswahl. Bei Bedarf weitere Belege oder Konten prüfen.")
	return {"supplier": identity["match"], "candidates": list(selected.values()), "questions": questions}



def _tool(name, description, properties=None):
	properties = properties or {}
	return {
		"name": name, "description": description,
		"inputSchema": {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False},
		"_meta": {fac_routing.ROUTING_META_KEY: {"version": fac_routing.ROUTING_VERSION, "audiences": ["code"]}},
	}


def catalogue():
	return [
		_tool("lookup_supplier", "Look up the merchant of this case. Returns {match: {name, supplier_name} or null, question}."),
		_tool("list_booked_receipts", "Historical submitted positions of the matched supplier and this Company. Returns "
			"{positions: [{position, receipt, date, description, account, same_object}], has_object, truncated}."),
		_tool("list_allowed_accounts", "Bona fide eligible accounts of this case Company. Returns "
			"{accounts: [{account, label, category, category_type}], truncated}."),
		_tool("verify_shortlist", "Validate a maximum of three selected accounts against eligible accounts and historical "
			"positions. Each item is {account, positions: [position IDs from list_booked_receipts]}, maximum three IDs per account. "
			"Pass an empty shortlist if no support exists. Returns the serialized verified result.",
			{"shortlist": {"type": "array", "items": {"type": "object", "properties": {
				"account": {"type": "string"},
				"positions": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": MAX_REFERENCES},
			}, "required": ["account", "positions"], "additionalProperties": False}, "maxItems": MAX_CANDIDATES}}),
	]



def dispatch(access, merchant, method, params):
	"""MCP operations over already authorised accounting context."""
	tools = catalogue()
	if method == "tools/list" and params == {}:
		return {"tools": fac_routing.tool_catalog(tools, audience="code")}
	if method != "tools/call" or not isinstance(params, dict) or set(params) != {"name", "arguments"}:
		raise frappe.PermissionError("Unzulässiger Werkzeugaufruf.")

	def run(_method, call):
		name, arguments = call["name"], call["arguments"]
		if name == "verify_shortlist" and isinstance(arguments, dict) and set(arguments) == {"shortlist"}:
			return {"structuredContent": verify(access, merchant, arguments["shortlist"])}
		if arguments == {}:
			if name == "lookup_supplier":
				return {"structuredContent": supplier(access, merchant)}
			if name == "list_booked_receipts":
				return {"structuredContent": prior_receipts(access, merchant)}
			if name == "list_allowed_accounts":
				return {"structuredContent": allowed_accounts(access)}
		raise frappe.PermissionError("Unzulässige Werkzeugargumente.")

	try:
		return fac_routing.call_tool(run, tools, params["name"], params["arguments"], audience="code")
	except (ValueError, TypeError):
		raise frappe.PermissionError("Unzulässiges Werkzeug für den Kontierungsvergleich.") from None
