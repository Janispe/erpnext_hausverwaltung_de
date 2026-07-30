from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, cstr, flt, nowdate

SERIENBRIEF_FIELDNAME = "hv_serienbrief_vorlage"
SERIENBRIEF_WERTE_FIELDNAME = "hv_serienbrief_werte"
DUNNING_FEE_SALES_INVOICE_FIELDNAME = "hv_dunning_fee_sales_invoice"
SALES_INVOICE_DUNNING_FIELDNAME = "hv_dunning"
SALES_INVOICE_IS_DUNNING_FEE_FIELDNAME = "hv_is_dunning_fee_invoice"
PATH_OVERRIDE_PREFIX = "__path__:"


def _money_cents(value: Any) -> Decimal:
	try:
		return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
	except (InvalidOperation, TypeError, ValueError):
		frappe.throw(_("Ungültiger Geldbetrag: {0}").format(value))


def sync_serienbrief_vorlage_from_dunning_type(doc, method=None) -> None:
	"""Backfill a Serienbrief Vorlage from the selected Dunning Type.

	We only fill the field when the Mahnung itself has no explicit template yet, so
	users can still override the default on a single Dunning document.
	"""
	if not frappe.db.has_column("Dunning", SERIENBRIEF_FIELDNAME):
		return

	if not doc.get("dunning_type"):
		return

	if doc.get(SERIENBRIEF_FIELDNAME):
		return

	if not frappe.db.has_column("Dunning Type", SERIENBRIEF_FIELDNAME):
		return

	template = frappe.db.get_value("Dunning Type", doc.dunning_type, SERIENBRIEF_FIELDNAME)
	if template:
		doc.set(SERIENBRIEF_FIELDNAME, template)


def _collect_werte_rows(rows) -> dict[str, dict[str, Any]]:
	werte: dict[str, dict[str, Any]] = {}
	for row in rows or []:
		name = (row.get("variable") or "").strip()
		if not name:
			continue
		key = name if name.startswith(PATH_OVERRIDE_PREFIX) else frappe.scrub(name)
		werte[key] = {"value": row.get("wert")}
	return werte


def collect_serienbrief_werte(dunning) -> dict[str, dict[str, Any]]:
	"""Sammle Serienbrief-Variablenwerte aus Dunning Type und Dunning.

	Liefert ein Mapping im selben Format wie ``variablen_werte``
	(``{scrub(variable): {"value": wert}}``), das der Serienbrief-Durchlauf in den
	Pro-Empfänger-Override (`row._iteration_variablen_werte`) mergen kann. Werte
	aus dem Dunning Type bilden den Default; Werte auf der konkreten Mahnung
	überschreiben gleichnamige Defaults.

	Defensiv: fehlende Tabelle / fehlende Spalte → ``{}``.
	``dunning`` darf ein Doc oder ein Dunning-Name (str) sein.
	"""
	dunning_type = None
	dunning_doc = None
	if isinstance(dunning, str):
		try:
			dunning_doc = frappe.get_cached_doc("Dunning", dunning)
		except frappe.DoesNotExistError:
			dunning_doc = None
	else:
		dunning_doc = dunning

	if dunning_doc:
		dunning_type = getattr(dunning_doc, "dunning_type", None)

	werte: dict[str, dict[str, Any]] = {}

	# Table-Felder haben keine Spalte am Parent — daher Meta-Check statt has_column.
	if dunning_type and frappe.get_meta("Dunning Type").get_field(SERIENBRIEF_WERTE_FIELDNAME):
		try:
			type_doc = frappe.get_cached_doc("Dunning Type", dunning_type)
		except frappe.DoesNotExistError:
			type_doc = None
		if type_doc:
			werte.update(_collect_werte_rows(type_doc.get(SERIENBRIEF_WERTE_FIELDNAME) or []))

	if dunning_doc and frappe.get_meta("Dunning").get_field(SERIENBRIEF_WERTE_FIELDNAME):
		werte.update(_collect_werte_rows(dunning_doc.get(SERIENBRIEF_WERTE_FIELDNAME) or []))

	return werte


