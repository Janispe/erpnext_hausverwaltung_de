import csv
import io
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import frappe
from frappe.model.document import Document
from frappe.model.naming import make_autoname
from frappe.utils import flt, getdate


RELEVANT_HEADERS = {
    "buchungstag": ["Buchungstag", "Buchungstag"],
    "betrag": ["Betrag", "Amount"],
    "soll": ["Soll"],
    "haben": ["Haben"],
    "iban": ["IBAN / Kontonummer", "IBAN", "Kontonummer"],
    "auftraggeber": ["Begünstigter / Auftraggeber", "Auftraggeber", "Empfänger"],
    "verwendungszweck": ["Verwendungszweck", "Verw. Zweck", "Zahlungsreferenz"],
    "waehrung": ["Währung", "Currency"],
}

SUPPORTED_PARTY_TYPES = ("Customer", "Supplier", "Eigentuemer")


class BankauszugImport(Document):
    def autoname(self):
        """Generiert einen sprechenden Namen aus Bank-Nr + Datumsrange + Counter.

        Wenn Rows beim Insert bereits vorhanden sind:
        ``BAI-{bank_no}-{YYYYMMDD}-{YYYYMMDD}-{####}``

        Im aktuellen CSV-Flow sind Rows bei ``autoname()`` meist noch leer
        (``parse_csv()`` läuft nach dem Insert). Dann fällt der Name bewusst
        auf ``BAI-{bank_no}-{####}`` zurück; der Zeitraum landet zuverlässig
        im ``title``.
        """
        bank_no = self._bank_account_number() or "XXXX"
        date_from, date_to = self._row_date_range()
        if date_from and date_to:
            prefix = f"BAI-{bank_no}-{date_from:%Y%m%d}-{date_to:%Y%m%d}"
        else:
            prefix = f"BAI-{bank_no}"
        self.name = make_autoname(f"{prefix}-.####")

    def before_save(self):
        # update info and clear rows if file changed
        pass

    def validate(self):
        self._compute_title()

    def onload(self):
        # Beim normalen Formular-Öffnen stale Payment-Entry-Links entfernen
        # (z.B. wenn ein Voucher außerhalb der Bankimport-UI storniert wurde).
        try:
            sync_cancelled_payment_entry_links(import_name=self.name)
            sync_cancelled_journal_entry_links(import_name=self.name)
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Bankauszug Import: Storno-Sync beim Öffnen fehlgeschlagen ({self.name})",
            )
        # Status beim Öffnen aus aktuellem Zeilen-Stand neu berechnen, damit
        # ältere Dokumente (deren Status zur Bulk-Create-Zeit eingefroren wurde)
        # die aktuelle Phase im Header zeigen.
        try:
            new_status = _recompute_doc_status(self.name)
            self.status = new_status
        except Exception:
            pass
        # Saldo neu berechnen, damit nach nachträglichen Buchungen / Cancels der
        # angezeigte ERP-Saldo immer aktuell ist (Stale-Bug ohne manuellen Klick
        # auf "Saldo neu prüfen").
        try:
            _refresh_saldo_fields(self)
            _persist_saldo_fields(self)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Title + Naming-Helper
    # ------------------------------------------------------------------

    def _compute_title(self):
        """Setzt ``self.title`` aus Bank-Label + Datumsrange + Anzahl + Immobilie."""
        bank_label = self._bank_account_label() or "?"
        date_from, date_to = self._row_date_range()
        n_rows = len(self.get("rows") or [])
        immobilie = self._eindeutige_immobilie()

        parts = [bank_label]
        if date_from and date_to:
            if date_from == date_to:
                parts.append(f"{date_from:%d.%m.%Y}")
            elif date_from.year == date_to.year:
                parts.append(f"{date_from:%d.%m.}–{date_to:%d.%m.%Y}")  # noqa: RUF001
            else:
                parts.append(f"{date_from:%d.%m.%Y}–{date_to:%d.%m.%Y}")  # noqa: RUF001
        if n_rows:
            parts.append(f"{n_rows} {'Buchung' if n_rows == 1 else 'Buchungen'}")
        if immobilie:
            parts.append(immobilie)
        self.title = " · ".join(parts)

    def _bank_account_number(self) -> Optional[str]:
        """``"1812"`` / ``"1804"`` etc — aus dem GL-Account des Bank Accounts."""
        if not self.bank_account:
            return None
        gl_account = frappe.db.get_value("Bank Account", self.bank_account, "account")
        if not gl_account:
            return None
        return frappe.db.get_value("Account", gl_account, "account_number")

    def _bank_account_label(self) -> Optional[str]:
        """``"Wilhelmshavener (1812)"`` — Kombination aus Bezeichnung + Nr.

        Der Bank Account hat keine ``bezeichnung``, aber sein ``name`` ist
        meist sprechend (``"Wilhelmshavener - Postbank, Ndl Deutsche Bank"``).
        Wir nehmen den Teil vor `` - ``.
        """
        if not self.bank_account:
            return None
        short = (self.bank_account or "").split(" - ", 1)[0].strip() or self.bank_account
        bank_no = self._bank_account_number()
        if bank_no:
            return f"{short} ({bank_no})"
        return short

    def _row_date_range(self) -> Tuple[Optional[Any], Optional[Any]]:
        """``MIN/MAX buchungstag`` aus ``self.rows``."""
        dates = [
            getdate(r.buchungstag)
            for r in (self.get("rows") or [])
            if r.get("buchungstag")
        ]
        if not dates:
            return (None, None)
        return (min(dates), max(dates))

    def _eindeutige_immobilie(self) -> Optional[str]:
        """Reverse-Lookup: Immobilie, deren ``haupt_bank_account`` (Link auf
        Bank Account) oder ``bankkonten``-Tabelle (Link auf GL-Konto über
        ``konto``) diesen Bank Account enthält.

        Nur wenn EXAKT eine Immobilie matched — bei 0 oder mehreren wird
        ``None`` zurückgegeben, damit der Titel nicht falsch zuordnet.
        """
        if not self.bank_account:
            return None

        from_haupt = frappe.get_all(
            "Immobilie",
            filters={"haupt_bank_account": self.bank_account},
            pluck="name",
        )

        # Child-Tabelle `Immobilie Bankkonto.konto` ist Link auf GL-Account
        # (nicht Bank Account). Wir bridgen via Bank Account.account.
        gl_account = frappe.db.get_value("Bank Account", self.bank_account, "account")
        from_child = []
        if gl_account:
            from_child = frappe.get_all(
                "Immobilie Bankkonto",
                filters={"konto": gl_account},
                fields=["parent"],
                distinct=True,
            )

        candidates = set(from_haupt) | {c.get("parent") for c in from_child if c.get("parent")}
        if len(candidates) == 1:
            return next(iter(candidates))
        return None


def _recompute_doc_status(docname: str) -> str:
    """Phasen-Status aus dem aktuellen Zeilen-Stand berechnen und persistieren.

    Wird nach jeder Zeilen-Mutation aufgerufen (Parse, Bulk-BT-Erstellung,
    manuelle Reconciliation), damit der User immer den aktuellen Fortschritt
    im Header sieht — nicht nur den Snapshot der letzten Bulk-Aktion.
    """
    rows = frappe.get_all(
        "Bankauszug Import Row",
        filters={"parent": docname, "parenttype": "Bankauszug Import"},
        fields=["party_type", "party", "bank_transaction", "payment_entry", "journal_entry", "row_status"],
    )
    total = len(rows)
    if not total:
        status = "Keine Zeilen geladen"
        offene_buchungen = 0
    else:
        with_party = sum(1 for r in rows if r.get("party_type") and r.get("party"))
        with_bt = sum(1 for r in rows if r.get("bank_transaction"))
        with_voucher = sum(1 for r in rows if r.get("payment_entry") or r.get("journal_entry"))
        failed = sum(1 for r in rows if (r.get("row_status") or "") == "failed")
        needs_review = sum(1 for r in rows if (r.get("row_status") or "") == "needs_review")
        offene_buchungen = total - with_voucher

        # Phasen-Logik hängt am bank_transaction, nicht am Party-Count: Zeilen
        # ohne Party können trotzdem als Journal Entry verbucht werden (z.B.
        # Bankgebühren), und wenn alle BTs erzeugt sind ist die Party-Phase
        # vorbei — egal wie viele Parties leer sind.
        if with_bt < total:
            if with_party < total:
                status = f"Phase 1: {with_party}/{total} Parteien zugeordnet"
            else:
                status = f"Phase 2: {with_bt}/{total} Bank-Transaktionen — {total - with_bt} bereit zum Buchen"
        elif with_voucher < total:
            status = f"Phase 3: {with_voucher}/{total} Belege zugeordnet — {offene_buchungen} offen"
        else:
            status = f"Abgeschlossen: {total} Zeilen verbucht"

        if failed:
            status += f" · Fehler: {failed}"
        if needs_review:
            status += f" · Prüfung: {needs_review}"

    frappe.db.set_value(
        "Bankauszug Import",
        docname,
        {"status": status, "offene_buchungen": offene_buchungen},
        update_modified=False,
    )
    return status


def _payment_entry_is_cancelled_or_missing(payment_entry_name: str | None) -> bool:
    return _voucher_is_cancelled_or_missing("Payment Entry", payment_entry_name)


def _voucher_is_cancelled_or_missing(doctype: str, voucher_name: str | None) -> bool:
    if not voucher_name:
        return False
    docstatus = frappe.db.get_value(doctype, voucher_name, "docstatus")
    if docstatus is None:
        return True
    try:
        return int(docstatus) == 2
    except Exception:
        return False


def sync_cancelled_voucher_links(
    voucher_doctype: str,
    voucher_name: str | None = None,
    import_name: str | None = None,
) -> Dict[str, Any]:
    """Entfernt stale Voucher-Links aus Bankimport-Zeilen.

    Wird nach PE/JE-Storno und beim Öffnen der Bankimport-UI genutzt. Die Bank
    Transaction bleibt an der Zeile; nur der erledigt wirkende Voucher-Link wird
    entfernt, damit die Zeile wieder in Phase 3 auftaucht.
    """
    if voucher_doctype not in ("Payment Entry", "Journal Entry"):
        frappe.throw(f"Voucher-Typ '{voucher_doctype}' wird nicht unterstützt.")

    direct_field = "payment_entry" if voucher_doctype == "Payment Entry" else "journal_entry"

    conditions = ["parenttype = 'Bankauszug Import'"]
    values: Dict[str, Any] = {}
    if import_name:
        conditions.append("parent = %(import_name)s")
        values["import_name"] = import_name
    if voucher_name:
        conditions.append(
            f"({direct_field} = %(voucher_name)s OR "
            "(payment_document_type = %(voucher_doctype)s AND payment_document = %(voucher_name)s))"
        )
        values["voucher_name"] = voucher_name
        values["voucher_doctype"] = voucher_doctype
    else:
        conditions.append(
            f"(({direct_field} IS NOT NULL AND {direct_field} != '') OR "
            "(payment_document_type = %(voucher_doctype)s AND payment_document IS NOT NULL AND payment_document != ''))"
        )
        values["voucher_doctype"] = voucher_doctype

    rows = frappe.db.sql(
        f"""
        SELECT
            name,
            parent,
            payment_entry,
            payment_document_type,
            payment_document,
            journal_entry,
            row_status,
            error
        FROM `tabBankauszug Import Row`
        WHERE {" AND ".join(conditions)}
        """,
        values,
        as_dict=True,
    ) or []

    checked: set[str] = set()
    stale: set[str] = set()
    cleared_rows: list[str] = []
    affected_imports: set[str] = set()

    for row in rows:
        if voucher_doctype == "Payment Entry" and row.get("journal_entry"):
            continue

        linked_vouchers = {
            value for value in (
                row.get(direct_field),
                row.get("payment_document")
                if row.get("payment_document_type") == voucher_doctype
                else None,
            )
            if value
        }
        if voucher_name:
            linked_vouchers.add(voucher_name)

        should_clear = False
        stale_name = None
        for linked_name in linked_vouchers:
            if linked_name not in checked:
                checked.add(linked_name)
                if _voucher_is_cancelled_or_missing(voucher_doctype, linked_name):
                    stale.add(linked_name)
            if linked_name in stale:
                should_clear = True
                stale_name = linked_name
                break

        if not should_clear:
            continue

        updates = {
            "payment_document_type": None,
            "payment_document": None,
            "auto_match_message": (
                f"Automatisch zurückgesetzt: {voucher_doctype} {stale_name} ist storniert."
            ),
        }
        updates[direct_field] = None
        if not row.get("error"):
            updates["row_status"] = None

        frappe.db.set_value(
            "Bankauszug Import Row",
            row.get("name"),
            updates,
            update_modified=False,
        )
        cleared_rows.append(row.get("name"))
        if row.get("parent"):
            affected_imports.add(row.get("parent"))

    if stale:
        try:
            from hausverwaltung.hausverwaltung.utils.bank_transaction_links import (
                remove_bank_transaction_payment_links,
            )

            for stale_name in sorted(stale):
                remove_bank_transaction_payment_links(voucher_doctype, stale_name)
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Bankauszug Import: Bank-Transaction-Delink fehlgeschlagen ({voucher_doctype})",
            )

    for docname in sorted(affected_imports):
        _recompute_doc_status(docname)
        _refresh_and_persist_saldo(docname)

    return {
        "checked": len(rows),
        "cleared": len(cleared_rows),
        "rows": cleared_rows,
        "imports": sorted(affected_imports),
    }


def sync_cancelled_payment_entry_links(
    payment_entry_name: str | None = None,
    import_name: str | None = None,
) -> Dict[str, Any]:
    """Backward-compatible Wrapper für Payment-Entry-Storno-Sync."""
    return sync_cancelled_voucher_links(
        "Payment Entry",
        voucher_name=payment_entry_name,
        import_name=import_name,
    )


