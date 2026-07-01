from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cstr, escape_html

from mail_merge.mail_merge.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
	_resolve_value_path,
)


IMMOBILIE_PATH_BY_TARGET = {
	"Mietvertrag": "objekt.wohnung.immobilie",
	"Betriebskostenabrechnung Mieter": "objekt.mietvertrag.wohnung.immobilie",
	"Dunning": "objekt.overdue_payments.sales_invoice.mietvertrag.wohnung.immobilie",
}

FOOTER_ROW_STYLE = (
	"font-size: 6pt !important; line-height: 1.05 !important; "
	"color: #000 !important; white-space: nowrap; overflow: hidden; "
	"text-overflow: ellipsis;"
)


def render_bankverbindung_footer(doc: Any | None = None) -> str:
	immobilie = _resolve_immobilie(doc)
	if not immobilie:
		return ""

	account_name = _bank_value(immobilie, "account_name")
	iban = _bank_value(immobilie, "iban")
	bic = _bank_value(immobilie, "bic")
	bank_name = _bank_name(immobilie)

	parts = []
	if account_name:
		parts.append(account_name)
	if iban:
		parts.append(f"IBAN {iban}")
	if bic:
		parts.append(f"BIC {bic}")
	if bank_name:
		parts.append(bank_name)

	if not parts:
		return ""
	return f'<div style="{FOOTER_ROW_STYLE}">{escape_html("Bankverbindung: " + " · ".join(parts))}</div>'


def _resolve_immobilie(doc: Any | None):
	target_doctype = cstr(getattr(doc, "iteration_doctype", "") or "").strip()
	target_name = cstr(getattr(doc, "objekt", "") or "").strip()

	if target_doctype and target_name:
		path = IMMOBILIE_PATH_BY_TARGET.get(target_doctype)
		if not path:
			return None
		try:
			target_doc = frappe.get_cached_doc(target_doctype, target_name)
		except Exception:
			return None
		return _resolve_value_path(path, {"objekt": target_doc})

	if not frappe.flags.get("hv_serienbrief_split_preview"):
		return None

	vorlage_name = cstr(getattr(doc, "vorlage", "") or "").strip()
	if not vorlage_name:
		return None
	try:
		template_doc = frappe.get_cached_doc("Serienbrief Vorlage", vorlage_name)
	except Exception:
		return None
	target_doctype = cstr(getattr(template_doc, "haupt_verteil_objekt", "") or "").strip()
	path = IMMOBILIE_PATH_BY_TARGET.get(target_doctype)
	if not path:
		return None

	from mail_merge.mail_merge.doctype.serienbrief_vorlage.serienbrief_vorlage import (
		_split_preview_context,
	)

	return _resolve_value_path(path, _split_preview_context(template_doc=template_doc))


def _get_field(value: Any, fieldname: str) -> Any:
	if value is None:
		return None
	if isinstance(value, dict):
		return value.get(fieldname)
	try:
		children = object.__getattribute__(value, "_children")
	except Exception:
		children = None
	if isinstance(children, dict) and fieldname not in children:
		return None
	try:
		result = getattr(value, fieldname)
	except Exception:
		return None
	if result.__class__.__name__ in {"SplitPreviewUndefined", "SplitPreviewDummy"}:
		return None
	return result


def _bank_value(immobilie: Any, fieldname: str) -> str:
	value = None
	if not frappe.flags.get("hv_serienbrief_split_preview"):
		konto = _get_field(immobilie, "bank_konto")
		value = _get_field(konto, fieldname)
		if not value and fieldname == "account_name":
			value = _get_field(konto, "account")
	if not value:
		value = _get_field(immobilie, fieldname)
	if not value and fieldname == "account_name":
		value = _get_field(immobilie, "bank_account_name")
	return cstr(value or "").strip()


def _bank_name(immobilie: Any) -> str:
	if not frappe.flags.get("hv_serienbrief_split_preview"):
		konto = _get_field(immobilie, "bank_konto")
		bank = _get_field(konto, "bank")
		if bank and not isinstance(bank, str):
			value = _get_field(bank, "bank_name") or _get_field(bank, "name")
			if value:
				return cstr(value).strip()
		if bank:
			try:
				if frappe.db.exists("Bank", bank):
					return cstr(frappe.db.get_value("Bank", bank, "bank_name") or bank).strip()
			except Exception:
				return cstr(bank).strip()
			return cstr(bank).strip()
	return cstr(_get_field(immobilie, "bank_name") or "").strip()
