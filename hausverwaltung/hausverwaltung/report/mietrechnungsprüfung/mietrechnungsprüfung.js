frappe.query_reports["Mietrechnungsprüfung"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Firma"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
		},
		{
			fieldname: "from_month",
			label: __("Von-Monat"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_start(),
		},
		{
			fieldname: "to_month",
			label: __("Bis-Monat"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_start(),
		},
		{
			fieldname: "show_ok_rows",
			label: __("OK-Zeilen anzeigen"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "only_issues",
			label: __("Nur Auffaelligkeiten"),
			fieldtype: "Check",
			default: 1,
		},
	],
};
