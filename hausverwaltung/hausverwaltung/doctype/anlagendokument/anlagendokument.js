frappe.ui.form.on("Anlagendokument", {
	setup(frm) {
		frm.set_query("bezugsdoctype", () => ({
			filters: {
				name: ["in", ["Technische Anlage", "Wartungstermin", "Anlagenwartung", "Anlagenmangel", "Wartungsvertrag"]],
			},
		}));
	},
});
