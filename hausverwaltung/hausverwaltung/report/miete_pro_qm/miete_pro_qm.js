// Filter + Formatter für „Miete pro qm".
//
// Der Report ist seit 2026-09 ein Script Report (siehe miete_pro_qm.py) —
// die Filter leben deshalb hier im JS, nicht mehr im Report-JSON.

frappe.query_reports["Miete pro qm"] = {
	filters: [
		{
			fieldname: "immobilie",
			label: __("Immobilie"),
			fieldtype: "Link",
			options: "Immobilie",
			reqd: 1,
		},
		{
			fieldname: "stichtag",
			label: __("Stichtag"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "vertragsstatus",
			label: __("Mietverträge"),
			fieldtype: "Select",
			options: ["Nur aktive", "Alle", "Nur beendete", "Nur künftige"].join("\n"),
			default: "Nur aktive",
		},
		{
			fieldname: "sortierung",
			label: __("Sortierung"),
			fieldtype: "Select",
			options: ["Gebäudeteil", "Wohnung", "Mieter"].join("\n"),
			default: "Gebäudeteil",
			description: __("Gebäudeteil: Vorderhaus, Seitenflügel, Hinterhaus; danach Etage und Wohnung."),
		},
		{
			fieldname: "leerstand_anzeigen",
			label: __("Leerstand anzeigen"),
			fieldtype: "Check",
			default: 0,
		},
	],

	formatter: (value, row, column, data, default_formatter) => {
		let formatted = default_formatter(value, row, column, data);

		const isAreaColumn =
			column?.fieldname === "größe" ||
			column?.fieldname === "groesse" ||
			column?.label === "Größe" ||
			column?.label === "Groesse";

		if (isAreaColumn && formatted) {
			formatted = `${formatted} m²`;
		}

		if (data?.is_total) {
			return `<span style="font-weight: 600">${formatted}</span>`;
		}

		if (data?.is_leerstand) {
			return `<span style="color: var(--text-muted)">${formatted}</span>`;
		}

		return formatted;
	},

	onload: function (report) {
		report.page.add_inner_button(__("Drucken"), () => {
			open_miete_pro_qm_print_dialog(report, false);
		});
		report.page.add_inner_button(__("PDF"), () => {
			open_miete_pro_qm_print_dialog(report, true);
		});

		// Konsistenz mit den anderen Hausverwaltungs-Reports: Stichtag-Presets
		// (Monatsanfang/-ende, Jahresanfang …) in die Toolbar hängen.
		try {
			frappe.require("/assets/hausverwaltung/js/date_range_presets.js", () => {
				if (window.hausverwaltung?.date_presets?.attach_to_query_report) {
					window.hausverwaltung.date_presets.attach_to_query_report(report, {
						from_field: "stichtag",
						to_field: "stichtag",
					});
				}
			});
		} catch (e) {
			// Lazy-load fail ist nicht tragisch, der Report läuft auch ohne Presets.
		}
	},
};

function open_miete_pro_qm_print_dialog(report, as_pdf) {
	if (!report.data?.some((row) => !row.is_total)) {
		frappe.msgprint(__("Keine Daten zum Drucken vorhanden."));
		return;
	}

	const dialog = frappe.ui.get_print_settings(
		false,
		(print_settings) => {
			const selected = print_settings.pick_columns ? (print_settings.columns || []) : null;
			if (print_settings.pick_columns && !selected.length) {
				frappe.msgprint(__("Bitte mindestens eine Spalte auswählen."));
				return;
			}

			// Frappes Standarddruck wechselt bei gewählten Spalten zum einfachen
			// Tabellenlayout. Die Auswahl separat übergeben, damit Vorschau und PDF
			// das gestaltete Layout dieses Berichts verwenden.
			print_settings.hv_columns = selected;
			print_settings.columns = null;
			print_settings.orientation = "Landscape";
			print_settings.include_filters = 0;

			if (as_pdf) {
				report.pdf_report(print_settings);
			} else {
				report.print_report(print_settings);
			}
		},
		report.report_doc?.letter_head,
		report.get_visible_columns(),
		true
	);
	report.add_portrait_warning?.(dialog);
}
