frappe.query_reports["Mieterkonto"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Firma"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "customer",
			label: __("Mieter/Debitor"),
			fieldtype: "Link",
			options: "Customer",
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("Von"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.year_start
				? frappe.datetime.year_start()
				: frappe.datetime.month_start(),
		},
		{
			fieldname: "to_date",
			label: __("Bis"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "show_invoice_details",
			label: __("Rechnungsspalten anzeigen"),
			fieldtype: "Check",
			default: 0,
		},
	],

	onload: function (report) {
		frappe.require("/assets/hausverwaltung/js/date_range_presets.js", () => {
			window.hausverwaltung?.date_presets?.attach_to_query_report(report, {
				from_field: "from_date",
				to_field: "to_date",
				include_gesamt: false,
			});
		});
	},

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "art" && data?.art) {
			const indicator = {
				Rechnung: "blue",
				Zahlung: "green",
				Abschreibung: "orange",
				Gutschrift: "gray",
				Eröffnung: "gray",
			}[data.art] || "gray";
			return `<span class="indicator-pill ${indicator}">${__(data.art)}</span>`;
		}
		return value;
	},
};
