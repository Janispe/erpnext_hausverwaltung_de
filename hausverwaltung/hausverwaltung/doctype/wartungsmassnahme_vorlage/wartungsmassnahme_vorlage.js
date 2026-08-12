frappe.ui.form.on("Wartungsmassnahme Vorlage", {
	setup(frm) {
		frm.set_query("massnahmenart", () => ({ filters: { deaktiviert: 0 } }));
	},
});
