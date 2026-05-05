frappe.query_reports["Mieterkonto"] = {
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
			fieldname: "customer",
			label: __("Mieter/Debitor"),
			fieldtype: "Link",
			options: "Customer",
			reqd: 1,
		},
		{
			fieldname: "from_date",
			label: __("Von"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.year_start
				? frappe.datetime.year_start()
				: frappe.datetime.month_start(),
		},
		{
			fieldname: "to_date",
			label: __("Bis"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "show_kategorien",
			label: __("Aufteilung nach Miete/BK/HK/Guthaben"),
			fieldtype: "Check",
			default: 1,
		},
	],

	onload: function (report) {
		report.page.add_inner_button(__("Drucken"), () => {
			open_print_dialog(report, false);
		});
		report.page.add_inner_button(__("PDF"), () => {
			open_print_dialog(report, true);
		});

		frappe.require("/assets/hausverwaltung/js/date_range_presets.js", () => {
			window.hausverwaltung?.date_presets?.attach_to_query_report(report, {
				from_field: "from_date",
				to_field: "to_date",
				include_gesamt: false,
			});
		});
	},

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "art" && data?.art) {
			const indicator = {
				Forderung: "blue",
				Zahlung: "green",
				Abschreibung: "orange",
				Gutschrift: "gray",
				Eröffnung: "gray",
			}[data.art] || "gray";
			return `<span class="indicator-pill ${indicator}">${__(data.art)}</span>`;
		}
		if (data?.is_total_row || data?.is_opening_row) {
			return `<strong>${value || ""}</strong>`;
		}
		return value;
	},
};

const MIETERKONTO_PRINT_COLUMNS = [
	"datum",
	"art",
	"belegnummer",
	"beschreibung",
	"betrag_miete",
	"betrag_betriebskosten",
	"betrag_heizkosten",
	"betrag_guthaben_nachzahlungen",
	"betrag_summe",
	"kontostand",
];

function open_print_dialog(report, as_pdf) {
	const dialog = frappe.ui.get_print_settings(
		false,
		(print_settings) => {
			print_settings.orientation = "Landscape";
			if (!print_settings.pick_columns) {
				print_settings.columns = MIETERKONTO_PRINT_COLUMNS.filter((fieldname) =>
					report.columns?.some((column) => column.fieldname === fieldname)
				);
			}
			if (as_pdf) {
				report.pdf_report(print_settings);
			} else {
				report.print_report(print_settings);
			}
		},
		report.report_doc?.letter_head,
		report.get_visible_columns()
	);
	report.add_portrait_warning?.(dialog);
}
