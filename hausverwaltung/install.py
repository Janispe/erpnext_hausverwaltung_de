from __future__ import annotations

import json
import os
from pathlib import Path

import frappe


def after_install() -> None:
    _run_bootstrap(reason="after_install")
    _run_post_install_patches(reason="after_install")
    _ensure_party_type_eigentuemer(reason="after_install")
    _sync_hausverwalter_permissions(reason="after_install")
    _ensure_desk_custom_permissions(reason="after_install")
    _ensure_hausverwalter_extra_permissions(reason="after_install")
    _ensure_hausverwalter_blocked_modules(reason="after_install")
    _ensure_hausverwalter_report_roles(reason="after_install")
    _ensure_eigentuemer_custom_permissions(reason="after_install")
    _import_supplier_bank_transfer(reason="after_install")
    _ensure_hv_user(reason="after_install")
    _ensure_agent_readonly_user(reason="after_install")
    _ensure_currency_symbol_on_right(reason="after_install")
    _ensure_main_cost_center_disabled(reason="after_install")
    _ensure_company_account_defaults(reason="after_install")
    _ensure_dunning_serienbrief_link_fields(reason="after_install")
    _ensure_serienbrief_print_format_link_field(reason="after_install")
    _ensure_serienbrief_dokument_print_format(reason="after_install")
    _ensure_hv_dunning_print_format(reason="after_install")
    _ensure_zahlungshistorie_baustein(reason="after_install")
    _ensure_euer_print_format(reason="after_install")
    _ensure_euer_print_format_default(reason="after_install")
    _ensure_sales_invoice_written_off_status(reason="after_install")
    _ensure_open_invoices_report_filters(reason="after_install")
    _ensure_tax_features_disabled(reason="after_install")
    ensure_hausverwaltung_workspace_layout()
    ensure_hausverwaltung_sidebar()


def _ensure_serienbrief_dokument_print_format(*, reason: str) -> None:
    """Only for new installations: create the Print Format used for Serienbrief Dokument PDFs."""
    try:
        if not frappe.db.exists("DocType", "Serienbrief Dokument"):
            return
        name = "Serienbrief Dokument"
        css = """
			@page {
				size: A4;
				margin: 20mm 20mm 20mm 25mm;
			}
			body,
			.serienbrief-root,
			.print-format,
			.print-format .serienbrief-root {
				font-family: "Arial", "Helvetica", sans-serif;
				font-size: 11pt;
				line-height: 1.4;
			}
			/* Wasserzeichen: als Vollseiten-Layer, damit es nicht abgeschnitten wirkt. */
			.hv-draft-watermark-layer {
				position: fixed;
				top: 0;
				left: 0;
				right: 0;
				bottom: 0;
				z-index: 9999;
				pointer-events: none;
				user-select: none;
			}
			.hv-draft-watermark {
				position: absolute;
				top: 50%;
				left: 50%;
				width: 140%;
				text-align: center;
				line-height: 1;
				-webkit-transform: translate(-50%, -50%) rotate(-45deg);
				transform: translate(-50%, -50%) rotate(-45deg);
				-webkit-transform-origin: 50% 50%;
				transform-origin: 50% 50%;
				font-size: 110pt;
				font-weight: 700;
				letter-spacing: 0.18em;
				color: rgba(200, 0, 0, 0.14);
				text-transform: uppercase;
				white-space: nowrap;
			}
			/* Serienbrief: Briefkopf-Layout (Inhalt liefert nur Klassen; Layout kommt aus CSS) */
			.sb-letterhead {
				margin-top: 0.7cm;
			}
			.sb-address-window {
				float: left;
				width: 60%;
				padding-top: 3.2cm;
				font-size: 10pt;
				box-sizing: border-box;
			}
			.sb-return-address {
				font-size: 7pt;
				text-decoration: underline;
				margin-bottom: 0.15cm;
			}
			.sb-sender {
				float: right;
				width: 40%;
				text-align: right;
				font-size: 9pt;
				box-sizing: border-box;
			}
			.sb-office-hours {
				font-size: 7.5pt;
				margin-top: 0.15cm;
			}
			.sb-letterhead:after {
				content: "";
				display: block;
				clear: both;
			}
			.sb-date {
				margin-top: 0.5cm;
				text-align: right;
			}
			.print-format {
				margin: 0 !important;
				padding: 0 !important;
				width: 100% !important;
				max-width: 100% !important;
				box-sizing: border-box;
			}
			.serienbrief-page {
				page-break-after: always;
				padding: 0;
			}
			.serienbrief-page:last-child {
				page-break-after: auto;
			}
			.serienbrief-page p {
				margin: 0 0 8px 0;
				line-height: 1.4;
			}
			.serienbrief-block {
				margin-bottom: 12px;
			}
			.serienbrief-block:last-child {
				margin-bottom: 0;
			}
        """
        html = f"""<style>{css}</style>
{{% if doc.docstatus == 0 %}}
<div class="hv-draft-watermark-layer"><div class="hv-draft-watermark">DRAFT</div></div>
{{% endif %}}
{{{{ (doc.html or '') | safe }}}}"""

        if frappe.db.exists("Print Format", name):
            doc = frappe.get_doc("Print Format", name)
            changed = False
            if doc.doc_type != "Serienbrief Dokument":
                doc.doc_type = "Serienbrief Dokument"
                changed = True
            if doc.print_format_type != "Jinja":
                doc.print_format_type = "Jinja"
                changed = True
            if int(getattr(doc, "custom_format", 0) or 0) != 1:
                doc.custom_format = 1
                changed = True
            if (doc.html or "").strip() != html:
                doc.html = html
                changed = True
            if int(getattr(doc, "disabled", 0) or 0) != 0:
                doc.disabled = 0
                changed = True
            if changed:
                doc.save(ignore_permissions=True)
        else:
            frappe.get_doc(
                {
                    "doctype": "Print Format",
                    "name": name,
                    "doc_type": "Serienbrief Dokument",
                    "print_format_type": "Jinja",
                    "custom_format": 1,
                    "html": html,
                }
            ).insert(ignore_permissions=True)

        try:
            frappe.db.commit()
        except Exception:
            pass
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung Serienbrief Dokument Print Format setup failed ({reason})",
            )
        except Exception:
            pass


def after_migrate() -> None:
    _run_bootstrap(reason="after_migrate")
    _ensure_party_type_eigentuemer(reason="after_migrate")
    _sync_hausverwalter_permissions(reason="after_migrate")
    _ensure_eigentuemer_custom_permissions(reason="after_migrate")
    _ensure_dunning_serienbrief_link_fields(reason="after_migrate")
    _ensure_serienbrief_print_format_link_field(reason="after_migrate")
    _ensure_serienbrief_dokument_print_format(reason="after_migrate")
    _ensure_hv_dunning_print_format(reason="after_migrate")
    _ensure_zahlungshistorie_baustein(reason="after_migrate")
    _ensure_euer_print_format(reason="after_migrate")
    _ensure_sales_invoice_written_off_status(reason="after_migrate")
    _ensure_open_invoices_report_filters(reason="after_migrate")
    _ensure_tax_features_disabled(reason="after_migrate")
    _ensure_eingabequelle_fields(reason="after_migrate")
    _ensure_currency_symbol_on_right(reason="after_migrate")
    _ensure_main_cost_center_disabled(reason="after_migrate")
    _ensure_company_account_defaults(reason="after_migrate")


def ensure_company_account_defaults() -> None:
    _ensure_company_account_defaults(reason="hook")


def _ensure_company_account_defaults(*, reason: str) -> None:
    """Setzt Company-Pflicht-Default-Konten (Round Off + Stock Received But Not Billed).

    Ohne diese Defaults blockiert ERPNext z. B. das Buchen von Eingangsrechnungen
    aus dem Buchungs-Cockpit mit "Bitte Standardwert für ... in Unternehmen
    Hausverwaltung Peters setzen". Die Helper aus sample_data sind generisch und
    funktionieren auch für Production-Companies.
    """
    try:
        from hausverwaltung.hausverwaltung.data_import.sample.sample_data import (
            _ensure_round_off_account,
            _ensure_srbnb_account,
        )

        companies = frappe.get_all("Company", pluck="name")
        for company in companies:
            try:
                # Round Off zuerst — Company.save schlägt sonst beim SRBNB-Setzen fehl
                _ensure_round_off_account(company, cost_center=None)
                _ensure_srbnb_account(company)
            except Exception as exc:
                frappe.log_error(
                    frappe.get_traceback(),
                    f"hausverwaltung Company defaults für {company} fehlgeschlagen ({reason}): {exc}",
                )
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f"hausverwaltung Company defaults sync fehlgeschlagen ({reason})",
        )


def ensure_eingabequelle_fields() -> None:
    _ensure_eingabequelle_fields(reason="hook")


def _ensure_eingabequelle_fields(*, reason: str) -> None:
    try:
        from hausverwaltung.hausverwaltung.patches.post_model_sync.add_eingabequelle_to_invoices import (
            execute,
        )

        execute()
        try:
            frappe.clear_cache(doctype="Purchase Invoice")
            frappe.clear_cache(doctype="Sales Invoice")
            frappe.clear_cache(doctype="Purchase Invoice Item")
            frappe.db.commit()
        except Exception:
            pass
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung eingabequelle field setup failed ({reason})",
            )
        except Exception:
            pass


def ensure_serienbrief_dokument_print_format() -> None:
    _ensure_serienbrief_dokument_print_format(reason="hook")


def ensure_serienbrief_print_format_link_field() -> None:
    _ensure_serienbrief_print_format_link_field(reason="hook")


def ensure_dunning_serienbrief_link_fields() -> None:
    _ensure_dunning_serienbrief_link_fields(reason="hook")


def ensure_hv_dunning_print_format() -> None:
    _ensure_hv_dunning_print_format(reason="hook")


def ensure_zahlungshistorie_baustein() -> None:
    _ensure_zahlungshistorie_baustein(reason="hook")


def ensure_euer_print_format() -> None:
    _ensure_euer_print_format(reason="hook")


def ensure_tax_features_disabled() -> None:
    _ensure_tax_features_disabled(reason="hook")


def ensure_euer_print_format_default() -> None:
    _ensure_euer_print_format_default(reason="hook")


