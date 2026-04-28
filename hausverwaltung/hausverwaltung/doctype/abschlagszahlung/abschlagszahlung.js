function applyDefaults(frm, defaults) {
	if (!defaults) return;
	Object.entries(defaults).forEach(([field, value]) => {
		if (value && !frm.doc[field]) {
			frm.set_value(field, value);
		}
	});
}

function openJaDialog(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Bitte zuerst speichern."));
		return;
	}
	if (frm.doc.ja_purchase_invoice) {
		frappe.msgprint(
			__(
				"Es existiert bereits eine Jahresabrechnung ({0}). Bitte die Eingangsrechnung zuerst stornieren.",
				[frm.doc.ja_purchase_invoice]
			)
		);
		return;
	}

	const today = frappe.datetime.get_today();
	const dialog = new frappe.ui.Dialog({
		title: __("Jahresabrechnung erstellen"),
		fields: [
			{ fieldtype: "Section Break", label: __("Buchung") },
			{
				fieldname: "kostenart",
				fieldtype: "Link",
				label: __("Kostenart (umlagefähig)"),
				options: "Betriebskostenart",
				default: frm.doc.kostenart || null,
			},
			{
				fieldname: "kostenart_nicht_umlagefaehig",
				fieldtype: "Link",
				label: __("Kostenart (nicht umlagefähig)"),
				options: "Kostenart nicht umlagefaehig",
				default: frm.doc.kostenart_nicht_umlagefaehig || null,
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "expense_account",
				fieldtype: "Link",
				label: __("Aufwandskonto"),
				options: "Account",
				default: frm.doc.expense_account || null,
			},
			{
				fieldname: "cost_center",
				fieldtype: "Link",
				label: __("Kostenstelle"),
				options: "Cost Center",
				default: frm.doc.cost_center || null,
			},
			{
				fieldname: "item_code",
				fieldtype: "Link",
				label: __("Artikel"),
				options: "Item",
				default: frm.doc.item_code || null,
			},
			{ fieldtype: "Section Break", label: __("Rechnung") },
			{
				fieldname: "ja_von",
				fieldtype: "Date",
				label: __("Abrechnungszeitraum von"),
				default: frm.doc.ja_von || null,
				reqd: 1,
			},
			{
				fieldname: "ja_bis",
				fieldtype: "Date",
				label: __("Abrechnungszeitraum bis"),
				default: frm.doc.ja_bis || null,
				reqd: 1,
			},
			{
				fieldname: "ja_betrag",
				fieldtype: "Currency",
				label: __("Jahresrechnungsbetrag"),
				default: frm.doc.ja_betrag || null,
				reqd: 1,
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "ja_rechnungsnr",
				fieldtype: "Data",
				label: __("Rechnungsnummer"),
				default: frm.doc.ja_rechnungsnr || null,
			},
			{
				fieldname: "ja_rechnungsdatum",
				fieldtype: "Date",
				label: __("Rechnungsdatum"),
				default: frm.doc.ja_rechnungsdatum || today,
			},
			{
				fieldname: "ja_wertstellungsdatum",
				fieldtype: "Date",
				label: __("Wertstellungsdatum (Leistungszeitraum)"),
				default: frm.doc.ja_wertstellungsdatum || frm.doc.ja_bis || null,
				description: __("Muss zwischen 'von' und 'bis' liegen. Bestimmt die Kosten-Periode in der Betriebskostenabrechnung."),
				reqd: 1,
			},
		],
		primary_action_label: __("Erstellen"),
		primary_action(values) {
			frm.call("jahresabrechnung_erstellen", values).then((r) => {
				if (r && r.message) {
					frappe.msgprint({
						title: __("Jahresabrechnung erstellt"),
						message: __(
							"Eingangsrechnung: {0}<br>Verrechnete Abschläge: {1}<br>Summe Abschläge: {2}<br>Ergebnis: {3}",
							[
								r.message.purchase_invoice,
								r.message.reconciled_count,
								format_currency(r.message.summe_abschlaege),
								r.message.status,
							]
						),
						indicator: "green",
					});
				}
				dialog.hide();
				frm.reload_doc();
			});
		},
	});

	dialog.fields_dict.kostenart.df.onchange = () => {
		const v = dialog.get_value("kostenart");
		if (!v) return;
		if (dialog.get_value("kostenart_nicht_umlagefaehig")) {
			dialog.set_value("kostenart_nicht_umlagefaehig", null);
		}
		frappe.call({
			method: "hausverwaltung.hausverwaltung.doctype.abschlagszahlung.abschlagszahlung.get_defaults_for_kostenart",
			args: { kostenart: v },
		}).then((r) => {
			if (r && r.message) {
				if (r.message.expense_account)
					dialog.set_value("expense_account", r.message.expense_account);
				if (r.message.item_code)
					dialog.set_value("item_code", r.message.item_code);
			}
		});
	};

	dialog.fields_dict.kostenart_nicht_umlagefaehig.df.onchange = () => {
		const v = dialog.get_value("kostenart_nicht_umlagefaehig");
		if (!v) return;
		if (dialog.get_value("kostenart")) {
			dialog.set_value("kostenart", null);
		}
		frappe.call({
			method: "hausverwaltung.hausverwaltung.doctype.abschlagszahlung.abschlagszahlung.get_defaults_for_kostenart",
			args: { kostenart_nicht_umlagefaehig: v },
		}).then((r) => {
			if (r && r.message) {
				if (r.message.expense_account)
					dialog.set_value("expense_account", r.message.expense_account);
				if (r.message.item_code)
					dialog.set_value("item_code", r.message.item_code);
			}
		});
	};

	dialog.fields_dict.expense_account.df.onchange = () => {
		const v = dialog.get_value("expense_account");
		if (!v) return;
		if (dialog.get_value("kostenart") || dialog.get_value("kostenart_nicht_umlagefaehig")) return;
		frappe.call({
			method: "hausverwaltung.hausverwaltung.doctype.abschlagszahlung.abschlagszahlung.get_defaults_for_konto",
			args: { konto: v },
		}).then((r) => {
			if (r && r.message) {
				if (r.message.kostenart) dialog.set_value("kostenart", r.message.kostenart);
				if (r.message.kostenart_nicht_umlagefaehig)
					dialog.set_value("kostenart_nicht_umlagefaehig", r.message.kostenart_nicht_umlagefaehig);
				if (r.message.item_code) dialog.set_value("item_code", r.message.item_code);
			}
		});
	};

	dialog.show();
}