def validate_serienbrief_werte(doc, method=None) -> None:
	"""Verhindert, dass zwei hv_serienbrief_werte-Zeilen nach frappe.scrub()
	denselben Variablennamen liefern. Sonst würden Werte stumm überschrieben
	(siehe collect_serienbrief_werte → dict-Assignment).

	Beispiele für Kollisionen: "Frist Tage" + "frist_tage", "Ueberschrift" +
	"Überschrift". Beide werden zu "frist_tage" bzw. "ueberschrift" — der zweite
	Eintrag gewänne stumm.
	"""
	rows = doc.get(SERIENBRIEF_WERTE_FIELDNAME) or []
	seen: dict[str, list[tuple[int, str]]] = {}
	for row in rows:
		name = (getattr(row, "variable", None) or "").strip()
		if not name:
			continue
		key = name if name.startswith(PATH_OVERRIDE_PREFIX) else frappe.scrub(name)
		seen.setdefault(key, []).append((getattr(row, "idx", 0), name))

	duplicates = [(key, occ) for key, occ in seen.items() if len(occ) > 1]
	if not duplicates:
		return

	parts = []
	for key, occ in duplicates:
		labels = ", ".join(f"#{idx} „{name}\"" for idx, name in occ)
		parts.append(f"<li><code>{key}</code> ({labels})</li>")
	frappe.throw(
		_(
			"Im Feld <strong>Serienbrief-Werte</strong> gibt es Variablen, "
			"die nach Normalisierung identisch sind und sich gegenseitig "
			"stumm überschreiben würden:<ul>{0}</ul>"
			"Bitte jede Variable nur einmal vergeben."
		).format("".join(parts)),
		title=_("Doppelte Variablen"),
	)


def validate_dunning_type_serienbrief_werte(doc, method=None) -> None:
	validate_serienbrief_werte(doc, method=method)


def validate_dunning(doc, method=None) -> None:
	sync_serienbrief_vorlage_from_dunning_type(doc, method=method)
	validate_serienbrief_werte(doc, method=method)


def _meta_has_field(doctype: str, fieldname: str) -> bool:
	try:
		return bool(frappe.get_meta(doctype).get_field(fieldname))
	except Exception:
		return False


def _dunning_fee_field_setup_complete() -> bool:
	return all(
		(
			_meta_has_field("Dunning", DUNNING_FEE_SALES_INVOICE_FIELDNAME),
			_meta_has_field("Sales Invoice", SALES_INVOICE_DUNNING_FIELDNAME),
			_meta_has_field("Sales Invoice", SALES_INVOICE_IS_DUNNING_FEE_FIELDNAME),
		)
	)


def _ensure_dunning_fee_invoice_fields() -> bool:
	"""Read-only runtime check; schema changes belong exclusively in after_migrate."""
	return _dunning_fee_field_setup_complete()


def _require_dunning_fee_invoice_fields() -> None:
	if _ensure_dunning_fee_invoice_fields():
		return
	frappe.throw(
		_(
			"Die Mahngebühr kann nicht sicher gebucht werden, weil die technischen "
			"Verknüpfungsfelder auf Dunning/Sales Invoice fehlen oder nicht eingerichtet "
			"werden konnten. Die Mahnung wurde nicht eingereicht."
		),
		title=_("Mahngebühr-Einrichtung unvollständig"),
	)


def _dunning_fee_sales_invoice(dunning_name: str) -> str | None:
	_ensure_dunning_fee_invoice_fields()
	if not _meta_has_field("Dunning", DUNNING_FEE_SALES_INVOICE_FIELDNAME):
		return None
	return frappe.db.get_value("Dunning", dunning_name, DUNNING_FEE_SALES_INVOICE_FIELDNAME)


def _dunning_overdue_sales_invoices(doc) -> list[str]:
	invoices: list[str] = []
	for row in doc.get("overdue_payments") or []:
		sales_invoice = row.get("sales_invoice")
		if sales_invoice and sales_invoice not in invoices:
			invoices.append(sales_invoice)
	return invoices


def _validate_dunning_income_account(account: str, company: str) -> str:
	account = cstr(account).strip()
	if not account:
		frappe.throw(
			_(
				"Für die positive Mahngebühr ist weder am Dunning Type/Dunning noch "
				"an der Firma ein Erlöskonto hinterlegt."
			)
		)
	values = frappe.db.get_value(
		"Account",
		account,
		["name", "company", "root_type", "is_group", "disabled"],
		as_dict=True,
		for_update=True,
	) or {}
	if (
		not values.get("name")
		or values.get("company") != company
		or values.get("root_type") != "Income"
		or cint(values.get("is_group"))
		or cint(values.get("disabled"))
	):
		frappe.throw(
			_(
				"Erlöskonto {0} ist kein aktives Blatt-Erlöskonto der Firma {1}."
			).format(account, company)
		)
	return account


