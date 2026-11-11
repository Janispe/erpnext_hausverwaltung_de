"""Explicit, state-bound submission of stored fee-free legacy full-balance letters.

This module never invents Payment Schedules or creates new reference-less drafts.
Only the dedicated confirmation endpoint can establish the process-local proof
used by the narrow Dunning reference adapter. Client document flags cannot do so.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from contextvars import ContextVar

import frappe
from frappe import _
from frappe.utils import flt

from hausverwaltung.hausverwaltung.utils.dunning_creation import (
	lock_dunning_invoices, reject_duplicate_dunning,
)
from hausverwaltung.hausverwaltung.utils.dunning_payment_schedule import match_dunning_rows
from hausverwaltung.hausverwaltung.utils.legacy_dunning_origin import require_legacy_origin

_TTL = 300
_ACTION = "submit_stored_legacy_full_balance_v1"
_proof = ContextVar("hv_legacy_dunning_confirmation", default=None)
_DOC_FIELDS = (
	"name", "customer", "company", "currency", "conversion_rate", "posting_date",
	"dunning_type", "dunning_fee", "rate_of_interest", "dunning_amount",
	"income_account", "cost_center",
)
_ROW_FIELDS = (
	"name", "sales_invoice", "payment_schedule", "outstanding", "due_date",
	"payment_amount", "invoice_portion", "payment_term", "mode_of_payment",
)


def _fingerprint(doc, invoices):
	values = {
		"action": _ACTION,
		"document": {field: doc.get(field) for field in _DOC_FIELDS},
		"rows": [{field: row.get(field) for field in _ROW_FIELDS} for row in doc.get("overdue_payments") or []],
		"invoices": [invoice.as_dict() for invoice in invoices],
		"legacy_origins": [require_legacy_origin(invoice) for invoice in invoices],
	}
	return hashlib.sha256(json.dumps(values, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _user():
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Bitte als berechtigter Benutzer anmelden."), frappe.PermissionError)
	return user


def _key(token):
	if not isinstance(token, str) or not 32 <= len(token) <= 128:
		frappe.throw(_("Die Bestätigung fehlt oder ist abgelaufen. Bitte erneut prüfen."))
	return "hv:legacy-dunning:" + hashlib.sha256(token.encode()).hexdigest()


def _validate_legacy_case(doc, invoices):
	payments = doc.get("overdue_payments") or []
	if not doc.get("posting_date"):
		frappe.throw(_("Für die Bestätigung ist ein eindeutiges Mahndatum erforderlich."))
	# This exception is deliberately limited to one existing legacy invoice.
	if len(invoices) != 1 or len(payments) != 1 or invoices[0].get("payment_schedule"):
		frappe.throw(_("Dieser Bestätigungsweg gilt nur für eine eindeutige alte Rechnung ohne Zahlungsplan."))
	invoice = invoices[0]
	if (invoice.customer, invoice.company, invoice.currency) != (doc.customer, doc.company, doc.currency):
		frappe.throw(_("Mahnung und Rechnung müssen denselben Mieter, dieselbe Firma und Währung haben."))
	if any(flt(doc.get(field)) for field in ("dunning_amount", "dunning_fee", "rate_of_interest")):
		frappe.throw(_("Der alte Vollsaldo darf nur ohne Mahngebühren und Verzugszinsen bestätigt werden."))
	require_legacy_origin(invoice)
	match_dunning_rows(invoice, payments, doc.posting_date, allow_legacy=True)
	reject_duplicate_dunning([invoice.name], doc.posting_date, exclude_dunning=doc.name)


def require_confirmation(doc, invoices):
	"""Validate a server-internal proof; never accept a client flag or bare bool."""
	_validate_legacy_case(doc, invoices)
	proof = _proof.get()
	if (
		not proof or proof["user"] != _user() or proof["name"] != doc.name
		or proof["action"] != _ACTION or proof["fingerprint"] != _fingerprint(doc, invoices)
		or proof.get("expires_at", 0) <= time.time()
		or doc.get("docstatus") != 1 or getattr(doc, "_action", None) != "submit"
	):
		frappe.throw(_("Diese alte Rechnung hat keinen Zahlungsplan. Bitte die Altmahnung zuerst prüfen und im Warnungsdialog ausdrücklich bestätigen."))


def _locked_context(name):
	_user()
	if not isinstance(name, str) or not name.strip():
		frappe.throw(_("Bitte einen eindeutigen gespeicherten Mahnentwurf angeben."))
	doc = frappe.get_doc("Dunning", name, for_update=True)
	doc.check_permission("read")
	doc.check_permission("write")
	doc.check_permission("submit")
	if int(doc.docstatus) != 0 or doc.is_new():
		frappe.throw(_("Nur ein bereits gespeicherter, noch nicht eingereichter Altentwurf kann bestätigt werden."))
	payments = doc.get("overdue_payments") or []
	names = [row.sales_invoice for row in payments if row.get("sales_invoice")]
	if not names or len(names) != len(payments):
		frappe.throw(_("Die Mahnung enthält keine eindeutige Rechnung."))
	invoices = lock_dunning_invoices(names, doc.posting_date)
	# Use the same effective Core setters as submission, only in memory.
	doc.validate_currency()
	doc.set_dunning_fee()
	return doc, invoices


@frappe.whitelist(methods=["POST"])
def prepare_legacy_dunning_confirmation(dunning):
	"""Read/lock/check only. Closing the dialog never creates or submits a doc."""
	doc, invoices = _locked_context(dunning)
	if all(invoice.get("payment_schedule") for invoice in invoices):
		return {"required": False}
	_validate_legacy_case(doc, invoices)
	token = secrets.token_urlsafe(32)
	payload = {
		"user": _user(), "name": doc.name, "action": _ACTION,
		"modified": str(doc.modified), "fingerprint": _fingerprint(doc, invoices),
		"expires_at": time.time() + _TTL,
	}
	frappe.cache.set_value(_key(token), payload, expires_in_sec=_TTL)
	invoice = invoices[0]
	return {"required": True, "token": token, "expires_in_seconds": _TTL,
		"dunning": doc.name, "invoice": invoice.name, "amount": flt(invoice.outstanding_amount),
		"currency": invoice.currency, "due_date": str(invoice.due_date), "posting_date": str(doc.posting_date)}


@frappe.whitelist(methods=["POST"])
def submit_confirmed_legacy_dunning(dunning, token=None, confirmed=False):
	if not (confirmed is True or isinstance(confirmed, str) and confirmed == "true"):
		frappe.throw(_("Bitte den Warnungsdialog ausdrücklich bestätigen."))
	user = _user()
	key = _key(token)
	with frappe.cache.lock(key + ":execute", timeout=120, blocking_timeout=5):
		payload = frappe.cache.get_value(key, expires=True, use_local_cache=False)
		if (
			not isinstance(payload, dict) or payload.get("user") != user
			or payload.get("name") != dunning or payload.get("action") != _ACTION
			or payload.get("expires_at", 0) <= time.time()
		):
			frappe.throw(_("Die Bestätigung fehlt, ist abgelaufen oder gehört zu einer anderen Aktion. Bitte erneut prüfen."))
		doc, invoices = _locked_context(dunning)
		_validate_legacy_case(doc, invoices)
		if payload["modified"] != str(doc.modified) or payload["fingerprint"] != _fingerprint(doc, invoices):
			frappe.throw(_("Mahnung oder Rechnung wurde seit dem Dialog geändert. Bitte erneut prüfen und bestätigen."))
		# Database/duplicate locks above can wait past the initial TTL check.
		# Recheck immediately before burning the challenge and entering submit.
		if payload["expires_at"] <= time.time():
			frappe.throw(_("Die Bestätigung ist während der Prüfung abgelaufen. Bitte erneut prüfen."))
		# Single use, fail closed even if the later submit fails; retry needs a new dialog.
		frappe.cache.delete_value(key)
		context = _proof.set(payload)
		try:
			doc.submit()
			doc.add_comment("Info", _("Altmahnung ohne Zahlungsplan: gebührenfreier Vollsaldo nach Warnungsdialog ausdrücklich bestätigt."))
		finally:
			_proof.reset(context)
		return {"name": doc.name, "docstatus": doc.docstatus}
