frappe.ui.form.on("Mietvertragsbuilder", {
	refresh(frm) {
		frm.add_custom_button("Mietvertrag als PDF", () => {
			frappe.call({
				method: "hausverwaltung.hausverwaltung.doctype.mietvertragsbuilder.mietvertragsbuilder.generiere_mietvertrag_pdf",
				args: { docname: frm.doc.name },
				callback: (r) => {
					if (r.message) {
						window.open(r.message);
					}
				},
			});
		});
	},
});
