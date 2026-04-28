frappe.query_reports["Noch offene Rechnungen und Forderungen"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Firma"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "mode",
			label: __("Ansicht"),
			fieldtype: "Select",
			options: "Forderungen\nRechnungen\nBeides",
			reqd: 1,
			default: "Forderungen",
			on_change: function () {
				update_dependent_filters();
				frappe.query_report.set_filter_value({
					party: "",
					party_account: "",
					voucher_type: "",
				});
				frappe.query_report.refresh();
			},
		},
		{
			fieldname: "von_faelligkeit",
			label: __("Von Fälligkeit"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_start(),
		},
		{
			fieldname: "bis_faelligkeit",
			label: __("Bis Fälligkeit"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.month_end(),
		},
		{
			fieldname: "party",
			label: __("Mieter/Kunde"),
			fieldtype: "MultiSelectList",
			options: "Customer",
			get_data: function (txt) {
				return frappe.db.get_link_options(get_party_doctype(), txt);
			},
		},
		{
			fieldname: "party_account",
			label: __("Forderungskonto"),
			fieldtype: "Link",
			options: "Account",
			get_query: () => {
				return {
					filters: {
						company: frappe.query_report.get_filter_value("company"),
						account_type: get_account_type_filter(),
						is_group: 0,
					},
				};
			},
		},
		{
			fieldname: "cost_center",
			label: __("Kostenstelle"),
			fieldtype: "Link",
			options: "Cost Center",
			get_query: () => {
				return {
					filters: {
						company: frappe.query_report.get_filter_value("company"),
					},
				};
			},
		},
		{
			fieldname: "voucher_type",
			label: __("Belegart"),
			fieldtype: "Select",
			options: "\nSales Invoice\nPayment Entry\nJournal Entry",
		},
		{
			fieldname: "zahlungsrichtung",
			label: __("Zahlungsrichtung"),
			fieldtype: "Select",
			options: "\nGeld bekommen\nGeld bezahlen / erstatten\nAusgeglichen",
			on_change: () => frappe.query_report.refresh(),
		},
		{
			fieldname: "sortierung",
			label: __("Sortierung"),
			fieldtype: "Select",
			options:
				"Fällig am\nRichtung: Geld bekommen zuerst\nRichtung: Geld bezahlen zuerst\nOffener Betrag absteigend",
			default: "Fällig am",
			on_change: () => frappe.query_report.refresh(),
		},
		{
			fieldname: "show_settled",
			label: __("Auch ausgeglichene anzeigen"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "show_written_off",
			label: __("Abgeschriebene anzeigen"),
			fieldtype: "Check",
			default: 0,
			on_change: () => frappe.query_report.refresh(),
		},
	],

	onload: function (report) {
		update_dependent_filters();
		report.page.add_inner_button(__("Ausgewählte abschreiben"), () => {
			write_off_selected_rows();
		});

		report.page.wrapper.off("click.hv_writeoff").on("click.hv_writeoff", ".hv-writeoff-row", function () {
			const invoice = $(this).data("invoice");
			window.hv_sales_invoice_writeoff.open_dialog([invoice], {
				on_success: () => frappe.query_report.refresh(),
			});
		});
	},

	formatter: function (value, row, column, data, default_formatter) {
		if (column.fieldname === "aktion") {
			if (!data || !data.can_write_off) return "";
			const invoice = frappe.utils.escape_html(data.belegnummer || "");
			return `<button class="btn btn-xs btn-default hv-writeoff-row" data-invoice="${invoice}">${__(
				"Abschreiben"
			)}</button>`;
		}
		if (column.fieldname === "zahlungsrichtung") {
			const label = data?.zahlungsrichtung || "";
			if (!label) return "";
			const indicator =
				label === "Geld bekommen" ? "green" : label === "Ausgeglichen" ? "gray" : "orange";
			return `<span class="indicator-pill ${indicator}">${__(label)}</span>`;
		}
		if (column.fieldname === "status") {
			const label = data?.status || "";
			if (!label) return "";
			if (["Abgeschrieben", "Teilweise bezahlt und abgeschrieben"].includes(label)) {
				return `<span class="indicator-pill blue">${__(label)}</span>`;
			}
			return default_formatter(value, row, column, data);
		}
		return default_formatter(value, row, column, data);
	},

	get_datatable_options(options) {
		return Object.assign(options, {
			checkboxColumn: true,
		});
	},
};

function write_off_selected_rows() {
	const selected_rows = get_selected_report_rows();
	if (!selected_rows.length) {
		frappe.msgprint(__("Bitte mindestens eine offene Sales Invoice-Zeile markieren."));
		return;
	}

	const invalid_rows = selected_rows.filter((row) => !row.can_write_off);
	if (invalid_rows.length) {
		frappe.msgprint(__("Bitte nur offene Sales Invoice-Forderungen zum Abschreiben markieren."));
		return;
	}

	window.hv_sales_invoice_writeoff.open_dialog(
		selected_rows.map((row) => row.belegnummer),
		{
			on_success: () => frappe.query_report.refresh(),
		}
	);
}

function get_selected_report_rows() {
	const report = frappe.query_report;
	const data = report.data || [];
	const datatable = report.datatable;
	const rowmanager = datatable && datatable.rowmanager;
	const checked = rowmanager && rowmanager.getCheckedRows ? rowmanager.getCheckedRows() : [];

	return (checked || [])
		.map((row_index) => data[row_index])
		.filter(Boolean);
}

function get_mode() {
	return frappe.query_report.get_filter_value("mode") || "Forderungen";
}

function get_party_doctype() {
	return get_mode() === "Rechnungen" ? "Supplier" : "Customer";
}

function get_account_type() {
	return get_mode() === "Rechnungen" ? "Payable" : "Receivable";
}

function get_account_type_filter() {
	return get_mode() === "Beides" ? ["in", ["Receivable", "Payable"]] : get_account_type();
}

function update_dependent_filters() {
	if (!frappe.query_report) return;

	const mode = get_mode();
	const is_payable = mode === "Rechnungen";
	const is_both = mode === "Beides";
	set_filter_df("voucher_type", {
		options: is_both
			? "\nSales Invoice\nPurchase Invoice\nPayment Entry\nJournal Entry"
			: is_payable
			? "\nPurchase Invoice\nPayment Entry\nJournal Entry"
			: "\nSales Invoice\nPayment Entry\nJournal Entry",
	});
	set_filter_df("party", {
		options: get_party_doctype(),
		label: is_both ? __("Partei") : is_payable ? __("Lieferant") : __("Mieter/Kunde"),
	});
	set_filter_df("party_account", {
		label: is_both ? __("Konto") : is_payable ? __("Verbindlichkeitskonto") : __("Forderungskonto"),
	});
}

function set_filter_df(fieldname, values) {
	const field = frappe.query_report.get_filter(fieldname);
	if (!field) return;

	Object.assign(field.df, values);
	field.refresh();
}
