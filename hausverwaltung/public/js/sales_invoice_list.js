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

// "<Mietvertrag-ID>|<MM/YYYY>": the contract ID is a technical key and the
// tenant is already shown by name, so only the billing period is displayed.
function format_mietabrechnung_id(value) {
	if (!value) return "";

	const parts = String(value)
		.split("|")
		.map((part) => part.trim())
		.filter(Boolean);

	return parts.length ? parts[parts.length - 1] : "";
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

	if (frappe.user.has_role(["Accounts Manager", "System Manager"])) {
		listview.page.add_menu_item(__("Kostenstellen korrigieren"), () =>
			show_cost_center_repair_dialog(listview)
		);
	}
};

const COST_CENTER_REPAIR_MODULE =
	"hausverwaltung.hausverwaltung.utils.sales_invoice_cost_center_repair";

// Gebuchte Rechnungen, deren Kopf-/Positions-Kostenstelle nicht zur Immobilie
// der Wohnung passt, blockieren den Bankimport. Die Korrektur setzt die
// Property-Kostenstelle; ERPNext erzeugt die Buchungssätze im Hintergrund neu.
function show_cost_center_repair_dialog(listview) {
	frappe.call({
		method: `${COST_CENTER_REPAIR_MODULE}.get_cost_center_repair_preview`,
		freeze: true,
		callback: (r) => {
			const invoices = r.message?.invoices || [];
			if (!invoices.length) {
				frappe.msgprint(__("Alle gebuchten Rechnungen mit Wohnung haben die richtige Kostenstelle."));
				return;
			}
			const esc = frappe.utils.escape_html;
			const rows = invoices
				.map(
					(inv) => `<tr>
						<td><a href="/app/sales-invoice/${encodeURIComponent(inv.name)}">${esc(inv.name)}</a></td>
						<td>${esc(frappe.datetime.str_to_user(inv.posting_date))}</td>
						<td>${esc(inv.customer || "")}</td>
						<td>${esc(inv.remarks || "")}</td>
						<td class="text-right">${format_currency(inv.outstanding_amount)}</td>
						<td>${esc(inv.header_cost_center || __("leer"))}</td>
						<td>${esc(inv.item_cost_centers || __("leer"))}</td>
						<td><b>${esc(inv.target_cost_center)}</b></td>
					</tr>`
				)
				.join("");
			const dialog = new frappe.ui.Dialog({
				title: __("Kostenstellen korrigieren ({0} Rechnungen)", [invoices.length]),
				size: "extra-large",
				fields: [{ fieldtype: "HTML", fieldname: "table" }],
				primary_action_label: __("Alle {0} korrigieren", [invoices.length]),
				primary_action: () => {
					dialog.hide();
					run_cost_center_repair(listview);
				},
			});
			dialog.fields_dict.table.$wrapper.html(`
				<p class="text-muted">${__(
					"Kopf und Positionen bekommen die Kostenstelle der Immobilie. Betrag, offener Posten und Zahlungen bleiben unverändert; die Buchungssätze werden im Hintergrund neu erzeugt."
				)}</p>
				<div style="max-height: 60vh; overflow: auto">
					<table class="table table-bordered table-condensed">
						<thead><tr>
							<th>${__("Rechnung")}</th><th>${__("Datum")}</th><th>${__("Kunde")}</th>
							<th>${__("Bemerkung")}</th><th>${__("Offen")}</th><th>${__("Kopf")}</th>
							<th>${__("Positionen")}</th><th>${__("Soll")}</th>
						</tr></thead>
						<tbody>${rows}</tbody>
					</table>
				</div>`);
			dialog.show();
		},
	});
}

function run_cost_center_repair(listview) {
	frappe.call({
		method: `${COST_CENTER_REPAIR_MODULE}.repair_sales_invoice_cost_centers`,
		freeze: true,
		freeze_message: __("Kostenstellen werden korrigiert …"),
		callback: (r) => {
			const res = r.message || {};
			const repaired = (res.repaired || []).length;
			const failed = res.failed || [];
			let message = __("{0} Rechnungen korrigiert. Die Buchungssätze werden im Hintergrund neu erzeugt.", [
				repaired,
			]);
			if (failed.length) {
				const esc = frappe.utils.escape_html;
				message += `<br><br><b>${__("Nicht korrigiert ({0}):", [failed.length])}</b><ul>${failed
					.map((f) => `<li>${esc(f.name)}: ${esc(f.error)}</li>`)
					.join("")}</ul>`;
			}
			frappe.msgprint({
				title: __("Kostenstellen korrigieren"),
				message,
				indicator: failed.length ? "orange" : "green",
			});
			listview.refresh();
		},
	});
}
