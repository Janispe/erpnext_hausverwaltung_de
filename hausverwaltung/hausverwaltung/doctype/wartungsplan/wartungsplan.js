frappe.ui.form.on("Wartungsplan", {
	setup(frm) {
		frm.set_query("technische_anlage", () => ({ filters: { status: "Aktiv" } }));
		frm.set_query("massnahmenvorlage", () => ({
			filters: {
				aktiv: 1,
				...(frm.doc.technische_anlage && frm._anlagenart
					? { anlagenart: frm._anlagenart }
					: {}),
			},
		}));
	},

	technische_anlage(frm) {
		if (!frm.doc.technische_anlage) return;
		frappe.db.get_value(
			"Technische Anlage",
			frm.doc.technische_anlage,
			["anlagenart", "wartungsfirma"]
		).then((anlage_result) => {
			const anlage = (anlage_result && anlage_result.message) || {};
			frm._anlagenart = anlage.anlagenart;
			if (anlage.wartungsfirma && !frm.doc.wartungsfirma) {
				frm.set_value("wartungsfirma", anlage.wartungsfirma);
			}
			if (frm.doc.massnahmenvorlage) frm.set_value("massnahmenvorlage", null);
		});
	},

	massnahmenvorlage(frm) {
		if (!frm.doc.massnahmenvorlage) return;
		return frappe.db.get_value(
				"Wartungsmassnahme Vorlage",
				frm.doc.massnahmenvorlage,
				[
					"bezeichnung",
					"massnahmenart",
					"intervall_anzahl",
					"intervall_einheit",
					"terminberechnung",
					"erinnerung_vorlauf_tage",
					"eskalation_nach_tagen",
				]
			).then((art_result) => {
				const art = (art_result && art_result.message) || {};
				frm.set_value({
					bezeichnung: frm.doc.bezeichnung || art.bezeichnung,
					massnahmenart: art.massnahmenart,
					intervall_anzahl: art.intervall_anzahl,
					intervall_einheit: art.intervall_einheit,
					terminberechnung: art.terminberechnung,
					erinnerung_vorlauf_tage: art.erinnerung_vorlauf_tage,
					eskalation_nach_tagen: art.eskalation_nach_tagen,
				});
			});
	},

	refresh(frm) {
		const gesperrt = !frm.is_new();
		["technische_anlage", "massnahmenvorlage", "intervall_anzahl", "intervall_einheit", "terminberechnung", "erste_faelligkeit"].forEach(
			(feld) => frm.set_df_property(feld, "read_only", gesperrt ? 1 : 0)
		);
		if (!frm.is_new()) {
			frm.add_custom_button(__("Wartung anlegen"), () => {
				frappe.call({
					method: "hausverwaltung.hausverwaltung.doctype.wartungstermin.wartungstermin.get_or_create_offener_termin",
					args: { wartungsplan: frm.doc.name },
				}).then((r) => {
					if (!r.message) {
						frappe.msgprint(__("Für diesen Wartungsplan gibt es keinen offenen Termin."));
						return;
					}
					frappe.new_doc("Anlagenwartung", { wartungstermin: r.message.name });
				});
			});
		}
	},
});
