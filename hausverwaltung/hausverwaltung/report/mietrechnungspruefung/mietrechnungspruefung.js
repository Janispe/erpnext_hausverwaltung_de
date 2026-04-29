frappe.query_reports["Mietrechnungspruefung"] = {
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

	onload: function (report) {
		frappe.require("/assets/hausverwaltung/js/date_range_presets.js", () => {
			window.hausverwaltung?.date_presets?.attach_to_query_report(report, {
				from_field: "from_month",
				to_field: "to_month",
				include_gesamt: false,
			});
		});
	},
};
