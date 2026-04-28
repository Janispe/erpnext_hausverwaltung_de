frappe.ui.form.on("Abschlagszahlungen", {
	refresh(frm) {
		frm.add_custom_button(__("Abschläge erzeugen/aktualisieren"), () => {
			return frm.call("create_or_update_abschlaege").then(() => frm.reload_doc());
		});
	},
});

