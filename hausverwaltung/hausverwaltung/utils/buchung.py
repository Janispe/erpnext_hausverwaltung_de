"""Shared helpers for booking-related tools (Buchungs-Cockpit, Abschlagszahlung, ...)."""

from __future__ import annotations

import frappe


DEFAULT_SERVICE_ITEM_CODE = "VHB-SERVICE"


def ensure_default_service_item() -> str:
    """Ensure a global non-stock service Item exists and return its item_code.

    We prefer an item with code DEFAULT_SERVICE_ITEM_CODE; create it if missing using
    any leaf Item Group (prefer 'Services').
    """
    def _ensure_root_item_group() -> str:
        root_name = "All Item Groups"
        if frappe.db.exists("Item Group", root_name):
            return root_name
        root = frappe.get_doc(
            {
                "doctype": "Item Group",
                "item_group_name": root_name,
                "parent_item_group": "",
                "is_group": 1,
            }
        )
        root.insert(ignore_permissions=True, ignore_mandatory=True)
        return root.name

    if frappe.db.exists("Item", DEFAULT_SERVICE_ITEM_CODE):
        return DEFAULT_SERVICE_ITEM_CODE

    group = None
    if frappe.db.exists("Item Group", {"name": "Services", "is_group": 0}):
        group = "Services"
    else:
        leaf_groups = frappe.get_all(
            "Item Group", filters={"is_group": 0}, fields=["name"], limit=1
        )
        if leaf_groups:
            group = leaf_groups[0]["name"]

    if not group:
        root_name = _ensure_root_item_group()
        if not frappe.db.exists("Item Group", "Services"):
            root = frappe.get_all(
                "Item Group", filters={"is_group": 1}, fields=["name"], limit=1
            )
            parent = root[0]["name"] if root else root_name
            ig = frappe.get_doc(
                {
                    "doctype": "Item Group",
                    "item_group_name": "Services",
                    "parent_item_group": parent,
                    "is_group": 0,
                }
            )
            ig.insert(ignore_permissions=True)
        group = "Services"

    uom = "Nos"
    if not frappe.db.exists("UOM", uom):
        any_uom = frappe.get_all("UOM", fields=["name"], limit=1)
        if any_uom:
            uom = any_uom[0]["name"]
        else:
            uom_doc = frappe.get_doc(
                {
                    "doctype": "UOM",
                    "uom_name": uom,
                    "must_be_whole_number": 1,
                }
            )
            uom_doc.insert(ignore_permissions=True, ignore_mandatory=True)

    item = frappe.get_doc(
        {
            "doctype": "Item",
            "item_code": DEFAULT_SERVICE_ITEM_CODE,
            "item_name": "Allgemeine Dienstleistung",
            "is_stock_item": 0,
            "include_item_in_manufacturing": 0,
            "disabled": 0,
            "item_group": group,
            "stock_uom": uom,
            "allow_alternative_item": 0,
            "standard_rate": 0,
        }
    )
    item.insert(ignore_permissions=True)
    return DEFAULT_SERVICE_ITEM_CODE