def _dunning_row_outstanding_by_invoice(doc) -> dict[str, Decimal]:
	amounts: dict[str, Decimal] = {}
	for row in doc.get("overdue_payments") or []:
		invoice_name = cstr(row.get("sales_invoice")).strip()
		if not invoice_name:
			frappe.throw(_("Eine Mahnungszeile hat keine Sales Invoice."))
		amount = _money_cents(row.get("outstanding"))
		if amount <= Decimal("0.00"):
			frappe.throw(
				_(
					"Die Mahnungszeile für Sales Invoice {0} hat keinen positiven "
					"offenen Betrag."
				).format(invoice_name)
			)
		amounts[invoice_name] = amounts.get(invoice_name, Decimal("0.00")) + amount
	return amounts


def _common_invoice_value(contexts: list[dict[str, Any]], fieldname: str) -> str | None:
	values = {
		cstr(context["invoice"].get(fieldname)).strip()
		for context in contexts
		if cstr(context["invoice"].get(fieldname)).strip()
	}
	return next(iter(values)) if len(values) == 1 else None


def _validate_and_lock_dunning_fee_context(doc) -> dict[str, Any] | None:
	amount_cents = _money_cents(doc.get("dunning_amount"))
	if amount_cents <= Decimal("0.00"):
		return None
	amount = float(amount_cents)
	_require_dunning_fee_invoice_fields()

	row_amounts = _dunning_row_outstanding_by_invoice(doc)
	if not row_amounts:
		frappe.throw(_("Die Mahnung enthält keine verknüpfte Sales Invoice."))

	from hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff import (
		lock_current_sales_invoice_contexts,
	)

	contexts_by_name = lock_current_sales_invoice_contexts(sorted(row_amounts))
	contexts: list[dict[str, Any]] = []
	booking_signatures: set[tuple[str, str]] = set()
	for invoice_name in sorted(row_amounts):
		context = contexts_by_name[invoice_name]
		invoice = context["invoice"]
		if cint(invoice.get("docstatus")) != 1:
			frappe.throw(
				_("Sales Invoice {0} ist nicht mehr eingereicht.").format(invoice_name)
			)
		if cint(invoice.get("is_return")):
			frappe.throw(
				_("Sales Invoice {0} ist ein Guthaben und nicht mahnfähig.").format(
					invoice_name
				)
			)
		if cstr(invoice.get("customer")).strip() != cstr(doc.get("customer")).strip():
			frappe.throw(
				_("Sales Invoice {0} gehört nicht zum Kunden der Mahnung.").format(
					invoice_name
				)
			)
		if cstr(invoice.get("company")).strip() != cstr(doc.get("company")).strip():
			frappe.throw(
				_("Sales Invoice {0} gehört nicht zur Firma der Mahnung.").format(
					invoice_name
				)
			)
		if cstr(invoice.get("currency")).strip() != cstr(doc.get("currency")).strip():
			frappe.throw(
				_("Sales Invoice {0} hat nicht die Währung der Mahnung.").format(
					invoice_name
				)
			)

		current_outstanding = _money_cents(invoice.get("outstanding_amount"))
		snapshot_outstanding = row_amounts[invoice_name]
		if (
			current_outstanding <= Decimal("0.00")
			or current_outstanding != snapshot_outstanding
		):
			frappe.throw(
				_(
					"Der OP von Sales Invoice {0} hat sich seit Erstellung der Mahnung "
					"geändert (Mahnung: {1}, aktuell: {2}). Bitte die Mahnung neu erstellen."
				).format(invoice_name, snapshot_outstanding, current_outstanding)
			)

		signature = (
			cstr(context.get("wohnung")).strip(),
			cstr(context.get("cost_center")).strip(),
		)
		booking_signatures.add(signature)
		contexts.append(context)

	if len(booking_signatures) != 1:
		frappe.throw(
			_(
				"Eine Mahngebühr darf nur Rechnungen derselben eindeutigen Wohnung "
				"und Property-Kostenstelle zusammenfassen."
			)
		)
	wohnung, cost_center = next(iter(booking_signatures))
	income_account = _validate_dunning_income_account(
		doc.get("income_account") or _fallback_income_account(doc.company),
		doc.company,
	)
	if wohnung:
		for doctype in ("Sales Invoice", "Sales Invoice Item"):
			if not _meta_has_field(doctype, "wohnung"):
				frappe.throw(
					_(
						"Das Pflichtfeld Wohnung fehlt auf {0}. "
						"Die Mahngebühr wurde nicht gebucht."
					).format(doctype)
				)

	return {
		"amount": amount,
		"invoice_names": sorted(row_amounts),
		"contexts": contexts,
		"wohnung": wohnung or None,
		"immobilie": contexts[0].get("immobilie"),
		"cost_center": cost_center,
		"income_account": income_account,
		"mietvertrag": _common_invoice_value(contexts, "mietvertrag"),
		"debit_to": _common_invoice_value(contexts, "debit_to"),
	}