def ensure_auto_repeat_for_purchase_invoice() -> None:
    """Aktiviert Frappes ``Auto Repeat`` für Eingangsrechnungen.

    Damit erscheint im Eingangsrechnungs-Menü „Auto Repeat" und Purchase Invoice
    taucht im Reference-Doctype-Dropdown auf. Wird hauptsächlich für
    wiederkehrende Personalzahlungen (Gehälter, SV-Beiträge, Lohnsteuer) genutzt.

    Idempotent — `make_property_setter` no-opt bei bereits gesetztem Wert.
    """
    try:
        from frappe.custom.doctype.property_setter.property_setter import make_property_setter

        make_property_setter(
            "Purchase Invoice",
            "",
            "allow_auto_repeat",
            "1",
            "Check",
            for_doctype=True,
        )
        frappe.clear_cache(doctype="Purchase Invoice")
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                "hausverwaltung allow_auto_repeat property setter failed",
            )
        except Exception:
            pass


def ensure_sales_invoice_written_off_status() -> None:
    _ensure_sales_invoice_written_off_status(reason="hook")


def ensure_open_invoices_report_filters() -> None:
    _ensure_open_invoices_report_filters(reason="hook")


def _ensure_open_invoices_report_filters(*, reason: str) -> None:
    report_name = "Noch offene Rechnungen und Forderungen"
    try:
        if not frappe.db.exists("Report", report_name):
            return

        desired = [
            {
                "fieldname": "zahlungsrichtung",
                "label": "Zahlungsrichtung",
                "fieldtype": "Select",
                "options": "\nGeld bekommen\nGeld bezahlen / erstatten\nAusgeglichen",
                "mandatory": 0,
                "wildcard_filter": 0,
            },
            {
                "fieldname": "sortierung",
                "label": "Sortierung",
                "fieldtype": "Select",
                "options": "Fällig am\nRichtung: Geld bekommen zuerst\nRichtung: Geld bezahlen zuerst\nOffener Betrag absteigend",
                "default": "Fällig am",
                "mandatory": 0,
                "wildcard_filter": 0,
            },
            {
                "fieldname": "show_written_off",
                "label": "Abgeschriebene anzeigen",
                "fieldtype": "Check",
                "default": "0",
                "mandatory": 0,
                "wildcard_filter": 0,
            },
        ]

        max_idx = frappe.db.sql(
            """
            SELECT COALESCE(MAX(idx), 0)
            FROM `tabReport Filter`
            WHERE parent = %s
              AND parenttype = 'Report'
              AND parentfield = 'filters'
            """,
            report_name,
        )[0][0]

        changed = False
        for field in desired:
            name = frappe.db.get_value(
                "Report Filter",
                {
                    "parent": report_name,
                    "parenttype": "Report",
                    "parentfield": "filters",
                    "fieldname": field["fieldname"],
                },
                "name",
            )
            if name:
                for key, value in field.items():
                    if frappe.db.get_value("Report Filter", name, key) != value:
                        frappe.db.set_value("Report Filter", name, key, value, update_modified=False)
                        changed = True
                continue

            max_idx += 1
            doc = frappe.get_doc(
                {
                    "doctype": "Report Filter",
                    "parent": report_name,
                    "parenttype": "Report",
                    "parentfield": "filters",
                    "idx": max_idx,
                    **field,
                }
            )
            doc.db_insert()
            changed = True

        if changed:
            frappe.clear_cache()
            frappe.db.commit()
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung open invoices report filter setup failed ({reason})",
            )
        except Exception:
            pass


def _ensure_sales_invoice_written_off_status(*, reason: str) -> None:
    try:
        meta = frappe.get_meta("Sales Invoice")
        field = meta.get_field("status")
        if not field:
            return

        options = [option for option in (field.options or "").split("\n") if option]
        changed = False
        for option in ("Abgeschrieben", "Teilweise bezahlt und abgeschrieben"):
            if option not in options:
                options.append(option)
                changed = True

        if changed:
            from frappe.custom.doctype.property_setter.property_setter import make_property_setter

            make_property_setter(
                "Sales Invoice",
                "status",
                "options",
                "\n" + "\n".join(options),
                "Text",
                for_doctype=False,
            )
            frappe.clear_cache(doctype="Sales Invoice")
            frappe.db.commit()
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung Sales Invoice Abgeschrieben status setup failed ({reason})",
            )
        except Exception:
            pass


def _ensure_tax_features_disabled(*, reason: str) -> None:
    role_based_hidden_fields_by_doctype = {
        "Customer": [
            "tax_category",
            "tax_id",
            "tax_withholding_category",
        ],
        "Sales Invoice": [
            "tax_id",
            "company_tax_id",
            "tax_category",
            "currency_and_price_list",
            "currency",
            "conversion_rate",
            "column_break2",
            "selling_price_list",
            "price_list_currency",
            "plc_conversion_rate",
            "ignore_pricing_rule",
            "taxes_section",
            "taxes_and_charges",
            "column_break_38",
            "shipping_rule",
            "column_break_55",
            "incoterm",
            "named_place",
            "section_break_40",
            "taxes",
            "section_break_43",
            "base_total_taxes_and_charges",
            "column_break_47",
            "total_taxes_and_charges",
            "sec_tax_breakup",
            "loyalty_points_redemption",
            "redeem_loyalty_points",
            "loyalty_points",
            "loyalty_amount",
            "column_break_77",
            "loyalty_program",
            "loyalty_redemption_account",
            "loyalty_redemption_cost_center",
            "sales_team_section_break",
            "sales_partner",
            "amount_eligible_for_commission",
            "column_break10",
            "commission_rate",
            "total_commission",
            "section_break2",
            "sales_team",
        ],
        "Purchase Invoice": [
            "tax_id",
            "apply_tds",
            "tax_withholding_category",
            "tax_category",
            "taxes_section",
            "taxes_and_charges",
            "column_break_58",
            "shipping_rule",
            "column_break_49",
            "incoterm",
            "named_place",
            "section_break_51",
            "taxes",
            "base_taxes_and_charges_added",
            "base_taxes_and_charges_deducted",
            "base_total_taxes_and_charges",
            "column_break_40",
            "taxes_and_charges_added",
            "taxes_and_charges_deducted",
            "total_taxes_and_charges",
            "tax_withheld_vouchers_section",
            "tax_withheld_vouchers",
            "sec_tax_breakup",
        ],
        "Payment Entry": [
            "paid_amount_after_tax",
            "base_paid_amount_after_tax",
            "received_amount_after_tax",
            "base_received_amount_after_tax",
            "taxes_and_charges_section",
            "purchase_taxes_and_charges_template",
            "sales_taxes_and_charges_template",
            "column_break_55",
            "apply_tax_withholding_amount",
            "tax_withholding_category",
            "section_break_56",
            "taxes",
            "section_break_60",
            "base_total_taxes_and_charges",
            "column_break_61",
            "total_taxes_and_charges",
            "deductions_or_loss_section",
            "deductions",
        ],
        "Journal Entry": [
            "apply_tds",
            "tax_withholding_category",
        ],
    }
    template_doctypes = (
        "Sales Taxes and Charges Template",
        "Purchase Taxes and Charges Template",
        "Item Tax Template",
    )

    try:
        changed = False
        for doctype, fieldnames in role_based_hidden_fields_by_doctype.items():
            setter_names = []
            for fieldname in fieldnames:
                try:
                    setter_names.extend(
                        frappe.get_all(
                            "Property Setter",
                            filters={
                                "doc_type": doctype,
                                "field_name": fieldname,
                                "property": "hidden",
                            },
                            pluck="name",
                        )
                    )
                except Exception:
                    continue

            for setter_name in dict.fromkeys(setter_names):
                try:
                    frappe.delete_doc("Property Setter", setter_name, ignore_permissions=True, force=True)
                    changed = True
                except Exception:
                    continue

        for doctype in template_doctypes:
            try:
                meta = frappe.get_meta(doctype)
            except Exception:
                continue
            if not meta.has_field("disabled"):
                continue
            try:
                names = frappe.get_all(doctype, filters={"disabled": 0}, pluck="name")
            except Exception:
                continue
            for name in names:
                try:
                    frappe.db.set_value(doctype, name, "disabled", 1, update_modified=False)
                    changed = True
                except Exception:
                    continue

        if changed:
            for doctype in role_based_hidden_fields_by_doctype:
                try:
                    frappe.clear_cache(doctype=doctype)
                except Exception:
                    pass
            frappe.db.commit()
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung tax feature disable failed ({reason})",
            )
        except Exception:
            pass


def _ensure_serienbrief_print_format_link_field(*, reason: str) -> None:
    try:
        from hausverwaltung.hausverwaltung.patches.post_model_sync.add_serienbrief_vorlage_to_print_format import (
            execute,
        )

        execute()
        try:
            frappe.db.commit()
        except Exception:
            pass
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung Print Format Serienbrief field setup failed ({reason})",
            )
        except Exception:
            pass


def _ensure_dunning_serienbrief_link_fields(*, reason: str) -> None:
    try:
        from hausverwaltung.hausverwaltung.patches.post_model_sync.add_serienbrief_vorlage_to_dunning import (
            execute,
        )

        execute()
        try:
            frappe.clear_cache(doctype="Dunning")
            frappe.clear_cache(doctype="Dunning Type")
            frappe.db.commit()
        except Exception:
            pass
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung Dunning Serienbrief field setup failed ({reason})",
            )
        except Exception:
            pass