def sync_cancelled_journal_entry_links(
    journal_entry_name: str | None = None,
    import_name: str | None = None,
) -> Dict[str, Any]:
    """Entfernt stale Journal-Entry-Links aus Bankimport-Zeilen."""
    return sync_cancelled_voucher_links(
        "Journal Entry",
        voucher_name=journal_entry_name,
        import_name=import_name,
    )


def on_payment_entry_cancel(doc, method=None) -> None:
    """Doc-event hook: Bankimport-Zeilen nach Payment-Entry-Storno öffnen."""
    try:
        sync_cancelled_payment_entry_links(payment_entry_name=doc.name)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Bankauszug Import: Payment-Entry-Storno-Sync fehlgeschlagen ({doc.name})",
        )


def on_journal_entry_cancel(doc, method=None) -> None:
    """Doc-event hook: Bankimport-Zeilen nach Journal-Entry-Storno öffnen."""
    try:
        sync_cancelled_journal_entry_links(journal_entry_name=doc.name)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Bankauszug Import: Journal-Entry-Storno-Sync fehlgeschlagen ({doc.name})",
        )


def _normalize_iban(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s.replace(" ", "").upper()


def _get_party_by_iban(iban: Optional[str]) -> Optional[Tuple[str, str]]:
    """Resolve (party_type, party) from an IBAN via `Bank Account`.

    If the same IBAN points to multiple different parties, keep the row
    unresolved so phase 1 can be decided manually.
    """
    iban_norm = _normalize_iban(iban)
    if not iban_norm:
        return None

    candidates = frappe.get_all(
        "Bank Account",
        filters={"iban": ("in", [iban_norm, iban])},
        fields=["party_type", "party"],
        limit=50,
    )
    parties = {
        (c["party_type"], c["party"])
        for c in candidates
        if c.get("party") and c.get("party_type") in SUPPORTED_PARTY_TYPES
    }
    if len(parties) == 1:
        return next(iter(parties))
    return None


def _get_default_group(doctype: str, setting_doctype: str, setting_field: str, fallback_name: str) -> str:
    try:
        val = frappe.db.get_single_value(setting_doctype, setting_field)
    except Exception:
        val = None
    if val and frappe.db.exists(doctype, val):
        return val
    if frappe.db.exists(doctype, fallback_name):
        return fallback_name
    rows = frappe.get_all(doctype, pluck="name", limit=1, order_by="name asc")
    if rows:
        return rows[0]
    frappe.throw(f"Kein {doctype} Datensatz vorhanden. Bitte zuerst Stammdaten konfigurieren.")


def _create_party_if_missing(party_type: str, party_name: str) -> Tuple[str, bool]:
    if frappe.db.exists(party_type, party_name):
        return party_name, False

    if party_type == "Customer":
        existing_customer = frappe.db.get_value("Customer", {"customer_name": party_name}, "name")
        if existing_customer:
            return existing_customer, False
        payload = {
            "doctype": "Customer",
            "customer_name": party_name,
            "customer_type": "Individual",
            "customer_group": _get_default_group(
                "Customer Group", "Selling Settings", "customer_group", "All Customer Groups"
            ),
        }
        if frappe.db.exists("Territory", "All Territories"):
            payload["territory"] = "All Territories"
        doc = frappe.get_doc(payload).insert(ignore_permissions=True)
        return doc.name, True

    existing_supplier = frappe.db.get_value("Supplier", {"supplier_name": party_name}, "name")
    if existing_supplier:
        return existing_supplier, False
    payload = {
        "doctype": "Supplier",
        "supplier_name": party_name,
        "supplier_type": "Company",
        "supplier_group": _get_default_group(
            "Supplier Group", "Buying Settings", "supplier_group", "All Supplier Groups"
        ),
    }
    doc = frappe.get_doc(payload).insert(ignore_permissions=True)
    return doc.name, True


def _get_default_bank() -> str:
    rows = frappe.get_all("Bank", pluck="name", limit=1, order_by="name asc")
    if not rows:
        frappe.throw("Kein Bank-Datensatz vorhanden. Bitte zuerst mindestens eine Bank anlegen.")
    return rows[0]


def _get_or_create_party_bank_account(*, party_type: str, party: str, iban: Optional[str]) -> Tuple[Optional[str], bool]:
    iban_norm = _normalize_iban(iban)
    if not iban_norm:
        return None, False

    existing = frappe.get_all(
        "Bank Account",
        filters={"iban": ("in", [iban_norm, iban])},
        fields=["name", "is_company_account", "party_type", "party"],
        limit=50,
    )
    party_lower = (party or "").lower()
    for bank in existing:
        if bank.get("is_company_account"):
            frappe.throw(f"IBAN {iban_norm} ist bereits einem Firmen-Bankkonto zugeordnet ({bank.get('name')}).")
        if (not bank.get("party")) and (not bank.get("party_type")):
            bank_doc = frappe.get_doc("Bank Account", bank.get("name"))
            bank_doc.party_type = party_type
            bank_doc.party = party
            if hasattr(bank_doc, "is_company_account"):
                bank_doc.is_company_account = 0
            bank_doc.save(ignore_permissions=True)
            return bank_doc.name, False
        # Case-insensitive vergleichen: Frappe-Link-Felder speichern den
        # tatsächlichen Doc-Namen (z.B. "BERLINER WASSERBETRIEBE"), während
        # der Caller den Namen in beliebiger Casing übergeben kann
        # ("Berliner Wasserbetriebe"). Beide referenzieren die gleiche Party.
        if (
            bank.get("party_type") == party_type
            and (bank.get("party") or "").lower() == party_lower
        ):
            return bank.get("name"), False
    # Wenn die IBAN bereits einer ANDEREN Party (Customer ↔ Supplier oder
    # Customer ↔ Customer) zugeordnet ist, legen wir bewusst einen ZWEITEN
    # Bank Account für die neue Party an. Dadurch sieht ``_get_party_by_iban``
    # mehrere Treffer und gibt None zurück → künftige Imports landen ohne
    # Auto-Zuordnung in der manuellen Phase, der User entscheidet pro Zeile.
    # Use-Case: gleiche IBAN bezahlt mal als Lieferant, mal als Mieter.

    # Bank Account Name = ``account_name + " - " + bank``. Frappe vergleicht
    # Namen case-insensitiv (utf8mb4_unicode_ci). Wenn schon ein Datensatz
    # mit kollidierendem Namen existiert, hängen wir die letzten 4 IBAN-
    # Zeichen an, um Eindeutigkeit zu erzwingen.
    bank_name = _get_default_bank()
    account_name = f"Konto {party}"
    candidate_pk = f"{account_name} - {bank_name}"
    if frappe.db.exists("Bank Account", candidate_pk):
        suffix = iban_norm[-4:] if iban_norm else ""
        if suffix:
            account_name = f"Konto {party} ({suffix})"
    doc = frappe.get_doc(
        {
            "doctype": "Bank Account",
            "account_name": account_name,
            "bank": bank_name,
            "iban": iban_norm,
            "is_company_account": 0,
            "party_type": party_type,
            "party": party,
        }
    ).insert(ignore_permissions=True)
    return doc.name, True


def _get_contract_contact_for_customer(mietvertrag: Document, customer: str) -> Optional[str]:
    contacts = [
        (getattr(row, "mieter", None) or "").strip()
        for row in (mietvertrag.get("mieter") or [])
        if (getattr(row, "mieter", None) or "").strip()
    ]
    if not contacts:
        return None

    linked_contacts = frappe.get_all(
        "Dynamic Link",
        filters={
            "parenttype": "Contact",
            "parent": ("in", contacts),
            "link_doctype": "Customer",
            "link_name": customer,
        },
        pluck="parent",
        limit=2,
    )
    if len(linked_contacts) == 1:
        return linked_contacts[0]

    if len(contacts) == 1:
        return contacts[0]

    return None


def _link_customer_bank_account_to_mietvertraege(customer: str, bank_account: Optional[str]) -> Dict[str, Any]:
    if not customer or not bank_account:
        return {"updated": 0, "unchanged": 0, "errors": []}

    rows = frappe.get_all(
        "Mietvertrag",
        filters={
            "kunde": customer,
            "docstatus": ("<", 2),
        },
        fields=["name"],
        limit=0,
        order_by="modified desc",
    )

    updated = 0
    unchanged = 0
    errors = []
    for row in rows:
        mv_name = row.get("name")
        if not mv_name:
            continue
        try:
            mv = frappe.get_doc("Mietvertrag", mv_name)
            if any(
                (getattr(link, "bankkonto", None) or "") == bank_account
                for link in (mv.get("kontoverbindungen") or [])
            ):
                unchanged += 1
                continue

            mv.append(
                "kontoverbindungen",
                {
                    "bankkonto": bank_account,
                    "kontakt": _get_contract_contact_for_customer(mv, customer),
                },
            )
            mv.save(ignore_permissions=True)
            updated += 1
        except Exception as exc:
            errors.append({"mietvertrag": mv_name, "error": str(exc)})
            frappe.log_error(
                frappe.get_traceback(),
                f"Bankauszug Import: Bankkonto-Link zu Mietvertrag fehlgeschlagen ({mv_name})",
            )

    return {"updated": updated, "unchanged": unchanged, "errors": errors}


def _get_row_by_name(doc: Document, row_name: str) -> Document:
    for row in doc.get("rows") or []:
        if row.name == row_name:
            return row
    frappe.throw(f"Zeile {row_name} wurde im Dokument {doc.name} nicht gefunden.")


def _get_bt_party_fieldnames(meta) -> Tuple[Optional[str], Optional[str]]:
    present = {d.fieldname for d in meta.fields}
    return (
        "party_type" if "party_type" in present else None,
        "party" if "party" in present else None,
    )


def _resolve_row_party(row: Document) -> Optional[Tuple[str, str]]:
    party_tuple = _get_party_by_iban(getattr(row, "iban", None))
    if party_tuple:
        return party_tuple
    if getattr(row, "party_type", None) in SUPPORTED_PARTY_TYPES and getattr(row, "party", None):
        return (row.party_type, row.party)
    return None


def _get_row_bank_transaction_name(row: Document) -> Optional[str]:
    bt_name = getattr(row, "bank_transaction", None) or getattr(row, "reference", None)
    if not bt_name:
        return None
    try:
        return bt_name if frappe.db.exists("Bank Transaction", bt_name) else None
    except Exception:
        return None


def _set_row_payment_document(row: Document, payment_document_type: str, payment_document: str) -> None:
    row.db_set("payment_document_type", payment_document_type)
    row.db_set("payment_document", payment_document)


def _row_set(row: Document, fieldname: str, value: Any) -> None:
    if hasattr(row, "db_set"):
        row.db_set(fieldname, value)
    else:
        setattr(row, fieldname, value)


def _doc_field(row: Document, fieldname: str, default=None):
    return row.get(fieldname, default) if hasattr(row, "get") else getattr(row, fieldname, default)


def _resolve_row_party_for_validation(row: Document) -> Optional[Tuple[str, str]]:
    return _resolve_row_party(row)


def _collect_rows_missing_party(doc: Document) -> List[Dict[str, Any]]:
    missing: List[Dict[str, Any]] = []
    for row in doc.get("rows") or []:
        party_tuple = _resolve_row_party_for_validation(row)
        if party_tuple:
            continue
        reason = "no_party_mapping"
        if not getattr(row, "iban", None) and not getattr(row, "party", None):
            reason = "missing_iban_and_party"
        elif getattr(row, "party_type", None) and not getattr(row, "party", None):
            reason = "party_type_without_party"
        elif getattr(row, "party", None) and getattr(row, "party_type", None) not in SUPPORTED_PARTY_TYPES:
            reason = "invalid_party_type"
        missing.append(
            {
                "row": getattr(row, "name", None),
                "buchungstag": str(getattr(row, "buchungstag", "") or ""),
                "betrag": getattr(row, "betrag", None),
                "iban": getattr(row, "iban", None),
                "reason": reason,
            }
        )
    return missing


def _throw_if_missing_party_rows(doc: Document) -> None:
    missing = _collect_rows_missing_party(doc)
    if not missing:
        return

    preview_limit = 12
    preview = missing[:preview_limit]
    lines = []
    for item in preview:
        lines.append(
            f"Zeile {item.get('row')} | Datum {item.get('buchungstag') or '-'} | "
            f"Betrag {item.get('betrag') or '-'} | IBAN {item.get('iban') or '-'} | "
            f"Grund {item.get('reason')}"
        )
    if len(missing) > preview_limit:
        lines.append(f"... und {len(missing) - preview_limit} weitere")

    msg = (
        f"Bank Transaktionen erstellt nicht: {len(missing)} Zeilen ohne Party.\n\n"
        + "\n".join(lines)
        + "\n\nBitte Party zuordnen oder Bankkonto mit passender IBAN anlegen und danach erneut starten."
    )
    frappe.throw(msg)


def _build_missing_party_warning_payload(doc: Document) -> Optional[Dict[str, Any]]:
    missing = _collect_rows_missing_party(doc)
    if not missing:
        return None

    preview_limit = 12
    preview = missing[:preview_limit]
    lines = []
    for item in preview:
        lines.append(
            f"Zeile {item.get('row')} | Datum {item.get('buchungstag') or '-'} | "
            f"Betrag {item.get('betrag') or '-'} | IBAN {item.get('iban') or '-'} | "
            f"Grund {item.get('reason')}"
        )
    if len(missing) > preview_limit:
        lines.append(f"... und {len(missing) - preview_limit} weitere")

    return {
        "requires_confirmation": True,
        "missing_count": len(missing),
        "preview_lines": lines,
        "message": (
            f"{len(missing)} Zeilen ohne Party gefunden.\n\n"
            + "\n".join(lines)
            + "\n\nSie können trotzdem fortfahren. In diesem Fall werden Bank Transaktionen ohne Party erstellt."
        ),
    }


def _update_bt_party_from_row(row: Document, *, overwrite: bool = True) -> Dict[str, Any]:
    bt_name = _get_row_bank_transaction_name(row)
    if not bt_name:
        return {"updated": False, "reason": "no_bank_transaction"}

    meta = frappe.get_meta("Bank Transaction")
    bt_party_type_field, bt_party_field = _get_bt_party_fieldnames(meta)
    if not bt_party_type_field or not bt_party_field:
        return {"updated": False, "reason": "bt_has_no_party_fields"}

    target_party = _resolve_row_party(row)
    if not target_party:
        return {"updated": False, "reason": "no_party_candidate"}
    target_party_type, target_party_name = target_party

    bt = frappe.get_doc("Bank Transaction", bt_name)
    current_party_type = getattr(bt, bt_party_type_field, None)
    current_party_name = getattr(bt, bt_party_field, None)

    if (
        str(current_party_type or "") == str(target_party_type)
        and str(current_party_name or "") == str(target_party_name)
    ):
        return {"updated": False, "reason": "unchanged"}

    if (not overwrite) and (current_party_type or current_party_name):
        return {"updated": False, "reason": "overwrite_disabled"}

    bt.db_set(bt_party_type_field, target_party_type, update_modified=False)
    bt.db_set(bt_party_field, target_party_name, update_modified=False)
    return {
        "updated": True,
        "bank_transaction": bt.name,
        "from_party_type": current_party_type,
        "from_party": current_party_name,
        "to_party_type": target_party_type,
        "to_party": target_party_name,
    }


def _set_bt_party(
    row: Document,
    party_type: Optional[str],
    party: Optional[str],
    *,
    clear: bool = False,
) -> Dict[str, Any]:
    bt_name = _get_row_bank_transaction_name(row)
    if not bt_name:
        return {"updated": False, "reason": "no_bank_transaction"}

    meta = frappe.get_meta("Bank Transaction")
    bt_party_type_field, bt_party_field = _get_bt_party_fieldnames(meta)
    if not bt_party_type_field or not bt_party_field:
        return {"updated": False, "reason": "bt_has_no_party_fields"}

    bt = frappe.get_doc("Bank Transaction", bt_name)
    current_party_type = getattr(bt, bt_party_type_field, None)
    current_party_name = getattr(bt, bt_party_field, None)
    target_party_type = None if clear else party_type
    target_party_name = None if clear else party

    if (
        str(current_party_type or "") == str(target_party_type or "")
        and str(current_party_name or "") == str(target_party_name or "")
    ):
        return {"updated": False, "reason": "unchanged", "bank_transaction": bt.name}

    bt.db_set(bt_party_type_field, target_party_type, update_modified=False)
    bt.db_set(bt_party_field, target_party_name, update_modified=False)
    return {
        "updated": True,
        "bank_transaction": bt.name,
        "from_party_type": current_party_type,
        "from_party": current_party_name,
        "to_party_type": target_party_type,
        "to_party": target_party_name,
    }


def _decode_file(file_url: str, encoding: str = "auto") -> str:
    if not file_url:
        frappe.throw("Bitte zuerst eine CSV-Datei hochladen.")
    file_name = frappe.get_value("File", {"file_url": file_url}, "name")
    if not file_name:
        frappe.throw("Datei nicht gefunden. Bitte speichern Sie das Dokument nach dem Hochladen und versuchen Sie es erneut.")
    file_doc = frappe.get_doc("File", file_name)
    content = file_doc.get_content()
    if isinstance(content, bytes):
        if encoding == "auto":
            for enc in ("utf-8", "latin-1", "cp1252"):
                try:
                    return content.decode(enc)
                except Exception:
                    continue
            return content.decode("utf-8", errors="ignore")
        return content.decode(encoding, errors="ignore")
    return content


def _sniff_delimiter(sample: str, preferred: str | None) -> str:
    if preferred and preferred.strip():
        return preferred
    try:
        dialect = csv.Sniffer().sniff(sample)
        return dialect.delimiter
    except Exception:
        return ";"


def _normalize_header(h: str) -> str:
    return (h or "").strip().strip("\ufeff").replace("\xa0", " ")


def _map_headers(headers: List[str]) -> Dict[str, int]:
    idx = {}
    norm = [_normalize_header(h) for h in headers]
    for key, options in RELEVANT_HEADERS.items():
        for opt in options:
            if opt in norm:
                idx[key] = norm.index(opt)
                break
    return idx


def _parse_decimal(x: str) -> float:
    """Wandelt deutsche Zahlenformate (1.234,56) in float um. 0.0 bei Fehler."""
    if not x:
        return 0.0
    x = x.replace(".", "").replace(",", ".").replace(" ", "")
    try:
        return float(x)
    except Exception:
        return 0.0


def _find_existing_bank_transaction(
    *,
    bank_account: str,
    buchungstag,
    betrag: float,
    richtung: Optional[str],
    iban: Optional[str] = None,
    verwendungszweck: Optional[str] = None,
) -> Optional[str]:
    """Findet eine bereits existierende Bank Transaction die zu den gegebenen
    CSV-Werten passt. Match-Strategie:

    1. Bank-Konto + Datum + Betrag (Eingang/Ausgang) — Pflicht
    2. Wenn IBAN vorhanden: zusätzlich ``bank_party_iban`` als Filter (sehr stark)
    3. Wenn ein Verwendungszweck vorhanden ist: bei mehreren oder abweichend
       beschriebenen Treffern nur eine Bank Transaction mit gleichem
       Verwendungszweck akzeptieren.

    Returns Name der BT oder None.
    """
    if not bank_account or not buchungstag or not betrag:
        return None
    try:
        meta = frappe.get_meta("Bank Transaction")
        fieldnames = {d.fieldname for d in meta.fields}
    except Exception:
        return None

    filters: Dict[str, Any] = {"bank_account": bank_account, "docstatus": ["<", 2]}

    # Datum
    for date_field in ("date", "posting_date", "transaction_date"):
        if date_field in fieldnames:
            filters[date_field] = buchungstag
            break

    # Betrag
    abs_betrag = abs(flt(betrag))
    if "deposit" in fieldnames and "withdrawal" in fieldnames:
        if richtung == "Eingang":
            filters["deposit"] = abs_betrag
        else:
            filters["withdrawal"] = abs_betrag
    elif "amount" in fieldnames:
        signed = abs_betrag if richtung == "Eingang" else -abs_betrag
        filters["amount"] = signed

    # IBAN als Verfeinerung (wenn vorhanden) — verhindert False-Positives
    iban_norm = _normalize_iban(iban)
    if iban_norm and "bank_party_iban" in fieldnames:
        filters["bank_party_iban"] = iban_norm

    try:
        fields = ["name"]
        if "description" in fieldnames:
            fields.append("description")
        existing = frappe.get_all(
            "Bank Transaction",
            filters=filters,
            fields=fields,
            limit=50,
            order_by="creation asc",
        )
        if not existing:
            return None

        purpose = (verwendungszweck or "").strip()
        if purpose and "description" in fieldnames:
            exact = [
                row
                for row in existing
                if (row.get("description") or "").strip() == purpose
            ]
            if exact:
                return exact[0].get("name")

            # Same date/amount/IBAN but different purpose: this is not a
            # duplicate. Example: two monthly rents posted on the same day.
            if len(existing) > 1 or (existing[0].get("description") or "").strip():
                return None

        return existing[0].get("name")
    except Exception:
        return None


def _extract_csv_kontostand_opening(possible: list) -> Optional[float]:
    """Eröffnungssaldo aus der Preamble — Postbank: ``Letzter Kontostand;;;;33.797,61;EUR``.

    "Letzter Kontostand" in Postbank-Sprech bedeutet: *der zuletzt bekannte
    Saldo bevor diese Periode begann* — also der Eröffnungssaldo. Wird nur als
    Fallback verwendet, falls die Footer-Zeile fehlt.
    """
    if not possible:
        return None
    first = _normalize_header(possible[0]).lower()
    if "letzter kontostand" not in first:
        return None
    for cell in possible[1:]:
        val = _parse_decimal(str(cell))
        if val:
            return val
    return None


def _extract_csv_kontostand_closing(raw: list) -> Optional[Tuple[float, Optional[str]]]:
    """Schluss-Saldo aus der Footer-Zeile — Postbank: ``Kontostand;5.5.2026;;;45.235,83;EUR``.

    Erste Spalte ist exakt ``Kontostand`` (ohne Präfix). Eine der nachfolgenden
    Spalten enthält das Stichtags-Datum (dd.mm.yyyy), eine andere den Betrag.
    Liefert ``(betrag, datum_iso)`` oder ``None`` wenn die Zeile nicht passt.
    """
    if not raw:
        return None
    first = _normalize_header(raw[0]).lower()
    # Genauer Match: nur "Kontostand" allein, NICHT "Letzter Kontostand" o.Ä.
    if first != "kontostand":
        return None
    datum_iso: Optional[str] = None
    betrag: Optional[float] = None
    for cell in raw[1:]:
        s = str(cell).strip()
        if not s:
            continue
        # Erst Datum versuchen — sonst parst _parse_decimal "5.5.2026" als 552026.
        if datum_iso is None:
            parsed_date = None
            for fmt in ("%d.%m.%Y", "%d.%m.%y"):
                try:
                    parsed_date = datetime.strptime(s, fmt).date()
                    break
                except Exception:
                    continue
            if parsed_date is not None:
                datum_iso = parsed_date.isoformat()
                continue
        if betrag is None:
            val = _parse_decimal(s)
            if val:
                betrag = val
    if betrag is None:
        return None
    return betrag, datum_iso


def reextract_saldo_from_csv(doc) -> Dict[str, Any]:
    """Liest Saldo + Datum aus der CSV erneut, ohne Rows anzufassen.

    Nutzbar von Patches, die historische Bankauszug-Imports nachträglich
    korrigieren wollen, die mit dem alten (falschen) Parser angelegt wurden
    und als ``saldo_laut_csv`` den Eröffnungssaldo statt den Schluss-Saldo
    halten.

    Returns ``{closing, opening, datum, applied}``. ``applied=False`` wenn
    keine CSV-Datei verlinkt ist oder die Datei nicht gelesen werden kann.
    """
    if not doc.get("csv_file"):
        return {"applied": False, "reason": "no_csv_file"}
    try:
        text = _decode_file(doc.csv_file, doc.encoding)
    except Exception as exc:
        return {"applied": False, "reason": f"decode_error: {exc}"}
    delimiter = _sniff_delimiter(text[:2048], doc.delimiter)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    csv_opening: Optional[float] = None
    csv_closing: Optional[float] = None
    csv_closing_datum: Optional[str] = None
    header_seen = False
    latest_buchungstag: Optional[str] = None

    for raw in reader:
        if not raw or (len(raw) == 1 and not raw[0].strip()):
            continue
        if not header_seen:
            ks = _extract_csv_kontostand_opening(raw)
            if ks is not None:
                csv_opening = ks
                continue
            tmp_map = _map_headers(raw)
            if "buchungstag" in tmp_map and (
                "betrag" in tmp_map or "soll" in tmp_map or "haben" in tmp_map
            ):
                header_seen = True
                header_map = tmp_map
                continue
        else:
            closing = _extract_csv_kontostand_closing(raw)
            if closing is not None:
                csv_closing, csv_closing_datum = closing
                break
            # Buchungstag mitschneiden für Fallback-Datum
            i = header_map.get("buchungstag")
            if i is not None and i < len(raw) and raw[i].strip():
                cell = raw[i].strip()
                for fmt in ("%d.%m.%Y", "%d.%m.%y"):
                    try:
                        d = datetime.strptime(cell, fmt).date().isoformat()
                        if (latest_buchungstag is None) or d > latest_buchungstag:
                            latest_buchungstag = d
                        break
                    except Exception:
                        continue

    saldo_value = csv_closing if csv_closing is not None else csv_opening
    if saldo_value is None:
        return {"applied": False, "reason": "no_kontostand_found"}

    doc.saldo_laut_csv = saldo_value
    if csv_closing_datum:
        doc.saldo_datum = csv_closing_datum
    elif latest_buchungstag and not doc.get("saldo_datum"):
        doc.saldo_datum = latest_buchungstag
    return {
        "applied": True,
        "closing": csv_closing,
        "opening": csv_opening,
        "datum": csv_closing_datum,
    }


@frappe.whitelist()
def parse_csv(docname: str) -> Dict[str, Any]:
    doc = frappe.get_doc("Bankauszug Import", docname)
    text = _decode_file(doc.csv_file, doc.encoding)
    sample = text[:2048]
    delimiter = _sniff_delimiter(sample, doc.delimiter)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    # Find the actual header row: skip bank preamble until a row contains required headers.
    # In der Preamble steht oft ein "Letzter Kontostand" — das ist Postbank-Sprech
    # für den Eröffnungssaldo, nicht den Schluss-Saldo. Wir merken ihn nur als
    # Fallback; den echten Schluss-Saldo holen wir aus der Footer-Zeile.
    header_map = {}
    headers = None
    csv_opening: Optional[float] = None
    for possible in reader:
        # skip empty or 1-col lines like "Umsätze" or date range
        if not possible or (len(possible) == 1 and not possible[0].strip()):
            continue
        ks = _extract_csv_kontostand_opening(possible)
        if ks is not None:
            csv_opening = ks
            continue
        # Normalize and try mapping
        tmp_map = _map_headers(possible)
        if "buchungstag" in tmp_map and (
            "betrag" in tmp_map or "soll" in tmp_map or "haben" in tmp_map
        ):
            header_map = tmp_map
            headers = possible
            break
    if not headers:
        frappe.throw("CSV muss mindestens eine Betrags-Spalte (Betrag/Soll/Haben) enthalten.")
    csv_closing: Optional[float] = None
    csv_closing_datum: Optional[str] = None

    # Validate other required fields (IBAN is optional in some lines, don't hard-fail here)
    rows = []
    party_cache: Dict[str, Optional[Tuple[str, str]]] = {}
    for raw in reader:
        if not any(raw):
            continue
        # Footer-Zeile "Kontostand;<datum>;;;<betrag>;EUR" = Schluss-Saldo. Wert
        # mitnehmen, dann Daten-Loop beenden.
        closing = _extract_csv_kontostand_closing(raw)
        if closing is not None:
            csv_closing, csv_closing_datum = closing
            break
        def getcol(key, default=""):
            i = header_map.get(key)
            return raw[i].strip() if i is not None and i < len(raw) else default

        buchungstag = getcol("buchungstag")
        betrag_txt = getcol("betrag")
        soll_txt = getcol("soll")
        haben_txt = getcol("haben")
        iban = getcol("iban")
        auftraggeber = getcol("auftraggeber")
        verwendungszweck = getcol("verwendungszweck")
        waehrung = getcol("waehrung", "EUR") or "EUR"

        party_type = None
        party = None
        iban_norm = _normalize_iban(iban)
        if iban_norm:
            if iban_norm not in party_cache:
                party_cache[iban_norm] = _get_party_by_iban(iban)
            party_tuple = party_cache.get(iban_norm)
            if party_tuple:
                party_type, party = party_tuple

        # parse amount and direction
        betrag = None
        richtung = None
        def parse_decimal(x: str) -> float:
            if not x:
                return 0.0
            x = x.replace(".", "").replace(",", ".").replace(" ", "")
            try:
                return float(x)
            except Exception:
                return 0.0

        if betrag_txt:
            amt = parse_decimal(betrag_txt)
            if amt < 0:
                betrag = abs(amt)
                richtung = "Ausgang"
            else:
                betrag = amt
                richtung = "Eingang"
        else:
            s = parse_decimal(soll_txt)
            h = parse_decimal(haben_txt)
            if s and not h:
                betrag = s
                richtung = "Ausgang"
            elif h and not s:
                betrag = h
                richtung = "Eingang"

        error = None
        # Datum parsen. Wichtig: deutsches Format dd.mm.yyyy (mit oder ohne
        # führende Nullen) ZUERST versuchen — getdate() bzw. dateutil parsen
        # ohne dayfirst-Hint und würden "4.12.2025" als 12. April lesen.
        parsed_date = None
        if buchungstag:
            s = buchungstag.strip()
            for fmt in ("%d.%m.%Y", "%d.%m.%y"):
                try:
                    parsed_date = datetime.strptime(s, fmt).date()
                    break
                except Exception:
                    continue
            if not parsed_date:
                # Fallback für ISO (yyyy-mm-dd) o.ä.
                try:
                    parsed_date = getdate(s)
                except Exception:
                    parsed_date = None
        if not parsed_date:
            error = "Ungültiges Datum"
        if not betrag or betrag == 0:
            error = error or "Betrag fehlt"
    # IBAN ist hilfreich, aber nicht immer vorhanden (z.B. Bargeld). Kein Hard-Error.

        # Bereits importierte BT erkennen — direkt beim Parsen, damit der User
        # in der Vorschau sofort sieht welche Zeilen schon im System sind.
        existing_bt = None
        existing_status = None
        if doc.bank_account and parsed_date and betrag and not error:
            existing_bt = _find_existing_bank_transaction(
                bank_account=doc.bank_account,
                buchungstag=parsed_date,
                betrag=betrag,
                richtung=richtung,
                iban=iban,
                verwendungszweck=verwendungszweck,
            )
            if existing_bt:
                existing_status = "schon vorhanden"

        rows.append({
            "doctype": "Bankauszug Import Row",
            "buchungstag": parsed_date,
            "betrag": betrag,
            "richtung": richtung,
            "iban": iban,
            "party_type": party_type,
            "party": party,
            "auftraggeber": auftraggeber,
            "verwendungszweck": verwendungszweck,
            "currency": waehrung,
            "error": error,
            "bank_transaction": existing_bt,
            "reference": existing_bt,
            "row_status": existing_status,
        })

    # replace child table
    doc.set("rows", [])
    for r in rows:
        doc.append("rows", r)

    # Saldo-Felder aus CSV. Reihenfolge:
    #   1. Footer "Kontostand;<datum>;;;<betrag>" = echter Schluss-Saldo (bevorzugt).
    #   2. Preamble "Letzter Kontostand" = Eröffnungssaldo, nur als Fallback wenn
    #      Footer fehlt — besser als nichts, ist aber semantisch der Anfangswert
    #      und wird zu einer Differenz gegen den ERP-Saldo führen.
    saldo_value = csv_closing if csv_closing is not None else csv_opening
    if saldo_value is not None:
        doc.saldo_laut_csv = saldo_value
    if csv_closing_datum:
        doc.saldo_datum = csv_closing_datum
    else:
        parsed_dates = [r.get("buchungstag") for r in rows if r.get("buchungstag")]
        if parsed_dates:
            doc.saldo_datum = max(parsed_dates)

    doc.save()
    _recompute_doc_status(doc.name)
    return {"rows": rows, "count": len(rows), "saldo_laut_csv": saldo_value}


@frappe.whitelist()
def create_party_and_bank_for_row(
    docname: str,
    row_name: str,
    party_type: str,
    party_name: Optional[str] = None,
) -> Dict[str, Any]:
    doc = frappe.get_doc("Bankauszug Import", docname)
    if not frappe.has_permission("Bankauszug Import", "write", doc=doc):
        frappe.throw("Keine Berechtigung zum Bearbeiten dieses Bankauszug Imports.")
    if party_type not in ("Customer", "Supplier"):
        frappe.throw("Party Typ muss Mieter oder Supplier sein.")

    row = _get_row_by_name(doc, row_name)
    name_input = (party_name or row.auftraggeber or row.verwendungszweck or "").strip()
    if not name_input:
        frappe.throw("Kein Name vorhanden. Bitte Name im Dialog eingeben.")

    party, party_created = _create_party_if_missing(party_type, name_input)
    bank_account, bank_created = _get_or_create_party_bank_account(
        party_type=party_type,
        party=party,
        iban=row.iban,
    )
    mietvertrag_links = {}
    if party_type == "Customer" and bank_account:
        mietvertrag_links = _link_customer_bank_account_to_mietvertraege(party, bank_account)

    row.party_type = party_type
    row.party = party
    if getattr(row, "error", None):
        row.error = None
    doc.save(ignore_permissions=True)
    _recompute_doc_status(doc.name)

    return {
        "party_type": party_type,
        "party": party,
        "party_created": party_created,
        "bank_account": bank_account,
        "bank_account_created": bank_created,
        "mietvertrag_links": mietvertrag_links,
    }


@frappe.whitelist()
def relink_parties_for_all_rows(docname: str, overwrite: int = 1) -> Dict[str, Any]:
    doc = frappe.get_doc("Bankauszug Import", docname)
    if not frappe.has_permission("Bankauszug Import", "write", doc=doc):
        frappe.throw("Keine Berechtigung zum Bearbeiten dieses Bankauszug Imports.")

    processed = 0
    updated = 0
    row_updated = 0
    unchanged = 0
    skipped = 0
    skipped_rows = []
    errors = []
    changes = []
    row_updates = False

    for row in doc.get("rows") or []:
        processed += 1
        try:
            # Keep row view in sync with the mapping candidate.
            row_target = _resolve_row_party(row)
            if row_target and (row.party_type != row_target[0] or row.party != row_target[1]):
                row.party_type = row_target[0]
                row.party = row_target[1]
                row_updates = True
                row_updated += 1

            upd = _update_bt_party_from_row(row, overwrite=bool(int(overwrite or 0)))
            if upd.get("updated"):
                updated += 1
                changes.append(
                    {
                        "row": row.name,
                        "bank_transaction": upd.get("bank_transaction"),
                        "from_party_type": upd.get("from_party_type"),
                        "from_party": upd.get("from_party"),
                        "to_party_type": upd.get("to_party_type"),
                        "to_party": upd.get("to_party"),
                    }
                )
                continue

            reason = upd.get("reason")
            if reason == "unchanged" or reason == "overwrite_disabled":
                unchanged += 1
            else:
                skipped += 1
                skipped_rows.append({"row": row.name, "reason": reason or "skipped"})
        except Exception:
            errors.append({"row": row.name, "error": frappe.get_traceback()})

    if row_updates:
        doc.save(ignore_permissions=True)

    _recompute_doc_status(docname)

    return {
        "processed": processed,
        "updated": updated,
        "row_updated": row_updated,
        "unchanged": unchanged,
        "skipped": skipped,
        "skipped_rows": skipped_rows,
        "errors": errors,
        "changes": changes,
    }


@frappe.whitelist()
def apply_party_to_row_and_relink(
    docname: str,
    row_name: str,
    party_type: Optional[str] = None,
    party: Optional[str] = None,
    iban: Optional[str] = None,
) -> Dict[str, Any]:
    doc = frappe.get_doc("Bankauszug Import", docname)
    if not frappe.has_permission("Bankauszug Import", "write", doc=doc):
        frappe.throw("Keine Berechtigung zum Bearbeiten dieses Bankauszug Imports.")

    row = _get_row_by_name(doc, row_name)
    changed_row = False

    # When called from Customer/Supplier auto-link with an IBAN, ensure a
    # Bank Account record exists for the party so the IBAN→party lookup works
    # for subsequent rows / future imports without manual setup.
    bank_account_info: Dict[str, Any] = {}
    iban_for_link = (iban or row.iban or "").strip()
    if party_type in SUPPORTED_PARTY_TYPES and party and iban_for_link:
        try:
            ba_name, ba_created = _get_or_create_party_bank_account(
                party_type=party_type, party=party, iban=iban_for_link
            )
            bank_account_info = {"bank_account": ba_name, "created": ba_created}
            if party_type == "Customer" and ba_name:
                bank_account_info["mietvertrag_links"] = _link_customer_bank_account_to_mietvertraege(
                    party, ba_name
                )
        except Exception as exc:
            bank_account_info = {"error": str(exc)}

    if party_type in SUPPORTED_PARTY_TYPES and party:
        if row.party_type != party_type or row.party != party:
            row.party_type = party_type
            row.party = party
            changed_row = True

    # Also refresh row party from IBAN mapping if available.
    row_target = _resolve_row_party(row)
    if row_target and (row.party_type != row_target[0] or row.party != row_target[1]):
        row.party_type = row_target[0]
        row.party = row_target[1]
        changed_row = True

    if changed_row:
        doc.save(ignore_permissions=True)

    upd = _update_bt_party_from_row(row, overwrite=True)

    # Now propagate the (possibly newly created) party/bank-account match to all
    # other rows in the document — every row whose IBAN now resolves to a party
    # via Bank Account gets its party_type/party + Bank Transaction party updated.
    # Non-destructive: existing matches are kept; only previously-unmatched rows
    # are touched. Skipped on errors so the primary row update isn't blocked.
    relink_all_count = 0
    relink_bt_count = 0
    try:
        any_change = False
        for other in doc.get("rows") or []:
            if other.name == row.name:
                continue
            target = _resolve_row_party(other)
            if target and (other.party_type != target[0] or other.party != target[1]):
                other.party_type = target[0]
                other.party = target[1]
                any_change = True
                relink_all_count += 1
            try:
                bt_upd = _update_bt_party_from_row(other, overwrite=True)
                if bt_upd.get("updated"):
                    relink_bt_count += 1
            except Exception:
                pass
        if any_change:
            doc.save(ignore_permissions=True)
    except Exception:
        pass

    _recompute_doc_status(docname)

    return {
        "row": row.name,
        "row_party_type": row.party_type,
        "row_party": row.party,
        "relink": upd,
        "bank_account": bank_account_info,
        "relink_all_count": relink_all_count,
        "relink_bt_count": relink_bt_count,
    }


def _linked_voucher_for_row(row: Document) -> Tuple[Optional[str], Optional[str]]:
    voucher_type = _doc_field(row, "payment_document_type")
    voucher_name = _doc_field(row, "payment_document")
    if voucher_type in ("Payment Entry", "Journal Entry") and voucher_name:
        return voucher_type, voucher_name
    if _doc_field(row, "payment_entry"):
        return "Payment Entry", _doc_field(row, "payment_entry")
    if _doc_field(row, "journal_entry"):
        return "Journal Entry", _doc_field(row, "journal_entry")
    return None, None


def _cancel_voucher_for_row(voucher_type: str, voucher_name: str) -> Dict[str, Any]:
    docstatus = frappe.db.get_value(voucher_type, voucher_name, "docstatus")
    if docstatus is None:
        return {"voucher_type": voucher_type, "voucher": voucher_name, "status": "missing"}

    try:
        docstatus_int = int(docstatus)
    except Exception:
        docstatus_int = docstatus

    if docstatus_int == 2:
        return {"voucher_type": voucher_type, "voucher": voucher_name, "status": "already_cancelled"}

    voucher = frappe.get_doc(voucher_type, voucher_name)
    if docstatus_int == 1:
        voucher.flags.ignore_permissions = True
        voucher.cancel()
        return {"voucher_type": voucher_type, "voucher": voucher_name, "status": "cancelled"}

    return {"voucher_type": voucher_type, "voucher": voucher_name, "status": "not_submitted"}


def _clear_row_booking_links(row: Document, message: str) -> None:
    for fieldname in (
        "payment_entry",
        "journal_entry",
        "payment_document_type",
        "payment_document",
    ):
        _row_set(row, fieldname, None)
    if not _doc_field(row, "error"):
        _row_set(row, "row_status", None)
    _row_set(row, "auto_match_message", message)


@frappe.whitelist()
def reset_row_booking(docname: str, row_name: str) -> Dict[str, Any]:
    doc = frappe.get_doc("Bankauszug Import", docname)
    if not frappe.has_permission("Bankauszug Import", "write", doc=doc):
        frappe.throw("Keine Berechtigung zum Bearbeiten dieses Bankauszug Imports.")

    row = _get_row_by_name(doc, row_name)
    voucher_type, voucher_name = _linked_voucher_for_row(row)
    if not voucher_type or not voucher_name:
        return {"ok": True, "reset": False, "reason": "no_voucher"}

    from hausverwaltung.hausverwaltung.utils.bank_transaction_links import (
        remove_bank_transaction_payment_links,
    )

    cancel_result = _cancel_voucher_for_row(voucher_type, voucher_name)
    delinked_bank_transactions = remove_bank_transaction_payment_links(voucher_type, voucher_name)
    _clear_row_booking_links(
        row,
        f"Zurückgesetzt: {voucher_type} {voucher_name} wurde storniert.",
    )

    _recompute_doc_status(docname)
    _refresh_and_persist_saldo(docname)
    return {
        "ok": True,
        "reset": True,
        "voucher_type": voucher_type,
        "voucher": voucher_name,
        "cancel": cancel_result,
        "delinked_bank_transactions": delinked_bank_transactions,
    }


def unlink_party_bank_account_for_row(
    row: Document,
    party_type: Optional[str],
    party: Optional[str],
) -> Dict[str, Any]:
    iban_norm = _normalize_iban(_doc_field(row, "iban"))
    if not iban_norm or not party_type or not party:
        return {"updated": 0, "bank_accounts": []}

    accounts = frappe.get_all(
        "Bank Account",
        filters={
            "iban": ("in", [iban_norm, _doc_field(row, "iban")]),
            "party_type": party_type,
            "party": party,
        },
        fields=["name", "is_company_account"],
        limit=50,
    )
    updated = []
    for account in accounts:
        if account.get("is_company_account"):
            continue
        try:
            bank_doc = frappe.get_doc("Bank Account", account.get("name"))
            bank_doc.party_type = None
            bank_doc.party = None
            if hasattr(bank_doc, "is_company_account"):
                bank_doc.is_company_account = 0
            bank_doc.save(ignore_permissions=True)
            updated.append(bank_doc.name)
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Bankauszug Import: Bankkonto-Party-Link entfernen fehlgeschlagen ({account.get('name')})",
            )
    return {"updated": len(updated), "bank_accounts": updated}


