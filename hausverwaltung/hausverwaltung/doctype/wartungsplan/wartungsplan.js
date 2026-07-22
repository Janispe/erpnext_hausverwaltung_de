frappe.ui.form.on("Wartungsplan", {
	setup(frm) {
		frm.set_query("technische_anlage", () => ({ filters: { status: "Aktiv" } }));
	},

	technische_anlage(frm) {
		if (!frm.doc.technische_anlage) return;
		frappe.db.get_value(
			"Technische Anlage",
			frm.doc.technische_anlage,
			["anlagenart", "wartungsfirma"]
		).then((anlage_result) => {
			const anlage = (anlage_result && anlage_result.message) || {};
			if (anlage.wartungsfirma && !frm.doc.wartungsfirma) {
				frm.set_value("wartungsfirma", anlage.wartungsfirma);
			}
			if (!anlage.anlagenart) return;
			return frappe.db.get_value(
				"Anlagenart",
				anlage.anlagenart,
				[
					"standard_massnahmenart",
					"standard_intervall_anzahl",
					"standard_intervall_einheit",
					"erinnerung_vorlauf_tage",
				]
			).then((art_result) => {
				const art = (art_result && art_result.message) || {};
				const werte = {};
				if (!frm.doc.massnahmenart && art.standard_massnahmenart) {
					werte.massnahmenart = art.standard_massnahmenart;
				}
				if (!frm.doc.intervall_anzahl && art.standard_intervall_anzahl) {
					werte.intervall_anzahl = art.standard_intervall_anzahl;
				}
				if (!frm.doc.intervall_einheit && art.standard_intervall_einheit) {
					werte.intervall_einheit = art.standard_intervall_einheit;
				}
				if (
					(frm.doc.erinnerung_vorlauf_tage === null ||
						frm.doc.erinnerung_vorlauf_tage === undefined) &&
					art.erinnerung_vorlauf_tage !== null
				) {
					werte.erinnerung_vorlauf_tage = art.erinnerung_vorlauf_tage;
				}
				if (Object.keys(werte).length) frm.set_value(werte);
			});
		});
	},

	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Wartung anlegen"), () => {
				frappe.new_doc("Anlagenwartung", {
					wartungsplan: frm.doc.name,
					technische_anlage: frm.doc.technische_anlage,
					massnahmenart: frm.doc.massnahmenart,
					soll_termin: frm.doc.naechste_faelligkeit,
					wartungsfirma: frm.doc.wartungsfirma,
				});
			});
		}
	},
});
