frappe.listview_settings["Sammelwartung"] = {
	get_indicator(doc) {
		const colors = {
			Entwurf: "gray",
			Geplant: "blue",
			"In Arbeit": "orange",
			Abgeschlossen: "green",
		};
		return [__(doc.status || "Entwurf"), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