def _ensure_hv_dunning_print_format(*, reason: str) -> None:
    """Create the Print Format used to render Dunning Serienbrief Vorlagen."""
    try:
        if not frappe.db.exists("DocType", "Dunning"):
            return

        name = "HV Dunning Letter"
        html = """
<div class="hv-dunning-print">
  <div class="hv-dunning-header">
    <div class="hv-dunning-address">
      <strong>{{ doc.customer_name or doc.customer }}</strong><br>
      {{ doc.address_display or '' }}
    </div>
    <div class="hv-dunning-meta">
      <h1>{{ doc.dunning_type or 'Mahnung' }}</h1>
      <div>{{ doc.name }}</div>
      <div>{{ frappe.utils.formatdate(doc.posting_date) if doc.posting_date else '' }}</div>
    </div>
  </div>
  <div class="hv-dunning-body">{{ (doc.body_text or '') | safe }}</div>
  <div class="hv-dunning-closing">{{ (doc.closing_text or '') | safe }}</div>
</div>
        """.strip()
        css = """
.hv-dunning-print {
  font-family: Arial, Helvetica, sans-serif;
  font-size: 11pt;
  line-height: 1.45;
}
.hv-dunning-header {
  display: flex;
  justify-content: space-between;
  gap: 2rem;
  margin-bottom: 1.5rem;
}
.hv-dunning-address {
  width: 58%;
}
.hv-dunning-meta {
  width: 32%;
  text-align: right;
}
.hv-dunning-meta h1 {
  margin: 0 0 0.25rem 0;
  font-size: 20pt;
}
.hv-dunning-body p,
.hv-dunning-closing p {
  margin: 0 0 0.75rem 0;
}
        """.strip()

        desired = {
            "doc_type": "Dunning",
            "module": "Accounts",
            "default_print_language": "de",
            "standard": "No",
            "custom_format": 1,
            "disabled": 0,
            "print_format_type": "Jinja",
            "raw_printing": 0,
            "html": html,
            "css": css,
            "show_section_headings": 0,
            "line_breaks": 0,
            "absolute_value": 0,
            "print_format_builder": 0,
        }

        if frappe.db.exists("Print Format", name):
            doc = frappe.get_doc("Print Format", name)
            changed = False
            for fieldname, value in desired.items():
                if getattr(doc, fieldname, None) != value:
                    setattr(doc, fieldname, value)
                    changed = True
            if changed:
                doc.save(ignore_permissions=True)
        else:
            frappe.get_doc(
                {
                    "doctype": "Print Format",
                    "name": name,
                    **desired,
                }
            ).insert(ignore_permissions=True)

        # Pin "HV Dunning Letter" as the default print format for Dunning so users
        # don't have to pick from the dropdown each time. The stock "Dunning Letter"
        # is English and ignores our Serienbrief Vorlage logic.
        try:
            frappe.make_property_setter(
                {
                    "doctype_or_field": "DocType",
                    "doctype": "Dunning",
                    "property": "default_print_format",
                    "value": name,
                    "property_type": "Data",
                },
                validate_fields_for_doctype=False,
            )
        except Exception:
            pass

        try:
            frappe.db.commit()
        except Exception:
            pass
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung HV Dunning Letter Print Format setup failed ({reason})",
            )
        except Exception:
            pass


def _ensure_zahlungshistorie_baustein(*, reason: str) -> None:
    """Create or refresh the seeded Zahlungshistorie Serienbrief Textbaustein."""
    try:
        from hausverwaltung.hausverwaltung.patches.post_model_sync.create_zahlungshistorie_baustein import (
            execute,
        )

        execute()
        try:
            frappe.db.commit()
        except Exception:
            pass
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung Zahlungshistorie Textbaustein setup failed ({reason})",
            )
        except Exception:
            pass


def _ensure_euer_print_format(*, reason: str) -> None:
    try:
        if not frappe.db.exists("DocType", "Einnahmen Ueberschuss Rechnung"):
            return

        path = Path(
            frappe.get_app_path(
                "hausverwaltung",
                "hausverwaltung",
                "print_format",
                "einnahmenueberschussrechnungdruckformat",
                "einnahmenueberschussrechnungdruckformat.json",
            )
        )
        if not path.exists():
            return

        payload = json.loads(path.read_text(encoding="utf-8"))
        name = payload.get("name") or "EinnahmenUeberschussRechnungDruckformat"
        desired = {
            "doc_type": payload.get("doc_type"),
            "module": payload.get("module"),
            "default_print_language": payload.get("default_print_language"),
            "standard": payload.get("standard"),
            "custom_format": payload.get("custom_format"),
            "disabled": payload.get("disabled"),
            "pdf_generator": payload.get("pdf_generator"),
            "print_format_type": payload.get("print_format_type"),
            "raw_printing": payload.get("raw_printing"),
            "html": payload.get("html"),
            "css": payload.get("css"),
            "margin_top": payload.get("margin_top"),
            "margin_bottom": payload.get("margin_bottom"),
            "margin_left": payload.get("margin_left"),
            "margin_right": payload.get("margin_right"),
            "align_labels_right": payload.get("align_labels_right"),
            "show_section_headings": payload.get("show_section_headings"),
            "line_breaks": payload.get("line_breaks"),
            "absolute_value": payload.get("absolute_value"),
            "page_number": payload.get("page_number"),
            "print_format_builder": payload.get("print_format_builder"),
            "print_format_builder_beta": payload.get("print_format_builder_beta"),
        }

        if frappe.db.exists("Print Format", name):
            doc = frappe.get_doc("Print Format", name)
            changed = False
            for fieldname, value in desired.items():
                if getattr(doc, fieldname, None) != value:
                    setattr(doc, fieldname, value)
                    changed = True
            if changed:
                doc.save(ignore_permissions=True)
        else:
            frappe.get_doc(
                {
                    "doctype": "Print Format",
                    "name": name,
                    **desired,
                }
            ).insert(ignore_permissions=True)

        try:
            frappe.db.commit()
        except Exception:
            pass
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung EÜR print format sync failed ({reason})",
            )
        except Exception:
            pass


def _ensure_euer_print_format_default(*, reason: str) -> None:
    try:
        if not frappe.db.exists("DocType", "Einnahmen Ueberschuss Rechnung"):
            return
        if not frappe.db.exists("Print Format", "EinnahmenUeberschussRechnungDruckformat"):
            return

        current = (
            frappe.db.get_value(
                "DocType",
                "Einnahmen Ueberschuss Rechnung",
                "default_print_format",
            )
            or ""
        ).strip()
        if current != "EinnahmenUeberschussRechnungDruckformat":
            frappe.db.sql(
                """
                update `tabDocType`
                set default_print_format = %s
                where name = %s
                """,
                (
                    "EinnahmenUeberschussRechnungDruckformat",
                    "Einnahmen Ueberschuss Rechnung",
                ),
            )
            frappe.clear_cache(doctype="Einnahmen Ueberschuss Rechnung")
            try:
                frappe.db.commit()
            except Exception:
                pass
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung EÜR print format default setup failed ({reason})",
            )
        except Exception:
            pass


def _sync_hausverwalter_permissions(*, reason: str) -> None:
    try:
        from hausverwaltung.hausverwaltung.patches.post_model_sync.fix_hausverwalter_permissions import (
            execute as fix_hausverwalter_permissions,
        )

        fix_hausverwalter_permissions()
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung hausverwalter permission sync failed ({reason})",
            )
        except Exception:
            pass


def sync_hausverwalter_permissions() -> None:
    _sync_hausverwalter_permissions(reason="hook")


def _ensure_desk_custom_permissions(*, reason: str) -> None:
    """Preserve standard Desk helper permissions when Custom DocPerm overrides exist."""
    try:
        modules = ("Core", "Custom", "Desk", "Email", "Printing")
        permission_fields = (
            "read",
            "write",
            "create",
            "delete",
            "submit",
            "cancel",
            "amend",
            "report",
            "export",
            "import",
            "share",
            "print",
            "email",
            "select",
        )

        doctypes = frappe.get_all(
            "DocType",
            filters={"module": ["in", modules], "istable": 0},
            pluck="name",
        )

        for doctype in doctypes:
            if not frappe.db.exists("Custom DocPerm", {"parent": doctype}):
                continue
            standard_rows = frappe.get_all(
                "DocPerm",
                filters={"parent": doctype},
                fields=["role", "permlevel", "if_owner", *permission_fields],
            )
            for standard in standard_rows:
                filters = {
                    "parent": doctype,
                    "role": standard.get("role"),
                    "permlevel": int(standard.get("permlevel") or 0),
                    "if_owner": int(standard.get("if_owner") or 0),
                }
                existing = frappe.get_all("Custom DocPerm", filters=filters, fields=["name"], limit=1)
                if existing:
                    row = frappe.get_doc("Custom DocPerm", existing[0]["name"])
                    changed = False
                    for fieldname in permission_fields:
                        value = int(standard.get(fieldname) or 0)
                        if int(row.get(fieldname) or 0) != value:
                            row.set(fieldname, value)
                            changed = True
                    if changed:
                        row.save(ignore_permissions=True)
                    continue

                payload = {
                    "doctype": "Custom DocPerm",
                    "parent": doctype,
                    "parenttype": "DocType",
                    "parentfield": "permissions",
                    **filters,
                }
                for fieldname in permission_fields:
                    payload[fieldname] = int(standard.get(fieldname) or 0)
                frappe.get_doc(payload).insert(ignore_permissions=True)

        for role in ("Hausverwalter", "Hausverwalter (Buchung)"):
            if not frappe.db.exists("Role", role):
                continue

            filters = {
                "parent": "Page",
                "role": role,
                "permlevel": 0,
                "if_owner": 0,
            }
            values = {fieldname: 0 for fieldname in permission_fields}
            values.update({"read": 1, "select": 1})

            existing = frappe.get_all("Custom DocPerm", filters=filters, fields=["name"], limit=1)
            if existing:
                row = frappe.get_doc("Custom DocPerm", existing[0]["name"])
                changed = False
                for fieldname, value in values.items():
                    if int(row.get(fieldname) or 0) != value:
                        row.set(fieldname, value)
                        changed = True
                if changed:
                    row.save(ignore_permissions=True)
                continue

            frappe.get_doc(
                {
                    "doctype": "Custom DocPerm",
                    "parent": "Page",
                    "parenttype": "DocType",
                    "parentfield": "permissions",
                    **filters,
                    **values,
                }
            ).insert(ignore_permissions=True)

        frappe.clear_cache()
        frappe.db.commit()
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung desk custom permission sync failed ({reason})",
            )
        except Exception:
            pass


def ensure_desk_custom_permissions() -> None:
    _ensure_desk_custom_permissions(reason="hook")


_HAUSVERWALTER_EXTRA_DOCTYPE_PERMS: tuple[tuple[str, dict], ...] = (
    ("Payment Reconciliation", {"read": 1, "write": 1, "create": 1}),
    ("Account", {"read": 1, "write": 1, "create": 1}),
    ("Accounts Settings", {"read": 1}),
    ("GL Entry", {"read": 1}),
    ("Journal Entry", {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "print": 1, "email": 1}),
    # Customer: kein "create" — Debitoren werden automatisch beim Mietvertrag-
    # Anlegen erzeugt (über hausverwaltung.utils.customer.get_or_create_customer
    # mit ignore_permissions=True). Manuelles Anlegen über die Mieter-Liste ist
    # daher nicht erlaubt. "create": 0 ist explizit, damit die Sync-Funktion ein
    # eventuell vorhandenes create=1 in der DB überschreibt.
    ("Customer", {"read": 1, "write": 1, "create": 0}),
    ("Dunning", {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "print": 1, "email": 1}),
    ("Dunning Type", {"read": 1}),
    ("Bank Account", {"read": 1, "write": 1, "create": 1}),
    # Bank: read reicht — wird beim Bank-Account-Anlegen aus dem BIC abgeleitet,
    # neue Banken legen Admins an. Ohne read antwortet Frappe mit "Nicht gefunden"
    # auf dem Bank-Account-Form, weil das Link-Feld die Bank nicht laden kann.
    ("Bank", {"read": 1}),
    # Contact + Address: zentrale Stammdaten für Mieter/Lieferanten. Hausverwalter
    # muss read/write/create können — Mieter-Telefon/E-Mail ändern, neuen Contact
    # für neuen Mieter über get_or_create_contact anlegen, Adresse pflegen. delete
    # bewusst NICHT erlaubt (zu gefährlich, zerstört verlinkte Belege).
    ("Contact", {"read": 1, "write": 1, "create": 1}),
    ("Address", {"read": 1, "write": 1, "create": 1}),
    ("Cost Center", {"read": 1}),
    # Buchhaltungs-Belege — werden vom Mietrechnungen Durchlauf, Bankauszug Import,
    # manueller Erfassung und Auto-Match-Pipeline angelegt.
    ("Sales Invoice", {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1, "print": 1, "email": 1}),
    ("Purchase Invoice", {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1, "print": 1, "email": 1}),
    ("Payment Entry", {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "amend": 1, "print": 1, "email": 1}),
    ("Bank Transaction", {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1, "print": 1}),
    # Stammdaten für Sales/Purchase Invoice
    ("Item", {"read": 1, "write": 1, "create": 1}),
    ("Item Group", {"read": 1}),
    ("Supplier", {"read": 1, "write": 1, "create": 1}),
    ("Supplier Group", {"read": 1}),
    ("Customer Group", {"read": 1}),
    ("UOM", {"read": 1}),
    ("Tax Withholding Category", {"read": 1}),
)