def validate_dunning_fee_booking_before_submit(doc, method=None) -> None:
	if (
		_money_cents(doc.get("dunning_amount")) > Decimal("0.00")
		and doc.get(DUNNING_FEE_SALES_INVOICE_FIELDNAME)
	):
		frappe.throw(
			_(
				"Eine Draft-Mahnung mit positiver Mahngebühr darf noch keine "
				"Mahngebühr-Rechnung verknüpfen."
			)
		)
	context = _validate_and_lock_dunning_fee_context(doc)
	if context:
		doc.flags.hv_dunning_fee_booking_context = context


def _fallback_income_account(company: str) -> str | None:
	if not company:
		return None

	return frappe.db.get_value("Company", company, "default_income_account")


def _set_fee_invoice_field(
	si,
	fieldname: str,
	value: Any,
	*,
	required: bool = False,
) -> None:
	if value in (None, ""):
		if required:
			frappe.throw(_("Pflichtwert {0} für die Mahngebühr fehlt.").format(fieldname))
		return
	if not si.meta.get_field(fieldname):
		if required:
			frappe.throw(
				_("Pflichtfeld {0} fehlt auf Sales Invoice.").format(fieldname)
			)
		return
	si.set(fieldname, value)


def _create_fee_sales_invoice_doc(doc, context: dict[str, Any]):
	from hausverwaltung.hausverwaltung.utils.rent_items import ensure_dunning_fee_item

	amount = flt(context["amount"])
	invoice_names = context["invoice_names"]
	income_account = context["income_account"]
	cost_center = context["cost_center"]
	item_code = ensure_dunning_fee_item(company=doc.company, income_account=income_account)
	reference_text = ", ".join(invoice_names)

	si = frappe.new_doc("Sales Invoice")
	si.customer = doc.customer
	si.customer_name = doc.get("customer_name")
	si.company = doc.company
	si.posting_date = doc.get("posting_date") or nowdate()
	si.due_date = si.posting_date
	si.ignore_pricing_rule = 1
	si.remarks = _("Mahngebühr/Verzugszinsen aus Mahnung {0} zu {1}").format(doc.name, reference_text)
	_set_fee_invoice_field(si, "currency", doc.get("currency"), required=True)
	_set_fee_invoice_field(si, "conversion_rate", doc.get("conversion_rate"))
	_set_fee_invoice_field(si, "mietvertrag", context.get("mietvertrag"))
	_set_fee_invoice_field(
		si,
		"wohnung",
		context.get("wohnung"),
		required=bool(context.get("wohnung")),
	)
	_set_fee_invoice_field(si, "immobilie", context.get("immobilie"))
	_set_fee_invoice_field(si, "cost_center", cost_center, required=True)
	_set_fee_invoice_field(si, "debit_to", context.get("debit_to"))

	for fieldname, value in (
		(SALES_INVOICE_DUNNING_FIELDNAME, doc.name),
		(SALES_INVOICE_IS_DUNNING_FEE_FIELDNAME, 1),
	):
		if not si.meta.get_field(fieldname):
			frappe.throw(
				_(
					"Technisches Verknüpfungsfeld {0} fehlt auf Sales Invoice. "
					"Die Mahngebühr wurde nicht gebucht."
				).format(fieldname)
			)
		si.set(fieldname, value)

	item_meta = frappe.get_meta("Sales Invoice Item")
	if not item_meta.get_field("cost_center"):
		frappe.throw(_("Pflichtfeld cost_center fehlt auf Sales Invoice Item."))
	if context.get("wohnung") and not item_meta.get_field("wohnung"):
		frappe.throw(_("Pflichtfeld wohnung fehlt auf Sales Invoice Item."))
	row = {
		"item_code": item_code,
		"item_name": "Mahngebühr",
		"description": _("Mahngebühr/Verzugszinsen aus Mahnung {0}").format(doc.name),
		"qty": 1,
		"rate": amount,
	}
	if income_account:
		row["income_account"] = income_account
	if cost_center:
		row["cost_center"] = cost_center
	if context.get("wohnung"):
		row["wohnung"] = context["wohnung"]
	si.append("items", row)
	return si


