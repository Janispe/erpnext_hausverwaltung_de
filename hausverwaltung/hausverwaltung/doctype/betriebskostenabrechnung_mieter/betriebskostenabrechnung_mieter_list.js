// Verhindert manuelle Neuerstellung über die Listenansicht.
frappe.listview_settings["Betriebskostenabrechnung Mieter"] = {
	onload(listview) {
		if (listview.page?.hide_primary_action) {
			listview.page.hide_primary_action();
		}
		if (listview.page?.btn_primary) {
			listview.page.btn_primary.remove();
		}
		if (listview.page?.clear_primary_action) {
			listview.page.clear_primary_action();
		}
		listview.page.set_title_sub(
			__("Neue Abrechnungen werden über 'Betriebskostenabrechnung Immobilie' erzeugt.")
		);
	},
};
