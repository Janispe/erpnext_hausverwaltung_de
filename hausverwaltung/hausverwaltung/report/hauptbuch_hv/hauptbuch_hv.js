frappe.query_reports["Hauptbuch HV"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Firma"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("Von Datum"),
			fieldtype: "Date",
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -1),
			reqd: 1,
		},
		{
			fieldname: "to_date",
			label: __("Bis Datum"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "account",
			label: __("Konto"),
			fieldtype: "MultiSelectList",
			options: "Account",
			get_data: function (txt) {
				return frappe.db.get_link_options("Account", txt, {
					company: frappe.query_report.get_filter_value("company"),
				});
			},
		},
		{
			fieldname: "voucher_no",
			label: __("Belegnummer"),
			fieldtype: "Data",
		},
		{
			fieldname: "against_voucher_no",
			label: __("Gegenbelegnummer"),
			fieldtype: "Data",
		},
		{
			fieldtype: "Break",
		},
		{
			fieldname: "party",
			label: __("Mieter/Kunde"),
			fieldtype: "MultiSelectList",
			options: "Customer",
			get_data: function (txt) {
				return frappe.db.get_link_options("Customer", txt);
			},
		},
		{
			fieldname: "cost_center",
			label: __("Kostenstelle"),
			fieldtype: "MultiSelectList",
			options: "Cost Center",
			get_data: function (txt) {
				return frappe.db.get_link_options("Cost Center", txt, {
					company: frappe.query_report.get_filter_value("company"),
				});
			},
		},
		{
			fieldname: "show_opening_entries",
			label: __("Eröffnungsbuchungen anzeigen"),
			fieldtype: "Check",
		},
		{
			fieldname: "show_cancelled_entries",
			label: __("Stornierte anzeigen"),
			fieldtype: "Check",
		},
	],
};