def create_dunning_fee_invoice(doc, method=None) -> None:
	"""Create and submit the fee/interest Sales Invoice for a submitted Dunning."""
	if _money_cents(doc.get("dunning_amount")) <= Decimal("0.00"):
		return
	_require_dunning_fee_invoice_fields()
	if doc.get(DUNNING_FEE_SALES_INVOICE_FIELDNAME):
		frappe.throw(
			_(
				"Die positive Mahngebühr ist vor der Buchung bereits mit einer "
				"Sales Invoice verknüpft. Die Mahnung wurde nicht eingereicht."
			)
		)

	context = getattr(doc.flags, "hv_dunning_fee_booking_context", None)
	if not context:
		context = _validate_and_lock_dunning_fee_context(doc)
	if not context:
		frappe.throw(_("Die positive Mahngebühr konnte nicht validiert werden."))

	si = _create_fee_sales_invoice_doc(doc, context)
	si.insert(ignore_permissions=True)
	si.submit()

	doc.db_set(DUNNING_FEE_SALES_INVOICE_FIELDNAME, si.name, update_modified=False)
	doc.add_comment(
		"Info",
		_("Mahngebühr/Verzugszinsen wurden als Sales Invoice {0} gebucht.").format(
			frappe.utils.get_link_to_form("Sales Invoice", si.name)
		),
	)


def _lock_dunning_source_booking_signature(doc) -> tuple[str, str]:
	invoice_names = sorted(_dunning_overdue_sales_invoices(doc))
	if not invoice_names:
		frappe.throw(_("Die Mahnung enthält keine verknüpfte Sales Invoice."))
	from hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff import (
		lock_current_sales_invoice_contexts,
	)

	contexts = lock_current_sales_invoice_contexts(invoice_names)
	signatures: set[tuple[str, str]] = set()
	for invoice_name in invoice_names:
		context = contexts[invoice_name]
		invoice = context["invoice"]
		if (
			cstr(invoice.get("customer")).strip() != cstr(doc.get("customer")).strip()
			or cstr(invoice.get("company")).strip() != cstr(doc.get("company")).strip()
		):
			frappe.throw(
				_(
					"Sales Invoice {0} passt nicht zu Kunde/Firma der Mahnung."
				).format(invoice_name)
			)
		signatures.add(
			(
				cstr(context.get("wohnung")).strip(),
				cstr(context.get("cost_center")).strip(),
			)
		)
	if len(signatures) != 1:
		frappe.throw(
			_(
				"Die Quellrechnungen der Mahnung haben keine eindeutige "
				"Wohnungs-/Kostenstellenidentität."
			)
		)
	return next(iter(signatures))


