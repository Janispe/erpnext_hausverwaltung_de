// Beschränkt Immobilie-Filter in Query Reports auf Haupt-Immobilien
// (Tree-Roots, also Records ohne ``parent_immobilie``).
//
// Hintergrund: Mama hat mehrere Häuser, einige sind als Tree mit Sub-Knoten
// modelliert (z.B. „Gropiusstr." → „Gropiusstr. - HH" / „Gropiusstr. - VH").
// In Reports will man pro Filter-Auswahl meist nur die echten Häuser sehen,
// nicht die Gebäudeteile.
//
// Wirkung: Nur in Query-Report-Filtern. Form-Felder (z.B. Wohnung.immobilie),
// Tree-Parent-Felder etc. bleiben unberührt.

(function () {
	function patchReportFilters() {
		try {
			if (frappe.get_route && frappe.get_route()[0] !== "query-report") return;
			const qr = frappe.query_report;
			if (!qr || !qr.filters) return;
			qr.filters.forEach((f) => {
				const opts = f.df && f.df.options;
				if (opts !== "Immobilie") return;
				if (f.df._hv_immobilie_root_filter_set) return;
				f.df.get_query = () => ({
					filters: { parent_immobilie: ["in", ["", null]] },
				});
				f.df._hv_immobilie_root_filter_set = true;
			});
		} catch (e) {
			// fail silent — falls Frappe-API sich ändert, bricht der Filter höchstens
			// auf "alle Immobilien" zurück, was kein Drama ist.
		}
	}

	$(document).on("page-change", function () {
		setTimeout(patchReportFilters, 50);
		setTimeout(patchReportFilters, 250);
	});
	$(window).on("hashchange", function () {
		setTimeout(patchReportFilters, 100);
	});
})();
