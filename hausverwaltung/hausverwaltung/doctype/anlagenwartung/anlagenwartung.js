frappe.ui.form.on("Anlagenwartung", {
	setup(frm) {
		frm.set_query("wartungsplan", () => ({
			filters: {
				status: "Aktiv",
				...(frm.doc.technische_anlage
					? { technische_anlage: frm.doc.technische_anlage }
					: {}),
			},
		}));
	},

	wartungsplan(frm) {
		if (!frm.doc.wartungsplan) return;
		frappe.db.get_value(
			"Wartungsplan",
			frm.doc.wartungsplan,
			["technische_anlage", "massnahmenart", "wartungsfirma", "naechste_faelligkeit"]
		).then((r) => {
			const plan = (r && r.message) || {};
			frm.set_value({
				technische_anlage: plan.technische_anlage,
				massnahmenart: plan.massnahmenart,
				wartungsfirma: plan.wartungsfirma,
				soll_termin: plan.naechste_faelligkeit,
			});
		});
	},
});