def _validate_and_lock_dunning_fee_invoice_ownership(
	doc,
	fee_invoice: str | None = None,
) -> str | None:
	amount = _money_cents(doc.get("dunning_amount"))
	fee_invoice = cstr(
		fee_invoice
		or doc.get(DUNNING_FEE_SALES_INVOICE_FIELDNAME)
		or _dunning_fee_sales_invoice(doc.name)
	).strip()
	if not fee_invoice:
		if amount > Decimal("0.00"):
			frappe.throw(
				_(
					"Die positive Mahnung {0} hat keine eindeutig verknüpfte "
					"Mahngebühr-Rechnung und kann nicht sicher storniert werden."
				).format(doc.name)
			)
		return None
	_require_dunning_fee_invoice_fields()
	expected_wohnung, expected_cost_center = _lock_dunning_source_booking_signature(doc)

	backlinks = frappe.db.sql(
		f"""
		SELECT name
		FROM `tabSales Invoice`
		WHERE `{SALES_INVOICE_DUNNING_FIELDNAME}` = %(dunning)s
		  AND docstatus < 2
		ORDER BY name
		FOR UPDATE
		""",
		{"dunning": doc.name},
		as_dict=True,
	)
	if [cstr(row.name) for row in backlinks] != [fee_invoice]:
		frappe.throw(
			_(
				"Die Mahnung {0} und ihre aktive Mahngebühr-Rechnung sind nicht "
				"bijektiv verknüpft."
			).format(doc.name)
		)

	rows = frappe.db.sql(
		f"""
		SELECT
			name, docstatus, is_return, customer, company, currency,
			grand_total, outstanding_amount, remarks, cost_center, wohnung,
			`{SALES_INVOICE_DUNNING_FIELDNAME}` AS hv_dunning,
			`{SALES_INVOICE_IS_DUNNING_FEE_FIELDNAME}` AS hv_is_dunning_fee
		FROM `tabSales Invoice`
		WHERE name = %(name)s
		FOR UPDATE
		""",
		{"name": fee_invoice},
		as_dict=True,
	)
	if len(rows) != 1:
		frappe.throw(
			_("Verknüpfte Mahngebühr-Rechnung {0} wurde nicht gefunden.").format(
				fee_invoice
			)
		)
	invoice = rows[0]
	expected_marker = f"Mahngebühr/Verzugszinsen aus Mahnung {doc.name}"
	if (
		cint(invoice.docstatus) != 1
		or cint(invoice.is_return)
		or cstr(invoice.customer).strip() != cstr(doc.get("customer")).strip()
		or cstr(invoice.company).strip() != cstr(doc.get("company")).strip()
		or cstr(invoice.currency).strip() != cstr(doc.get("currency")).strip()
		or cstr(invoice.hv_dunning).strip() != cstr(doc.name).strip()
		or not cint(invoice.hv_is_dunning_fee)
		or expected_marker not in cstr(invoice.remarks)
		or _money_cents(invoice.grand_total) != amount
		or _money_cents(invoice.outstanding_amount) != amount
		or cstr(invoice.cost_center).strip() != expected_cost_center
		or cstr(invoice.wohnung).strip() != expected_wohnung
	):
		frappe.throw(
			_(
				"Sales Invoice {0} ist nicht die eindeutig unveränderte "
				"Mahngebühr-Rechnung der Mahnung {1}."
			).format(fee_invoice, doc.name)
		)

	items = frappe.db.sql(
		"""
		SELECT
			name, item_code, qty, rate, amount, description, cost_center, wohnung
		FROM `tabSales Invoice Item`
		WHERE parent = %(parent)s
		  AND parenttype = 'Sales Invoice'
		ORDER BY idx, name
		FOR UPDATE
		""",
		{"parent": fee_invoice},
		as_dict=True,
	)
	if len(items) != 1:
		frappe.throw(
			_(
				"Mahngebühr-Rechnung {0} muss exakt eine unveränderte Position enthalten."
			).format(fee_invoice)
		)
	item = items[0]
	if (
		cstr(item.item_code).strip() != "Mahngebuehr"
		or _money_cents(item.qty) != Decimal("1.00")
		or _money_cents(item.rate) != amount
		or _money_cents(item.amount) != amount
		or expected_marker not in cstr(item.description)
		or cstr(item.cost_center).strip() != expected_cost_center
		or cstr(item.wohnung).strip() != expected_wohnung
	):
		frappe.throw(
			_(
				"Position der Mahngebühr-Rechnung {0} passt nicht eindeutig zur Mahnung."
			).format(fee_invoice)
		)
	return fee_invoice


