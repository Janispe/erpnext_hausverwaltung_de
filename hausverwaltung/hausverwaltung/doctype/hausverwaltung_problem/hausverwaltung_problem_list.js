frappe.listview_settings["Hausverwaltung Problem"] = {
	add_fields: ["status", "schweregrad"],
	get_indicator(doc) {
		const colors = { Offen: "red", "In Bearbeitung": "orange", Behoben: "green", Akzeptiert: "gray" };
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
	onload(listview) {
		listview.page.add_inner_button(__("Jetzt prüfen"), async () => {
			await frappe.call({
				method: "hausverwaltung.hausverwaltung.doctype.hausverwaltung_problem.hausverwaltung_problem.run_problem_checks",
				freeze: true,
				freeze_message: __("Probleme werden geprüft …"),
			});
			await listview.refresh();
			frappe.show_alert({ message: __("Prüfung abgeschlossen"), indicator: "green" });
		});
	},
};
