"""Clean legacy technical rent markers from Sales Invoice remarks.

Older rent invoices stored metadata in the user-visible `remarks` field, e.g.
`[TYPE:Betriebskosten] [MV:MV-1] 05/2026`. Newer invoices use the structured
`mietabrechnung_id` field and human-readable remarks, so this patch rewrites
the old visible text once.
"""

from __future__ import annotations

import re

_TYPE_RE = re.compile(r"\[TYPE:([^\]]+)\]")
_MV_RE = re.compile(r"\[MV:[^\]]+\]")
_MONTH_RE = re.compile(r"(?<!\d)(\d{2}/\d{4})(?!\d)")
_WS_RE = re.compile(r"\s+")

_TYPE_LABELS = {
	"Miete": "Miete",
	"Betriebskosten": "BK",
	"Heizkosten": "HK",
	"Untermietzuschlag": "UMZ",
}


def execute():
	import frappe

	rows = frappe.get_all(
		"Sales Invoice",
		filters={"remarks": ("like", "%[TYPE:%")},
		fields=["name", "remarks"],
		limit_page_length=0,
	)

	updated = 0
	for row in rows:
		old = row.get("remarks") or ""
		new = clean_legacy_remark(old)
		if new and new != old:
			frappe.db.set_value("Sales Invoice", row.name, "remarks", new, update_modified=False)
			updated += 1

	if updated:
		frappe.db.commit()
	frappe.log(f"[clean_legacy_sales_invoice_remarks] updated {updated} Sales Invoice remarks")


def clean_legacy_remark(remark: str | None) -> str:
	value = str(remark or "").strip()
	if not value:
		return ""

	type_match = _TYPE_RE.search(value)
	if not type_match:
		return value

	raw_type = type_match.group(1).strip()
	label = _TYPE_LABELS.get(raw_type, raw_type)
	month_match = _MONTH_RE.search(value)

	without_markers = _TYPE_RE.sub("", value)
	without_markers = _MV_RE.sub("", without_markers)
	if month_match:
		without_markers = without_markers.replace(month_match.group(1), "", 1)
	extra = _WS_RE.sub(" ", without_markers).strip(" -|")

	if month_match:
		base = f"{label} {month_match.group(1)}" if label else month_match.group(1)
		return f"{base} - {extra}" if extra else base

	return _WS_RE.sub(" ", f"{label} {extra}").strip(" -|")
