frappe.ui.form.on("Anlagenart", {
	setup(frm) {
		frm.set_query("kategorie", () => ({ filters: { deaktiviert: 0 } }));
	},
});