def _row_is_unbooked(row: Document) -> bool:
    voucher_type, voucher_name = _linked_voucher_for_row(row)
    return not voucher_type and not voucher_name


@frappe.whitelist()
def change_row_party(
    docname: str,
    row_name: str,
    party_type: Optional[str] = None,
    party: Optional[str] = None,
    clear_party: int = 0,
    update_iban_mapping: int = 0,
    propagate_same_iban: int = 0,
    create_if_missing: int = 0,
) -> Dict[str, Any]:
    doc = frappe.get_doc("Bankauszug Import", docname)
    if not frappe.has_permission("Bankauszug Import", "write", doc=doc):
        frappe.throw("Keine Berechtigung zum Bearbeiten dieses Bankauszug Imports.")

    row = _get_row_by_name(doc, row_name)
    old_party_type = _doc_field(row, "party_type")
    old_party = _doc_field(row, "party")
    clear = bool(int(clear_party or 0))

    if not clear:
        if party_type not in SUPPORTED_PARTY_TYPES or not party:
            frappe.throw("Bitte eine gültige Partei auswählen.")
        if not frappe.db.exists(party_type, party):
            if bool(int(create_if_missing or 0)) and party_type in ("Customer", "Supplier"):
                party, party_created = _create_party_if_missing(party_type, party)
            else:
                frappe.throw(f"{party_type} {party} wurde nicht gefunden.")
        else:
            party_created = False
    else:
        party_created = False

    reset = reset_row_booking(docname, row_name)
    if reset.get("reset"):
        doc = frappe.get_doc("Bankauszug Import", docname)
        row = _get_row_by_name(doc, row_name)

    bank_account_unlink = {"updated": 0, "bank_accounts": []}
    bank_account_link = {}
    if bool(int(update_iban_mapping or 0)):
        bank_account_unlink = unlink_party_bank_account_for_row(row, old_party_type, old_party)
        if not clear:
            ba_name, ba_created = _get_or_create_party_bank_account(
                party_type=party_type,
                party=party,
                iban=_doc_field(row, "iban"),
            )
            bank_account_link = {"bank_account": ba_name, "created": ba_created}
            if party_type == "Customer" and ba_name:
                bank_account_link["mietvertrag_links"] = _link_customer_bank_account_to_mietvertraege(
                    party, ba_name
                )

    _row_set(row, "party_type", None if clear else party_type)
    _row_set(row, "party", None if clear else party)
    if not _doc_field(row, "error"):
        _row_set(row, "row_status", None)
    _row_set(
        row,
        "auto_match_message",
        "Partei entfernt." if clear else f"Partei geändert: {party_type} {party}",
    )
    bt_update = _set_bt_party(row, None if clear else party_type, None if clear else party, clear=clear)

    propagated_rows = []
    propagation_skipped = None
    if (
        not clear
        and bool(int(propagate_same_iban or 0))
        and _normalize_iban(_doc_field(row, "iban"))
    ):
        resolved = _get_party_by_iban(_doc_field(row, "iban"))
        if resolved == (party_type, party):
            iban_norm = _normalize_iban(_doc_field(row, "iban"))
            for other in doc.get("rows") or []:
                if other.name == row.name:
                    continue
                if _normalize_iban(_doc_field(other, "iban")) != iban_norm:
                    continue
                if not _row_is_unbooked(other):
                    continue
                if _doc_field(other, "party_type") == party_type and _doc_field(other, "party") == party:
                    continue
                _row_set(other, "party_type", party_type)
                _row_set(other, "party", party)
                if not _doc_field(other, "error"):
                    _row_set(other, "row_status", None)
                bt_res = _set_bt_party(other, party_type, party)
                propagated_rows.append({
                    "row": other.name,
                    "bank_transaction": bt_res.get("bank_transaction"),
                    "bt_updated": bt_res.get("updated"),
                })
        else:
            propagation_skipped = "iban_not_unique"

    if hasattr(doc, "save"):
        doc.save(ignore_permissions=True)
    _recompute_doc_status(docname)
    _refresh_and_persist_saldo(docname)

    return {
        "ok": True,
        "row": row.name,
        "old_party_type": old_party_type,
        "old_party": old_party,
        "row_party_type": None if clear else party_type,
        "row_party": None if clear else party,
        "party_created": party_created,
        "reset": reset,
        "bank_transaction": bt_update,
        "bank_account_unlink": bank_account_unlink,
        "bank_account_link": bank_account_link,
        "propagated_rows": propagated_rows,
        "propagation_skipped": propagation_skipped,
    }


