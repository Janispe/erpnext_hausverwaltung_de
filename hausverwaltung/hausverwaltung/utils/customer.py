"""Customer helpers used by Mietvertrag and other domain code."""

from __future__ import annotations

import uuid

import frappe


def get_or_create_customer_group() -> str:
	"""Stellt sicher, dass die Customer Group *Mieter* existiert."""
	if frappe.db.exists("Customer Group", "Mieter"):
		return "Mieter"

	def _ensure_customer_group_root() -> str:
		for preferred in ("All Customer Groups", "Alle Kundengruppen"):
			try:
				if frappe.db.exists("Customer Group", preferred):
					return preferred
			except Exception:
				pass

		try:
			rows = frappe.get_all(
				"Customer Group",
				fields=["name", "parent_customer_group", "is_group"],
				limit=200,
			)
			for row in rows:
				if row.get("is_group") and not row.get("parent_customer_group"):
					return row["name"]
		except Exception:
			pass

		try:
			doc = (
				frappe.get_doc(
					{
						"doctype": "Customer Group",
						"customer_group_name": "All Customer Groups",
						"is_group": 1,
					}
				)
				.insert(ignore_if_duplicate=True, ignore_permissions=True)
			)
			return doc.name
		except Exception:
			return "All Customer Groups"

	parent = _ensure_customer_group_root()
	return (
		frappe.get_doc(
			{
				"doctype": "Customer Group",
				"customer_group_name": "Mieter",
				"parent_customer_group": parent,
			}
		)
		.insert(ignore_if_duplicate=True, ignore_permissions=True)
		.name
	)


def build_customer_id(wohnlabel: str, von_date: str, nachname: str) -> str:
	"""Generiert eine sprechende Customer-ID im Schema ``{wohnung} Mieter: {nachname}``.

	Parallel zum Mietvertrag-Naming (``{wohnung} Mietvertrag: {von}``) — gleiche
	Wohnung als Prefix, anderer Begriff. Bei Kollision (selbe Wohnung + selber
	Nachname) wird ein numerischer Suffix angehängt: ``... (2)``, ``... (3)``.

	Fallback (wenn weder Wohnung noch Nachname bekannt): zufällige UUID-ID.

	Args:
	    wohnlabel: Wohnungs-Name (z.B. "Kirchhof | VH | EG links").
	    von_date: Wird aktuell nicht verwendet — bleibt für Backward-Compat im Signaturen.
	    nachname: Nachname des Mieters (oder Vorname als Fallback).
	"""
	_ = von_date  # Backward-Compat-Parameter, aktuell ungenutzt
	wohn = (wohnlabel or "").strip()
	nm = (nachname or "").strip()

	if wohn and nm:
		base = f"{wohn} Mieter: {nm}"
	elif wohn:
		base = f"{wohn} Mieter"
	elif nm:
		base = f"Mieter: {nm}"
	else:
		# Weder Wohnung noch Nachname — Fallback auf altes UUID-Schema
		while True:
			candidate = f"MIETER-{uuid.uuid4().hex[:10].upper()}"
			if not frappe.db.exists("Customer", candidate, cache=False):
				return candidate

	if not frappe.db.exists("Customer", base, cache=False):
		return base

	# Kollisionsauflösung: gleiche Wohnung + gleicher Nachname → numerisches Suffix
	for n in range(2, 100):
		candidate = f"{base} ({n})"
		if not frappe.db.exists("Customer", candidate, cache=False):
			return candidate

	# Notfall-Fallback: random Suffix
	return f"{base} {uuid.uuid4().hex[:6].upper()}"


def get_or_create_customer(
	cust_id: str,
	customer_name: str | None = None,
	company: str | None = None,
) -> str:
	"""Erzeugt (oder holt) einen Customer-Datensatz.

	Die Buchung läuft über ein Sammelkonto Debitoren (Company.default_receivable_account);
	pro Customer wird kein eigenes Konto gepinnt.
	"""
	customer_name = (customer_name or cust_id or "").strip() or cust_id

	if frappe.db.exists("Customer", cust_id):
		if frappe.db.get_value("Customer", cust_id, "customer_name") != customer_name:
			frappe.db.set_value("Customer", cust_id, "customer_name", customer_name, update_modified=False)
		return cust_id

	group = get_or_create_customer_group()

	doc = {
		"doctype": "Customer",
		"customer_name": customer_name,
		"customer_type": "Individual",
		"customer_group": group,
	}
	if company:
		doc["company"] = company
	return (
		frappe.get_doc(doc)
		.insert()
		.name
	)
