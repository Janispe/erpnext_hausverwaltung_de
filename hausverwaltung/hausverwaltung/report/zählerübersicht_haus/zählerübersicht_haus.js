frappe.query_reports["Zählerübersicht Haus"] = {
	filters: [
		{
			fieldname: "immobilie",
			label: __("Immobilie"),
			fieldtype: "Link",
			options: "Immobilie",
			reqd: 1,
		},
		{
			fieldname: "stichtag",
			label: __("Stichtag"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
	],

	formatter(value, row, column, data, default_formatter) {
		const formatted = default_formatter(value, row, column, data);
		if (!["gas", "strom"].includes(column.fieldname) || !value) {
			return formatted;
		}

		return String(value)
			.split("\n")
			.map((entry) => frappe.utils.escape_html(entry))
			.join("<br>");
	},
};