@frappe.whitelist()
def create_bank_transactions(docname: str, allow_missing_party: int = 0) -> Dict[str, Any]:
    doc = frappe.get_doc("Bankauszug Import", docname)
    if not doc.bank_account:
        frappe.throw("Bitte Bankkonto auswählen.")
    # get_doc (uncached): falls is_company_account zwischen Anlage und Aufruf
    # geaendert wurde, soll der aktuelle Stand gelesen werden, nicht der Cache.
    bank_account = frappe.get_doc("Bank Account", doc.bank_account)
    if hasattr(bank_account, "is_company_account") and not bank_account.is_company_account:
        frappe.throw("Bitte ein Firmen-Bankkonto auswählen (Bank Account mit 'Is Company Account' = 1).")

    warning = _build_missing_party_warning_payload(doc)
    if warning and not bool(int(allow_missing_party or 0)):
        return {
            "created": [],
            "errors": [],
            "warning": warning,
        }

    # Globaler Cutoff aus Hausverwaltung Einstellungen — CSV-Zeilen mit
    # buchungstag VOR diesem Datum werden übersprungen.
    bankimport_start_datum = None
    try:
        cutoff_raw = frappe.db.get_single_value(
            "Hausverwaltung Einstellungen", "bankimport_start_datum"
        )
        if cutoff_raw:
            bankimport_start_datum = getdate(cutoff_raw)
    except Exception:
        bankimport_start_datum = None

    created = []
    errors = []
    created_without_party = 0
    skipped_before_cutoff = 0
    auto_matched = []
    auto_abschlag_matched = []
    auto_kredit_matched = []
    auto_match_failed = []
    from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
        auto_match_bank_transaction,
    )

    # get meta and field names to be version-safe
    meta = frappe.get_meta("Bank Transaction")
    fieldnames = {d.fieldname for d in meta.fields}

    def set_if_exists(d, field, value):
        if field in fieldnames:
            d.set(field, value)

    def set_iban(d, iban_value: str):
        # Try common fieldnames first
        for fname in ("party_iban", "counterparty_iban", "bank_statement_party_iban", "iban"):
            if fname in fieldnames:
                d.set(fname, iban_value)
                return True
        # Fallback: match by label containing 'iban'
        try:
            for f in meta.fields:
                if getattr(f, "label", None) and "iban" in f.label.lower():
                    d.set(f.fieldname, iban_value)
                    return True
        except Exception:
            pass
        return False

    def find_duplicate(row_doc):
        return _find_existing_bank_transaction(
            bank_account=doc.bank_account,
            buchungstag=row_doc.buchungstag,
            betrag=row_doc.betrag,
            richtung=row_doc.richtung,
            iban=row_doc.iban,
            verwendungszweck=row_doc.verwendungszweck,
        )

    # Älteste Bank-Zeilen zuerst verarbeiten: damit beim anschließenden
    # Auto-Match (FIFO über offene Rechnungen, älteste zuerst) eine alte
    # Bank-Zahlung auch eine alte offene Rechnung erwischt — und nicht eine
    # spätere Bank-Zahlung der älteren Rechnung „dazwischenfunkt". Sekundär
    # nach idx (= CSV-Reihenfolge), um stabil zu bleiben.
    sorted_rows = sorted(
        doc.rows,
        key=lambda r: (
            getdate(r.buchungstag) if r.buchungstag else getdate("9999-12-31"),
            r.idx,
        ),
    )
    for row in sorted_rows:
        if row.error:
            errors.append({"row": row.name, "error": row.error})
            row.db_set("row_status", "failed")
            continue
        if row.bank_transaction:
            row.db_set("reference", row.bank_transaction)
            if not row.row_status:
                row.db_set("row_status", "schon vorhanden")
            continue

        # Globaler Cutoff: Buchungen vor dem konfigurierten Start-Datum überspringen
        if bankimport_start_datum and row.buchungstag and getdate(row.buchungstag) < bankimport_start_datum:
            skipped_before_cutoff += 1
            row.db_set("row_status", "vor Start-Datum")
            continue

        try:
            # skip if duplicate exists
            dup = find_duplicate(row)
            if dup:
                row.db_set("bank_transaction", dup)
                row.db_set("row_status", "schon vorhanden")
                row.db_set("reference", dup)
                continue

            bt = frappe.new_doc("Bank Transaction")
            bt.bank_account = doc.bank_account
            # set date
            if "date" in fieldnames:
                bt.date = row.buchungstag
            elif "posting_date" in fieldnames:
                bt.posting_date = row.buchungstag
            elif "transaction_date" in fieldnames:
                bt.transaction_date = row.buchungstag

            # set amount fields
            amt_abs_for_unalloc = 0.0
            if "amount" in fieldnames:
                amt = flt(row.betrag)
                bt.amount = abs(amt) if row.richtung == "Eingang" else -abs(amt)
                amt_abs_for_unalloc = abs(bt.amount)
            elif "deposit" in fieldnames and "withdrawal" in fieldnames:
                if row.richtung == "Eingang":
                    bt.deposit = flt(row.betrag)
                    bt.withdrawal = 0
                    amt_abs_for_unalloc = abs(bt.deposit)
                else:
                    bt.withdrawal = flt(row.betrag)
                    bt.deposit = 0
                    amt_abs_for_unalloc = abs(bt.withdrawal)

            # description/currency
            set_if_exists(bt, "description", row.verwendungszweck or row.auftraggeber)
            set_if_exists(bt, "currency", row.currency or "EUR")
            set_if_exists(bt, "bank_party_name", row.auftraggeber)
            # transaction_type if present
            if "transaction_type" in fieldnames:
                bt.transaction_type = "Deposit" if row.richtung == "Eingang" else "Withdrawal"

            # store IBAN on standard field (e.g., Party IBAN (Bank Statement))
            set_iban(bt, row.iban)
            set_if_exists(bt, "counterparty_name", row.auftraggeber)
            set_if_exists(bt, "reference_number", None)

            # set party by row selection, fallback to IBAN resolution
            if getattr(row, "party_type", None) and getattr(row, "party", None):
                set_if_exists(bt, "party_type", row.party_type)
                set_if_exists(bt, "party", row.party)
            else:
                party_tuple = _get_party_by_iban(row.iban)
                if party_tuple:
                    party_type, party = party_tuple
                    set_if_exists(bt, "party_type", party_type)
                    set_if_exists(bt, "party", party)
                else:
                    created_without_party += 1

            # mark as unreconciled if such fields exist
            set_if_exists(bt, "status", "Unreconciled")
            set_if_exists(bt, "reconciliation_status", "Unreconciled")
            set_if_exists(bt, "is_reconciled", 0)
            set_if_exists(bt, "reconciled", 0)
            if "unallocated_amount" in fieldnames and amt_abs_for_unalloc:
                bt.unallocated_amount = amt_abs_for_unalloc

            bt.insert(ignore_permissions=True)
            # submit if submittable
            try:
                if getattr(meta, "is_submittable", 0):
                    bt.submit()
            except Exception as submit_exc:
                error_msg = f"Bank Transaction konnte nicht eingereicht werden: {submit_exc}"
                try:
                    bt.delete(ignore_permissions=True)
                except Exception:
                    frappe.log_error(
                        frappe.get_traceback(),
                        f"Bankauszug Import: Draft Bank Transaction Cleanup fehlgeschlagen für {bt.name}",
                    )
                row.db_set("error", error_msg)
                row.db_set("row_status", "failed")
                errors.append({"row": row.name, "error": error_msg})
                frappe.log_error(
                    frappe.get_traceback(),
                    f"Bankauszug Import: Bank Transaction Submit fehlgeschlagen für {bt.name}",
                )
                continue
            row.db_set("bank_transaction", bt.name)
            row.db_set("row_status", "success")
            row.db_set("reference", bt.name)
            created.append(bt.name)

            # Auto-Match: versuche, exakt passende offene Rechnungen zu
            # finden und ein Payment Entry anzulegen. Schlägt der Match
            # fehl (kein/mehrdeutig/Teilbetrag), bleibt die BT unreconciled
            # und der User klickt manuell.
            try:
                match_result = auto_match_bank_transaction(bt.name)
                if match_result.get("matched"):
                    row.db_set("payment_entry", match_result.get("payment_entry"))
                    _set_row_payment_document(row, "Payment Entry", match_result.get("payment_entry"))
                    row.db_set("auto_match_message", match_result.get("message"))
                    auto_matched.append(bt.name)
                else:
                    row.db_set("auto_match_message", match_result.get("message"))

                    # Kreditraten-Match: vor dem Abschlagsplan-Fallback. Greift bei
                    # Ausgängen — Supplier ist optional (kann auch ohne Party matchen,
                    # solange Bankkonto + Betrag + Datum eindeutig sind).
                    if row.get("richtung") == "Ausgang":
                        try:
                            from hausverwaltung.hausverwaltung.doctype.kreditvertrag.kreditvertrag import (
                                link_bank_transaction_to_kreditvertrag_rate,
                            )
                            kredit_result = link_bank_transaction_to_kreditvertrag_rate(
                                bank_account=bt.bank_account,
                                posting_date=bt.date,
                                amount=row.get("betrag"),
                                bank_transaction=bt.name,
                                supplier=row.get("party") if row.get("party_type") == "Supplier" else None,
                                reference_text=row.get("verwendungszweck"),
                            )
                            if kredit_result and kredit_result.get("match_count") == 1:
                                je_name = kredit_result["journal_entry"]
                                row.db_set("journal_entry", je_name)
                                _set_row_payment_document(row, "Journal Entry", je_name)
                                row.db_set("row_status", "success")
                                if kredit_result.get("created_from_statement"):
                                    kredit_message = (
                                        f"Kreditrate aus Kontoauszug angelegt und gebucht: "
                                        f"{kredit_result['kreditvertrag']} Zeile {kredit_result['row_idx']} "
                                        f"→ {je_name}"
                                    )
                                else:
                                    kredit_message = (
                                        f"Kreditrate automatisch gebucht: "
                                        f"{kredit_result['kreditvertrag']} Zeile {kredit_result['row_idx']} "
                                        f"({kredit_result['gesamtbetrag']:.2f} €) → {je_name}"
                                    )
                                row.db_set(
                                    "auto_match_message",
                                    kredit_message,
                                )
                                auto_kredit_matched.append(bt.name)
                                continue
                            elif kredit_result and kredit_result.get("blocked"):
                                blocked_message = (
                                    kredit_result.get("message")
                                    or "Kreditrate nicht automatisch gebucht — bitte prüfen."
                                )
                                row.db_set("row_status", "needs_review")
                                row.db_set(
                                    "auto_match_message",
                                    blocked_message,
                                )
                                auto_match_failed.append({
                                    "row": row.name,
                                    "bank_transaction": bt.name,
                                    "reason": kredit_result.get("reason") or "kreditrate_blocked",
                                    "message": blocked_message,
                                })
                                continue
                            elif kredit_result and kredit_result.get("match_count", 0) > 1:
                                row.db_set(
                                    "auto_match_message",
                                    (
                                        f"{kredit_result['match_count']} mögliche Kreditraten — "
                                        "bitte manuell zuordnen (Aktion 'Kreditrate zuordnen')."
                                    ),
                                )
                        except Exception:
                            frappe.log_error(
                                frappe.get_traceback(),
                                f"Bankauszug Import: Kredit-Match fehlgeschlagen für {bt.name}",
                            )

                    if (
                        row.get("richtung") == "Ausgang"
                        and row.get("party_type") == "Supplier"
                        and match_result.get("reason") in ("no_open_invoices", "no_matching_cost_center")
                    ):
                        try:
                            candidate_payload = get_abschlagsplan_candidates_for_row(doc.name, row.name)
                            auto_tolerance = int(candidate_payload.get("auto_tolerance_days") or 0)
                            strict_candidates = [
                                c for c in candidate_payload.get("candidates", [])
                                if c.get("delta_days") is None or c.get("delta_days") <= auto_tolerance
                            ]
                            if len(strict_candidates) == 1:
                                abschlag_result = assign_abschlagsplan_row(
                                    doc.name,
                                    row.name,
                                    strict_candidates[0].get("row_name"),
                                    remarks=row.get("verwendungszweck") or row.get("auftraggeber") or None,
                                )
                                row.db_set(
                                    "auto_match_message",
                                    (
                                        f"Abschlag automatisch zugeordnet: "
                                        f"{abschlag_result.get('zahlungsplan')} Zeile {abschlag_result.get('row_idx')}"
                                    ),
                                )
                                auto_abschlag_matched.append(bt.name)
                                continue
                        except Exception:
                            frappe.log_error(
                                frappe.get_traceback(),
                                f"Bankauszug Import: Abschlagsplan-Auto-Zuordnung fehlgeschlagen für {bt.name}",
                            )
                    if match_result.get("reason") not in ("no_party", "wrong_direction_for_customer", "wrong_direction_for_supplier"):
                        # Diagnose-Info für die Liste — kein "Fehler" im engeren Sinne
                        auto_match_failed.append({
                            "row": row.name,
                            "bank_transaction": bt.name,
                            "reason": match_result.get("reason"),
                        })
            except Exception as match_exc:
                # Match-Fehler sollen den Import nicht abbrechen.
                frappe.log_error(
                    frappe.get_traceback(),
                    f"Bankauszug Import: Auto-Match fehlgeschlagen für {bt.name}",
                )
                try:
                    row.db_set("auto_match_message", f"Auto-Match-Fehler: {match_exc}")
                except Exception:
                    pass
        except Exception as e:
            frappe.log_error(frappe.get_traceback(), "Bankauszug Import: create error")
            row.db_set("error", str(e))
            row.db_set("row_status", "failed")
            errors.append({"row": row.name, "error": str(e)})

    doc.reload()
    _refresh_saldo_fields(doc)
    doc.save()
    _recompute_doc_status(doc.name)
    return {
        "created": created,
        "errors": errors,
        "created_without_party": created_without_party,
        "skipped_before_cutoff": skipped_before_cutoff,
        "cutoff_date": str(bankimport_start_datum) if bankimport_start_datum else None,
        "auto_matched": auto_matched,
        "auto_abschlag_matched": auto_abschlag_matched,
        "auto_kredit_matched": auto_kredit_matched,
        "auto_match_failed": auto_match_failed,
        "warning": warning if warning and bool(int(allow_missing_party or 0)) else None,
    }


