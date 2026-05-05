// Buchungs-Inbox: Master-Detail-Ansicht für extrahierte Eingangsrechnungen.
// UI-Logik liegt in /assets/hausverwaltung/js/buchungs_inbox.js (per app_include_js geladen).

frappe.pages["buchungs_inbox"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Buchungs-Inbox"),
		single_column: true,
	});

	const route_options = frappe.route_options || {};
	frappe.route_options = null;  // verbrauchen, damit nächste Page sauber startet
	hausverwaltung.buchungs_inbox.mount($(page.body), route_options);
};
