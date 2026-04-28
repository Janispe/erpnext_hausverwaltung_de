frappe.query_reports["Kontostand alle Konten"] = {
	"filters": [
		{
			"fieldname": "company",
			"label": __("Firma"),
			"fieldtype": "Link",
			"options": "Company",
			"reqd": 1
		},
		{
			"fieldname": "to_date",
			"label": __("Stichtag"),
			"fieldtype": "Date",
			"reqd": 1,
			"default": frappe.datetime.get_today()
		},
		{
			"fieldname": "include_groups",
			"label": __("Gruppenkonten anzeigen"),
			"fieldtype": "Check",
			"default": 1
		},
		{
			"fieldname": "show_zero",
			"label": __("Konten mit 0 anzeigen"),
			"fieldtype": "Check",
			"default": 0
		},
		{
			"fieldname": "include_disabled",
			"label": __("Deaktivierte Konten einschliessen"),
			"fieldtype": "Check",
			"default": 0
		}
	]
};
