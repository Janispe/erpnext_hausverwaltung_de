frappe.ui.form.on("Serienbrief Dokument", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.durchlauf) {
			frm.add_custom_button(__("Durchlauf öffnen"), () => {
				frappe.set_route("Form", "Serienbrief Durchlauf", frm.doc.durchlauf);
			});
		}
	},
});

