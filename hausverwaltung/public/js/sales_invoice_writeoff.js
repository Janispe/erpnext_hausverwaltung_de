(() => {
	const METHOD_PREVIEW =
		"hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff.get_writeoff_preview";
	const METHOD_WRITE_OFF =
		"hausverwaltung.hausverwaltung.utils.sales_invoice_writeoff.write_off_sales_invoices";

	function escape(value) {
		return frappe.utils.escape_html(value == null ? "" : String(value));
	}

	function format_amount(amount, currency) {
		if (typeof format_currency === "function") {
			return format_currency(amount, currency);
		}
		return frappe.format(amount, { fieldtype: "Currency", options: currency });
	}

	function open_dialog(invoice_names, opts = {}) {
		const names = normalize_names(invoice_names);
		if (!names.length) {
			frappe.msgprint(__("Bitte mindestens eine Rechnung auswählen."));
			return;
		}

		frappe.call({
			method: METHOD_PREVIEW,
			args: {
				invoice_names: JSON.stringify(names),
			},
			freeze: true,
			callback: (response) => {
				const preview = response.message;
				if (!preview || !preview.invoices || !preview.invoices.length) return;
				show_dialog(preview, opts);
			},
		});
	}

	function show_dialog(preview, opts) {
		const dialog = new frappe.ui.Dialog({
			title: __("Forderung abschreiben"),
			fields: [
				{
					fieldname: "summary",
					fieldtype: "HTML",
					options: render_preview(preview),
				},
				{
					fieldname: "posting_date",
					label: __("Buchungsdatum"),
					fieldtype: "Date",
					reqd: 1,
					default: preview.posting_date || frappe.datetime.get_today(),
				},
			],
			primary_action_label: __("Abschreiben"),
			primary_action(values) {
				dialog.disable_primary_action();
				frappe.call({
					method: METHOD_WRITE_OFF,
					args: {
						invoice_names: JSON.stringify(preview.invoices.map((row) => row.sales_invoice)),
						posting_date: values.posting_date,
					},
					freeze: true,
					callback: (response) => {
						dialog.hide();
						show_result(response.message);
						if (opts.frm) {
							opts.frm.reload_doc();
						}
						if (opts.on_success) {
							opts.on_success(response.message);
						}
					},
					always: () => {
						dialog.enable_primary_action();
					},
				});
			},
		});
		dialog.show();
	}

	function render_preview(preview) {
		const rows = preview.invoices
			.map(
				(row) => `
					<tr>
						<td>${escape(row.sales_invoice)}</td>
						<td>${escape(row.customer)}</td>
						<td>${escape(row.cost_center)}</td>
						<td class="text-right">${format_amount(row.amount, row.currency)}</td>
					</tr>`
			)
			.join("");
		const first_currency = preview.invoices[0].currency;

		return `
			<div class="small text-muted" style="margin-bottom: 10px;">
				${__("Abschreibungskonto")}: <b>${escape(preview.writeoff_account)}</b>
			</div>
			<table class="table table-bordered table-condensed" style="margin-bottom: 10px;">
				<thead>
					<tr>
						<th>${__("Rechnung")}</th>
						<th>${__("Kunde")}</th>
						<th>${__("Kostenstelle")}</th>
						<th class="text-right">${__("Offen")}</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
			<div>
				<b>${__("Summe")}:</b> ${format_amount(preview.total, first_currency)}
			</div>`;
	}

	function show_result(result) {
		if (!result || !result.journal_entries) return;

		const links = result.journal_entries
			.map((row) => {
				const je_link = `<a href="/app/journal-entry/${encodeURIComponent(
					row.journal_entry
				)}">${escape(row.journal_entry)}</a>`;
				const si_link = `<a href="/app/sales-invoice/${encodeURIComponent(
					row.sales_invoice
				)}">${escape(row.sales_invoice)}</a>`;
				return `<li>${si_link}: ${je_link}</li>`;
			})
			.join("");

		frappe.msgprint({
			title: __("Abschreibung gebucht"),
			indicator: "green",
			message: `<p>${__("Erzeugte Journal Entries")}:</p><ul>${links}</ul>`,
		});
	}

	function normalize_names(invoice_names) {
		if (typeof invoice_names === "string") {
			return invoice_names
				.split(",")
				.map((name) => name.trim())
				.filter(Boolean);
		}
		return [...new Set((invoice_names || []).map((name) => String(name).trim()).filter(Boolean))];
	}

	window.hv_sales_invoice_writeoff = {
		open_dialog,
	};
})();
