frappe.query_reports["Kautionskonten"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Firma"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "stichtag",
			label: __("Stichtag"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "immobilie",
			label: __("Immobilie"),
			fieldtype: "Link",
			options: "Immobilie",
		},
		{
			fieldname: "nur_aktive_vertraege",
			label: __("Nur aktive Mietverträge"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "nur_mit_kautionskonto",
			label: __("Nur mit Kautionskonto"),
			fieldtype: "Check",
			default: 1,
		},
	],

	onload: function (report) {
		report.page.add_inner_button(__("Drucken"), () => {
			open_kautionskonten_compact_print(report);
		});
		report.page.add_inner_button(__("PDF"), () => {
			open_kautionskonten_print_dialog(report, true);
		});
	},

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "pruefung" && data?.pruefung) {
			const indicator = {
				OK: "green",
				Unterdeckt: "red",
				Überdeckt: "orange",
				"Kautionskonto fehlt": "red",
				"Kaution fehlt": "orange",
			}[data.pruefung] || "gray";
			return `<span class="indicator-pill ${indicator}">${__(data.pruefung)}</span>`;
		}
		if (column.fieldname === "differenz" && Math.abs(data?.differenz || 0) > 0.01) {
			return `<strong>${value || ""}</strong>`;
		}
		return value;
	},
};

const KAUTIONSKONTEN_PRINT_COLUMNS = [
	"pruefung",
	"mietvertrag",
	"immobilie",
	"wohnung",
	"kautionskonto",
	"iban",
	"kaution_betrag",
	"saldo",
	"differenz",
	"kaution_notizen",
];

const KAUTIONSKONTEN_COMPACT_COLUMNS = [
	{ fieldname: "pruefung", label: __("Prüfung"), type: "text" },
	{ fieldname: "mietvertrag", label: __("Mieter"), type: "link_label" },
	{ fieldname: "immobilie", label: __("Immobilie"), type: "text" },
	{ fieldname: "wohnung", label: __("Wohnung"), type: "text" },
	{ fieldname: "kautionskonto", label: __("Kautionskonto"), type: "text" },
	{ fieldname: "iban", label: __("IBAN"), type: "text" },
	{ fieldname: "kaution_betrag", label: __("Kaution"), type: "currency" },
	{ fieldname: "saldo", label: __("Saldo"), type: "currency" },
	{ fieldname: "differenz", label: __("Diff."), type: "currency" },
	{ fieldname: "kaution_notizen", label: __("Notizen"), type: "text" },
];

