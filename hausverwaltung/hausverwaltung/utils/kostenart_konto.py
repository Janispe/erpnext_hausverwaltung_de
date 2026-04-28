"""Eindeutigkeit von `konto` über die beiden Kostenart-Doctypes hinweg.

Ein Konto darf entweder in `Betriebskostenart` ODER in `Kostenart nicht umlagefaehig`
referenziert sein, niemals in beiden gleichzeitig oder mehrfach in einer der Listen.
Diese Invariante ermöglicht den Reverse-Lookup vom Konto zur Kostenart im Buchungs-
Cockpit.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import frappe


BK_DOCTYPE = "Betriebskostenart"
KOSTENART_NICHT_UL_DOCTYPE = "Kostenart nicht umlagefaehig"
NICHT_UMLAGEFAEHIG_PARENT = "Nicht Umlagefähig"


def assert_konto_unique(*, konto: str | None, doctype: str, name: str | None) -> None:
	"""Wirft, wenn `konto` schon in BK oder Kostenart-nicht-UL belegt ist.

	`doctype`/`name` identifizieren den aktuell gespeicherten Datensatz, der vom
	Vergleich ausgenommen wird.
	"""
	if not konto:
		return

	other_doctype = (
		KOSTENART_NICHT_UL_DOCTYPE if doctype == BK_DOCTYPE else BK_DOCTYPE
	)

	# Konflikt im selben Doctype (anderer Datensatz, gleiches Konto)?
	same_filters: dict = {"konto": konto}
	if name:
		same_filters["name"] = ["!=", name]
	conflict = frappe.db.get_value(doctype, same_filters, "name")
	if conflict:
		frappe.throw(
			f"Konto „{konto}“ ist bereits in {doctype} „{conflict}“ hinterlegt. "
			f"Ein Konto darf nur einmal als Kostenart referenziert werden."
		)

	# Konflikt im anderen Doctype?
	conflict = frappe.db.get_value(other_doctype, {"konto": konto}, "name")
	if conflict:
		frappe.throw(
			f"Konto „{konto}“ ist bereits in {other_doctype} „{conflict}“ hinterlegt. "
			f"Ein Konto kann entweder umlagefähig (Betriebskostenart) oder nicht "
			f"umlagefähig sein, nicht beides."
		)


def auto_create_kostenart_on_account_insert(doc, method=None) -> None:
	"""Account-after_insert-Hook: legt automatisch eine ``Kostenart nicht
	umlagefaehig`` für neu erstellte Blatt-Konten unter „Nicht Umlagefähig" an.

	Greift bei:
	- Manuellem Anlegen via UI
	- COA-Import (jede neue Account-Row triggert after_insert)
	- Programmatisch erzeugte Konten

	Idempotent — überspringt Konten die schon irgendwo als Kostenart erfasst sind.
	Keine Hard-Fails — Fehler werden geloggt aber blockieren nicht den Account-Insert.
	"""
	try:
		if not doc or doc.get("is_group"):
			return
		if doc.get("root_type") and doc.root_type != "Expense":
			return
		if not _account_is_under_parent(doc, NICHT_UMLAGEFAEHIG_PARENT):
			return
		# Schon erfasst?
		if frappe.db.exists(KOSTENART_NICHT_UL_DOCTYPE, {"konto": doc.name}):
			return
		if frappe.db.exists(BK_DOCTYPE, {"konto": doc.name}):
			return

		from hausverwaltung.hausverwaltung.utils.buchung import ensure_default_service_item
		try:
			artikel = ensure_default_service_item()
		except Exception:
			artikel = None

		frappe.get_doc(
			{
				"doctype": KOSTENART_NICHT_UL_DOCTYPE,
				"name1": doc.get("account_name") or doc.name,
				"konto": doc.name,
				"artikel": artikel,
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			frappe.get_traceback(),
			f"Auto-Kostenart-Anlage fehlgeschlagen ({getattr(doc, 'name', '?')})",
		)


def _account_is_under_parent(account_doc, parent_account_name: str) -> bool:
	"""Prüft ob ein Account ein Nachfahre eines bestimmten Gruppen-Kontos ist.

	Geht den ``parent_account``-Pfad nach oben statt lft/rgt zu nutzen — robuster
	bei ``after_insert``, weil NestedSet-Felder dort noch nicht zwingend final
	gesetzt sind.
	"""
	if not account_doc:
		return False
	current_parent_name = account_doc.get("parent_account")
	visited: set[str] = set()
	while current_parent_name and current_parent_name not in visited:
		visited.add(current_parent_name)
		parent = frappe.db.get_value(
			"Account",
			current_parent_name,
			["account_name", "is_group", "parent_account"],
			as_dict=True,
		)
		if not parent:
			return False
		if parent.is_group and parent.account_name == parent_account_name:
			return True
		current_parent_name = parent.parent_account
	return False


@frappe.whitelist()
def create_kostenarten_for_nicht_umlagefaehig_accounts(
	company: str,
	parent_account_name: str = NICHT_UMLAGEFAEHIG_PARENT,
	artikel: Optional[str] = None,
) -> Dict[str, Any]:
	"""Legt für jedes Blatt-Konto unter 'Nicht Umlagefähig' eine
	``Kostenart nicht umlagefaehig`` an, wenn noch keine vorhanden ist.

	Args:
	    company: Ziel-Firma. Nur Konten dieser Company werden betrachtet.
	    parent_account_name: Name des Gruppen-Kontos unter dem alle nicht-umlage-
	        fähigen Aufwandskonten hängen (Default: "Nicht Umlagefähig").
	    artikel: Optionaler Item-Code, der als Default-Artikel verwendet wird.
	        Wenn ``None``: ``ensure_default_service_item()`` wird genutzt.

	Idempotent: Konten, die bereits in irgendeiner Kostenart-Liste auftauchen,
	werden übersprungen (verhindert Konflikte mit der Konto-Eindeutigkeit).

	Returns Dict mit ``created`` (Liste der angelegten Kostenart-Namen) und
	``skipped`` (Diagnose pro übersprungenes Konto).
	"""
	from hausverwaltung.hausverwaltung.utils.buchung import ensure_default_service_item

	# Parent-Knoten suchen
	parent = frappe.db.get_value(
		"Account",
		{"company": company, "account_name": parent_account_name, "is_group": 1},
		["name", "lft", "rgt"],
		as_dict=True,
	)
	if not parent:
		return {
			"created": [],
			"skipped": [],
			"total_leaves": 0,
			"reason": f"Gruppe '{parent_account_name}' nicht gefunden für Company '{company}'",
		}

	# Bevorzuge NestedSet-Filter wenn lft/rgt gesetzt sind, sonst Fallback auf
	# rekursiven parent_account-Walk (nach frischem Bulk-Insert sind lft/rgt
	# evtl. noch nicht aktualisiert).
	if parent.get("lft") is not None and parent.get("rgt") is not None:
		leaves = frappe.get_all(
			"Account",
			filters={
				"company": company,
				"is_group": 0,
				"lft": [">", parent.lft],
				"rgt": ["<", parent.rgt],
			},
			fields=["name", "account_name", "account_number"],
			order_by="account_number asc, account_name asc",
		)
	else:
		# Fallback: alle Accounts laden und per parent_account-Walk filtern
		all_accounts = frappe.get_all(
			"Account",
			filters={"company": company, "is_group": 0},
			fields=["name", "account_name", "account_number", "parent_account"],
			order_by="account_number asc, account_name asc",
		)
		leaves = [
			a for a in all_accounts
			if _account_is_under_parent(a, parent_account_name)
		]

	if artikel is None:
		try:
			artikel = ensure_default_service_item()
		except Exception:
			artikel = None

	created: List[str] = []
	skipped: List[Dict[str, str]] = []

	for acc in leaves:
		# Schon irgendwo als Kostenart erfasst? Idempotenz + Konto-Eindeutigkeits-Invariante
		if frappe.db.exists(KOSTENART_NICHT_UL_DOCTYPE, {"konto": acc.name}):
			skipped.append({"konto": acc.name, "reason": "already_in_kostenart_nicht_ul"})
			continue
		if frappe.db.exists(BK_DOCTYPE, {"konto": acc.name}):
			skipped.append({"konto": acc.name, "reason": "already_in_betriebskostenart"})
			continue
		try:
			doc = frappe.get_doc(
				{
					"doctype": KOSTENART_NICHT_UL_DOCTYPE,
					"name1": acc.get("account_name") or acc.name,
					"konto": acc.name,
					"artikel": artikel,
				}
			).insert(ignore_permissions=True)
			created.append(doc.name)
		except Exception as exc:
			skipped.append({"konto": acc.name, "reason": f"error: {exc}"})
			frappe.log_error(
				frappe.get_traceback(),
				f"Kostenart nicht umlagefaehig konnte nicht angelegt werden ({acc.name})",
			)

	frappe.db.commit()
	return {
		"created": created,
		"skipped": skipped,
		"total_leaves": len(leaves),
		"parent_account": parent.name,
	}
