// Filter-Definitionen für „Mieterhöhungs-Kandidaten".
//
// Default-Verhalten: Filter „Nur Kandidaten" ist aktiv → Verträge mit
// Staffelmiete (zukünftige Staffeln vereinbart), Sperrfrist (<12 Mon. seit
// letzter Erhöhung) oder ausgeschöpfter Kappungsgrenze (15%) werden
// ausgeblendet. Kappung + Sperrfrist sind konfigurierbar — sodass z.B.
// non-Berlin-Szenarien (20% Kappung) oder strengere Sperrfristen (15 Mon.
// nach §558 BGB) abgebildet werden können.

frappe.query_reports["Mieterhoehungs Kandidaten"] = {
	filters: [
		{
			fieldname: "stichtag",
			label: __("Stichtag"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 0,
		},
		{
			fieldname: "immobilie",
			label: __("Immobilie"),
			fieldtype: "Link",
			options: "Immobilie",
		},
		{
			fieldname: "nur_kandidaten",
			label: __("Nur erhöhungsfähige Kandidaten"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "nur_aktive_vertraege",
			label: __("Nur aktive Mietverträge"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "sperrfrist_monate",
			label: __("Sperrfrist (Monate)"),
			fieldtype: "Int",
			default: 12,
			description: __("BGB §558 Abs. 1 — Mindestabstand seit letzter Mieterhöhung. Default 12, in der Praxis oft 15 (12 + 3 Monate Karenz)."),
		},
		{
			fieldname: "kappungsgrenze_pct",
			label: __("Kappungsgrenze % (3 Jahre)"),
			fieldtype: "Float",
			default: 15.0,
			description: __("BGB §558 Abs. 3 — max % Erhöhung in 3 Jahren. Berlin/München/angespannter Wohnungsmarkt: 15%, sonst 20%."),
		},
	],

	onload: function (report) {
		// Stichtag-Presets analog zu anderen Reports
		try {
			frappe.require(
				"/assets/hausverwaltung/js/date_range_presets.js",
				() => {
					if (window.hausverwaltung?.date_presets?.attach_to_query_report) {
						window.hausverwaltung.date_presets.attach_to_query_report(report, {
							from_field: "stichtag",
							to_field: "stichtag",
						});
					}
				},
			);
		} catch (e) {
			// Lazy-load fail ist nicht tragisch — Filter funktioniert auch ohne Presets.
		}
	},
};
