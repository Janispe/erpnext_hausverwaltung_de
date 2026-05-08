"""Helper für den Page-Footer im Serienbrief-PDF.

Frappes Chrome-PDF rendert ``<div id="footer-html">`` aus dem Print Format
„Serienbrief Dokument" (siehe ``install.py``) auf jeder Seite. Dieser Helper
liefert eine optionale Bankverbindungs-Zeile, **wenn die Vorlage den
Baustein „Bankverbindung Immobilie" referenziert** — sonst leeren String.

So bleibt die Notation einheitlich: der Vorlagen-Autor steuert die Anzeige
über die Baustein-Liste, die Visualisierung läuft zentral durch den Footer.
"""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.utils import cstr, escape_html


_FOOTER_BAUSTEIN = "Bankverbindung Immobilie"
_FOOTER_VARIABLE = "immobilie"
# Erkennt Inline-Aufrufe wie ``{{ baustein("Bankverbindung Immobilie") }}``
# oder ``{{ textbaustein("Bankverbindung Immobilie") }}`` im Vorlagen-Body.
_BAUSTEIN_INLINE_RE = re.compile(
	r"\{\{\s*(?:baustein|textbaustein)\s*\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}"
)


def _vorlage_referenziert_baustein(vorlage_doc, baustein_name: str) -> bool:
	"""Prüft, ob die Vorlage den Baustein referenziert — entweder über die
	``textbausteine``-Child-Table oder als Inline-Aufruf im Body.
	"""
	if any(
		cstr(getattr(row, "baustein", "")).strip() == baustein_name
		for row in (vorlage_doc.get("textbausteine") or [])
	):
		return True
	for fieldname in ("content", "html_content", "jinja_content"):
		text = cstr(getattr(vorlage_doc, fieldname, "") or "")
		if not text:
			continue
		for match in _BAUSTEIN_INLINE_RE.finditer(text):
			if match.group(1).strip() == baustein_name:
				return True
	return False


@frappe.whitelist()
def get_footer_bankverbindung_html(doc) -> str:
	"""Gibt HTML-Snippet für die Bankverbindung-Footer-Zeile zurück, oder
	leeren String wenn die Vorlage den Baustein nicht referenziert.

	Im Live-Preview-Modus (siehe ``frappe.flags.hv_serienbrief_split_preview``)
	wird ein hartkodiertes Mock-Snippet zurückgegeben — der echte Resolver
	würde sonst gegen die SplitPreview-Mocks laufen, die kein gültiges
	Frappe-Doc sind.
	"""
	vorlage_name = cstr(getattr(doc, "vorlage", "") or "").strip()
	if not vorlage_name or not frappe.db.exists("Serienbrief Vorlage", vorlage_name):
		return ""

	vorlage = frappe.get_cached_doc("Serienbrief Vorlage", vorlage_name)
	if not _vorlage_referenziert_baustein(vorlage, _FOOTER_BAUSTEIN):
		return ""

	# Live-Preview: hartkodiertes Mock-Snippet, weil iter-Doc kein echtes
	# Frappe-Doc ist und der Resolver damit nicht arbeiten kann.
	if frappe.flags.get("hv_serienbrief_split_preview"):
		return (
			"Bankverbindung: Beispielkonto Hausverwaltung · "
			"IBAN DE12 3456 7890 1234 5678 90 · Beispielbank"
		)

	iteration_doctype = cstr(getattr(doc, "iteration_doctype", "") or "").strip()
	iteration_name = cstr(getattr(doc, "objekt", "") or "").strip()
	if not iteration_doctype or not iteration_name:
		frappe.throw(
			_("Footer-Bankverbindung: Iterationsobjekt fehlt im Serienbrief-Dokument."),
			title=_("Serienbrief Footer-Fehler"),
		)

	# Standardpfad vom Baustein für den aktuellen Iteration-Doctype.
	from hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf import (
		_get_block_default_path_map,
		_resolve_value_path,
	)

	block_doc = frappe.get_cached_doc("Serienbrief Textbaustein", _FOOTER_BAUSTEIN)
	path_map = _get_block_default_path_map(block_doc, iteration_doctype) or {}
	immobilie_path = (
		cstr(path_map.get(_FOOTER_VARIABLE) or "").strip()
		or cstr(path_map.get("Immobilie") or "").strip()
	)
	if not immobilie_path:
		frappe.throw(
			_(
				"Footer-Bankverbindung: kein Standardpfad für Iteration-Doctype "
				"<strong>{0}</strong> im Baustein „Bankverbindung Immobilie\" gepflegt."
			).format(iteration_doctype),
			title=_("Serienbrief Footer-Fehler"),
		)

	try:
		iter_doc = frappe.get_cached_doc(iteration_doctype, iteration_name)
	except frappe.DoesNotExistError:
		frappe.throw(
			_("Footer-Bankverbindung: Iterationsobjekt {0} {1} nicht gefunden.").format(
				iteration_doctype, iteration_name
			),
			title=_("Serienbrief Footer-Fehler"),
		)

	immobilie = _resolve_value_path(immobilie_path, {"objekt": iter_doc})
	if immobilie is None:
		frappe.throw(
			_(
				"Footer-Bankverbindung: Pfad <code>{0}</code> liefert keine Immobilie "
				"für {1} {2}."
			).format(immobilie_path, iteration_doctype, iteration_name),
			title=_("Serienbrief Footer-Fehler"),
		)

	bk = getattr(immobilie, "bank_konto", None)
	if bk is None:
		frappe.throw(
			_(
				"Footer-Bankverbindung: Immobilie <strong>{0}</strong> hat kein "
				"Hauptkonto mit Bank-Account-Link. Bitte unter Immobilie ▸ "
				"Bankkonten ein Hauptkonto pflegen, dessen Account einen "
				"verknüpften Bank Account hat."
			).format(getattr(immobilie, "name", "?")),
			title=_("Serienbrief Footer-Fehler"),
		)

	account_name = escape_html(cstr(getattr(bk, "account_name", "") or ""))
	iban = escape_html(cstr(getattr(bk, "iban", "") or ""))
	bank = escape_html(cstr(getattr(bk, "bank", "") or ""))
	return f"Bankverbindung: {account_name} · IBAN {iban} · {bank}"
