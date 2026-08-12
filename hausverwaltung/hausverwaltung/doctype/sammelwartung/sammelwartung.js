function reload_with_message(frm, message) {
	if (message) frappe.show_alert({ message, indicator: "green" });
	frm.reload_doc();
}

frappe.ui.form.on("Sammelwartung", {
	setup(frm) {
		frm.set_query("immobilie", () => ({
			filters: { parent_immobilie: ["in", ["", null]] },
		}));
		frm.set_query("anlagenart", () => ({ filters: { deaktiviert: 0 } }));
	},

	wartungsvertrag(frm) {
		if (!frm.doc.wartungsvertrag) return;
		frappe.db.get_value("Wartungsvertrag", frm.doc.wartungsvertrag, "wartungsfirma").then((r) => {
			frm.set_value("wartungsfirma", (r.message || {}).wartungsfirma);
		});
	},

	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Fälligkeiten übernehmen"), () => {
			const dialog = new frappe.ui.Dialog({
				title: __("Offene Wartungstermine übernehmen"),
				fields: [
					{
						fieldname: "nur_faellige",
						fieldtype: "Check",
						label: __("Nur bis zum Stichtag fällige Termine"),
						default: 1,
					},
					{
						fieldname: "faellig_bis",
						fieldtype: "Date",
						label: __("Fällig bis"),
						default: frm.doc.faellig_bis || frm.doc.termin_bis || frm.doc.termin_von,
						depends_on: "eval:doc.nur_faellige",
						reqd: 1,
					},
				],
				primary_action_label: __("Übernehmen"),
				primary_action(values) {
					frm.call("positionen_uebernehmen", values).then((r) => {
						const result = (r && r.message) || {};
						dialog.hide();
						reload_with_message(
							frm,
							__("{0} Termine hinzugefügt, {1} insgesamt", [
								result.hinzugefuegt || 0,
								result.gesamt || 0,
							])
						);
					});
				},
			});
			dialog.show();
		});

		frm.add_custom_button(__("Einzelwartungen anlegen"), () => {
			frm.call("anlagenwartungen_anlegen").then((r) => {
				const result = (r && r.message) || {};
				reload_with_message(
					frm,
					__("{0} Wartungen angelegt, {1} übersprungen", [
						(result.erstellt || []).length,
						result.uebersprungen || 0,
					])
				);
			});
		});

		frm.add_custom_button(__("Fortschritt aktualisieren"), () => {
			frm.call("fortschritt_aktualisieren").then(() => frm.reload_doc());
		});

		frm.add_custom_button(__("Noch nicht gewartet"), () => {
			frappe.route_options = {
				sammelwartung: frm.doc.name,
				status: ["!=", "Durchgeführt"],
			};
			frappe.set_route("List", "Anlagenwartung");
		});
	},
});