def _ensure_hausverwalter_extra_permissions(*, reason: str) -> None:
    """Grant Hausverwalter access to accounting tools that aren't covered by stock roles.

    `Payment Reconciliation` (the allocator tool) doesn't get a permission row from any of the
    stock roles assigned to Hausverwalter, so without an explicit Custom DocPerm the workspace
    link is filtered out and the tool is unreachable.
    """
    try:
        for role in ("Hausverwalter", "Hausverwalter (Buchung)"):
            if not frappe.db.exists("Role", role):
                continue
            for doctype, perms in _HAUSVERWALTER_EXTRA_DOCTYPE_PERMS:
                if not frappe.db.exists("DocType", doctype):
                    continue
                filters = {"parent": doctype, "role": role, "permlevel": 0, "if_owner": 0}
                existing = frappe.get_all("Custom DocPerm", filters=filters, fields=["name"], limit=1)
                if existing:
                    row = frappe.get_doc("Custom DocPerm", existing[0]["name"])
                    changed = False
                    for k, v in perms.items():
                        if int(row.get(k) or 0) != v:
                            row.set(k, v)
                            changed = True
                    if changed:
                        row.save(ignore_permissions=True)
                else:
                    frappe.get_doc({
                        "doctype": "Custom DocPerm",
                        "parenttype": "DocType",
                        "parentfield": "permissions",
                        **filters,
                        **perms,
                    }).insert(ignore_permissions=True)
        frappe.clear_cache()
        frappe.db.commit()
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung Hausverwalter accounting perm sync failed ({reason})",
            )
        except Exception:
            pass


def ensure_hausverwalter_extra_permissions() -> None:
    _ensure_hausverwalter_extra_permissions(reason="hook")


# Modules that should NOT appear as Workspace Sidebars for Hausverwalter users.
# Hausverwalter still has Sales Invoice, Payment Entry etc. via the HV workspace —
# blocking the module just hides the redundant Banking/Invoicing/Buying sidebars.
_HAUSVERWALTER_BLOCKED_MODULES: tuple[str, ...] = (
    "Accounts",
    "Assets",
    "Automation",
    "Buying",
    "CRM",
    "EDI",
    "ERPNext Integrations",
    "Maintenance",
    "Manufacturing",
    "Portal",
    "Projects",
    "Quality Management",
    "Regional",
    "Selling",
    "Stock",
    "Subcontracting",
    "Support",
    "Website",
)
_HAUSVERWALTER_ROLES = {"Hausverwalter", "Hausverwalter (Buchung)"}
_OVERRIDE_ROLES = {"System Manager", "Accounts Manager", "Sales Manager", "Stock Manager", "Manufacturing Manager"}


def _ensure_hausverwalter_blocked_modules(*, reason: str) -> None:
    """Hide non-Hausverwaltung Workspace Sidebars from Hausverwalter users.

    Frappe filters Workspace Sidebars by `user.allow_modules` (= all modules - block_modules).
    Without this, navigating to e.g. a Dunning form replaces the HV sidebar with the
    standard ERPNext "Banking"/"Bankwesen" sidebar, which is confusing.

    Skips users that also carry any *Manager role — those are intentionally privileged.
    """
    try:
        if not frappe.db.exists("DocType", "Module Def"):
            return

        candidate_users = frappe.get_all(
            "Has Role",
            filters={"role": ("in", list(_HAUSVERWALTER_ROLES))},
            pluck="parent",
            distinct=True,
        )

        for user_name in candidate_users:
            if user_name in ("Administrator", "Guest"):
                continue
            user_roles = set(frappe.get_all("Has Role", filters={"parent": user_name}, pluck="role"))
            if user_roles & _OVERRIDE_ROLES:
                continue
            try:
                user_doc = frappe.get_doc("User", user_name)
            except Exception:
                continue
            existing_blocked = {row.module for row in (user_doc.block_modules or [])}
            changed = False
            for module in _HAUSVERWALTER_BLOCKED_MODULES:
                if not frappe.db.exists("Module Def", module):
                    continue
                if module in existing_blocked:
                    continue
                user_doc.append("block_modules", {"module": module})
                changed = True
            if changed:
                user_doc.flags.ignore_permissions = True
                user_doc.flags.ignore_validate = True
                user_doc.save(ignore_permissions=True)
        frappe.db.commit()
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung Hausverwalter blocked modules sync failed ({reason})",
            )
        except Exception:
            pass


def ensure_hausverwalter_blocked_modules() -> None:
    _ensure_hausverwalter_blocked_modules(reason="hook")


def ensure_hausverwaltung_workspace_layout() -> None:
    """Keep the Hausverwaltung workspace authoritative and remove legacy report workspaces.

    Creates the Workspace stub if it doesn't exist (e.g. after a fresh import that wiped
    workspaces along with demo data), so the layout-apply step always has something to write to.
    """
    try:
        if frappe.db.exists("Workspace", "Hausverwaltung Reports"):
            frappe.delete_doc("Workspace", "Hausverwaltung Reports", ignore_permissions=True, force=True)

        if frappe.db.exists("Workspace", "Reports"):
            frappe.delete_doc("Workspace", "Reports", ignore_permissions=True, force=True)

        if not frappe.db.exists("Workspace", "Hausverwaltung"):
            ws = frappe.new_doc("Workspace")
            ws.title = "Hausverwaltung"
            ws.label = "Hausverwaltung"
            ws.module = "Hausverwaltung"
            ws.public = 1
            ws.is_hidden = 0
            ws.icon = "table_2"
            ws.flags.ignore_links = True
            ws.flags.ignore_mandatory = True
            ws.insert(ignore_permissions=True)

        _apply_hausverwaltung_workspace_layout()

        frappe.clear_cache()
        frappe.db.commit()
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                "hausverwaltung workspace layout sync failed",
            )
        except Exception:
            pass


# Canonical layout for the Hausverwaltung workspace (sidebar + content).
# Order here defines the order users see. Edit here to change both surfaces.
_HAUSVERWALTUNG_CARD_SECTIONS: list[dict] = [
    {
        "label": "Buchen",
        "icon": "receipt",
        "links": [
            {"label": "Buchungs-Cockpit", "link_type": "Page", "link_to": "buchen_cockpit"},
            # Eingangsrechnung = Lieferantenrechnung (Purchase Invoice)
            {"label": "Eingangsrechnung", "link_type": "DocType", "link_to": "Purchase Invoice"},
            # Ausgangsrechnung = Mieter-/Kundenrechnung (Sales Invoice)
            {"label": "Ausgangsrechnung", "link_type": "DocType", "link_to": "Sales Invoice"},
            {"label": "Abschlagsplan/Zahlungsplan", "link_type": "DocType", "link_to": "Zahlungsplan"},
            {"label": "Zahlungsabgleich", "link_type": "DocType", "link_to": "Payment Reconciliation"},
            {"label": "Noch offene Rechnungen und Forderungen", "link_type": "Report", "link_to": "Noch offene Rechnungen und Forderungen"},
            {"label": "Mahnung", "link_type": "DocType", "link_to": "Dunning"},
            {"label": "Buchungssatz (Journal Entry)", "link_type": "DocType", "link_to": "Journal Entry"},
            {"label": "Kontenplan", "link_type": "DocType", "link_to": "Account"},
        ],
    },
    {
        "label": "Bank",
        "icon": "money-coins-1",
        "links": [
            {"label": "Import Bank CSV", "link_type": "DocType", "link_to": "Bankauszug Import"},
            {"label": "Bankkonto", "link_type": "DocType", "link_to": "Bank Account"},
        ],
    },
    {
        "label": "Stammdaten",
        "icon": "database",
        "links": [
            {"label": "Immobilie", "link_type": "DocType", "link_to": "Immobilie"},
            {"label": "Wohnung", "link_type": "DocType", "link_to": "Wohnung"},
            {"label": "Mietvertrag", "link_type": "DocType", "link_to": "Mietvertrag"},
            {"label": "Debitor (Mieter)", "link_type": "DocType", "link_to": "Customer"},
            {"label": "Eigentümer", "link_type": "DocType", "link_to": "Eigentuemer"},
            {"label": "Telefonnummern", "link_type": "DocType", "link_to": "Telefonnummernauszug"},
        ],
    },
    {
        "label": "Betriebskosten",
        "icon": "accounting",
        "links": [
            {"label": "Betriebskostenabrechnung erstellen", "link_type": "DocType", "link_to": "Betriebskostenabrechnung Immobilie"},
            {"label": "Betriebskosten Art", "link_type": "DocType", "link_to": "Betriebskostenart"},
        ],
    },
    {
        "label": "Serienbriefe",
        "icon": "mail",
        "links": [
            {"label": "Serienbrief Vorlage", "link_type": "Page", "link_to": "serienbrief_vorlagenbaum"},
            {"label": "Serienbrief Durchlauf", "link_type": "DocType", "link_to": "Serienbrief Durchlauf"},
            {"label": "Sprachnotiz Aufnahme", "link_type": "Page", "link_to": "sprachnotiz-aufnahme"},
        ],
    },
    {
        "label": "Berichte",
        "icon": "sheet",
        "links": [
            {"label": "EÜR", "link_type": "DocType", "link_to": "Einnahmen Ueberschuss Rechnung"},
            {"label": "Mieterkonto", "link_type": "Report", "link_to": "Mieterkonto"},
            {"label": "Mietrechnungsprüfung", "link_type": "Report", "link_to": "Mietrechnungspruefung"},
            {"label": "Offene Abschlagszahlungen", "link_type": "Report", "link_to": "Offene Abschlagszahlungen"},
            {"label": "Kontostand alle Konten", "link_type": "Report", "link_to": "Kontostand alle Konten"},
            {"label": "Mieten Übersicht", "link_type": "Report", "link_to": "Miete pro qm"},
            {"label": "Staffelmieterhöhungen", "link_type": "Report", "link_to": "Staffelmieterhoehungen"},
        ],
    },
    {
        "label": "Einstellungen",
        "icon": "setting-gear",
        "links": [
            {"label": "Hausverwaltung Einstellungen", "link_type": "DocType", "link_to": "Hausverwaltung Einstellungen"},
            {"label": "Kostenart (umlagefähig)", "link_type": "DocType", "link_to": "Betriebskostenart"},
            {"label": "Kostenart (nicht umlagefähig)", "link_type": "DocType", "link_to": "Kostenart nicht umlagefaehig"},
        ],
    },
]

