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
			open_kautionskonten_compact_print_dialog(report, false);
		});
		report.page.add_inner_button(__("PDF"), () => {
			open_kautionskonten_compact_print_dialog(report, true);
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
	"mietvertrag",
	"immobilie",
	"wohnung",
	"kautionskonto",
	"iban",
	"kaution_betrag",
];

const KAUTIONSKONTEN_COMPACT_COLUMNS = [
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

function open_kautionskonten_compact_print_dialog(report, as_pdf) {
	if (!report.data?.length) {
		frappe.msgprint(__("Keine Daten zum Drucken vorhanden."));
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: as_pdf ? __("Spalten für das PDF") : __("Spalten für den Ausdruck"),
		fields: [
			{
				fieldname: "columns",
				fieldtype: "MultiCheck",
				label: __("Spalten"),
				columns: 2,
				sort_options: false,
				select_all: true,
				options: KAUTIONSKONTEN_COMPACT_COLUMNS.map((column) => ({
					label: column.label,
					value: column.fieldname,
					checked: KAUTIONSKONTEN_PRINT_COLUMNS.includes(column.fieldname),
				})),
			},
		],
		primary_action_label: as_pdf ? __("PDF erstellen") : __("Drucken"),
		primary_action(values) {
			const selected = new Set(values.columns || []);
			const columns = KAUTIONSKONTEN_COMPACT_COLUMNS.filter((column) => selected.has(column.fieldname));
			if (!columns.length) {
				frappe.msgprint(__("Bitte mindestens eine Spalte auswählen."));
				return;
			}
			if (as_pdf) {
				frappe.render_pdf(build_kautionskonten_print_html(report, columns, false), {
					orientation: "Landscape",
					report_name: "Kautionskonten.pdf",
				});
			} else {
				open_kautionskonten_compact_print(report, columns);
			}
			dialog.hide();
		},
	});
	dialog.show();
}

function open_kautionskonten_compact_print(report, columns) {
	const print_window = window.open("", "_blank");
	if (!print_window) {
		frappe.msgprint(__("Der Browser hat das Druckfenster blockiert."));
		return;
	}
	print_window.document.open();
	print_window.document.write(build_kautionskonten_print_html(report, columns, true));
	print_window.document.close();
}

function build_kautionskonten_print_html(report, columns, auto_print) {
	const rows = report.data || [];
	const filters = build_kautionskonten_filter_text(report);
	const generated_at = frappe.datetime.str_to_user(frappe.datetime.now_datetime());
	return `
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
					margin-bottom: 10px;
					border-bottom: 1px solid #d1d5db;
					padding-bottom: 8px;
				}
				header::after { content: ""; display: table; clear: both; }
				header > div:first-child { float: left; }
				header > div:last-child { float: right; }
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
					word-wrap: break-word;
				}
				thead { display: table-header-group; }
				tr { page-break-inside: avoid; }
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
					<tr>${columns.map(render_print_header).join("")}</tr>
				</thead>
				<tbody>
					${rows.map((row) => render_kautionskonten_print_row(row, columns)).join("")}
				</tbody>
				${columns.some((column) => column.type === "currency")
					? `<tfoot>${render_kautionskonten_print_total_row(rows, columns)}</tfoot>`
					: ""}
			</table>
			${auto_print ? `<script>window.onload = function () { window.print(); };</script>` : ""}
		</body>
		</html>
	`;
}

function render_print_header(column) {
	const cls = column.type === "currency" ? " class=\"number\"" : "";
	return `<th${cls}>${escape_html(column.label)}</th>`;
}

function render_kautionskonten_print_row(row, columns) {
	return `<tr>${columns.map((column) => render_print_cell(row, column)).join("")}</tr>`;
}

function render_kautionskonten_print_total_row(rows, columns) {
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
	const label_index = columns.findIndex((column) => column.type !== "currency");
	const cells = columns.map((column, index) => {
		if (index === label_index) {
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
