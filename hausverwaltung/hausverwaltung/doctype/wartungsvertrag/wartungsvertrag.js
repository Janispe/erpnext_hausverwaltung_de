frappe.ui.form.on("Wartungsvertrag", {
	setup(frm) {
		frm.set_query("wartungsplan", "positionen", () => ({ filters: { status: ["in", ["Aktiv", "Pausiert"]] } }));
	},
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Vertragsdokument hinzufügen"), () => {
				frappe.new_doc("Anlagendokument", {
					bezugsdoctype: "Wartungsvertrag",
					bezug: frm.doc.name,
					dokumentart: "Vertrag",
				});
			});
		}
	},
});

frappe.ui.form.on("Wartungsvertrag Position", {
	wartungsplan(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.wartungsplan) return;
		frappe.db.get_value("Wartungsplan", row.wartungsplan, "technische_anlage").then((r) => {
			frappe.model.set_value(cdt, cdn, "technische_anlage", (r.message || {}).technische_anlage);
		});
	},
});