_HAUSVERWALTUNG_TOP_SHORTCUTS: list[dict] = [
    {"label": "Alle Immobilien", "type": "Page", "link_to": "immobilienbaumansich", "color": "Green"},
    {"label": "Mieten sollstellen", "type": "DocType", "link_to": "Mietrechnungen Durchlauf", "color": "Blue"},
    {"label": "Buchungs-Cockpit", "type": "Page", "link_to": "buchen_cockpit", "color": "Purple"},
    {"label": "Email", "type": "DocType", "link_to": "Communication", "color": "Grey"},
]


def _apply_hausverwaltung_workspace_layout() -> None:
    # Content JSON: header + top shortcuts + section cards
    content_blocks: list[dict] = [
        {"id": "hv_header", "type": "header", "data": {"text": '<span class="h4">Hausverwaltung</span>', "col": 12}},
    ]
    for sc in _HAUSVERWALTUNG_TOP_SHORTCUTS:
        content_blocks.append({
            "id": f"hv_sc_{_slug(sc['label'])}",
            "type": "shortcut",
            "data": {"shortcut_name": sc["label"], "col": 3},
        })
    for section in _HAUSVERWALTUNG_CARD_SECTIONS:
        content_blocks.append({
            "id": f"hv_card_{_slug(section['label'])}",
            "type": "card",
            "data": {"card_name": section["label"], "col": 4},
        })
    frappe.db.set_value("Workspace", "Hausverwaltung", "content", json.dumps(content_blocks))

    # Wipe all existing links/shortcuts for a clean rebuild (keeps DB authoritative to code).
    frappe.db.delete("Workspace Link", {"parent": "Hausverwaltung"})
    frappe.db.delete("Workspace Shortcut", {"parent": "Hausverwaltung"})

    idx = 1
    for section in _HAUSVERWALTUNG_CARD_SECTIONS:
        frappe.get_doc({
            "doctype": "Workspace Link",
            "parent": "Hausverwaltung",
            "parenttype": "Workspace",
            "parentfield": "links",
            "idx": idx,
            "type": "Card Break",
            "label": section["label"],
            "link_count": len(section["links"]),
            "hidden": 0,
            "onboard": 0,
        }).insert(ignore_permissions=True)
        idx += 1
        for link in section["links"]:
            frappe.get_doc({
                "doctype": "Workspace Link",
                "parent": "Hausverwaltung",
                "parenttype": "Workspace",
                "parentfield": "links",
                "idx": idx,
                "type": "Link",
                "label": link["label"],
                "link_type": link["link_type"],
                "link_to": link["link_to"],
                "hidden": 0,
                "onboard": 0,
            }).insert(ignore_permissions=True)
            idx += 1

    for sc_idx, sc in enumerate(_HAUSVERWALTUNG_TOP_SHORTCUTS, start=1):
        frappe.get_doc({
            "doctype": "Workspace Shortcut",
            "parent": "Hausverwaltung",
            "parenttype": "Workspace",
            "parentfield": "shortcuts",
            "idx": sc_idx,
            "label": sc["label"],
            "type": sc["type"],
            "link_to": sc["link_to"],
            "color": sc.get("color"),
        }).insert(ignore_permissions=True)


def _slug(text: str) -> str:
    return "".join(c.lower() if c.isalnum() else "_" for c in text).strip("_")


def ensure_hausverwaltung_sidebar() -> None:
    """Rebuild the v16 Workspace Sidebar for Hausverwaltung to match the workspace layout."""
    try:
        if not frappe.db.exists("DocType", "Workspace Sidebar"):
            return  # older versions
        if not frappe.db.exists("Workspace", "Hausverwaltung"):
            return

        # Recreate from scratch so order/labels match code.
        if frappe.db.exists("Workspace Sidebar", "Hausverwaltung"):
            frappe.delete_doc("Workspace Sidebar", "Hausverwaltung", force=True, ignore_permissions=True)

        sidebar = frappe.new_doc("Workspace Sidebar")
        sidebar.title = "Hausverwaltung"
        sidebar.module = "Hausverwaltung"
        sidebar.header_icon = "table_2"

        items: list[dict] = []
        idx = 0

        def add(item: dict) -> None:
            nonlocal idx
            item["idx"] = idx
            items.append(item)
            idx += 1

        # Top shortcuts (daily drivers)
        add({"label": "Alle Immobilien", "type": "Link", "link_type": "Page", "link_to": "immobilienbaumansich", "icon": "list-tree"})
        add({"label": "Mieten sollstellen", "type": "Link", "link_type": "DocType", "link_to": "Mietrechnungen Durchlauf", "icon": "calendar-sync"})
        # Sections mirror the workspace cards
        for section in _HAUSVERWALTUNG_CARD_SECTIONS:
            add({
                "type": "Section Break",
                "label": section["label"],
                "collapsible": 1,
                "indent": 1,
                "icon": section.get("icon"),
            })
            for link in section["links"]:
                add({
                    "label": link["label"],
                    "type": "Link",
                    "link_type": link["link_type"],
                    "link_to": link["link_to"],
                    "child": 1,
                    "icon": link.get("icon"),
                })
        for data in items:
            sidebar.append("items", data)

        sidebar.insert(ignore_permissions=True)
        frappe.clear_cache()
        frappe.db.commit()
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                "hausverwaltung sidebar sync failed",
            )
        except Exception:
            pass


def ensure_hausverwalter_workspace_visibility() -> None:
    """Hide non-Hausverwaltung workspaces from Hausverwalter users.

    - Hausverwaltung: explicitly allow Hausverwalter, Hausverwalter (Buchung), System Manager.
    - Every other currently-unrestricted workspace: add System Manager so stock workspaces disappear
      for users that only have Hausverwalter roles. Workspaces that already carry role restrictions
      are left alone so existing ERPNext manager roles keep working.
    """
    try:
        hv_workspaces = {"Hausverwaltung"}
        admin_role = "System Manager"
        hv_roles = ["Hausverwalter", "Hausverwalter (Buchung)", admin_role]

        def _save_roles(doc) -> None:
            # Stock ERPNext workspaces can carry dangling links or miss
            # mandatory fields — bypass both since we only touch the roles table.
            doc.flags.ignore_links = True
            doc.flags.ignore_mandatory = True
            doc.save(ignore_permissions=True)

        for ws in hv_workspaces:
            if not frappe.db.exists("Workspace", ws):
                continue
            try:
                doc = frappe.get_doc("Workspace", ws)
                existing = {r.role for r in (doc.roles or [])}
                changed = False
                for role in hv_roles:
                    if role in existing or not frappe.db.exists("Role", role):
                        continue
                    doc.append("roles", {"role": role})
                    changed = True
                if changed:
                    _save_roles(doc)
            except Exception:
                frappe.log_error(frappe.get_traceback(), f"workspace roles sync failed: {ws}")

        others = frappe.get_all(
            "Workspace",
            filters={"name": ["not in", list(hv_workspaces)]},
            pluck="name",
        )
        for ws in others:
            try:
                doc = frappe.get_doc("Workspace", ws)
                if doc.roles:
                    continue
                doc.append("roles", {"role": admin_role})
                _save_roles(doc)
            except Exception:
                frappe.log_error(frappe.get_traceback(), f"workspace roles sync failed: {ws}")

        frappe.clear_cache()
        frappe.db.commit()
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                "hausverwaltung workspace visibility sync failed",
            )
        except Exception:
            pass


def ensure_hausverwalter_desktop_icon_visibility() -> None:
    """Hide legacy /desk Desktop Icon tiles from Hausverwalter roles.

    The /desk landing page in v16 still renders tiles from the legacy Desktop Icon
    DocType. Workspace role restrictions don't govern these tiles, so we have to
    restrict them explicitly. We add 'System Manager' to every icon except the
    Hausverwaltung-owned ones, leaving Administrator untouched.
    """
    try:
        if not frappe.db.exists("DocType", "Desktop Icon"):
            return

        keep_visible = {"Hausverwaltung"}
        admin_role = "System Manager"

        icons = frappe.get_all(
            "Desktop Icon",
            filters={"label": ["not in", list(keep_visible)]},
            pluck="name",
        )

        for icon_name in icons:
            try:
                doc = frappe.get_doc("Desktop Icon", icon_name)
                existing = {r.role for r in (doc.get("roles") or [])}
                if admin_role in existing:
                    continue
                doc.append("roles", {"role": admin_role})
                doc.flags.ignore_links = True
                doc.flags.ignore_mandatory = True
                doc.save(ignore_permissions=True)
            except Exception:
                frappe.log_error(frappe.get_traceback(), f"desktop icon role sync failed: {icon_name}")

        # Bust cached desktop icons so existing sessions see the change on next load.
        try:
            frappe.cache.delete_key("desktop_icons")
        except Exception:
            pass
        frappe.clear_cache()
        frappe.db.commit()
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                "hausverwaltung desktop icon visibility sync failed",
            )
        except Exception:
            pass


_HAUSVERWALTER_EXTRA_REPORTS = (
    # ERPNext-Standard-Reports die Hausverwalter für tägliche Buchhaltung brauchen.
    # Werden zusätzlich zu Module='Hausverwaltung'-Reports freigeschaltet.
    "General Ledger",
    "Trial Balance",
    "Accounts Receivable",
    "Accounts Receivable Summary",
    "Accounts Payable",
    "Accounts Payable Summary",
    "Bank Reconciliation Statement",
    "Bank Clearance Summary",
    "Cash Flow",
    "Balance Sheet",
    "Profit and Loss Statement",
    "Sales Register",
    "Purchase Register",
)


