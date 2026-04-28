frappe.listview_settings["Sales Invoice"] = frappe.listview_settings["Sales Invoice"] || {};

frappe.listview_settings["Sales Invoice"].get_indicator = function (doc) {
	const status_colors = {
		Draft: "red",
		Unpaid: "orange",
		Paid: "green",
		Abgeschrieben: "purple",
		"Teilweise bezahlt und abgeschrieben": "purple",
		Return: "gray",
		"Credit Note Issued": "gray",
		"Unpaid and Discounted": "orange",
		"Partly Paid and Discounted": "yellow",
		"Overdue and Discounted": "red",
		Overdue: "red",
		"Partly Paid": "yellow",
		"Internal Transfer": "darkgrey",
		Cancelled: "red",
		Submitted: "blue",
	};

	return [__(doc.status), status_colors[doc.status] || "blue", "status,=," + doc.status];
};
