frappe.listview_settings.Versicherungsfall = {
	get_indicator(doc) {
		const colors = {
			Entwurf: "gray",
			Gemeldet: "blue",
			"In Prüfung": "orange",
			Bewilligt: "blue",
			"Teilweise reguliert": "orange",
			Reguliert: "green",
			Abgelehnt: "red",
			Abgeschlossen: "green",
		};
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
