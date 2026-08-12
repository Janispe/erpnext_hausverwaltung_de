frappe.ui.form.on("Anlagenwartung", {
	setup(frm) {
		frm.set_query("wartungstermin", () => ({
			filters: { status: ["in", ["Offen", "Beauftragt"]] },
		}));
		frm.set_query("wartungsplan", () => ({
			filters: {
				status: "Aktiv",
				...(frm.doc.technische_anlage
					? { technische_anlage: frm.doc.technische_anlage }
					: {}),
			},
		}));
	},

	wartungstermin(frm) {
		if (!frm.doc.wartungstermin) return;
		frappe.db.get_value(
			"Wartungstermin",
			frm.doc.wartungstermin,
			["wartungsplan", "technische_anlage", "massnahmenart", "soll_termin", "sammelwartung"]
		).then((r) => {
			const termin = (r && r.message) || {};
			frm.set_value({
				wartungsplan: termin.wartungsplan,
				technische_anlage: termin.technische_anlage,
				massnahmenart: termin.massnahmenart,
				soll_termin: termin.soll_termin,
				sammelwartung: termin.sammelwartung,
			});
		});
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

	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Dokument hinzufügen"), () => {
				frappe.new_doc("Anlagendokument", {
					bezugsdoctype: "Anlagenwartung",
					bezug: frm.doc.name,
					dokumentart: "Wartungsprotokoll",
				});
			});
		}
	},
});
