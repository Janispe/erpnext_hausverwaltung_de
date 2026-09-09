"""Explicit Customer allocations belonging to one bank statement row."""

import json
from decimal import Decimal, InvalidOperation

import frappe
from frappe.utils import flt

from hausverwaltung.hausverwaltung.doctype.bankauszug_import import bankauszug_import as bi
from hausverwaltung.hausverwaltung.utils import payment_auto_match as payments


def customer_payments(row):
    value = row.get("customer_payments")
    return json.loads(value) if isinstance(value, str) and value else (value or [])


def split_vouchers(row):
    return list(
        dict.fromkeys(
            ("Journal Entry", item["journal_entry"])
            if item.get("journal_entry")
            else ("Payment Entry", item["payment_entry"])
            for item in customer_payments(row)
        )
    )


def _amount(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal("0.01")):
            raise ValueError
        return amount
    except (InvalidOperation, ValueError, TypeError):
        frappe.throw("Teilbeträge müssen positiv sein und dürfen höchstens zwei Nachkommastellen haben.")


def _contract(customer, *, for_update=False):
    frappe.get_doc("Customer", customer).check_permission("read")
    contracts = frappe.get_all(
        "Mietvertrag",
        filters={"kunde": customer, "docstatus": ["!=", 2]},
        pluck="name",
        limit=2,
    )
    if len(contracts) != 1:
        frappe.throw(f"Customer {customer} muss genau einem Mietvertrag zugeordnet sein.")
    contract = frappe.get_doc("Mietvertrag", contracts[0], for_update=for_update)
    contract.check_permission("read")
    if contract.kunde != customer or not contract.wohnung or contract.docstatus == 2:
        frappe.throw(f"Mietvertrag von {customer} hat keine eindeutige Wohnungszuordnung.")
    return contract


def _validate_contract_invoice(invoice, contract):
    if invoice.get("wohnung") and invoice.wohnung != contract.wohnung:
        frappe.throw(f"Rechnung {invoice.name} gehört nicht zur Wohnung von {contract.name}.")
    if invoice.get("mietvertrag") and invoice.mietvertrag != contract.name:
        frappe.throw(f"Rechnung {invoice.name} gehört nicht zu Mietvertrag {contract.name}.")
    structured = invoice.get("mietabrechnung_id") or ""
    if "|" in structured and structured.rsplit("|", 1)[0] != contract.name:
        frappe.throw(f"Rechnung {invoice.name} verweist auf einen anderen Mietvertrag.")


@frappe.whitelist()
def get_customer_split_invoices(docname, row_name, customer):
    doc = frappe.get_doc("Bankauszug Import", docname)
    doc.check_permission("read")
    bi._get_row_by_name(doc, row_name)
    contract = _contract(customer)
    bank = frappe.get_doc("Bank Account", doc.bank_account)
    currency = frappe.get_cached_value("Company", bank.company, "default_currency")
    invoices = frappe.get_list(
        "Sales Invoice",
        filters={
            "customer": customer,
            "company": bank.company,
            "currency": currency,
            "docstatus": 1,
            "outstanding_amount": ["!=", 0],
        },
        fields=["name", "posting_date", "remarks", "outstanding_amount"],
        order_by="posting_date asc",
        limit=200,
    )
    return {
        "invoices": invoices,
        "customer": customer,
        "contract": contract.name,
        "wohnung": contract.wohnung,
    }


