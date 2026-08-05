frappe.ui.form.on("Immobilie", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(
			__("Zählerübersicht"),
			() => {
				frappe.set_route("query-report", "Zählerübersicht Haus", {
					immobilie: frm.doc.name,
					stichtag: frappe.datetime.get_today(),
				});
			},
			__("Zähler"),
		);
	},
});
