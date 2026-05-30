frappe.listview_settings["Sales Invoice"] = frappe.listview_settings["Sales Invoice"] || {};

frappe.listview_settings["Sales Invoice"].get_indicator = function (doc) {
	const status_labels = {
		Return: __("Guthaben"),
		"Credit Note Issued": __("Guthaben ausgestellt"),
	};
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

	return [
		status_labels[doc.status] || __(doc.status),
		status_colors[doc.status] || "blue",
		"status,=," + doc.status,
	];
};

// Sammelaktion „Mietrechnung korrigieren" für ausgewählte Rechnungen (beliebige
// Auswahl in der Liste). Nutzt dieselbe Bulk-Logik wie der Mietrechnungsprüfung-Report.
frappe.listview_settings["Sales Invoice"].onload = function (listview) {
	listview.page.add_action_item(__("Mietrechnung korrigieren"), () => {
		const names = listview.get_checked_items(true);
		if (!names.length) {
			frappe.msgprint(__("Bitte zuerst Rechnungen auswählen."));
			return;
		}
		frappe.require("/assets/hausverwaltung/js/mietrechnung_korrektur_report.js", () => {
			window.hausverwaltung?.korrektur?.run_bulk(names, {
				onDone: () => listview.refresh(),
			});
		});
	});
};
