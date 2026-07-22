frappe.listview_settings["Anlagenwartung"] = {
	get_indicator(doc) {
		const colors = {
			Geplant: "blue",
			Beauftragt: "orange",
			Durchgeführt: "green",
			Ausgefallen: "red",
			Abgebrochen: "gray",
		};
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