def _ensure_hausverwalter_report_roles(*, reason: str) -> None:
    """Ensure Hausverwaltung + Standard-Buchhaltungs-Reports für Hausverwalter sichtbar."""
    try:
        hv_reports = frappe.get_all(
            "Report",
            filters={"module": "Hausverwaltung", "disabled": 0},
            pluck="name",
        )
        # Plus ERPNext-Standard-Reports (falls auf der Site installiert).
        extra_reports = [
            r for r in _HAUSVERWALTER_EXTRA_REPORTS if frappe.db.exists("Report", r)
        ]
        report_names = list(dict.fromkeys(list(hv_reports) + extra_reports))
        target_roles = ("Hausverwalter", "Hausverwalter (Buchung)")

        for report_name in report_names:
            frappe.db.sql(
                """
                delete from `tabHas Role`
                where parenttype = 'Report'
                    and parent = %s
                    and (role is null or role = '')
                """,
                report_name,
            )

            existing_roles = {
                row.role
                for row in frappe.get_all(
                    "Has Role",
                    filters={"parenttype": "Report", "parent": report_name},
                    fields=["role"],
                )
                if row.role
            }
            max_idx = max(
                [
                    int(row.idx or 0)
                    for row in frappe.get_all(
                        "Has Role",
                        filters={"parenttype": "Report", "parent": report_name},
                        fields=["idx"],
                    )
                ]
                or [0]
            )

            for role in target_roles:
                if role in existing_roles:
                    continue
                max_idx += 1
                frappe.get_doc(
                    {
                        "doctype": "Has Role",
                        "parent": report_name,
                        "parenttype": "Report",
                        "parentfield": "roles",
                        "idx": max_idx,
                        "role": role,
                    }
                ).insert(ignore_permissions=True)

        frappe.clear_cache()
        frappe.db.commit()
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung report role sync failed ({reason})",
            )
        except Exception:
            pass


def ensure_hausverwalter_report_roles() -> None:
    _ensure_hausverwalter_report_roles(reason="hook")


def _ensure_eigentuemer_custom_permissions(*, reason: str) -> None:
    """When Custom DocPerm exists for Eigentuemer, ensure HV roles keep create rights."""
    try:
        if not frappe.db.exists("DocType", "Eigentuemer"):
            return

        roles = ("Hausverwalter", "Hausverwalter (Buchung)")
        target = {
            "read": 1,
            "write": 1,
            "create": 1,
            "delete": 0,
            "submit": 0,
            "cancel": 0,
            "amend": 0,
            "report": 1,
            "export": 1,
            "import": 1,
            "share": 1,
            "print": 1,
            "email": 1,
            "select": 1,
        }

        for role in roles:
            existing = frappe.get_all(
                "Custom DocPerm",
                filters={"parent": "Eigentuemer", "role": role, "permlevel": 0, "if_owner": 0},
                fields=["name"],
                limit=1,
            )

            if existing:
                row = frappe.get_doc("Custom DocPerm", existing[0]["name"])
                changed = False
                for fieldname, value in target.items():
                    if int(row.get(fieldname) or 0) != value:
                        row.set(fieldname, value)
                        changed = True
                if changed:
                    row.save(ignore_permissions=True)
                continue

            payload = {
                "doctype": "Custom DocPerm",
                "parent": "Eigentuemer",
                "role": role,
                "permlevel": 0,
                "if_owner": 0,
            }
            payload.update(target)
            frappe.get_doc(payload).insert(ignore_permissions=True)

        try:
            frappe.db.commit()
        except Exception:
            pass
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung eigentuemer custom permissions failed ({reason})",
            )
        except Exception:
            pass


def _run_bootstrap(*, reason: str) -> None:
    try:
        from hausverwaltung.hausverwaltung.scripts.bootstrap_site import run

        res = run()
        try:
            frappe.logger("hausverwaltung").info("bootstrap_site (%s): %s", reason, res)
        except Exception:
            pass
    except Exception:
        try:
            frappe.log_error(frappe.get_traceback(), f"hausverwaltung bootstrap_site failed ({reason})")
        except Exception:
            pass


_POST_INSTALL_PATCHES: tuple[str, ...] = (
    # These patches seed required defaults and are safe/idempotent.
    "hausverwaltung.hausverwaltung.patches.post_model_sync.create_hausverwalter_role",
    # Ensure rent-related service items exist for invoice creation.
    "hausverwaltung.hausverwaltung.patches.post_model_sync.ensure_rent_items",
    # Ensure accounting dimension exists even when Patch Handler isn't executed on fresh installs.
    "hausverwaltung.hausverwaltung.patches.post_model_sync.add_accounting_dimension_wohnung",
    # Ensure workflow exists on fresh installs as well.
    "hausverwaltung.hausverwaltung.patches.post_model_sync.create_mieterwechsel_workflow",
    # Seed default process versions for the Mieterwechsel builder.
    "hausverwaltung.hausverwaltung.patches.post_model_sync.create_mieterwechsel_process_versions",
    # Seed v2 typed task versions for the Mieterwechsel builder.
    "hausverwaltung.hausverwaltung.patches.post_model_sync.create_mieterwechsel_process_versions_v2",
    # Reset broken custom permission overrides for Mieterwechsel/Wohnung where Hausverwalter rights are missing.
    "hausverwaltung.hausverwaltung.patches.post_model_sync.reset_mieterwechsel_permissions",
    # Remove the deprecated generic process doctypes from active development sites.
    "hausverwaltung.hausverwaltung.patches.post_model_sync.remove_legacy_vorgang_components",
    # Remove legacy agent custom overrides and normalize as DocPerm on install.
    "hausverwaltung.hausverwaltung.patches.post_model_sync.normalize_agent_readonly_permissions",
    # Temporal orchestration owns transitions; keep workflow records as history only.
    "hausverwaltung.hausverwaltung.patches.post_model_sync.disable_core_workflows_for_temporal",
    # Migrate legacy Immobilie account fields into child tables.
    "hausverwaltung.hausverwaltung.patches.post_model_sync.migrate_immobilie_accounts_to_child_tables",
)


def _run_post_install_patches(*, reason: str) -> None:
    for patch in _POST_INSTALL_PATCHES:
        try:
            execute = frappe.get_attr(f"{patch}.execute")
        except Exception:
            _log_install_error(title=f"hausverwaltung post-install patch import failed ({reason})", patch=patch)
            continue

        try:
            execute()
            if _should_mark_patch_executed(patch):
                _mark_patch_executed(patch)
        except Exception:
            _log_install_error(title=f"hausverwaltung post-install patch failed ({reason})", patch=patch)

    try:
        frappe.db.commit()
    except Exception:
        pass


def _ensure_workspace_report_link(
    *,
    workspace: str,
    label: str,
    report_name: str,
    after_label: str,
) -> None:
    if frappe.db.exists("Workspace Link", {"parent": workspace, "link_to": report_name}):
        return

    insertion_after = (
        frappe.db.get_value(
            "Workspace Link",
            {"parent": workspace, "label": after_label, "type": "Link"},
            "idx",
        )
        or 5
    )
    frappe.db.sql(
        """
        UPDATE `tabWorkspace Link`
        SET idx = idx + 1
        WHERE parent = %s
          AND idx > %s
        """,
        (workspace, insertion_after),
    )
    frappe.get_doc(
        {
            "doctype": "Workspace Link",
            "parent": workspace,
            "parenttype": "Workspace",
            "parentfield": "links",
            "idx": int(insertion_after) + 1,
            "type": "Link",
            "label": label,
            "link_type": "Report",
            "link_to": report_name,
            "is_query_report": 1,
            "hidden": 0,
            "onboard": 0,
            "link_count": 0,
        }
    ).insert(ignore_permissions=True)


def _mark_patch_executed(patch: str) -> None:
    # Keep Patch Log in sync so `bench migrate` won't re-run these.
    try:
        if not frappe.db.table_exists("Patch Log"):
            return
    except Exception:
        return

    try:
        if frappe.db.exists("Patch Log", {"patch": patch}):
            return
    except Exception:
        pass

    try:
        frappe.get_doc({"doctype": "Patch Log", "patch": patch}).insert(ignore_permissions=True)
    except Exception:
        pass


def _should_mark_patch_executed(patch: str) -> bool:
    # Avoid "marking as executed" when preconditions aren't met yet; then `bench migrate` can still apply it.
    try:
        if patch.endswith("create_hausverwalter_role"):
            if not frappe.db.table_exists("DocType"):
                return False
            count = int(frappe.db.count("DocType", {"module": "Hausverwaltung"}) or 0)
            return count > 0

        if patch.endswith("add_accounting_dimension_wohnung"):
            # Only mark as executed when ERPNext + our reference DocType are present,
            # otherwise `bench migrate` should still be able to apply it later.
            if not frappe.db.exists("DocType", "Accounting Dimension"):
                return False
            return bool(frappe.db.exists("DocType", "Wohnung"))

        if patch.endswith("ensure_rent_items"):
            return bool(frappe.db.exists("DocType", "Item"))

        if patch.endswith("create_mieterwechsel_workflow"):
            return bool(frappe.db.exists("DocType", "Mieterwechsel"))

        if patch.endswith("create_mieterwechsel_process_versions"):
            return bool(frappe.db.exists("DocType", "Prozess Version"))

        if patch.endswith("create_mieterwechsel_process_versions_v2"):
            return bool(frappe.db.exists("DocType", "Prozess Version"))

        if patch.endswith("ensure_mieterwechsel_process_version_seeded"):
            return bool(frappe.db.exists("Prozess Version", {"runtime_doctype": "Mieterwechsel"}))

        if patch.endswith("reset_mieterwechsel_permissions"):
            return bool(frappe.db.exists("DocType", "Mieterwechsel"))

        if patch.endswith("remove_legacy_vorgang_components"):
            return not bool(frappe.db.exists("DocType", "Vorgang"))

        if patch.endswith("remove_mieterwechsel_specific_process_version_components"):
            return not bool(frappe.db.exists("DocType", "Mieterwechsel Prozessversion"))

        if patch.endswith("remove_mieterwechsel_specific_process_task_components"):
            return not bool(frappe.db.exists("DocType", "Mieterwechsel Aufgabe"))

        if patch.endswith("normalize_agent_readonly_permissions"):
            return bool(frappe.db.exists("DocType", "DocType"))
        if patch.endswith("disable_core_workflows_for_temporal"):
            return bool(frappe.db.exists("DocType", "Workflow"))

    except Exception:
        return False

    return True


