frappe.ui.form.on("Technische Anlage", {
	setup(frm) {
		frm.set_query("wohnung", () => ({
			filters: frm.doc.immobilie ? { immobilie: frm.doc.immobilie } : {},
		}));
		frm.set_query("anlagenart", () => ({ filters: { deaktiviert: 0 } }));
	},

	immobilie(frm) {
		if (frm.doc.wohnung) {
			frm.set_value("wohnung", null);
		}
	},
});
