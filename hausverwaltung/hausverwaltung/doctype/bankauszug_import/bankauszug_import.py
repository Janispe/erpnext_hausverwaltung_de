import csv
import io
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

import frappe
from frappe.model.document import Document
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
    def before_save(self):
        # update info and clear rows if file changed
        pass


def _normalize_iban(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s.replace(" ", "").upper()


def _get_party_by_iban(iban: Optional[str]) -> Optional[Tuple[str, str]]:
    """Resolve (party_type, party) from an IBAN via `Bank Account`."""
    iban_norm = _normalize_iban(iban)
    if not iban_norm:
        return None

    candidates = frappe.get_all(
        "Bank Account",
        filters={"iban": ("in", [iban_norm, iban])},
        fields=["party_type", "party"],
        limit=50,
    )
    for c in candidates:
        if c.get("party") and c.get("party_type") in SUPPORTED_PARTY_TYPES:
            return (c["party_type"], c["party"])
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
        if bank.get("party") and bank.get("party_type") and (
            bank.get("party_type") != party_type or bank.get("party") != party
        ):
            frappe.throw(
                f"IBAN {iban_norm} ist bereits {bank.get('party_type')} {bank.get('party')} zugeordnet "
                f"({bank.get('name')})."
            )
        if bank.get("party_type") == party_type and bank.get("party") == party:
            return bank.get("name"), False

    doc = frappe.get_doc(
        {
            "doctype": "Bank Account",
            "account_name": f"Konto {party}",
            "bank": _get_default_bank(),
            "iban": iban_norm,
            "is_company_account": 0,
            "party_type": party_type,
            "party": party,
        }
    ).insert(ignore_permissions=True)
    return doc.name, True


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


def _extract_csv_kontostand(possible: list) -> Optional[float]:
    """Sucht in einer CSV-Vorzeile nach 'Letzter Kontostand' und gibt den Betrag zurück.

    Postbank-Format: ``Letzter Kontostand;;;;14.619,26;EUR`` — der Betrag steht
    in einer der hinteren Spalten. Wir nehmen die erste numerisch parsbare.
    """
    if not possible:
        return None
    first = _normalize_header(possible[0]).lower()
    if "kontostand" not in first:
        return None
    for cell in possible[1:]:
        val = _parse_decimal(str(cell))
        if val:
            return val
    return None


@frappe.whitelist()
def parse_csv(docname: str) -> Dict[str, Any]:
    doc = frappe.get_doc("Bankauszug Import", docname)
    text = _decode_file(doc.csv_file, doc.encoding)
    sample = text[:2048]
    delimiter = _sniff_delimiter(sample, doc.delimiter)
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    # Find the actual header row: skip bank preamble until a row contains required headers.
    # Während wir die Preamble lesen, schnappen wir uns auch den 'Letzter Kontostand'-Wert.
    header_map = {}
    headers = None
    csv_kontostand: Optional[float] = None
    for possible in reader:
        # skip empty or 1-col lines like "Umsätze" or date range
        if not possible or (len(possible) == 1 and not possible[0].strip()):
            continue
        # Kontostand erkennen, bevor wir bei der eigentlichen Header-Zeile abbrechen
        ks = _extract_csv_kontostand(possible)
        if ks is not None:
            csv_kontostand = ks
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

    # Validate other required fields (IBAN is optional in some lines, don't hard-fail here)
    rows = []
    party_cache: Dict[str, Optional[Tuple[str, str]]] = {}
    for raw in reader:
        if not any(raw):
            continue
        # Stop at footer lines like "Kontostand"
        if raw and _normalize_header(raw[0]).lower().startswith("kontostand"):
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
        })

    # replace child table
    doc.set("rows", [])
    for r in rows:
        doc.append("rows", r)
    doc.status = f"{len(rows)} Zeilen geladen"

    # Saldo-Felder aus CSV: 'Letzter Kontostand' + spätestes Buchungsdatum als Stichtag
    if csv_kontostand is not None:
        doc.saldo_laut_csv = csv_kontostand
    parsed_dates = [r.get("buchungstag") for r in rows if r.get("buchungstag")]
    if parsed_dates:
        doc.saldo_datum = max(parsed_dates)

    doc.save()
    return {"rows": rows, "count": len(rows), "saldo_laut_csv": csv_kontostand}


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

    row.party_type = party_type
    row.party = party
    if getattr(row, "error", None):
        row.error = None
    doc.save(ignore_permissions=True)

    return {
        "party_type": party_type,
        "party": party,
        "party_created": party_created,
        "bank_account": bank_account,
        "bank_account_created": bank_created,
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

    return {
        "row": row.name,
        "row_party_type": row.party_type,
        "row_party": row.party,
        "relink": upd,
        "bank_account": bank_account_info,
        "relink_all_count": relink_all_count,
        "relink_bt_count": relink_bt_count,
    }


@frappe.whitelist()
def create_bank_transactions(docname: str, allow_missing_party: int = 0) -> Dict[str, Any]:
    doc = frappe.get_doc("Bankauszug Import", docname)
    if not doc.bank_account:
        frappe.throw("Bitte Bankkonto auswählen.")
    bank_account = frappe.get_cached_doc("Bank Account", doc.bank_account)
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
        # Try to find an existing Bank Transaction with same date, amount, bank_account and description
        filters = {"bank_account": doc.bank_account}
        # date field could be 'date' or 'posting_date' or 'transaction_date'
        for date_field in ("date", "posting_date", "transaction_date"):
            if date_field in fieldnames:
                filters[date_field] = row_doc.buchungstag
                break
        # amount could be 'amount' or 'deposit/withdrawal'
        if "amount" in fieldnames:
            filters["amount"] = flt(row_doc.betrag if row_doc.richtung == "Eingang" else -abs(row_doc.betrag))
        elif "deposit" in fieldnames and "withdrawal" in fieldnames:
            if row_doc.richtung == "Eingang":
                filters["deposit"] = flt(row_doc.betrag)
                filters["withdrawal"] = 0
            else:
                filters["withdrawal"] = flt(row_doc.betrag)
                filters["deposit"] = 0
        # description
        if "description" in fieldnames:
            filters["description"] = row_doc.verwendungszweck or row_doc.auftraggeber
        try:
            existing = frappe.get_all("Bank Transaction", filters=filters, pluck="name", limit=1)
            return existing[0] if existing else None
        except Exception:
            return None

    for row in doc.rows:
        if row.error:
            errors.append({"row": row.name, "error": row.error})
            row.db_set("row_status", "failed")
            continue
        if row.bank_transaction:
            row.db_set("row_status", "schon vorhanden")
            row.db_set("reference", row.bank_transaction)
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
            except Exception:
                # ignore submit errors to not block the rest
                pass
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
                    row.db_set("auto_match_message", match_result.get("message"))
                    auto_matched.append(bt.name)
                else:
                    row.db_set("auto_match_message", match_result.get("message"))
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
    status_parts = [
        f"Erstellt: {len(created)}",
        f"Zugeordnet: {len(auto_matched)}",
        f"Fehler: {len(errors)}",
    ]
    if skipped_before_cutoff:
        status_parts.insert(1, f"Übersprungen (vor Start): {skipped_before_cutoff}")
    doc.status = ", ".join(status_parts)
    _refresh_saldo_fields(doc)
    doc.save()
    return {
        "created": created,
        "errors": errors,
        "created_without_party": created_without_party,
        "skipped_before_cutoff": skipped_before_cutoff,
        "cutoff_date": str(bankimport_start_datum) if bankimport_start_datum else None,
        "auto_matched": auto_matched,
        "auto_match_failed": auto_match_failed,
        "warning": warning if warning and bool(int(allow_missing_party or 0)) else None,
    }


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
        reconcile_voucher_with_bt,
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

    # Rechnungen einzeln laden, um aktuelle outstanding_amount zu prüfen.
    # Allocation pro Rechnung: explizit aus Frontend (falls gesetzt) sonst Vollbetrag.
    invoices = []
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
        if explicit_alloc is not None and explicit_alloc > 0:
            if flt(explicit_alloc) > flt(inv.outstanding_amount) + 0.01:
                frappe.throw(
                    f"Zuweisung für {inv_name} ({explicit_alloc:.2f} €) übersteigt "
                    f"offenen Betrag ({flt(inv.outstanding_amount):.2f} €)."
                )
            inv["allocated_amount"] = flt(explicit_alloc)
        invoices.append(inv)

    target_amount = flt(row.betrag)
    pe = create_payment_entry_for_invoices(
        bt=bt,
        invoices=invoices,
        invoice_doctype=invoice_doctype,
        target_amount=target_amount,
        leftover_as_advance=bool(int(leftover_as_advance or 0)),
    )

    reconcile_voucher_with_bt(bt, "Payment Entry", pe.name, target_amount)

    row.db_set("payment_entry", pe.name)
    row.db_set(
        "auto_match_message",
        f"Manuell zugeordnet: {len(invoices)} Rechnung(en), {target_amount:.2f} €"
        + (" (mit Vorauszahlung)" if int(leftover_as_advance or 0) else ""),
    )

    return {
        "ok": True,
        "payment_entry": pe.name,
        "invoices": [i.name for i in invoices],
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
        reconcile_voucher_with_bt,
    )

    doc, row, bt = _row_with_unreconciled_bt(docname, row_name)

    pe = create_standalone_payment_entry(
        bt=bt,
        party_type=party_type or row.get("party_type"),
        party=party or row.get("party"),
        remarks=remarks,
    )
    target_amount = flt(row.betrag)
    reconcile_voucher_with_bt(bt, "Payment Entry", pe.name, target_amount)

    row.db_set("payment_entry", pe.name)
    row.db_set(
        "auto_match_message",
        f"Manuell verbucht: Standalone Payment Entry über {target_amount:.2f} € (unallocated)",
    )
    return {"ok": True, "payment_entry": pe.name}


@frappe.whitelist()
def create_journal_entry_for_row(
    docname: str,
    row_name: str,
    account: str,
    cost_center: Optional[str] = None,
    remarks: Optional[str] = None,
) -> Dict[str, Any]:
    """Journal Entry: Bank-Konto vs. übergebenes GL-Konto.

    Eingang (deposit > 0): Bank Soll, account Haben.
    Ausgang (withdrawal > 0): Bank Haben, account Soll.

    Use-Case: Bankgebühren, Eigentümer-Entnahmen, manuelle Korrekturen ohne
    Party-Bezug.
    """
    from hausverwaltung.hausverwaltung.utils.payment_auto_match import (
        create_journal_entry_for_bt,
        reconcile_voucher_with_bt,
    )

    doc, row, bt = _row_with_unreconciled_bt(docname, row_name)

    je = create_journal_entry_for_bt(
        bt=bt,
        account=account,
        cost_center=cost_center,
        remarks=remarks,
    )
    target_amount = flt(row.betrag)
    reconcile_voucher_with_bt(bt, "Journal Entry", je.name, target_amount)

    row.db_set("journal_entry", je.name)
    row.db_set(
        "auto_match_message",
        f"Buchungssatz: {target_amount:.2f} € gegen {account}",
    )
    return {"ok": True, "journal_entry": je.name}