def _persist_saldo_fields(doc) -> None:
    """Schreibt aktualisierte Saldo-Werte ohne ``modified``-Timestamp zu ändern.

    Genutzt von ``onload`` und nach Voucher-Erstellungen, damit Listenansicht
    und Reports konsistente Zahlen sehen, ohne dass jede Form-Anzeige als
    "Änderung" gezählt wird.

    ``saldo_laut_csv`` muss mit drin sein, weil ``reextract_saldo_from_csv``
    (Patch-Helfer) ihn nur in-memory setzt und auf diese Funktion zum
    Persistieren angewiesen ist. Für ``onload`` und nach Voucher-Erstellung
    ist das ein No-op (der Wert ändert sich dort nicht), schadet aber nichts.
    """
    for field in ("saldo_laut_csv", "saldo_laut_erp", "saldo_differenz", "saldo_datum"):
        value = doc.get(field)
        if value is None:
            continue
        try:
            frappe.db.set_value(
                "Bankauszug Import", doc.name, field, value, update_modified=False,
            )
        except Exception:
            # Best-effort: stale Werte in der DB sind keine Katastrophe.
            pass


def _refresh_and_persist_saldo(docname: str) -> None:
    """Lädt das Doc, rechnet Saldo neu und persistiert ohne ``modified``-Bump.

    Aufrufstelle: am Ende jeder Whitelist-Funktion, die Voucher erzeugt
    (Payment Entry, Journal Entry) — damit der Saldo sofort den neuen
    GL-Stand widerspiegelt, statt erst nach manuellem "Saldo neu prüfen".
    """
    try:
        doc = frappe.get_doc("Bankauszug Import", docname)
        _refresh_saldo_fields(doc)
        _persist_saldo_fields(doc)
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Bankauszug Import: Saldo-Refresh nach Voucher fehlgeschlagen ({docname})",
        )