def _log_install_error(*, title: str, patch: str) -> None:
    try:
        frappe.log_error(frappe.get_traceback(), f"{title}: {patch}")
    except Exception:
        pass


def _ensure_party_type_eigentuemer(*, reason: str) -> None:
    try:
        from hausverwaltung.hausverwaltung.patches.post_model_sync.ensure_party_type_eigentuemer import (
            execute as ensure_party_type_eigentuemer,
        )

        ensure_party_type_eigentuemer()
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung ensure party type eigentuemer failed ({reason})",
            )
        except Exception:
            pass


def _conf_str(key: str) -> str:
    try:
        return str(frappe.conf.get(key) or "").strip()
    except Exception:
        return ""


def _conf_bool(key: str, default: bool = False) -> bool:
    value = _conf_str(key)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _is_truthy(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _default_supplier_bank_transfer_dir() -> Path:
    app_root = Path(frappe.get_app_path("hausverwaltung")).parent
    return app_root / "import" / "supplier_bank_transfer"


def _latest_json_file(folder: Path) -> str:
    if not folder.exists() or not folder.is_dir():
        return ""

    files = [path for path in folder.glob("*.json") if path.is_file()]
    if not files:
        return ""

    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return str(files[0])


def _resolve_supplier_bank_transfer_path(raw_path: str) -> str:
    candidate = (raw_path or "").strip()
    if candidate:
        path = Path(candidate)
        if path.is_dir():
            return _latest_json_file(path)
        if path.exists() and path.is_file():
            return str(path)
        return ""

    return _latest_json_file(_default_supplier_bank_transfer_dir())


def _import_supplier_bank_transfer(*, reason: str) -> None:
    enabled = _is_truthy(
        os.environ.get("HV_IMPORT_SUPPLIER_BANK_ON_INSTALL"),
        default=_conf_bool("hv_import_supplier_bank_on_install", default=True),
    )
    if not enabled:
        return

    configured_path = (
        os.environ.get("HV_SUPPLIER_BANK_TRANSFER_PATH")
        or _conf_str("hv_supplier_bank_transfer_path")
        or ""
    ).strip()
    path = _resolve_supplier_bank_transfer_path(configured_path)
    if not path:
        try:
            frappe.logger("hausverwaltung").info(
                "Skip supplier bank transfer import (%s): no JSON found in %s",
                reason,
                configured_path or str(_default_supplier_bank_transfer_dir()),
            )
        except Exception:
            pass
        return

    try:
        from hausverwaltung.hausverwaltung.scripts.supplier_bank_transfer import import_supplier_bank_data
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung supplier bank transfer import failed ({reason}): import function missing",
            )
        except Exception:
            pass
        return

    try:
        result = import_supplier_bank_data(path=path, update_existing=1, dry_run=0)
        try:
            frappe.logger("hausverwaltung").info(
                "Supplier bank transfer import done (%s): path=%s result=%s",
                reason,
                path,
                result,
            )
        except Exception:
            pass
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung supplier bank transfer import failed ({reason}): {path}",
            )
        except Exception:
            pass


def _ensure_role_exists(role_name: str) -> None:
    try:
        if frappe.db.exists("Role", role_name):
            role = frappe.get_doc("Role", role_name)
            if hasattr(role, "desk_access") and not int(getattr(role, "desk_access") or 0):
                role.desk_access = 1
                role.save(ignore_permissions=True)
            return
    except Exception:
        return

    try:
        frappe.get_doc(
            {
                "doctype": "Role",
                "role_name": role_name,
                "desk_access": 1,
            }
        ).insert(ignore_permissions=True)
    except Exception:
        pass


def _ensure_agent_readonly_role(role_name: str) -> None:
    try:
        if frappe.db.exists("Role", role_name):
            role = frappe.get_doc("Role", role_name)
            changed = False
            if hasattr(role, "desk_access") and int(getattr(role, "desk_access") or 0) != 0:
                role.desk_access = 0
                changed = True
            if changed:
                role.save(ignore_permissions=True)
            return
    except Exception:
        pass

    try:
        frappe.get_doc(
            {
                "doctype": "Role",
                "role_name": role_name,
                "desk_access": 0,
            }
        ).insert(ignore_permissions=True)
    except Exception:
        pass


def _ensure_agent_readonly_docperms(role_name: str) -> None:
    sensitive_doctypes = {
        "Access Log",
        "Activity Log",
        "Authentication Log",
        "DefaultValue",
        "DocShare",
        "Has Role",
        "OAuth Bearer Token",
        "OAuth Client",
        "OAuth Authorization Code",
        "Session Default Settings",
        "Sessions",
        "User",
        "User Email",
        "User Group",
        "User Permission",
    }

    try:
        doctypes = frappe.get_all(
            "DocType",
            filters={"istable": 0},
            pluck="name",
        )
    except Exception:
        return

    readonly_flags = {
        "select": 1,
        "read": 1,
        "write": 0,
        "create": 0,
        "delete": 0,
        "submit": 0,
        "cancel": 0,
        "amend": 0,
        "report": 1,
        "export": 1,
        "import": 0,
        "print": 1,
        "email": 0,
        "share": 0,
    }

    changed = False
    for dt in doctypes or []:
        if not dt or dt in sensitive_doctypes:
            continue

        # Remove legacy Custom DocPerm entries for the agent role.
        # Custom DocPerm overrides all default DocPerm rows in Permission Manager,
        # which hid Hausverwalter/System Manager permissions in UI.
        try:
            custom_rows = frappe.get_all(
                "Custom DocPerm",
                filters={"parent": dt, "role": role_name, "permlevel": 0},
                fields=["name"],
            )
        except Exception:
            custom_rows = []

        for row in custom_rows:
            try:
                frappe.delete_doc("Custom DocPerm", row.get("name"), ignore_permissions=True, force=True)
                changed = True
            except Exception:
                pass

        # Keep agent read access via normal DocPerm (no override side effects).
        target_flags = readonly_flags.copy()
        try:
            meta = frappe.get_cached_doc("DocType", dt)
            if not int(getattr(meta, "is_submittable", 0) or 0):
                target_flags["submit"] = 0
                target_flags["cancel"] = 0
                target_flags["amend"] = 0
            if int(getattr(meta, "issingle", 0) or 0):
                target_flags["import"] = 0
                target_flags["export"] = 0
            if not int(getattr(meta, "allow_import", 0) or 0):
                target_flags["import"] = 0
        except Exception:
            pass

        try:
            existing = frappe.get_all(
                "DocPerm",
                filters={"parent": dt, "role": role_name, "permlevel": 0, "if_owner": 0},
                fields=["name"],
                limit=1,
            )
        except Exception:
            existing = []

        if existing:
            try:
                row = frappe.get_doc("DocPerm", existing[0].get("name"))
                row_changed = False
                for fieldname, desired in target_flags.items():
                    current = int(getattr(row, fieldname, 0) or 0)
                    if current != desired:
                        setattr(row, fieldname, desired)
                        row_changed = True
                if row_changed:
                    row.save(ignore_permissions=True)
                    changed = True
            except Exception:
                pass
            continue

        try:
            frappe.get_doc(
                {
                    "doctype": "DocPerm",
                    "parent": dt,
                    "parenttype": "DocType",
                    "parentfield": "permissions",
                    "role": role_name,
                    "permlevel": 0,
                    "if_owner": 0,
                    **target_flags,
                }
            ).insert(ignore_permissions=True)
            changed = True
        except Exception:
            pass

    if changed:
        try:
            frappe.clear_cache()
        except Exception:
            pass


def _ensure_agent_readonly_user(*, reason: str) -> None:
    """Create/update a technical readonly user for LLM agent API usage (new installs)."""

    enabled = _is_truthy(
        os.environ.get("HV_AGENT_USER_ENABLED"),
        default=_conf_bool("hv_agent_user_enabled", default=True),
    )
    if not enabled:
        return

    role_name = (os.environ.get("HV_AGENT_ROLE") or _conf_str("hv_agent_role") or "Agent Readonly API").strip()
    email = (
        os.environ.get("HV_AGENT_EMAIL") or _conf_str("hv_agent_email") or "agent-readonly@example.com"
    ).strip()
    username = (os.environ.get("HV_AGENT_USERNAME") or _conf_str("hv_agent_username") or "agent-readonly").strip()
    password = (
        os.environ.get("HV_AGENT_PASSWORD") or _conf_str("hv_agent_password") or "change-me-agent-readonly"
    ).strip()

    try:
        from frappe.utils.password import update_password
    except Exception:
        update_password = None

    try:
        _ensure_agent_readonly_role(role_name)
        _ensure_agent_readonly_docperms(role_name)

        created = False
        if not frappe.db.exists("User", email):
            doc = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": "Agent",
                    "last_name": "Readonly",
                    "enabled": 1,
                    "send_welcome_email": 0,
                }
            )
            if hasattr(doc, "username"):
                doc.username = username or None
            if hasattr(doc, "user_type"):
                doc.user_type = "System User"
            doc.insert(ignore_permissions=True)
            created = True
        else:
            doc = frappe.get_doc("User", email)

        changed = False
        if hasattr(doc, "enabled") and int(getattr(doc, "enabled") or 0) != 1:
            doc.enabled = 1
            changed = True
        if hasattr(doc, "user_type") and (getattr(doc, "user_type", "") or "").strip() != "System User":
            doc.user_type = "System User"
            changed = True
        if hasattr(doc, "username") and username and (getattr(doc, "username", "") or "").strip() != username:
            doc.username = username
            changed = True
        if hasattr(doc, "role_profile_name") and (getattr(doc, "role_profile_name", "") or "").strip():
            doc.role_profile_name = ""
            changed = True

        if getattr(doc, "roles", None) is not None:
            allowed = {role_name}
            existing = {row.role for row in (doc.get("roles") or []) if getattr(row, "role", None)}
            if role_name not in existing:
                doc.append("roles", {"role": role_name})
                changed = True

            for row in list(doc.get("roles") or []):
                role = (getattr(row, "role", "") or "").strip()
                if role and role not in allowed:
                    try:
                        doc.remove(row)
                        changed = True
                    except Exception:
                        pass

        if changed:
            doc.save(ignore_permissions=True)

        if password and update_password:
            update_password(email, password)

        try:
            # Ensure API credentials are present for direct token auth.
            if not (getattr(doc, "api_key", None) or "").strip():
                from frappe.core.doctype.user.user import generate_keys

                generate_keys(email)
        except Exception:
            pass

        try:
            frappe.db.commit()
        except Exception:
            pass

        try:
            frappe.logger("hausverwaltung").info(
                "Ensured agent readonly user %s (created=%s, role=%s, reason=%s)",
                email,
                int(created),
                role_name,
                reason,
            )
        except Exception:
            pass
    except Exception:
        try:
            frappe.log_error(
                frappe.get_traceback(),
                f"hausverwaltung ensure agent readonly user failed ({reason}): {email}",
            )
        except Exception:
            pass