function open_kautionskonten_print_dialog(report, as_pdf) {
	const dialog = frappe.ui.get_print_settings(
		false,
		(print_settings) => {
			print_settings.orientation = "Landscape";
			print_settings.include_filters = 1;
			if (!print_settings.pick_columns) {
				print_settings.columns = KAUTIONSKONTEN_PRINT_COLUMNS.filter((fieldname) =>
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

function open_kautionskonten_compact_print(report) {
	const rows = report.data || [];
	if (!rows.length) {
		frappe.msgprint(__("Keine Daten zum Drucken vorhanden."));
		return;
	}

	const print_window = window.open("", "_blank");
	if (!print_window) {
		frappe.msgprint(__("Der Browser hat das Druckfenster blockiert."));
		return;
	}

	const filters = build_kautionskonten_filter_text(report);
	const generated_at = frappe.datetime.str_to_user(frappe.datetime.now_datetime());
	const html = `
		<!doctype html>
		<html>
		<head>
			<meta charset="utf-8">
			<title>${escape_html(__("Kautionskonten"))}</title>
			<style>
				@page { size: A4 landscape; margin: 12mm; }
				* { box-sizing: border-box; }
				body {
					margin: 0;
					color: #111827;
					font-family: Arial, sans-serif;
					font-size: 10px;
				}
				header {
					display: flex;
					justify-content: space-between;
					gap: 16px;
					margin-bottom: 10px;
					border-bottom: 1px solid #d1d5db;
					padding-bottom: 8px;
				}
				h1 {
					margin: 0 0 4px;
					font-size: 18px;
					font-weight: 700;
				}
				.meta {
					color: #4b5563;
					font-size: 9px;
					line-height: 1.35;
				}
				.summary {
					text-align: right;
					white-space: nowrap;
				}
				table {
					width: 100%;
					border-collapse: collapse;
					table-layout: fixed;
				}
				th,
				td {
					border: 1px solid #d1d5db;
					padding: 4px 5px;
					vertical-align: top;
					overflow-wrap: anywhere;
				}
				th {
					background: #f3f4f6;
					font-weight: 700;
					text-align: left;
				}
				tfoot td {
					background: #f9fafb;
					font-weight: 700;
				}
				td.number,
				th.number {
					text-align: right;
					white-space: nowrap;
				}
				.status {
					font-weight: 700;
					white-space: nowrap;
				}
				.status-ok { color: #166534; }
				.status-bad { color: #991b1b; }
				.status-warn { color: #9a3412; }
				.notes { font-size: 9px; }
				@media print {
					button { display: none; }
				}
			</style>
		</head>
		<body>
			<header>
				<div>
					<h1>${escape_html(__("Kautionskonten"))}</h1>
					<div class="meta">${filters}</div>
				</div>
				<div class="meta summary">
					${escape_html(__("Stand"))}: ${escape_html(generated_at)}<br>
					${escape_html(__("Anzahl"))}: ${rows.length}
				</div>
			</header>
			<table>
				<thead>
					<tr>${KAUTIONSKONTEN_COMPACT_COLUMNS.map(render_print_header).join("")}</tr>
				</thead>
				<tbody>
					${rows.map(render_kautionskonten_print_row).join("")}
				</tbody>
				<tfoot>
					${render_kautionskonten_print_total_row(rows)}
				</tfoot>
			</table>
			<script>
				window.onload = function () {
					window.print();
				};
			</script>
		</body>
		</html>
	`;
	print_window.document.open();
	print_window.document.write(html);
	print_window.document.close();
}

function render_print_header(column) {
	const cls = column.type === "currency" ? " class=\"number\"" : "";
	return `<th${cls}>${escape_html(column.label)}</th>`;
}

function render_kautionskonten_print_row(row) {
	return `<tr>${KAUTIONSKONTEN_COMPACT_COLUMNS.map((column) => render_print_cell(row, column)).join("")}</tr>`;
}

function render_kautionskonten_print_total_row(rows) {
	const totals = rows.reduce(
		(acc, row) => {
			acc.kaution_betrag += Number(row.kaution_betrag || 0);
			acc.saldo += Number(row.saldo || 0);
			acc.differenz += Number(row.differenz || 0);
			acc.currency = acc.currency || row.currency;
			return acc;
		},
		{ kaution_betrag: 0, saldo: 0, differenz: 0, currency: null }
	);
	const cells = KAUTIONSKONTEN_COMPACT_COLUMNS.map((column, index) => {
		if (index === 0) {
			return `<td><strong>${escape_html(__("Summe"))}</strong></td>`;
		}
		if (["kaution_betrag", "saldo", "differenz"].includes(column.fieldname)) {
			return `<td class="number"><strong>${escape_html(
				format_print_currency(totals[column.fieldname], totals.currency)
			)}</strong></td>`;
		}
		return "<td></td>";
	});
	return `<tr>${cells.join("")}</tr>`;
}

function render_print_cell(row, column) {
	let value = row[column.fieldname];
	let cls = "";
	if (column.type === "link_label" && column.fieldname === "mietvertrag") {
		value = row.mietvertrag_name || row.kunde_anzeige || row.kunde || row.mietvertrag;
	}
	if (column.type === "currency") {
		cls = "number";
		value = format_print_currency(value, row.currency);
	}
	if (column.fieldname === "pruefung") {
		cls = `status ${status_class(value)}`;
	}
	if (column.fieldname === "kaution_notizen") {
		cls = "notes";
	}
	return `<td${cls ? ` class="${cls}"` : ""}>${escape_html(value || "")}</td>`;
}

function build_kautionskonten_filter_text(report) {
	const labels = {
		company: __("Firma"),
		stichtag: __("Stichtag"),
		immobilie: __("Immobilie"),
		nur_aktive_vertraege: __("Nur aktive Mietverträge"),
		nur_mit_kautionskonto: __("Nur mit Kautionskonto"),
	};
	const parts = Object.keys(labels)
		.map((fieldname) => {
			let value = report.get_filter_value?.(fieldname);
			if (value === undefined || value === null || value === "") {
				return null;
			}
			if (fieldname === "stichtag") {
				value = frappe.datetime.str_to_user(value);
			}
			if (fieldname.startsWith("nur_")) {
				value = value ? __("Ja") : __("Nein");
			}
			return `${escape_html(labels[fieldname])}: ${escape_html(value)}`;
		})
		.filter(Boolean);
	return parts.join("<br>");
}

function format_print_currency(value, currency) {
	if (value === undefined || value === null || value === "") {
		return "";
	}
	if (frappe.format) {
		return frappe.format(value, { fieldtype: "Currency", options: "currency" }, {}, { currency });
	}
	return Number(value).toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function status_class(status) {
	if (status === "OK") {
		return "status-ok";
	}
	if (["Unterdeckt", "Kautionskonto fehlt"].includes(status)) {
		return "status-bad";
	}
	return "status-warn";
}

function escape_html(value) {
	return String(value)
		.replaceAll("&", "&amp;")
		.replaceAll("<", "&lt;")
		.replaceAll(">", "&gt;")
		.replaceAll('"', "&quot;")
		.replaceAll("'", "&#039;");
}
