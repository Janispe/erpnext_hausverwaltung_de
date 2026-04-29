frappe.query_reports["Staffelmieterhoehungen"] = {
	onload: function (report) {
		frappe.require("/assets/hausverwaltung/js/date_range_presets.js", () => {
			window.hausverwaltung?.date_presets?.attach_to_query_report(report, {
				from_field: "von_datum",
				to_field: "bis_datum",
				include_gesamt: false,
			});
		});
	},
};