def _ensure_hv_user(*, reason: str) -> None:
    """Ensure a default Hausverwaltung user exists (idempotent).

    Configuration precedence:
      1) env: HV_HV_EMAIL / HV_HV_USERNAME / HV_HV_PASSWORD
      2) site_config: hv_user_email / hv_user_username / hv_user_password
    """

    email = (os.environ.get("HV_HV_EMAIL") or _conf_str("hv_user_email") or "hv@example.com").strip()
    username = (os.environ.get("HV_HV_USERNAME") or _conf_str("hv_user_username") or "hv").strip()
    password = (os.environ.get("HV_HV_PASSWORD") or _conf_str("hv_user_password") or "hv").strip()

    try:
        from frappe.utils.password import update_password
    except Exception:
        update_password = None

    required_roles = (
        "Hausverwalter",
        "Hausverwalter (Buchung)",
    )

    created = False
    try:
        if not frappe.db.exists("User", email):
            doc = frappe.get_doc(
                {
                    "doctype": "User",
                    "email": email,
                    "first_name": username or "hv",
                    "enabled": 1,
                    "send_welcome_email": 0,
                }
            )
            if hasattr(doc, "username"):
                doc.username = username or None
            if hasattr(doc, "user_type"):
                doc.user_type = "System User"
            doc.insert(ignore_permissions=True)
            created = True
        else:
            doc = frappe.get_doc("User", email)

        changed = False

        if hasattr(doc, "enabled") and int(getattr(doc, "enabled") or 0) != 1:
            doc.enabled = 1
            changed = True
        if hasattr(doc, "user_type") and (getattr(doc, "user_type", "") or "").strip() != "System User":
            doc.user_type = "System User"
            changed = True
        if hasattr(doc, "username") and username and (getattr(doc, "username", "") or "").strip() != username:
            doc.username = username
            changed = True

        if hasattr(doc, "role_profile_name") and (getattr(doc, "role_profile_name", None) or "").strip():
            # Ensure *only* Hausverwalter roles apply (a role profile may add extra roles).
            doc.role_profile_name = ""
            changed = True

        if getattr(doc, "roles", None) is not None:
            for role in required_roles:
                _ensure_role_exists(role)

            allowed = set(required_roles)
            existing = {row.role for row in (doc.get("roles") or []) if getattr(row, "role", None)}
            for role in required_roles:
                if role in existing:
                    continue
                doc.append("roles", {"role": role})
                existing.add(role)
                changed = True

            for row in list(doc.get("roles") or []):
                r = (getattr(row, "role", None) or "").strip()
                if not r:
                    continue
                if r not in allowed:
                    try:
                        doc.remove(row)
                        changed = True
                    except Exception:
                        pass

        if changed:
            doc.save(ignore_permissions=True)

        if password and update_password:
            update_password(email, password)

            frappe.logger("hausverwaltung").info("Ensured password for user %s (%s)", username, reason)

        try:
            frappe.db.commit()
        except Exception:
            pass

    except Exception:
        try:
            frappe.log_error(frappe.get_traceback(), f"hausverwaltung ensure hv user failed ({reason}): {email}")
        except Exception:
            pass


def _ensure_currency_symbol_on_right(*, reason: str) -> None:
    """Ensure currency symbol is displayed on the right (e.g. `1,00 €`) for EUR/default currency.

    Some ERPNext/Frappe versions control this via a checkbox on the `Currency` DocType
    (label: "Show Currency Symbol on Right Side").
    """

    try:
        if not frappe.db.exists("DocType", "Currency"):
            return
    except Exception:
        return

    try:
        meta = frappe.get_meta("Currency")
    except Exception:
        return

    candidates = (
        "symbol_on_right",
        "show_currency_symbol_on_right_side",
        "show_currency_symbol_on_right",
    )
    fieldname = next((f for f in candidates if meta.has_field(f)), "")
    if not fieldname:
        return

    def get_global_default(key: str) -> str:
        try:
            defaults = getattr(frappe, "defaults", None)
            getter = getattr(defaults, "get_global_default", None) if defaults else None
            if getter:
                return str(getter(key) or "").strip()
        except Exception:
            pass
        try:
            getter = getattr(frappe.db, "get_default", None)
            if getter:
                return str(getter(key) or "").strip()
        except Exception:
            pass
        return ""

    default_currency = (
        os.environ.get("HV_DEFAULT_CURRENCY")
        or _conf_str("hv_default_currency")
        or get_global_default("currency")
        or get_global_default("default_currency")
        or "EUR"
    ).strip() or "EUR"

    targets = [default_currency]
    if default_currency != "EUR":
        targets.append("EUR")

    # Ensure the plain `currency` default (used by `frappe.boot.sysdefaults.currency`,
    # which Currency-formatting in the desk falls back to) matches the configured
    # currency. Without this Frappe keeps its hardcoded INR default and Currency
    # columns in reports render as `₹` even when Global Defaults already says EUR.
    try:
        current_default_currency = (frappe.db.get_default("currency") or "").strip()
    except Exception:
        current_default_currency = ""
    if current_default_currency != default_currency:
        try:
            frappe.db.set_default("currency", default_currency)
            frappe.db.commit()
            frappe.logger("hausverwaltung").info(
                "Set default currency to %s (was %r) (%s)",
                default_currency, current_default_currency, reason,
            )
        except Exception:
            pass

    # Ensure `System Settings.currency` is set. ERPNext falls back to this when
    # creating Sales/Purchase Invoices without an explicit currency; if it's
    # empty or wrong (Setup Wizard skipped), `frappe.defaults` returns the
    # hardcoded INR and invoices fail validation against EUR-currency accounts.
    # Use .save() so `SystemSettings.on_update` fires and propagates the value
    # to `tabDefaultValue.__default.currency` in the same go — otherwise opening
    # and re-saving System Settings later silently overwrites our default.
    try:
        ss_meta = frappe.get_meta("System Settings")
    except Exception:
        ss_meta = None
    if ss_meta and ss_meta.has_field("currency"):
        try:
            current_ss_currency = (frappe.db.get_single_value("System Settings", "currency") or "").strip()
        except Exception:
            current_ss_currency = ""
        if current_ss_currency != default_currency:
            try:
                ss = frappe.get_single("System Settings")
                ss.currency = default_currency
                ss.flags.ignore_permissions = True
                ss.save()
                frappe.db.commit()
                frappe.logger("hausverwaltung").info(
                    "Set System Settings.currency to %s (was %r) (%s)",
                    default_currency, current_ss_currency, reason,
                )
            except Exception:
                pass

    desired_number_format = "#.###,##"
    desired_currency_format = "#.###,## ¤"

    changed = False
    for code in targets:
        try:
            if not frappe.db.exists("Currency", code):
                continue
        except Exception:
            continue

        try:
            current = frappe.db.get_value("Currency", code, fieldname)
        except Exception:
            current = None

        if int(current or 0) == 1:
            continue

        try:
            frappe.db.set_value("Currency", code, fieldname, 1, update_modified=False)
            changed = True
        except Exception:
            continue

    if not changed:
        return

    try:
        frappe.db.commit()
        frappe.logger("hausverwaltung").info(
            "Ensured Currency.%s=1 for %s (%s)", fieldname, ",".join(targets), reason
        )
    except Exception:
        pass

    def should_override_currency_format(current: str) -> bool:
        current = (current or "").strip()
        if not current:
            return True
        if "¤" not in current:
            return False
        # Override only when symbol is before digits (e.g. "¤ #.###,##").
        return current.find("¤") <= current.find("#")

    def set_single_if_allowed(fieldname: str, desired: str) -> None:
        if not meta.has_field(fieldname):
            return
        try:
            current = (frappe.db.get_single_value("System Settings", fieldname) or "").strip()
        except Exception:
            current = ""

        if current == desired:
            return

        try:
            frappe.db.set_single_value("System Settings", fieldname, desired)
        except Exception:
            return

    def get_global_default(key: str) -> str:
        try:
            defaults = getattr(frappe, "defaults", None)
            getter = getattr(defaults, "get_global_default", None) if defaults else None
            if getter:
                return str(getter(key) or "").strip()
        except Exception:
            pass
        try:
            getter = getattr(frappe.db, "get_default", None)
            if getter:
                return str(getter(key) or "").strip()
        except Exception:
            pass
        return ""

    def set_global_default(key: str, value: str) -> None:
        try:
            defaults = getattr(frappe, "defaults", None)
            setter = getattr(defaults, "set_global_default", None) if defaults else None
            if setter:
                setter(key, value)
                return
        except Exception:
            pass
        try:
            setter = getattr(frappe.db, "set_default", None)
            if setter:
                setter(key, value)
        except Exception:
            pass

    set_single_if_allowed("number_format", desired_number_format)

    if meta.has_field("currency_format"):
        try:
            current = (frappe.db.get_single_value("System Settings", "currency_format") or "").strip()
        except Exception:
            current = ""
        if current != desired_currency_format and should_override_currency_format(current):
            set_single_if_allowed("currency_format", desired_currency_format)
    else:
        current = get_global_default("currency_format")
        if current != desired_currency_format and should_override_currency_format(current):
            set_global_default("currency_format", desired_currency_format)

    try:
        frappe.db.commit()
        frappe.logger("hausverwaltung").info("Ensured System Settings formats (%s)", reason)
    except Exception:
        pass


def _ensure_main_cost_center_disabled(*, reason: str) -> None:
    """Disable the auto-created `Main` cost center per company.

    ERPNext legt beim Anlegen einer Company automatisch eine Kostenstelle `Main`
    an. Im Hausverwaltungs-Workflow werden Kostenstellen pro Immobilie geführt,
    `Main` bleibt ungenutzt und stört nur in Dropdowns.
    """

    try:
        if not frappe.db.exists("DocType", "Cost Center"):
            return
    except Exception:
        return

    try:
        rows = frappe.get_all(
            "Cost Center",
            filters={"cost_center_name": "Main", "is_group": 0, "disabled": 0},
            fields=["name"],
        )
    except Exception:
        return

    if not rows:
        return

    changed = False
    for row in rows:
        try:
            frappe.db.set_value("Cost Center", row["name"], "disabled", 1, update_modified=False)
            changed = True
            frappe.logger("hausverwaltung").info(
                "Disabled cost center %s (%s)", row["name"], reason
            )
        except Exception:
            continue

    if changed:
        try:
            frappe.db.commit()
        except Exception:
            pass
