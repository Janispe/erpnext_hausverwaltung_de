// Sammel-Korrektur für die Mietrechnungsprüfung-Reports.
// Hängt einen Button „Abweichungen korrigieren" in die Report-Toolbar, der alle
// FALSCHE_SUMME-Zeilen (mit Sales Invoice) storniert und aus der aktuellen
// Staffelmiete neu erzeugt. FEHLT-Zeilen haben keine Rechnung → nicht korrigierbar.

window.hausverwaltung = window.hausverwaltung || {};
window.hausverwaltung.korrektur = {
	// Report-Button: korrigiert alle FALSCHE_SUMME-Zeilen des aktuellen Reports.
	attach_to_report(report) {
		report.page.add_inner_button(__("Abweichungen korrigieren"), () => {
			const rows = (report.data || []).filter(
				(r) => r.status === "FALSCHE_SUMME" && r.sales_invoice
			);
			const sis = [...new Set(rows.map((r) => r.sales_invoice))];
			if (!sis.length) {
				frappe.msgprint(
					__("Keine korrigierbaren Abweichungen (Status FALSCHE_SUMME) im aktuellen Report.")
				);
				return;
			}
			window.hausverwaltung.korrektur.run_bulk(sis, { onDone: () => report.refresh() });
		});
	},

	// Sammel-Korrektur: Dialog mit optionaler direkter Zahlungsübernahme →
	// Backend-Bulk → Ergebnis-Dialog.
	run_bulk(sales_invoices, opts = {}) {
		const sis = [...new Set(sales_invoices || [])];
		if (!sis.length) {
			frappe.msgprint(__("Keine Rechnungen ausgewählt."));
			return;
		}
		const message =
			opts.confirm_message ||
			__(
				"{0} Rechnung(en) werden storniert und aus der aktuellen Staffelmiete neu erzeugt. Bestehende Zahlungsbuchungen bleiben erhalten und können unten direkt neu zugeordnet werden; festgeschriebene Rechnungen werden per Gutschrift korrigiert.",
				[sis.length]
			);
		const dialog = new frappe.ui.Dialog({
			title: __("Sollstellungen korrigieren"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p>${frappe.utils.escape_html(message)}</p>`,
				},
				{
					fieldtype: "Check",
					fieldname: "rebook_payments",
					label: __("Bestehende Zahlungen direkt den neuen Sollstellungen zuordnen"),
					default: opts.rebook_payments_default ? 1 : 0,
					description: __(
						"Die Zahlungsbuchungen und ihre Bankverknüpfungen bleiben unverändert bestehen. Ist die Zahlung höher, bleibt der Rest als offenes Guthaben stehen; ist sie niedriger, bleibt die neue Sollstellung teilweise offen."
					),
				},
			],
			primary_action_label: __("Korrigieren"),
			primary_action(values) {
				dialog.hide();
				frappe.call({
					method: "hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur.korrigiere_mietrechnungen_bulk",
					args: {
						sales_invoices: JSON.stringify(sis),
						rebook_payments: values.rebook_payments ? 1 : 0,
					},
					freeze: true,
					freeze_message: __("Korrigiere {0} Rechnung(en)…", [sis.length]),
					callback: (r) => {
						if (r.exc || !r.message) return;
						const m = r.message;
						frappe.msgprint({
							title: __("Korrektur abgeschlossen"),
							message:
								__("{0} erfolgreich, {1} Fehler von {2}.", [m.ok, m.fehler, m.total]) +
								render_payment_rebooking(m) +
								render_errors(m),
							indicator: m.fehler || (m.zahlungsfehler || []).length ? "orange" : "green",
						});
						if (typeof opts.onDone === "function") opts.onDone(m);
					},
				});
			},
			secondary_action_label: __("Abbrechen"),
			secondary_action() {
				dialog.hide();
			},
		});
		dialog.show();
	},
};

function render_payment_rebooking(m) {
	const rows = (m.ergebnisse || []).flatMap((e) => e.zahlungsuebernahmen || []);
	const kept = [
		...new Set((m.ergebnisse || []).flatMap((e) => e.beibehaltene_payment_entries || [])),
	];
	if (!rows.length && !kept.length) return "";
	const keptMessage = kept.length
		? `<div>${__("Zahlungsbuchungen blieben bestehen (nicht storniert): {0}.", [
				frappe.utils.escape_html(kept.join(", ")),
			])}</div>`
		: "";
	if (!rows.length) return `<hr>${keptMessage}`;
	const allocated = rows.reduce((sum, row) => sum + flt(row.zugeordnet), 0);
	const payment_open_by_name = new Map();
	rows.forEach((row) => {
		if (row.payment_entry) {
			// Ein PE kann erst seinem bisherigen Typ und danach zum Ausgleich einer
			// weiteren Sollstellung zugeordnet werden. Nur den finalen Rest zählen.
			payment_open_by_name.set(row.payment_entry, flt(row.zahlung_offen));
		}
	});
	const payment_open = [...payment_open_by_name.values()].reduce((sum, value) => sum + value, 0);
	const invoice_open_by_name = new Map();
	rows.forEach((row) => {
		if (row.neue_sollstellung) {
			// Bei mehreren Teilzahlungen derselben Rechnung enthält die letzte
			// Übernahme deren finalen offenen Betrag; nicht Zwischenstände addieren.
			invoice_open_by_name.set(row.neue_sollstellung, flt(row.rechnung_offen));
		}
	});
	const invoice_open = [...invoice_open_by_name.values()].reduce((sum, value) => sum + value, 0);
	return `<hr>${keptMessage}<div>${__(
		"Bestehende Zahlungsbuchungen direkt neu zugeordnet: {0}. Zugeordnet: {1}; offenes Guthaben: {2}; offene Sollstellung: {3}.",
		[
			payment_open_by_name.size,
			format_currency(allocated),
			format_currency(payment_open),
			format_currency(invoice_open),
		]
	)}</div>`;
}

function render_errors(m) {
	const errs = (m.ergebnisse || []).filter((e) => !e.ok);
	const paymentErrors = m.zahlungsfehler || [];
	if (!errs.length && !paymentErrors.length) return "";
	const items = errs
		.map(
			(e) =>
				`<li>${frappe.utils.escape_html(e.sales_invoice)}: ${frappe.utils.escape_html(
					e.error || ""
				)}</li>`
		)
		.concat(
			paymentErrors.map(
				(e) =>
					`<li>${frappe.utils.escape_html(e.payment_entry || "")}` +
					`: ${frappe.utils.escape_html(e.error || "")}</li>`
			)
		)
		.join("");
	return `<hr><div><b>${__("Fehler")}:</b><ul>${items}</ul></div>`;
}
