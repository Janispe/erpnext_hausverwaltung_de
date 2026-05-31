frappe.listview_settings["Sales Invoice"] = frappe.listview_settings["Sales Invoice"] || {};

const sales_invoice_list_settings = frappe.listview_settings["Sales Invoice"];
const existing_add_fields = sales_invoice_list_settings.add_fields || [];

sales_invoice_list_settings.add_fields = Array.from(
	new Set([
		...existing_add_fields,
		"customer",
		"customer_name",
		"hv_sollstellung_titel",
		"mietabrechnung_id",
		"posting_date",
		"grand_total",
		"currency",
	])
);

sales_invoice_list_settings.formatters = sales_invoice_list_settings.formatters || {};

sales_invoice_list_settings.formatters.customer_name = function (value, _df, doc) {
	if (doc.hv_sollstellung_titel) {
		return doc.hv_sollstellung_titel;
	}

	const customer_name = value || doc.customer_name || doc.customer || doc.name;
	const mietabrechnung = format_mietabrechnung_id(doc.mietabrechnung_id);

	if (mietabrechnung) {
		return `${customer_name} · ${mietabrechnung}`;
	}

	if (doc.posting_date) {
		return `${customer_name} · ${frappe.datetime.str_to_user(doc.posting_date)}`;
	}

	return customer_name;
};

function format_mietabrechnung_id(value) {
	if (!value) return "";

	const parts = String(value)
		.split("|")
		.map((part) => part.trim())
		.filter(Boolean);

	if (!parts.length) return "";

	const period = parts[parts.length - 1];
	const contract = parts.length > 1 ? parts.slice(0, -1).join(" | ") : "";

	return contract ? `${contract} · ${period}` : period;
}

sales_invoice_list_settings.get_indicator = function (doc) {
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

const existing_onload = sales_invoice_list_settings.onload;

// Sammelaktion „Mietrechnung korrigieren" für ausgewählte Rechnungen (beliebige
// Auswahl in der Liste). Nutzt dieselbe Bulk-Logik wie der Mietrechnungsprüfung-Report.
sales_invoice_list_settings.onload = function (listview) {
	if (existing_onload) {
		existing_onload(listview);
	}

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
