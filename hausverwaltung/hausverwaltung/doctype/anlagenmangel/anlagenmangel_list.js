frappe.listview_settings["Anlagenmangel"] = {
	get_indicator(doc) {
		const farben = { Offen: "red", "In Bearbeitung": "orange", Behoben: "green", Akzeptiert: "gray" };
		return [__(doc.status), farben[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
