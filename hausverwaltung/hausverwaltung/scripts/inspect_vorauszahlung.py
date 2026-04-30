"""Inspect Mietvertrag-Strukturen für Vorauszahlung-Felder."""
import frappe


@frappe.whitelist()
def run():
	print("=== Mietvertrag Vorauszahlung-Felder ===")
	for f in frappe.get_meta("Mietvertrag").fields:
		fn = (f.fieldname or "").lower()
		if any(k in fn for k in ["vorauszahlung", "voraus", "bk", "hk", "neben", "betrieb", "heiz"]):
			print(f"  {f.fieldname} ({f.fieldtype}) → {f.options or '-'}")

	print("\n=== Mietvertrag Child-Tables ===")
	for f in frappe.get_meta("Mietvertrag").fields:
		if f.fieldtype in ("Table", "Table MultiSelect"):
			print(f"  {f.fieldname} → {f.options}")
			# Inspect child fields
			try:
				for cf in frappe.get_meta(f.options).fields:
					print(f"      .{cf.fieldname} ({cf.fieldtype})")
			except Exception as e:
				print(f"      ERROR: {e}")

	print("\n=== Sample Mietvertrag with vorauszahlung ===")
	# Find a Mietvertrag with festbetraege rows
	rows = frappe.db.sql("""
		SELECT parent FROM `tabMietvertrag Festbetrag` LIMIT 1
	""", as_dict=True)
	if rows:
		mv = rows[0]["parent"]
		doc = frappe.get_doc("Mietvertrag", mv)
		print(f"  Mietvertrag: {mv}")
		for f in frappe.get_meta("Mietvertrag").fields:
			if f.fieldtype in ("Currency", "Float", "Int") and any(
				k in (f.fieldname or "").lower()
				for k in ["miete", "voraus", "bk", "hk", "kalt", "warm"]
			):
				v = doc.get(f.fieldname)
				if v: print(f"    {f.fieldname} = {v}")
		# Also check festbetraege rows
		fb = doc.get("festbetraege") or []
		for r in fb[:5]:
			print(f"    festbetraege: {r.as_dict()}")
