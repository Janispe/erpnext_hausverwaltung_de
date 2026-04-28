frappe.ui.form.on("Telefonnummernauszug", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}
		frm.add_custom_button(__("Einträge laden"), () => {
			frappe.confirm(
				__("Bestehende Einträge werden überschrieben. Fortfahren?"),
				() => {
					frappe.call({
						method: "hausverwaltung.hausverwaltung.doctype.telefonnummernauszug.telefonnummernauszug.lade_eintraege",
						args: { name: frm.doc.name },
						freeze: true,
						freeze_message: __("Einträge werden geladen…"),
					}).then((r) => {
						const anzahl = (r && r.message && r.message.anzahl) || 0;
						frappe.show_alert({
							message: __("{0} Einträge geladen.", [anzahl]),
							indicator: "green",
						});
						frm.reload_doc();
					});
				}
			);
		});
	},
});
