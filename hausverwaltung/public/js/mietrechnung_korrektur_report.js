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

	// Sammel-Korrektur: Bestätigung → Backend-Bulk → Ergebnis-Dialog.
	run_bulk(sales_invoices, opts = {}) {
		const sis = [...new Set(sales_invoices || [])];
		if (!sis.length) {
			frappe.msgprint(__("Keine Rechnungen ausgewählt."));
			return;
		}
		frappe.confirm(
			__(
				"{0} Rechnung(en) werden storniert und aus der aktuellen Staffelmiete neu erzeugt. Bezahlte Rechnungen werden inkl. Zahlungs-Neuzuordnung behandelt, festgeschriebene per Gutschrift. Fortfahren?",
				[sis.length]
			),
			() => {
				frappe.call({
					method: "hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur.korrigiere_mietrechnungen_bulk",
					args: { sales_invoices: JSON.stringify(sis) },
					freeze: true,
					freeze_message: __("Korrigiere {0} Rechnung(en)…", [sis.length]),
					callback: (r) => {
						if (r.exc || !r.message) return;
						const m = r.message;
						frappe.msgprint({
							title: __("Korrektur abgeschlossen"),
							message:
								__("{0} erfolgreich, {1} Fehler von {2}.", [m.ok, m.fehler, m.total]) +
								render_errors(m),
							indicator: m.fehler ? "orange" : "green",
						});
						if (typeof opts.onDone === "function") opts.onDone(m);
					},
				});
			}
		);
	},
};

function render_errors(m) {
	const errs = (m.ergebnisse || []).filter((e) => !e.ok);
	if (!errs.length) return "";
	const items = errs
		.map(
			(e) =>
				`<li>${frappe.utils.escape_html(e.sales_invoice)}: ${frappe.utils.escape_html(
					e.error || ""
				)}</li>`
		)
		.join("");
	return `<hr><div><b>${__("Fehler")}:</b><ul>${items}</ul></div>`;
}
