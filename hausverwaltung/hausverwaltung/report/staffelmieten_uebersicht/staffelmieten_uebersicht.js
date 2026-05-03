// Filter-Definitionen für „Staffelmieten Übersicht"
//
// Im Gegensatz zum Staffelmieterhoehungen-Report (Zeile pro Erhöhung)
// liefert dieser Report eine Pivot-Sicht: 1 Zeile = 1 Mietvertrag,
// dynamische Spalten je Staffel-Slot.

frappe.query_reports["Staffelmieten Uebersicht"] = {
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
			fieldname: "nur_aktive_vertraege",
			label: __("Nur aktive Mietverträge"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "nur_mit_offenen_staffeln",
			label: __("Nur Verträge mit offenen Staffeln"),
			fieldtype: "Check",
			default: 1,
		},
	],

	onload: function (report) {
		// Date-Range-Presets sind hier nicht nötig (es gibt nur den Stichtag),
		// aber wir hängen die generischen Hausverwaltung-Helper trotzdem an,
		// damit der Konsistenz-Look mit anderen Reports erhalten bleibt.
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
			// Lazy-load fail ist nicht tragisch, der Report läuft auch ohne Presets.
		}
	},
};
