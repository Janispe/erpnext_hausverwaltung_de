// Buchungs-Cockpit: zentraler Einstieg für vereinfachte Buchungsvorgänge.
// Die eigentliche UI-Logik liegt in /assets/hausverwaltung/js/buchen_cockpit.js
// und wird per app_include_js global geladen.

frappe.pages["buchen_cockpit"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Buchungs-Cockpit"),
		single_column: true,
	});

	hausverwaltung.buchen_cockpit.mount($(page.body));
};