def _parse_allocations(allocations):
    try:
        groups = json.loads(allocations) if isinstance(allocations, str) else allocations
    except (ValueError, TypeError):
        frappe.throw("Ungültige Zahlungsaufteilung.")
    if not isinstance(groups, list) or not 2 <= len(groups) <= 50:
        frappe.throw("Bitte mindestens zwei und höchstens 50 Customers auswählen.")
    customers, names, parsed = set(), set(), []
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("customer"), str) or not group["customer"]:
            frappe.throw("Jede Teilzahlung braucht einen Customer.")
        customer = group["customer"]
        if customer in customers:
            frappe.throw(f"Customer {customer} wurde mehrfach ausgewählt.")
        customers.add(customer)
        invoices = group.get("invoices")
        if not isinstance(invoices, list) or not invoices:
            frappe.throw(f"Bitte für {customer} mindestens einen Beleg auswählen.")
        total, selected = Decimal(0), []
        for inv in invoices:
            if not isinstance(inv, dict) or not isinstance(inv.get("name"), str) or not inv["name"]:
                frappe.throw("Jede Belegzuordnung braucht einen Rechnungsnamen.")
            if inv["name"] in names:
                frappe.throw(f"Beleg {inv['name']} wurde mehrfach ausgewählt.")
            names.add(inv["name"])
            amount = _amount(inv.get("allocated_amount"))
            total += amount
            selected.append({"name": inv["name"], "allocated_amount": float(amount)})
        parsed.append({"customer": customer, "invoices": selected, "amount": total})
    return parsed


def _create_settlement_journal(bt, groups, company, bank):
    """One real bank movement, with signed invoice legs on separate Customers."""
    if not frappe.has_permission("Journal Entry", "create") or not frappe.has_permission(
        "Journal Entry", "submit"
    ):
        frappe.throw("Keine Berechtigung zum Erstellen und Buchen der Verrechnungsbuchung.")
    shape = payments._bank_transaction_shape(bt)
    cost_center = payments._resolve_expected_cost_center_for_bt(bt, for_update=True)
    je = frappe.new_doc("Journal Entry")
    je.update(
        {
            "voucher_type": "Bank Entry",
            "company": company,
            "posting_date": bt.date,
            "cheque_no": bt.reference_number or bt.name,
            "cheque_date": bt.date,
            "user_remark": "Verrechnung Nachzahlung/Guthaben: " + (bt.description or bt.name),
        }
    )
    je.append(
        "accounts",
        {
            "account": bank.account,
            "cost_center": cost_center,
            "debit_in_account_currency": shape.amount if shape.direction == "in" else 0,
            "credit_in_account_currency": shape.amount if shape.direction == "out" else 0,
        },
    )
    for group in groups:
        for selected in group["invoices"]:
            amount = selected["signed_amount"]
            je.append(
                "accounts",
                {
                    "account": selected["account"],
                    "party_type": "Customer",
                    "party": group["customer"],
                    "reference_type": "Sales Invoice",
                    "reference_name": selected["name"],
                    "cost_center": selected["cost_center"],
                    "debit_in_account_currency": float(-amount) if amount < 0 else 0,
                    "credit_in_account_currency": float(amount) if amount > 0 else 0,
                },
            )
    je.insert()
    je.submit()
    for group in groups:
        for selected in group["invoices"]:
            outstanding = Decimal(
                str(frappe.db.get_value("Sales Invoice", selected["name"], "outstanding_amount"))
            )
            if outstanding != selected["outstanding"] - selected["signed_amount"]:
                frappe.throw(f"Der offene Betrag von {selected['name']} wurde nicht korrekt verrechnet.")
    return je