def _refresh_saldo_fields(doc) -> None:
    """Berechnet ``saldo_laut_erp`` und ``saldo_differenz`` für das Bankkonto
    zum Stichtag ``saldo_datum``. Wenn keine Vergleichsdaten da sind, no-op.
    """
    if not doc.get("bank_account") or not doc.get("saldo_datum"):
        return
    try:
        gl_account = frappe.db.get_value("Bank Account", doc.bank_account, "account")
        if not gl_account:
            return
        # get_balance_on liefert vorzeichenbehaftet; bei Bank-Konten ist Soll-Saldo positiv
        from erpnext.accounts.utils import get_balance_on
        balance = flt(get_balance_on(account=gl_account, date=doc.saldo_datum))
        doc.saldo_laut_erp = balance
        if doc.get("saldo_laut_csv") is not None:
            doc.saldo_differenz = flt(doc.saldo_laut_csv) - balance
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"Bankauszug Import: Saldo-Berechnung fehlgeschlagen ({doc.name})",
        )


@frappe.whitelist()
def refresh_saldo(docname: str) -> Dict[str, Any]:
    """Manueller Refresh nach manueller Reconciliation o.ä.

    Liest den GL-Saldo neu und vergleicht mit dem CSV-Wert. Erlaubt Mama nach
    manuellen Zuordnungen schnell zu prüfen, ob der ERP-Saldo jetzt zum Bank-
    Saldo passt — ohne Neuparsen der CSV.
    """
    doc = frappe.get_doc("Bankauszug Import", docname)
    if not frappe.has_permission("Bankauszug Import", "write", doc=doc):
        frappe.throw("Keine Berechtigung.")
    _refresh_saldo_fields(doc)
    doc.save(ignore_permissions=True)
    return {
        "saldo_laut_csv": doc.get("saldo_laut_csv"),
        "saldo_laut_erp": doc.get("saldo_laut_erp"),
        "saldo_differenz": doc.get("saldo_differenz"),
        "saldo_datum": doc.get("saldo_datum"),
    }


# ---------------------------------------------------------------------------
# Manual reconciliation endpoints (Phase A)
#
# Pro Bankauszug-Import-Zeile, deren Bank Transaction nicht auto-gematcht
# wurde, kann der User direkt in der Tabelle weiterarbeiten ohne ins
# ERPNext Bank Reconciliation Tool zu wechseln.
# ---------------------------------------------------------------------------


def _row_with_unreconciled_bt(docname: str, row_name: str) -> Tuple[Document, Document, Document]:
    """Lädt (doc, row, bt). Wirft, wenn Zeile keine BT hat oder bereits reconciled ist."""
    doc = frappe.get_doc("Bankauszug Import", docname)
    if not frappe.has_permission("Bankauszug Import", "write", doc=doc):
        frappe.throw("Keine Berechtigung zum Bearbeiten dieses Bankauszug Imports.")

    row = _get_row_by_name(doc, row_name)
    bt_name = getattr(row, "bank_transaction", None)
    if not bt_name:
        frappe.throw(
            "Diese Zeile hat noch keine Bank Transaction. Bitte zuerst "
            "'Bank Transaktionen erstellen' ausführen."
        )
    if getattr(row, "payment_entry", None) or getattr(row, "journal_entry", None):
        frappe.throw(
            "Zeile ist bereits einem Beleg zugeordnet "
            f"({getattr(row, 'payment_entry', None) or getattr(row, 'journal_entry', None)})."
        )

    bt = frappe.get_doc("Bank Transaction", bt_name)
    if bt.get("payment_entries"):
        frappe.throw(
            "Bank Transaction ist bereits reconciled — bitte vorher die "
            "verknüpften Belege prüfen."
        )
    return doc, row, bt


@frappe.whitelist()
def get_expected_cost_center_for_row(docname: str, row_name: str) -> Dict[str, Any]:
    """Liefert die erwartete Kostenstelle (aus Immobilie via Bank Account) für die Zeile.

    Wird vom Frontend genutzt, um z.B. den JE-Dialog mit der Kostenstelle vorzubelegen.
    """
    from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
        _resolve_expected_cost_center_for_bt,
    )

    doc = frappe.get_doc("Bankauszug Import", docname)
    if not frappe.has_permission("Bankauszug Import", "read", doc=doc):
        frappe.throw("Keine Berechtigung.")
    row = _get_row_by_name(doc, row_name)
    bt_name = getattr(row, "bank_transaction", None)
    if not bt_name:
        return {"cost_center": None}
    try:
        bt = frappe.get_doc("Bank Transaction", bt_name)
    except Exception:
        return {"cost_center": None}
    return {"cost_center": _resolve_expected_cost_center_for_bt(bt)}


