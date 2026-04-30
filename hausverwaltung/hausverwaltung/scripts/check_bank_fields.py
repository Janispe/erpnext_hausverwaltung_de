"""Find bank-related fields on Immobilie + Bank Account."""
import frappe


@frappe.whitelist()
def run():
	print("=== Immobilie Bankkonto child fields ===")
	for f in frappe.get_meta("Immobilie Bankkonto").fields:
		print(f"  {f.fieldname} ({f.fieldtype}) → {f.options}")
	print("\n=== Sample Immobilie with bankkonten ===")
	rows = frappe.db.sql("""
		SELECT DISTINCT parent FROM `tabImmobilie Bankkonto` LIMIT 1
	""", as_dict=True)
	if rows:
		name = rows[0]["parent"]
		print(f"  parent = {name}")
		doc = frappe.get_doc("Immobilie", name)
		for r in doc.get("bankkonten") or []:
			print(f"    row: {r.as_dict()}")
		# Also check Account-Link `konto`
		print(f"  konto = {doc.get('konto')!r}")
		if doc.get("konto"):
			# Account → Bank Account?
			acc_doc = frappe.get_doc("Account", doc.get("konto"))
			print(f"  Account fields with bank/iban: ")
			for k, v in acc_doc.as_dict().items():
				if any(s in k.lower() for s in ["bank", "iban", "bic", "blz"]) and v:
					print(f"    {k} = {v!r}")