def validate_dunning_fee_invoice_can_cancel(doc, method=None) -> None:
	fee_invoice = doc.get(DUNNING_FEE_SALES_INVOICE_FIELDNAME) or _dunning_fee_sales_invoice(doc.name)
	if not fee_invoice:
		_validate_and_lock_dunning_fee_invoice_ownership(doc)
		return
	fee_invoice = _validate_and_lock_dunning_fee_invoice_ownership(doc, fee_invoice)
	doc.flags.hv_owned_dunning_fee_invoice = fee_invoice

	payment_refs = frappe.get_all(
		"Payment Entry Reference",
		filters={
			"reference_doctype": "Sales Invoice",
			"reference_name": fee_invoice,
			"parenttype": "Payment Entry",
		},
		fields=["parent", "allocated_amount"],
		limit_page_length=0,
	)
	if not payment_refs:
		return

	payment_names = list({row.parent for row in payment_refs if row.parent})
	if not payment_names:
		return

	submitted_payments = frappe.get_all(
		"Payment Entry",
		filters={"name": ("in", payment_names), "docstatus": 1},
		pluck="name",
		limit_page_length=0,
	)
	if not submitted_payments:
		return

	links = ", ".join(
		frappe.utils.get_link_to_form("Payment Entry", name) for name in submitted_payments
	)
	frappe.throw(
		_(
			"Die Mahnung kann nicht storniert werden, weil die Mahngebühr-Rechnung {0} "
			"bereits mit Payment Entry {1} ausgeglichen wurde. Bitte zuerst die Zahlung "
			"stornieren oder auf eine andere offene Rechnung umbuchen."
		).format(fee_invoice, links),
		title=_("Zahlung zuerst klären"),
	)


def cancel_dunning_fee_invoice(doc, method=None) -> None:
	fee_invoice = doc.get(DUNNING_FEE_SALES_INVOICE_FIELDNAME) or _dunning_fee_sales_invoice(doc.name)
	if not fee_invoice:
		return

	try:
		si = frappe.get_doc("Sales Invoice", fee_invoice)
	except frappe.DoesNotExistError:
		return

	if si.docstatus == 1:
		frappe.flags.hv_cancelling_dunning_fee_invoice = si.name
		try:
			si.cancel()
		finally:
			frappe.flags.hv_cancelling_dunning_fee_invoice = None
	elif si.docstatus == 0:
		si.delete(ignore_permissions=True)


def prevent_direct_cancel_of_dunning_fee_invoice(doc, method=None) -> None:
	if not _meta_has_field("Sales Invoice", SALES_INVOICE_IS_DUNNING_FEE_FIELDNAME):
		return
	if not _meta_has_field("Sales Invoice", SALES_INVOICE_DUNNING_FIELDNAME):
		return
	if not doc.get(SALES_INVOICE_IS_DUNNING_FEE_FIELDNAME) or not doc.get(SALES_INVOICE_DUNNING_FIELDNAME):
		return
	if getattr(frappe.flags, "hv_cancelling_dunning_fee_invoice", None) == doc.name:
		return

	dunning = doc.get(SALES_INVOICE_DUNNING_FIELDNAME)
	frappe.throw(
		_(
			"Diese Sales Invoice gehört zur Mahnung {0}. Bitte die Mahnung stornieren; "
			"die verknüpfte Mahngebühr-Rechnung wird dann automatisch mit storniert."
		).format(dunning),
		title=_("Über Mahnung stornieren"),
	)


def validate_payment_entry_not_against_fee_dunning(doc, method=None) -> None:
	for row in doc.get("references") or []:
		if row.get("reference_doctype") != "Dunning" or not row.get("reference_name"):
			continue
		fee_invoice = _dunning_fee_sales_invoice(row.reference_name)
		detail = (
			_(" Die Mahngebühr ist als Sales Invoice {0} gebucht.").format(fee_invoice)
			if fee_invoice
			else ""
		)
		frappe.throw(
			_(
				"Zahlungen auf Mahnung {0} sind deaktiviert.{1} Bitte die Zahlung "
				"gegen die offenen Sales Invoices ausgleichen."
			).format(row.reference_name, detail),
			title=_("Zahlung gegen Mahnung nicht erlaubt"),
		)


@frappe.whitelist()
def get_payment_entry_guarded(dt, dn, *args, **kwargs):
	if dt == "Dunning":
		fee_invoice = _dunning_fee_sales_invoice(dn)
		detail = (
			_(" Die Mahngebühr ist als Sales Invoice {0} gebucht.").format(fee_invoice)
			if fee_invoice
			else ""
		)
		frappe.throw(
			_(
				"Zahlungen werden nicht aus der Mahnung erstellt.{0} Bitte Zahlung "
				"gegen die offenen Sales Invoices erstellen."
			).format(detail),
			title=_("Zahlung über Rechnung buchen"),
		)

	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	return get_payment_entry(dt, dn, *args, **kwargs)