@frappe.whitelist()
def get_open_invoices_for_row(docname: str, row_name: str) -> Dict[str, Any]:
    """Listet offene Rechnungen für die Party einer Bankauszug-Zeile.

    Returns:
        {
          invoice_doctype: "Sales Invoice"|"Purchase Invoice"|None,
          invoices: [{name, outstanding_amount, posting_date, remarks}],
          target_amount: float,  # Bank-Betrag der Zeile
        }
    """
    doc = frappe.get_doc("Bankauszug Import", docname)
    if not frappe.has_permission("Bankauszug Import", "read", doc=doc):
        frappe.throw("Keine Berechtigung.")

    row = _get_row_by_name(doc, row_name)
    if not row.get("party_type") or not row.get("party"):
        return {"invoice_doctype": None, "invoices": [], "target_amount": flt(row.betrag)}

    if row.party_type == "Customer":
        invoice_doctype = "Sales Invoice"
        party_field = "customer"
    elif row.party_type == "Supplier":
        invoice_doctype = "Purchase Invoice"
        party_field = "supplier"
    else:
        return {"invoice_doctype": None, "invoices": [], "target_amount": flt(row.betrag)}

    invoices = frappe.get_all(
        invoice_doctype,
        filters={
            party_field: row.party,
            "docstatus": 1,
            "outstanding_amount": [">", 0.001],
        },
        fields=["name", "outstanding_amount", "posting_date", "remarks", "grand_total"],
        order_by="posting_date asc",
        limit=200,
    )
    return {
        "invoice_doctype": invoice_doctype,
        "invoices": invoices,
        "target_amount": flt(row.betrag),
    }


@frappe.whitelist()
def get_abschlagsplan_candidates_for_row(docname: str, row_name: str) -> dict[str, Any]:
    """Listet offene Abschlagsplan-Zeilen für eine Supplier-Ausgangszeile.

    Die Kandidaten sind bewusst Plan-Zeilen, keine Rechnungen: der spätere
    Beleg ist ein unallocated Supplier Payment Entry, der an die Zeile gehängt
    und erst bei der Jahresabrechnung verrechnet wird.
    """
    from hausverwaltung.hausverwaltung.doctype.zahlungsplan.zahlungsplan import (
        MODUS_ABSCHLAGSPLAN,
        _get_abschlag_tolerance_days,
    )
    from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
        _resolve_expected_cost_center_for_bt,
    )

    doc = frappe.get_doc("Bankauszug Import", docname)
    if not frappe.has_permission("Bankauszug Import", "read", doc=doc):
        frappe.throw("Keine Berechtigung.")

    row = _get_row_by_name(doc, row_name)
    if row.get("richtung") != "Ausgang" or row.get("party_type") != "Supplier" or not row.get("party"):
        return {"candidates": [], "target_amount": flt(row.get("betrag")), "reason": "not_supplier_outgoing"}

    bt_name = _get_row_bank_transaction_name(row)
    if not bt_name:
        return {"candidates": [], "target_amount": flt(row.get("betrag")), "reason": "no_bank_transaction"}

    bt = frappe.get_doc("Bank Transaction", bt_name)
    target_amount = flt(row.get("betrag"))
    target_date = getdate(row.get("buchungstag")) if row.get("buchungstag") else None
    tolerance_days = _get_abschlag_tolerance_days()
    manual_window_days = max(tolerance_days, 45)
    expected_cc = _resolve_expected_cost_center_for_bt(bt)
    bank_account = getattr(bt, "bank_account", None)

    rows = frappe.db.sql(
        """
        SELECT
            p.name AS row_name,
            p.idx AS row_idx,
            p.faelligkeitsdatum,
            p.betrag,
            p.bemerkung,
            az.name AS zahlungsplan,
            az.bezeichnung,
            az.company,
            az.lieferant,
            az.immobilie,
            az.wohnung,
            az.bank_account,
            az.cost_center
        FROM `tabZahlungsplan Zeile` p
        INNER JOIN `tabZahlungsplan` az ON az.name = p.parent
        WHERE
            az.modus = %(modus)s
            AND az.status != 'Abgerechnet'
            AND az.lieferant = %(supplier)s
            AND (p.payment_entry IS NULL OR p.payment_entry = '')
        ORDER BY p.faelligkeitsdatum ASC, az.name ASC, p.idx ASC
        """,
        {"modus": MODUS_ABSCHLAGSPLAN, "supplier": row.party},
        as_dict=True,
    )

    candidates = []
    for item in rows:
        if abs(flt(item.get("betrag")) - target_amount) > 0.01:
            continue
        if bank_account and item.get("bank_account") and item.get("bank_account") != bank_account:
            continue
        if expected_cc and item.get("cost_center") and item.get("cost_center") != expected_cc:
            continue

        row_date = getdate(item.get("faelligkeitsdatum")) if item.get("faelligkeitsdatum") else None
        delta_days = abs((row_date - target_date).days) if row_date and target_date else None
        item["delta_days"] = delta_days
        item["bank_account_match"] = bool(bank_account and item.get("bank_account") == bank_account)
        item["cost_center_match"] = bool(expected_cc and item.get("cost_center") == expected_cc)
        candidates.append(item)

    candidates.sort(
        key=lambda c: (
            0 if c.get("bank_account_match") else 1,
            0 if c.get("cost_center_match") else 1,
            c.get("delta_days") if c.get("delta_days") is not None else 9999,
            c.get("faelligkeitsdatum") or "9999-12-31",
        )
    )
    return {
        "candidates": candidates,
        "target_amount": target_amount,
        "target_date": str(target_date) if target_date else None,
        "bank_account": bank_account,
        "expected_cost_center": expected_cc,
        "auto_tolerance_days": tolerance_days,
        "manual_window_days": manual_window_days,
    }


@frappe.whitelist()
def manually_reconcile_row(
    docname: str,
    row_name: str,
    invoice_names: str,
    leftover_as_advance: int = 0,
) -> Dict[str, Any]:
    """Erstellt Payment Entry mit Allocations gegen die ausgewählten Rechnungen.

    Args:
        invoice_names: JSON-Array oder kommaseparierte Liste der Rechnungs-Namen.
        leftover_as_advance: Wenn 1 und Auswahl-Summe < BT-Betrag, bleibt der Rest
            als ``unallocated_amount`` am PE (Vorauszahlung am Mieter).
    """
    import json as _json
    from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
        create_payment_entry_for_invoices,
        reconcile_created_voucher_or_rollback,
    )

    doc, row, bt = _row_with_unreconciled_bt(docname, row_name)

    # invoice_names parsen — drei akzeptierte Formate:
    #   1. JSON-Array von Objekten: [{"name": "SINV-1", "allocated_amount": 500}, ...] (UI sendet das)
    #   2. JSON-Array von Strings: ["SINV-1", "SINV-2"] (gibt Vollbetrag jeder Rechnung)
    #   3. Kommaseparierte Liste: "SINV-1,SINV-2" (Legacy)
    parsed = None
    try:
        if invoice_names and invoice_names.strip().startswith("["):
            parsed = _json.loads(invoice_names)
    except Exception:
        parsed = None

    if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
        # Format 1: explizite Allocations
        items = [{"name": p.get("name"), "allocated_amount": flt(p.get("allocated_amount"))} for p in parsed]
    elif isinstance(parsed, list):
        # Format 2: nur Namen, kein Betrag → später Vollbetrag verwenden
        items = [{"name": n, "allocated_amount": None} for n in parsed]
    else:
        # Format 3: CSV
        items = [{"name": n.strip(), "allocated_amount": None} for n in (invoice_names or "").split(",") if n.strip()]

    if not items:
        frappe.throw("Bitte mindestens eine Rechnung auswählen.")

    if row.party_type == "Customer":
        invoice_doctype = "Sales Invoice"
    elif row.party_type == "Supplier":
        invoice_doctype = "Purchase Invoice"
    else:
        frappe.throw(f"Party-Typ '{row.party_type}' nicht unterstützt für manuelle Zuordnung.")

    target_amount = flt(row.betrag)

    # Rechnungen einzeln laden, um aktuelle outstanding_amount zu prüfen.
    # Allocation pro Rechnung: explizit aus Frontend (falls gesetzt) sonst Vollbetrag.
    invoices = []
    explicit_allocated_total = 0.0
    for item in items:
        inv_name = item["name"]
        inv = frappe.db.get_value(
            invoice_doctype,
            inv_name,
            ["name", "outstanding_amount", "posting_date"],
            as_dict=True,
        )
        if not inv:
            frappe.throw(f"Rechnung {inv_name} nicht gefunden.")
        if flt(inv.outstanding_amount) <= 0:
            frappe.throw(f"Rechnung {inv_name} hat keinen offenen Betrag mehr.")
        # Allocation festlegen: Frontend-Wert hat Vorrang, sonst voller outstanding_amount
        explicit_alloc = item.get("allocated_amount")
        if explicit_alloc is not None:
            explicit_alloc = flt(explicit_alloc)
            if explicit_alloc <= 0:
                frappe.throw(f"Zuweisung für {inv_name} muss größer als 0 € sein.")
            if explicit_alloc > flt(inv.outstanding_amount) + 0.01:
                frappe.throw(
                    f"Zuweisung für {inv_name} ({explicit_alloc:.2f} €) übersteigt "
                    f"offenen Betrag ({flt(inv.outstanding_amount):.2f} €)."
                )
            inv["allocated_amount"] = explicit_alloc
            explicit_allocated_total += explicit_alloc
        invoices.append(inv)

    if explicit_allocated_total > target_amount + 0.01:
        frappe.throw(
            f"Zuweisungen summieren auf {explicit_allocated_total:.2f} €, "
            f"Bank-Betrag ist {target_amount:.2f} €. Bitte Beträge reduzieren."
        )

    pe = create_payment_entry_for_invoices(
        bt=bt,
        invoices=invoices,
        invoice_doctype=invoice_doctype,
        target_amount=target_amount,
        leftover_as_advance=bool(int(leftover_as_advance or 0)),
    )

    reconcile_created_voucher_or_rollback(bt, "Payment Entry", pe.name, target_amount)

    row.db_set("payment_entry", pe.name)
    _set_row_payment_document(row, "Payment Entry", pe.name)
    row.db_set("row_status", "success")
    row.db_set(
        "auto_match_message",
        f"Manuell zugeordnet: {len(invoices)} Rechnung(en), {target_amount:.2f} €"
        + (" (mit Vorauszahlung)" if int(leftover_as_advance or 0) else ""),
    )
    _recompute_doc_status(docname)
    _refresh_and_persist_saldo(docname)

    return {
        "ok": True,
        "payment_entry": pe.name,
        "invoices": [i.name for i in invoices],
    }


@frappe.whitelist()
def assign_abschlagsplan_row(
    docname: str,
    row_name: str,
    plan_row_name: str,
    remarks: str | None = None,
) -> dict[str, Any]:
    """Bucht eine Supplier-Bankausgangszeile als Anzahlung und verlinkt sie zur Abschlagsplan-Zeile."""
    from hausverwaltung.hausverwaltung.doctype.zahlungsplan.zahlungsplan import MODUS_ABSCHLAGSPLAN
    from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
        _resolve_expected_cost_center_for_bt,
        create_standalone_payment_entry,
        reconcile_created_voucher_or_rollback,
    )

    _doc, row, bt = _row_with_unreconciled_bt(docname, row_name)
    if row.get("richtung") != "Ausgang" or row.get("party_type") != "Supplier" or not row.get("party"):
        frappe.throw("Abschlagsplan-Zuordnung ist nur für Lieferanten-Ausgänge möglich.")

    plan_row = frappe.db.get_value(
        "Zahlungsplan Zeile",
        plan_row_name,
        ["name", "parent", "idx", "faelligkeitsdatum", "betrag", "payment_entry"],
        as_dict=True,
    )
    if not plan_row:
        frappe.throw("Abschlagsplan-Zeile nicht gefunden.")
    if plan_row.get("payment_entry"):
        frappe.throw("Diese Abschlagsplan-Zeile ist bereits bezahlt.")

    plan = frappe.get_doc("Zahlungsplan", plan_row.parent)
    if plan.get("modus") != MODUS_ABSCHLAGSPLAN:
        frappe.throw("Die ausgewählte Zeile gehört nicht zu einem Abschlagsplan.")
    if plan.get("status") == "Abgerechnet":
        frappe.throw("Der ausgewählte Abschlagsplan ist bereits abgerechnet.")
    if plan.get("lieferant") != row.get("party"):
        frappe.throw("Lieferant der Bankzeile passt nicht zum Abschlagsplan.")
    if abs(flt(plan_row.get("betrag")) - flt(row.get("betrag"))) > 0.01:
        frappe.throw("Betrag der Bankzeile passt nicht zur Abschlagsplan-Zeile.")
    if getattr(bt, "bank_account", None) and plan.get("bank_account") and plan.bank_account != bt.bank_account:
        frappe.throw("Bankkonto der Bankzeile passt nicht zum Abschlagsplan.")

    expected_cc = _resolve_expected_cost_center_for_bt(bt)
    if expected_cc and plan.get("cost_center") and plan.cost_center != expected_cc:
        frappe.throw("Kostenstelle der Bankzeile passt nicht zum Abschlagsplan.")

    pe = create_standalone_payment_entry(
        bt=bt,
        party_type="Supplier",
        party=row.party,
        remarks=remarks or row.get("verwendungszweck") or row.get("auftraggeber") or None,
    )
    target_amount = flt(row.betrag)
    reconcile_created_voucher_or_rollback(bt, "Payment Entry", pe.name, target_amount)

    row.db_set("payment_entry", pe.name)
    _set_row_payment_document(row, "Payment Entry", pe.name)
    row.db_set("row_status", "success")
    plan_row_doc = frappe.get_doc("Zahlungsplan Zeile", plan_row.name)
    plan_row_doc.db_set("payment_entry", pe.name, update_modified=False)
    plan_row_doc.db_set("bank_transaction", bt.name, update_modified=False)
    if row.get("buchungstag"):
        plan_row_doc.db_set("gebucht_am", getdate(row.buchungstag), update_modified=False)
    row.db_set(
        "auto_match_message",
        f"Abschlag zugeordnet: {plan.name} Zeile {plan_row.idx}, {target_amount:.2f} €",
    )
    _recompute_doc_status(docname)
    _refresh_and_persist_saldo(docname)

    return {
        "ok": True,
        "payment_entry": pe.name,
        "bank_transaction": bt.name,
        "zahlungsplan": plan.name,
        "row_idx": plan_row.idx,
        "plan_row": plan_row.name,
    }


