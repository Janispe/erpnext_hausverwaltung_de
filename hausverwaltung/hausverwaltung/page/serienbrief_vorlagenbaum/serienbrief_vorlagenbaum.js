// Die komplette Browser-Logik liegt in
// `/assets/hausverwaltung/js/serienbrief_vorlagen_browser.js` und wird per
// `app_include_js` global geladen. Diese Seite ist nur noch ein Mount-Punkt
// im Manage-Modus, damit Picker (Dialog) und Seite konsistent bleiben.

frappe.pages["serienbrief_vorlagenbaum"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Serienbrief Vorlagen"),
		single_column: true,
	});

	hausverwaltung.serienbrief.mount_vorlagen_browser($(page.body), { mode: "manage" });
};
