frappe.listview_settings["Wartungsplan"] = {
	get_indicator(doc) {
		const colors = {
			Überfällig: "red",
			"Bald fällig": "orange",
			Geplant: "blue",
			"Nicht terminiert": "gray",
			Inaktiv: "gray",
		};
		return [__(doc.faelligkeitsstatus || "Nicht terminiert"), colors[doc.faelligkeitsstatus] || "gray", `faelligkeitsstatus,=,${doc.faelligkeitsstatus}`];
	},
};