frappe.ui.form.on("Abschlagszahlung", {
	refresh(frm) {
		if (frm.doc.ja_status) {
			let color = "blue";
			if (frm.doc.ja_differenz > 0.01) color = "orange";
			else if (frm.doc.ja_differenz < -0.01) color = "green";
			else color = "green";
			frm.dashboard.add_indicator(
				__("Letzte Jahresabrechnung: {0}", [frm.doc.ja_status]),
				color
			);
		}

		if (!frm.is_new()) {
			frm.add_custom_button(__("Jahresabrechnung erstellen"), () =>
				openJaDialog(frm)
			);
		}
	},

	immobilie(frm) {
		if (!frm.doc.immobilie) return;
		frappe.call({
			method: "hausverwaltung.hausverwaltung.doctype.abschlagszahlung.abschlagszahlung.get_defaults_for_immobilie",
			args: { immobilie: frm.doc.immobilie },
		}).then((r) => applyDefaults(frm, r && r.message));
	},

	plan_vorbelegen_btn(frm) {
		if (frm.is_dirty()) {
			frappe.msgprint(
				__("Bitte zuerst speichern, bevor der Plan vorbelegt wird.")
			);
			return;
		}
		const default_betrag = frm.doc.betrag || 0;
		const today = frappe.datetime.get_today();
		const next_year = frappe.datetime.add_months(today, 12);

		const dialog = new frappe.ui.Dialog({
			title: __("Plan vorbelegen"),
			fields: [
				{
					fieldname: "rhythmus",
					fieldtype: "Select",
					label: __("Rhythmus"),
					options: "Monatlich\nVierteljährlich\nHalbjährlich\nJährlich",
					default: "Monatlich",
					reqd: 1,
				},
				{
					fieldname: "von",
					fieldtype: "Date",
					label: __("Von"),
					default: today,
					reqd: 1,
				},
				{
					fieldname: "bis",
					fieldtype: "Date",
					label: __("Bis"),
					default: next_year,
					reqd: 1,
				},
				{
					fieldname: "betrag",
					fieldtype: "Currency",
					label: __("Betrag pro Zeile"),
					default: default_betrag,
					reqd: 1,
				},
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
					rhythmus: values.rhythmus,
					von: values.von,
					bis: values.bis,
					betrag: values.betrag,
					replace: values.replace ? 1 : 0,
				}).then((r) => {
					if (r && r.message) {
						frappe.show_alert({
							message: __(
								"Plan vorbelegt: {0} neu, {1} übersprungen, {2} gesamt.",
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
	},

});