@frappe.whitelist()
def reconcile_customer_split(docname, row_name, allocations):
    groups = _parse_allocations(allocations)
    if not frappe.has_permission("Payment Entry", "create") or not frappe.has_permission(
        "Payment Entry", "submit"
    ):
        frappe.throw("Keine Berechtigung zum Erstellen und Buchen von Zahlungen.")
    savepoint = "bankimport_customer_split"
    frappe.db.savepoint(savepoint)
    try:
        _doc, row, bt = bi._row_with_unreconciled_bt(docname, row_name)
        if customer_payments(row):
            frappe.throw("Die bisherige Zahlungsaufteilung muss zuerst vollständig zurückgesetzt werden.")
        shape = payments._bank_transaction_shape(bt)
        if _amount(shape.amount) != _amount(row.betrag):
            frappe.throw("Der Bankbetrag stimmt nicht mit der Importzeile überein.")
        if (row.richtung == "Ausgang") != (shape.direction == "out"):
            frappe.throw("Die Zahlungsrichtung stimmt nicht mit dem Bankumsatz überein.")
        company, bank = payments._resolve_company_and_bank_account(bt)
        currency = payments._get_company_currency(company)

        # Validate all contract identities before creating the first voucher.
        for group in sorted(groups, key=lambda item: item["customer"]):
            contract = _contract(group["customer"], for_update=True)
            group["contract"], group["wohnung"] = contract.name, contract.wohnung
            group["signed_amount"] = Decimal(0)
            for selected in sorted(group["invoices"], key=lambda item: item["name"]):
                invoice = frappe.get_doc("Sales Invoice", selected["name"], for_update=True)
                invoice.check_permission("read")
                if invoice.customer != group["customer"]:
                    frappe.throw(f"Rechnung {invoice.name} gehört nicht zu {group['customer']}.")
                _validate_contract_invoice(invoice, contract)
                if _amount(selected["allocated_amount"]) > abs(Decimal(str(invoice.outstanding_amount))):
                    frappe.throw(f"Teilbetrag für {invoice.name} übersteigt den aktuellen offenen Betrag.")
                payments._lock_and_validate_invoices(
                    invoices=[selected],
                    invoice_doctype="Sales Invoice",
                    company=company,
                    party=group["customer"],
                    company_currency=currency,
                    credit_notes=invoice.outstanding_amount < 0,
                )
                selected["outstanding"] = Decimal(str(invoice.outstanding_amount))
                selected["signed_amount"] = _amount(selected["allocated_amount"]) * (
                    1 if invoice.outstanding_amount > 0 else -1
                )
                selected["account"] = invoice.debit_to
                selected["cost_center"] = payments._get_cost_center_of_invoice(
                    invoice.name, "Sales Invoice", for_update=True
                )
                group["signed_amount"] += selected["signed_amount"]

        total = sum((group["signed_amount"] for group in groups), Decimal(0))
        if total != Decimal(str(shape.signed_amount)):
            frappe.throw(
                "Nachzahlungen minus Guthaben müssen genau dem vorzeichenbehafteten Bankbetrag entsprechen."
            )
        mixed = len({selected["signed_amount"] > 0 for group in groups for selected in group["invoices"]}) > 1

        result = []
        journal = _create_settlement_journal(bt, groups, company, bank) if mixed else None
        if journal:
            payments.reconcile_voucher_with_bt(bt, "Journal Entry", journal.name, shape.amount)
        for group in groups:
            amount = float(group["signed_amount"] if mixed else group["amount"])
            if journal:
                voucher = {
                    "journal_entry": journal.name,
                    "invoices": [
                        {"name": selected["name"], "amount": float(selected["signed_amount"])}
                        for selected in group["invoices"]
                    ],
                }
            else:
                pe = payments.create_payment_entry_for_invoices(
                    bt=bt,
                    invoices=group["invoices"],
                    invoice_doctype="Sales Invoice",
                    target_amount=amount,
                    customer=group["customer"],
                    partial=True,
                )
                payments.reconcile_voucher_with_bt(bt, "Payment Entry", pe.name, amount, partial=True)
                voucher = {"payment_entry": pe.name}
            result.append(
                {
                    "customer": group["customer"],
                    "contract": group["contract"],
                    "wohnung": group["wohnung"],
                    **voucher,
                    "amount": amount,
                }
            )

        bt.reload()
        expected = (
            {("Journal Entry", journal.name): shape.amount}
            if journal
            else {("Payment Entry", item["payment_entry"]): item["amount"] for item in result}
        )
        actual = {
            (item.payment_document, item.payment_entry): flt(item.allocated_amount)
            for item in bt.payment_entries
        }
        if actual != expected or len(bt.payment_entries) != len(expected) or flt(bt.unallocated_amount) != 0:
            frappe.throw("Die Teilzahlungen wurden nicht vollständig mit dem Bankumsatz abgeglichen.")
        # Do not run party auto-matching again on this multi-Customer bank movement.
        bt.db_set("party_type", None)
        bt.db_set("party", None)
        row.db_set("party_type", None)
        row.db_set("party", None)
        row.db_set("customer_payments", json.dumps(result))
        row.db_set(
            "journal_entry" if journal else "payment_entry",
            journal.name if journal else result[0]["payment_entry"],
        )
        bi._set_row_payment_document(
            row,
            "Journal Entry" if journal else "Payment Entry",
            journal.name if journal else result[0]["payment_entry"],
        )
        row.db_set("row_status", "success")
        row.db_set("auto_match_message", f"Manuell auf {len(result)} Mieter aufgeteilt: {total:.2f} EUR.")
        bi._recompute_doc_status(docname)
        bi._refresh_and_persist_saldo(docname)
        return {"ok": True, "payments": result}
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise


