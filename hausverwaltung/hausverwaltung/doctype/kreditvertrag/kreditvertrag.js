function openPlanVorbelegenDialog(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Bitte zuerst speichern, bevor der Plan vorbelegt wird."));
		return;
	}
	const today = frappe.datetime.get_today();
	const default_start = frm.doc.laufzeit_start || today;
	const default_ende = frm.doc.laufzeit_ende || frappe.datetime.add_months(default_start, 24);

	if (!frm.doc.anfangs_restschuld || parseFloat(frm.doc.anfangs_restschuld) <= 0) {
		frappe.msgprint(
			__("Bitte zuerst die Anfangs-Restschuld am Kreditvertrag setzen, dann den Plan generieren.")
		);
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Tilgungsplan vorbelegen (Annuität)"),
		fields: [
			{
				fieldtype: "HTML",
				options: __(
					"Anfangsschuld: <b>{0}</b> (aus Feld 'Anfangs-Restschuld' — zum Ändern Dialog schließen und am Kreditvertrag editieren).",
					[format_currency(frm.doc.anfangs_restschuld)]
				),
			},
			{
				fieldname: "zinssatz_p_a",
				fieldtype: "Percent",
				label: __("Zinssatz p.a."),
				reqd: 1,
				description: __("Nominaler Jahreszinssatz, z.B. 3.5"),
			},
			{
				fieldname: "annuitaet",
				fieldtype: "Currency",
				label: __("Annuität (monatliche Rate)"),
				reqd: 1,
			},
			{ fieldtype: "Section Break" },
			{
				fieldname: "start",
				fieldtype: "Date",
				label: __("Erste Rate"),
				default: default_start,
				reqd: 1,
			},
			{
				fieldname: "ende",
				fieldtype: "Date",
				label: __("Letzte Rate (oder Vollständig)"),
				default: default_ende,
				reqd: 1,
				description: __(
					"Plan endet entweder am angegebenen Datum oder wenn Restschuld 0 erreicht — je nachdem was zuerst eintritt."
				),
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "replace",
				fieldtype: "Check",
				label: __("Bestehenden Plan ersetzen"),
				default: 0,
			},
		],
		primary_action_label: __("Vorbelegen"),
		primary_action(values) {
			frm.call("plan_vorbelegen", {
				start: values.start,
				ende: values.ende,
				zinssatz_p_a: values.zinssatz_p_a,
				annuitaet: values.annuitaet,
				replace: values.replace ? 1 : 0,
			}).then((r) => {
				if (r && r.message) {
					frappe.show_alert({
						message: __(
							"Plan: {0} neu, {1} übersprungen, {2} gesamt.",
							[r.message.added, r.message.skipped, r.message.total_rows]
						),
						indicator: "green",
					});
				}
				dialog.hide();
				frm.reload_doc();
			});
		},
	});
	dialog.show();
}

function openCsvImportDialog(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Bitte zuerst speichern, bevor eine CSV importiert wird."));
		return;
	}
	const dialog = new frappe.ui.Dialog({
		title: __("Tilgungsplan aus CSV importieren"),
		fields: [
			{
				fieldname: "file",
				fieldtype: "Attach",
				label: __("CSV-Datei"),
				reqd: 1,
				description: __(
					"Spalten: datum, zinsanteil, tilgungsanteil, optional sondertilgung, optional restschuld. Delimiter ; oder ,."
				),
			},
			{
				fieldname: "mode",
				fieldtype: "Select",
				label: __("Modus"),
				options: [
					{ value: "extend", label: __("Nur neue Daten ergänzen") },
					{ value: "replace", label: __("Plan ersetzen") },
				],
				default: "extend",
				reqd: 1,
			},
		],
		primary_action_label: __("Importieren"),
		primary_action(values) {
			frm.call("plan_csv_import", {
				file_url: values.file,
				mode: values.mode,
			}).then((r) => {
				if (r && r.message) {
					const msg = r.message;
					let body = __("Importiert: {0}, übersprungen: {1}, gesamt: {2}", [
						msg.added,
						msg.skipped,
						msg.total_rows,
					]);
					if (msg.restschuld_mismatches && msg.restschuld_mismatches.length) {
						body += "<br><br><b>" + __("Restschuld-Abweichungen ggü. CSV:") + "</b><br>";
						body += msg.restschuld_mismatches
							.slice(0, 10)
							.map(
								(m) =>
									`${m.datum}: erwartet ${format_currency(m.erwartet)}, berechnet ${format_currency(m.berechnet)}, Diff ${format_currency(m.differenz)}`
							)
							.join("<br>");
					}
					frappe.msgprint({
						title: __("CSV-Import abgeschlossen"),
						message: body,
						indicator: msg.restschuld_mismatches && msg.restschuld_mismatches.length ? "orange" : "green",
					});
				}
				dialog.hide();
				frm.reload_doc();
			});
		},
	});
	dialog.show();
}

function renderRestschuldIndicator(frm) {
	if (frm.is_new()) return;
	const abweichung = parseFloat(frm.doc.restschuld_abweichung || 0);
	const aktuelle = parseFloat(frm.doc.aktuelle_restschuld || 0);
	const gl = parseFloat(frm.doc.gl_saldo_darlehenskonto || 0);

	// Restschuld-Indicator immer anzeigen
	frm.dashboard.add_indicator(
		__("Restschuld berechnet: {0}", [format_currency(aktuelle)]),
		"blue"
	);
	frm.dashboard.add_indicator(
		__("GL-Saldo Darlehen: {0}", [format_currency(gl)]),
		"blue"
	);

	if (Math.abs(abweichung) > 1.0) {
		frm.dashboard.add_indicator(
			__("Abweichung: {0} — bitte Eröffnungsbuchung prüfen", [format_currency(abweichung)]),
			"red"
		);
	} else {
		frm.dashboard.add_indicator(__("Restschuld ↔ GL stimmig"), "green");
	}
}

frappe.ui.form.on("Kreditvertrag", {
	refresh(frm) {
		renderRestschuldIndicator(frm);

		// Filter Darlehenskonto auf Liability
		frm.set_query("darlehenskonto", () => ({
			filters: {
				root_type: "Liability",
				is_group: 0,
				company: frm.doc.company,
			},
		}));

		frm.set_query("zinsaufwandskonto", () => ({
			filters: {
				root_type: "Expense",
				is_group: 0,
				company: frm.doc.company,
			},
		}));
	},

	plan_vorbelegen_btn(frm) {
		openPlanVorbelegenDialog(frm);
	},

	plan_csv_import_btn(frm) {
		openCsvImportDialog(frm);
	},

	immobilie(frm) {
		if (!frm.doc.immobilie) return;
		frappe.call({
			method: "hausverwaltung.hausverwaltung.doctype.kreditvertrag.kreditvertrag.get_defaults_for_immobilie",
			args: { immobilie: frm.doc.immobilie },
		}).then((r) => {
			const m = (r && r.message) || {};
			if (m.cost_center && !frm.doc.cost_center) {
				frm.set_value("cost_center", m.cost_center);
			}
		});
	},
});
