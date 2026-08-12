frappe.listview_settings["Wartungstermin"] = {
	get_indicator(doc) {
		const farben = { Offen: "orange", Beauftragt: "blue", Abgeschlossen: "green", Entfallen: "gray" };
		return [__(doc.status), farben[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
