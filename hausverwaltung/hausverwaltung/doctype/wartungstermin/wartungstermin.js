frappe.ui.form.on("Wartungstermin", {
	setup(frm) {
		frm.set_query("wartungsplan", () => ({ filters: { status: "Aktiv" } }));
	},

	wartungsplan(frm) {
		if (!frm.doc.wartungsplan) return;
		frappe.db.get_value(
			"Wartungsplan",
			frm.doc.wartungsplan,
			["technische_anlage", "massnahmenart", "naechste_faelligkeit"]
		).then((r) => {
			const plan = (r && r.message) || {};
			frm.set_value({
				technische_anlage: plan.technische_anlage,
				massnahmenart: plan.massnahmenart,
				soll_termin: plan.naechste_faelligkeit,
			});
		});
	},

	refresh(frm) {
		const gesperrt = !frm.is_new();
		["wartungsplan", "technische_anlage", "soll_termin"].forEach((feld) =>
			frm.set_df_property(feld, "read_only", gesperrt ? 1 : 0)
		);
		if (!frm.is_new() && ["Offen", "Beauftragt"].includes(frm.doc.status) && !frm.doc.anlagenwartung) {
			frm.add_custom_button(__("Durchführung anlegen"), () => {
				frappe.new_doc("Anlagenwartung", { wartungstermin: frm.doc.name });
			});
		}
	},
});
