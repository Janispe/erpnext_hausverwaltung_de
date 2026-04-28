frappe.query_reports["Offene Abschlagszahlungen"] = {
	"filters": [
		{
			"fieldname": "immobilie",
			"label": __("Immobilie"),
			"fieldtype": "Link",
			"options": "Immobilie"
		},
		{
			"fieldname": "von",
			"label": __("Von"),
			"fieldtype": "Date",
			"reqd": 1,
			"default": frappe.datetime.add_months(frappe.datetime.get_today(), -12)
		},
		{
			"fieldname": "bis",
			"label": __("Bis"),
			"fieldtype": "Date",
			"reqd": 1,
			"default": frappe.datetime.add_months(frappe.datetime.get_today(), 12)
		}
	],
	"formatter": function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (data && column.fieldname === "status" && data.status === "Überfällig") {
			value = `<span style="color: var(--red-500); font-weight: 600;">${value}</span>`;
		}
		if (data && column.fieldname === "tage_offen" && (data.tage_offen || 0) > 0) {
			value = `<span style="color: var(--red-500); font-weight: 600;">${value}</span>`;
		}
		return value;
	}
};