@frappe.whitelist()
def create_standalone_payment_for_row(
    docname: str,
    row_name: str,
    party_type: Optional[str] = None,
    party: Optional[str] = None,
    remarks: Optional[str] = None,
) -> Dict[str, Any]:
    """Standalone Payment Entry: kompletter BT-Betrag als unallocated.

    Wird z.B. genutzt wenn ein Mieter eine Vorauszahlung tätigt und die
    zugehörige Rechnung erst später erstellt wird. Der PE bleibt komplett
    unallocated und kann später manuell auf eine konkrete Rechnung verteilt
    werden.
    """
    from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
        create_standalone_payment_entry,
        reconcile_created_voucher_or_rollback,
    )

    doc, row, bt = _row_with_unreconciled_bt(docname, row_name)

    effective_party_type = party_type or row.get("party_type")
    effective_party = party or row.get("party")
    pe = create_standalone_payment_entry(
        bt=bt,
        party_type=effective_party_type,
        party=effective_party,
        remarks=remarks,
    )
    target_amount = flt(row.betrag)
    reconcile_created_voucher_or_rollback(bt, "Payment Entry", pe.name, target_amount)

    row.db_set("payment_entry", pe.name)
    _set_row_payment_document(row, "Payment Entry", pe.name)
    row.db_set("row_status", "success")

    # Bei Lieferanten-Auszahlungen mit aktivem Abschlagsplan: PE direkt mit
    # passender Plan-Zeile verknüpfen, damit Mama nicht hinterher manuell
    # verlinken muss. Year-End-Reconciliation funktioniert weiter über
    # unallocated_amount, ist also unabhängig von dieser Verknüpfung.
    abschlag_match = None
    if effective_party_type == "Supplier" and effective_party:
        try:
            from hausverwaltung.hausverwaltung.doctype.zahlungsplan.zahlungsplan import (
                link_payment_entry_to_abschlagsplan_row,
            )
            abschlag_match = link_payment_entry_to_abschlagsplan_row(
                supplier=effective_party,
                posting_date=row.get("buchungstag"),
                amount=target_amount,
                payment_entry=pe.name,
                bank_transaction=bt.name,
            )
        except Exception:
            frappe.log_error(
                frappe.get_traceback(),
                f"Bankauszug Import: Abschlagsplan-Verknüpfung fehlgeschlagen ({docname}/{row.name})",
            )

    msg = f"Manuell verbucht: Standalone Payment Entry über {target_amount:.2f} € (unallocated)"
    if abschlag_match:
        msg += (
            f" · verlinkt mit Abschlagsplan {abschlag_match['plan']} "
            f"Zeile {abschlag_match['row_idx']} ({abschlag_match['faelligkeitsdatum']})"
        )
    row.db_set("auto_match_message", msg)
    _recompute_doc_status(docname)
    _refresh_and_persist_saldo(docname)
    return {"ok": True, "payment_entry": pe.name}


@frappe.whitelist()
def create_journal_entry_for_row(
    docname: str,
    row_name: str,
    account: Optional[str] = None,
    cost_center: Optional[str] = None,
    remarks: Optional[str] = None,
    splits: Optional[str] = None,
) -> Dict[str, Any]:
    """Journal Entry: Bank-Konto vs. ein oder mehrere Gegenkonten.

    Eingang: Bank Soll, Gegenkonten Haben.
    Ausgang: Bank Haben, Gegenkonten Soll.

    ``splits`` (JSON-Array oder Liste): ``[{account, cost_center?, amount}, ...]``.
    Summe muss dem BT-Betrag entsprechen. Wenn ``splits`` leer ist, wird der
    Single-Account-Modus mit ``account`` + ``cost_center`` genutzt.

    Use-Case: Bankgebühren, Eigentümer-Entnahmen, manuelle Korrekturen — und
    Splits wie „Hauptbetrag + Bankgebühr in einem Vorgang".
    """
    import json as _json
    from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
        create_journal_entry_for_bt,
        reconcile_created_voucher_or_rollback,
    )

    doc, row, bt = _row_with_unreconciled_bt(docname, row_name)

    parsed_splits = None
    if splits:
        if isinstance(splits, str):
            try:
                parsed_splits = _json.loads(splits)
            except Exception:
                frappe.throw("Ungültiges Splits-Format (kein gültiges JSON).")
        else:
            parsed_splits = splits
        if not isinstance(parsed_splits, list) or not parsed_splits:
            frappe.throw("Splits muss eine nicht-leere Liste sein.")

    je = create_journal_entry_for_bt(
        bt=bt,
        account=account,
        cost_center=cost_center,
        splits=parsed_splits,
        remarks=remarks,
    )
    target_amount = flt(row.betrag)
    reconcile_created_voucher_or_rollback(bt, "Journal Entry", je.name, target_amount)

    row.db_set("journal_entry", je.name)
    _set_row_payment_document(row, "Journal Entry", je.name)
    row.db_set("row_status", "success")
    if parsed_splits:
        accs = ", ".join((s.get("account") or "") for s in parsed_splits)
        message = (
            f"Buchungssatz: {target_amount:.2f} € auf {len(parsed_splits)} Konten ({accs})"
        )
    else:
        message = f"Buchungssatz: {target_amount:.2f} € gegen {account}"
    row.db_set("auto_match_message", message)
    _recompute_doc_status(docname)
    _refresh_and_persist_saldo(docname)
    return {"ok": True, "journal_entry": je.name}


# ---------------------------------------------------------------------------
# Kreditvertrag-Match (manuelle Fallback-Aktion)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_open_kreditraten_for_row(docname: str, row_name: str) -> Dict[str, Any]:
    """Liefert die Kandidatenliste offener Kreditraten für eine Bankimport-Zeile.

    Server holt sich Bankkonto/Buchungsdatum/Betrag/Supplier selbst aus
    Row + Bank Transaction — UI übergibt nur docname + row_name (verhindert
    Parameter-Drift zwischen UI und Server-Match).
    """
    from hausverwaltung.hausverwaltung.doctype.kreditvertrag.kreditvertrag import (
        _extract_loan_match_hints,
        _find_kreditvertraege_for_statement,
        _loan_hints_are_complete,
        get_open_rates_for_match,
    )

    doc, row, bt = _row_with_unreconciled_bt(docname, row_name)

    supplier = row.get("party") if row.get("party_type") == "Supplier" else None
    candidates = get_open_rates_for_match(
        bank_account=bt.bank_account,
        posting_date=bt.date,
        amount=row.get("betrag"),
        supplier=supplier,
        reference_text=row.get("verwendungszweck"),
    )

    # Statement-Hint: kann die Rate direkt aus dem Verwendungszweck angelegt werden?
    # Fall: keine vorhandene Planrate, aber "AZ … Tilgung X Zinsen Y" steht im
    # Verwendungszweck UND genau ein Kreditvertrag (Bankkonto + Vertragsnummer=AZ)
    # passt. Dann kann der Dialog die Rate anlegen+buchen (statement-getrieben).
    statement_hints = _extract_loan_match_hints(row.get("verwendungszweck"))
    can_create_from_statement = False
    statement_kreditvertrag = None
    if row.get("richtung") == "Ausgang" and _loan_hints_are_complete(statement_hints):
        contracts = _find_kreditvertraege_for_statement(
            bank_account=bt.bank_account,
            vertragsnummer=statement_hints["vertragsnummer"],
            supplier=supplier,
        )
        if len(contracts) == 1:
            can_create_from_statement = True
            statement_kreditvertrag = contracts[0].name

    return {
        "bank_account": bt.bank_account,
        "bank_transaction": bt.name,
        "posting_date": str(bt.date),
        "amount": flt(row.betrag),
        "supplier": supplier,
        "candidates": candidates,
        "statement_hints": statement_hints,
        "can_create_from_statement": can_create_from_statement,
        "kreditvertrag": statement_kreditvertrag,
    }


@frappe.whitelist()
def assign_kreditrate_to_bank_row(
    docname: str,
    row_name: str,
    kreditvertrag: str,
    rate_name: str,
) -> Dict[str, Any]:
    """Manuelle Zuordnung: erzeugt JE für die ausgewählte Rate und verlinkt alles.

    Wird vom „Kreditrate zuordnen"-Dialog im Bankimport gerufen. Server
    leitet alle Match-Parameter aus der Row/BT ab (UI darf nicht überschreiben).
    """
    from hausverwaltung.hausverwaltung.doctype.kreditvertrag.kreditvertrag import (
        assign_kreditrate,
    )

    doc, row, bt = _row_with_unreconciled_bt(docname, row_name)

    result = assign_kreditrate(
        kreditvertrag=kreditvertrag,
        rate_name=rate_name,
        bank_account=bt.bank_account,
        posting_date=bt.date,
        amount=row.get("betrag"),
        bank_transaction=bt.name,
    )

    je_name = result["journal_entry"]
    row.db_set("journal_entry", je_name)
    _set_row_payment_document(row, "Journal Entry", je_name)
    row.db_set("row_status", "success")
    row.db_set(
        "auto_match_message",
        (
            f"Kreditrate manuell gebucht: {result['kreditvertrag']} "
            f"Zeile {result['row_idx']} → {je_name}"
        ),
    )
    _recompute_doc_status(docname)
    _refresh_and_persist_saldo(docname)
    return {
        "ok": True,
        "journal_entry": je_name,
        "kreditvertrag": result["kreditvertrag"],
        "row_idx": result["row_idx"],
    }


@frappe.whitelist()
def book_kreditrate_from_statement_for_row(docname: str, row_name: str) -> Dict[str, Any]:
    """Legt eine Kreditrate aus dem Kontoauszug-Verwendungszweck an und bucht sie.

    Für den Fall, dass noch keine Planrate existiert (z.B. Darlehen ohne erfassten
    Tilgungsplan): nutzt den Statement-Hint (AZ + Tilgung + Zinsen). Bei genau
    einem passenden Vertrag (Bankkonto + Vertragsnummer=AZ) legt
    ``link_bank_transaction_to_kreditvertrag_rate`` die Rate an, erzeugt den JE mit
    Zins-/Tilgungs-Split und reconciled die Bank Transaction (inkl. Savepoint-
    Rollback). Spiegelt die Logik des Auto-Match-Loops in ``create_bank_transactions``
    für eine einzelne, bereits importierte Zeile.
    """
    from hausverwaltung.hausverwaltung.doctype.kreditvertrag.kreditvertrag import (
        link_bank_transaction_to_kreditvertrag_rate,
    )

    doc, row, bt = _row_with_unreconciled_bt(docname, row_name)
    if row.get("richtung") != "Ausgang":
        frappe.throw("Kreditraten-Buchung ist nur für Ausgänge möglich.")

    result = link_bank_transaction_to_kreditvertrag_rate(
        bank_account=bt.bank_account,
        posting_date=bt.date,
        amount=row.get("betrag"),
        bank_transaction=bt.name,
        supplier=row.get("party") if row.get("party_type") == "Supplier" else None,
        reference_text=row.get("verwendungszweck"),
    )

    if result and result.get("match_count") == 1:
        je_name = result["journal_entry"]
        row.db_set("journal_entry", je_name)
        _set_row_payment_document(row, "Journal Entry", je_name)
        row.db_set("row_status", "success")
        if result.get("created_from_statement"):
            msg = (
                f"Kreditrate aus Kontoauszug angelegt und gebucht: "
                f"{result['kreditvertrag']} Zeile {result['row_idx']} → {je_name}"
            )
        else:
            msg = (
                f"Kreditrate gebucht: {result['kreditvertrag']} "
                f"Zeile {result['row_idx']} → {je_name}"
            )
        row.db_set("auto_match_message", msg)
        _recompute_doc_status(docname)
        _refresh_and_persist_saldo(docname)
        return {
            "ok": True,
            "journal_entry": je_name,
            "kreditvertrag": result["kreditvertrag"],
            "row_idx": result["row_idx"],
            "created_from_statement": bool(result.get("created_from_statement")),
        }

    # Kein eindeutiges Ergebnis (blocked / 0 / >1 Treffer) — kein Throw, damit der
    # Dialog die Begründung anzeigen kann.
    message = (result.get("message") if result else None) or (
        "Keine eindeutige Kreditrate aus dem Kontoauszug ableitbar — bitte "
        "Kreditvertrag (Vertragsnummer = AZ) und Verwendungszweck prüfen."
    )
    return {
        "ok": False,
        "blocked": bool(result and result.get("blocked")),
        "match_count": (result.get("match_count") if result else 0) or 0,
        "message": message,
    }