def sync_cancelled_splits(voucher_name=None, import_name=None, voucher_doctype="Payment Entry"):
    """Keep ownership of every split, even after an external partial cancellation."""
    filters = {"parenttype": "Bankauszug Import", "customer_payments": ["is", "set"]}
    if import_name:
        filters["parent"] = import_name
    rows = frappe.get_all(
        "Bankauszug Import Row", filters=filters, fields=["name", "parent", "customer_payments", "row_status"]
    )
    affected = set()
    from hausverwaltung.hausverwaltung.utils.bank_transaction_links import (
        remove_bank_transaction_payment_links,
    )

    for row in rows:
        vouchers = split_vouchers(row)
        if voucher_name and (voucher_doctype, voucher_name) not in vouchers:
            continue
        stale = [
            (doctype, name)
            for doctype, name in vouchers
            if doctype == voucher_doctype and bi._voucher_is_cancelled_or_missing(doctype, name)
        ]
        if not stale:
            continue
        for doctype, name in stale:
            remove_bank_transaction_payment_links(doctype, name)
        frappe.db.set_value(
            "Bankauszug Import Row",
            row.name,
            {
                "payment_entry": None,
                "journal_entry": None,
                "payment_document_type": None,
                "payment_document": None,
                "row_status": "needs_review",
                "auto_match_message": "Teilzahlung storniert. Bitte die Zahlungsaufteilung vollständig zurücksetzen und neu zuordnen.",
            },
            update_modified=False,
        )
        affected.add(row.parent)
    for name in affected:
        bi._recompute_doc_status(name)
        bi._refresh_and_persist_saldo(name)


def reset_customer_split(docname, row):
    from hausverwaltung.hausverwaltung.utils.bank_transaction_links import (
        remove_bank_transaction_payment_links,
    )

    vouchers = split_vouchers(row)
    for doctype, name in sorted(vouchers):
        bi._get_doc_for_update_if_exists(doctype, name)
        if bi._other_import_row_references_voucher(
            doctype,
            name,
            exclude_row_name=row.name,
            for_update=True,
        ):
            frappe.throw(f"{doctype} {name} wird auch von einer anderen Bankimport-Zeile verwendet.")

    savepoint = "bankimport_reset_customer_split"
    frappe.db.savepoint(savepoint)
    try:
        results = []
        for doctype, name in vouchers:
            results.append(bi._cancel_voucher_for_row(doctype, name))
            remove_bank_transaction_payment_links(doctype, name)
        # The shared delink helper logs failures. Verify the postcondition before
        # discarding ownership, otherwise a failed unlink would strand payments.
        if any(
            frappe.get_all(
                "Bank Transaction Payments",
                filters={
                    "payment_document": doctype,
                    "payment_entry": name,
                },
                pluck="name",
                limit=1,
            )
            for doctype, name in vouchers
        ):
            frappe.throw(
                "Die Bankverknüpfungen konnten nicht vollständig gelöst werden. Storno zurückgerollt."
            )
        bi._clear_row_booking_links(row, "Zahlungsaufteilung vollständig zurückgesetzt.")
        bi._recompute_doc_status(docname)
        bi._refresh_and_persist_saldo(docname)
        return {"ok": True, "reset": True, "payments": results}
    except Exception:
        frappe.db.rollback(save_point=savepoint)
        raise
