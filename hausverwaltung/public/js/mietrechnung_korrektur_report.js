// Sammel-Korrektur für die Mietrechnungsprüfung-Reports.
// Hängt einen Button „Abweichungen korrigieren" in die Report-Toolbar, der alle
// FALSCHE_SUMME-Zeilen (mit Sales Invoice) storniert und aus der aktuellen
// Staffelmiete neu erzeugt. FEHLT-Zeilen haben keine Rechnung → nicht korrigierbar.

window.hausverwaltung = window.hausverwaltung || {};
window.hausverwaltung.korrektur = {
	run_for_mietvertrag(mietvertrag, opts = {}) {
		frappe.call({
			method:
				"hausverwaltung.hausverwaltung.scripts.check_mietrechnungen.get_korrigierbare_sollstellungen_fuer_mietvertrag",
			args: {
				mietvertrag,
				scope: opts.scope ? JSON.stringify(opts.scope) : undefined,
			},
			freeze: true,
			freeze_message: __("Prüfe Sollstellungen..."),
			callback: (r) => {
				if (r.exc || !r.message) return;
				if (opts.frm && window.cur_frm && window.cur_frm !== opts.frm) return;
				const invoices = r.message.sales_invoices || [];
				if (!invoices.length) {
					frappe.msgprint(__("Keine korrigierbaren Abweichungen gefunden."));
					return;
				}
				window.hausverwaltung.korrektur.run_bulk(invoices, {
					...opts,
					changes: r.message.aenderungen || [],
				});
			},
		});
	},

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
		const changes = render_changes(opts.changes || []);
		const dialog = new frappe.ui.Dialog({
			title: __("Sollstellungen korrigieren"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p>${frappe.utils.escape_html(message)}</p>${changes}`,
				},
				{
					fieldtype: "Check",
					fieldname: "rebook_payments",
					label: __("Bestehende Zahlungen direkt neu zuordnen (empfohlen)"),
					default: opts.rebook_payments_default === false ? 0 : 1,
					description: __(
						"Aktiviert: Die bisherigen Zahlungsanteile werden direkt auf die ausgewählten neuen Sollstellungen übernommen. Deaktiviert: Die Zahlungsbuchungen und Bankverknüpfungen bleiben bestehen, der gelöste Betrag bleibt jedoch als offenes Guthaben unzugeordnet. Ist die Zahlung niedriger als die neue Sollstellung, bleibt nur die Differenz offen."
					),
				},
			],
			primary_action_label: __("Korrigieren"),
			primary_action(values) {
				const selected_invoices = opts.changes?.length
					? dialog.$wrapper
							.find(".hv-sollstellung-select:checked")
							.map((_index, checkbox) => checkbox.dataset.invoice)
							.get()
					: sis;
				if (!selected_invoices.length) {
					frappe.msgprint(__("Bitte mindestens eine Sollstellung auswählen."));
					return;
				}
				dialog.hide();
				frappe.call({
					method: "hausverwaltung.hausverwaltung.utils.mietrechnung_korrektur.korrigiere_mietrechnungen_bulk",
					args: {
						sales_invoices: JSON.stringify(selected_invoices),
						rebook_payments: values.rebook_payments ? 1 : 0,
						dialog_version: 2,
					},
					freeze: true,
					freeze_message: __("Korrigiere {0} Rechnung(en)…", [selected_invoices.length]),
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
		if (opts.changes?.length) setup_change_selection(dialog, opts.changes.length);
	},
};

function render_changes(changes) {
	if (!changes.length) return "";
	const esc = (value) => frappe.utils.escape_html(String(value ?? ""));
	const money = (value) =>
		Number(value || 0).toLocaleString("de-DE", {
			minimumFractionDigits: 2,
			maximumFractionDigits: 2,
		}) + " €";
	const month_key = (value) => {
		const [month, year] = String(value || "").split("/");
		return `${year || ""}-${String(month || "").padStart(2, "0")}`;
	};
	const rows = [...changes]
		.sort((a, b) =>
			`${month_key(a.monat)}|${a.typ}`.localeCompare(`${month_key(b.monat)}|${b.typ}`)
		)
		.map((change) => {
			const current = Number(change.aktuell || 0);
			const expected = Number(change.erwartet || 0);
			const difference = expected - current;
			const signedDifference = `${difference > 0 ? "+" : ""}${money(difference)}`;
			return `<tr>
				<td><input type="checkbox" class="hv-sollstellung-select" data-invoice="${esc(
					change.sales_invoice
				)}" checked aria-label="${esc(__("Sollstellung auswählen"))}: ${esc(
					change.sales_invoice
				)}"></td>
				<td>${esc(change.monat)}</td>
				<td>${esc(change.typ)}</td>
				<td><a href="/app/sales-invoice/${encodeURIComponent(
					change.sales_invoice
				)}" target="_blank">${esc(change.sales_invoice)}</a></td>
				<td class="text-right">${money(current)}</td>
				<td class="text-right"><strong>${money(expected)}</strong></td>
				<td class="text-right">${signedDifference}</td>
			</tr>`;
		})
		.join("");
	return `<div class="table-responsive mt-3" style="max-height:360px;overflow:auto">
		<table class="table table-bordered table-sm">
			<thead><tr>
				<th><input type="checkbox" class="hv-sollstellung-select-all" checked aria-label="${esc(__(
					"Alle Sollstellungen auswählen"
				))}"></th>
				<th>${__("Monat")}</th>
				<th>${__("Art")}</th>
				<th>${__("Sollstellung")}</th>
				<th class="text-right">${__("Bisher")}</th>
				<th class="text-right">${__("Neu")}</th>
				<th class="text-right">${__("Änderung")}</th>
			</tr></thead>
			<tbody>${rows}</tbody>
		</table>
		<p class="text-muted small">${__("Ausgewählt")}: <span class="hv-sollstellung-selected-count">${
		changes.length
	}</span> / ${changes.length}</p>
	</div>`;
}

function setup_change_selection(dialog, total) {
	const select_all = dialog.$wrapper.find(".hv-sollstellung-select-all");
	const selections = dialog.$wrapper.find(".hv-sollstellung-select");
	const update_state = () => {
		const selected = selections.filter(":checked").length;
		select_all.prop("checked", selected === total);
		select_all.prop("indeterminate", selected > 0 && selected < total);
		dialog.$wrapper.find(".hv-sollstellung-selected-count").text(selected);
	};
	select_all.on("change", () => {
		selections.prop("checked", select_all.prop("checked"));
		update_state();
	});
	selections.on("change", update_state);
	update_state();
}

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
