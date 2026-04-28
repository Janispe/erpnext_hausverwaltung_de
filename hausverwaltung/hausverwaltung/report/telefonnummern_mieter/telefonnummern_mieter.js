frappe.query_reports["Telefonnummern Mieter"] = {
	filters: [
		{
			fieldname: "immobilie",
			label: __("Immobilie"),
			fieldtype: "Link",
			options: "Immobilie",
			reqd: 0,
		},
		{
			fieldname: "pro_wohnung",
			label: __("Pro Wohnung gruppieren"),
			fieldtype: "Check",
			default: 0,
			on_change: () => frappe.query_report.refresh(),
		},
	],

	get_datatable_options: function (options) {
		return Object.assign(options, {
			dynamicRowHeight: true,
		});
	},

	formatter: function (value, row, column, data, default_formatter) {
		if (column.fieldname === "mieter" || column.fieldname === "telefonnummern") {
			const raw = data?.[column.fieldname] || "";
			const text = frappe.utils.escape_html(raw);
			const grouped = !!frappe.query_report.get_filter_value("pro_wohnung");
			if (grouped) {
				return `<pre style="white-space: pre-wrap; line-height: 1.3; margin: 0;">${text}</pre>`;
			}
			const title = text.replaceAll('"', "&quot;");
			return `<span title="${title}" style="display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${text}</span>`;
		}

		return default_formatter(value, row, column, data);
	},
};
