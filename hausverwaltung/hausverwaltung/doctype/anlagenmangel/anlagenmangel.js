frappe.ui.form.on("Anlagenmangel", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Dokument hinzufügen"), () => {
				frappe.new_doc("Anlagendokument", {
					bezugsdoctype: "Anlagenmangel",
					bezug: frm.doc.name,
					dokumentart: "Foto",
				});
			});
		}
	},
});
