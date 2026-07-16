frappe.ui.form.on("Customer", {
	refresh(frm) {
		window.hv_role_field_visibility?.apply(frm);
		auto_link_import_row(frm);
		if (frm.is_new()) return;

		frm.add_custom_button(__("Mietvertrag"), () => {
			open_customer_mietvertrag(frm);
		}, __("View"));

		frm.add_custom_button(__("Festbeträge"), () => {
			show_customer_festbetraege(frm);
		}, __("View"));

		frm.add_custom_button(__("Zahlungsabgleich öffnen"), () => {
			hv_open_payment_reconciliation({
				company: frappe.defaults.get_user_default("Company"),
				party_type: "Customer",
				party: frm.doc.name,
			});
		}, __("Accounting"));

		frm.add_custom_button(__("Mieterkonto"), () => {
			hv_open_mieterkonto_report({
				customer: frm.doc.name,
			});
		}, __("Accounting"));
	},
	onload_post_render(frm) {
		window.hv_role_field_visibility?.apply(frm);
	},
});

async function open_customer_mietvertrag(frm) {
	const rows = await frappe.db.get_list("Mietvertrag", {
		fields: ["name"],
		filters: { kunde: frm.doc.name },
		limit: 1,
		order_by: "modified desc",
	});
	const name = rows && rows.length ? rows[0].name : null;
	if (!name) {
		frappe.msgprint(__("Kein Mietvertrag für diesen Mieter gefunden."));
		return;
	}
	frappe.set_route("Form", "Mietvertrag", name);
}

async function show_customer_festbetraege(frm) {
	const escape = (value) => frappe.utils.escape_html(String(value || ""));
	const format_date = (value) => value ? frappe.datetime.str_to_user(value) : "–";
	const format_amount = (value) => format_currency(value || 0, frappe.defaults.get_default("currency"));
	const dialog = new frappe.ui.Dialog({
		title: __("Festbeträge – {0}", [frm.doc.customer_name || frm.doc.name]),
		fields: [
			{
				fieldtype: "Date",
				fieldname: "von",
				label: __("Von"),
				default: frappe.datetime.year_start(),
				reqd: 1,
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Date",
				fieldname: "bis",
				label: __("Bis"),
				default: frappe.datetime.year_end(),
				reqd: 1,
			},
			{ fieldtype: "Section Break" },
			{ fieldtype: "HTML", fieldname: "festbetraege_html" },
		],
		primary_action_label: __("Filter anwenden"),
		primary_action: () => load_rows(),
		size: "large",
	});

	const wrapper = dialog.fields_dict.festbetraege_html.$wrapper;
	const render_rows = (data) => {
		const manualRows = data.manual_rows || [];
		const dimensionRows = data.dimension_rows || [];
		let html = `<div class="d-flex justify-content-between align-items-center mb-2">
			<h5 class="mb-0">${__("Manuelle Festbeträge")}</h5>
			<button class="btn btn-xs btn-default" data-action="edit-manual">
				${__("Manuelle Festbeträge bearbeiten")}
			</button>
		</div>
		<div class="table-responsive"><table class="table table-bordered">
			<thead><tr>
				<th>${__("Festbetrag / Zusatzposten")}</th>
				<th>${__("Wohnung")}</th>
				<th class="text-right">${__("Betrag")}</th>
				<th>${__("Gültig von")}</th>
				<th>${__("Gültig bis")}</th>
			</tr></thead><tbody>`;

		if (!manualRows.length) {
			html += `<tr><td colspan="5" class="text-muted text-center">
				${__("Im gewählten Zeitraum sind keine manuellen Festbeträge hinterlegt.")}
			</td></tr>`;
		} else {
			manualRows.forEach((row) => {
				html += `<tr>
					<td><a href="/app/mietvertrag/${encodeURIComponent(row.mietvertrag)}">${escape(row.bezeichnung)}</a></td>
					<td>${escape(row.wohnung)}</td>
					<td class="text-right">${escape(format_amount(row.betrag))}</td>
					<td>${escape(format_date(row.gueltig_von))}</td>
					<td>${escape(format_date(row.gueltig_bis))}</td>
				</tr>`;
			});
		}
		html += `</tbody></table></div>
			<h5 class="mt-4">${__("Dimensionsbuchungen (nicht manuell änderbar)")}</h5>
			<p class="text-muted small">${__("Diese Beträge stammen aus Buchungsbelegen mit der Abrechnungsdimension Wohnung.")}</p>
			<div class="table-responsive"><table class="table table-bordered">
				<thead><tr>
					<th>${__("Kostenart")}</th>
					<th>${__("Wohnung")}</th>
					<th class="text-right">${__("Betrag")}</th>
					<th>${__("Belegdatum")}</th>
					<th>${__("Belegtyp")}</th>
					<th>${__("Belegnummer")}</th>
				</tr></thead><tbody>`;

		if (!dimensionRows.length) {
			html += `<tr><td colspan="6" class="text-muted text-center">
				${__("Im gewählten Zeitraum sind keine Dimensionsbuchungen vorhanden.")}
			</td></tr>`;
		} else {
			dimensionRows.forEach((row) => {
				html += `<tr>
					<td>${escape(row.bezeichnung)}</td>
					<td>${escape(row.wohnung)}</td>
					<td class="text-right">${escape(format_amount(row.betrag))}</td>
					<td>${escape(format_date(row.belegdatum))}</td>
					<td>${escape(row.belegtyp)}</td>
					<td>${escape(row.belegnummer)}</td>
				</tr>`;
			});
		}
		html += "</tbody></table></div>";
		wrapper.html(html);
		wrapper.find('[data-action="edit-manual"]').on("click", () => {
			dialog.hide();
			open_customer_mietvertrag(frm);
		});
	};

	const load_rows = async () => {
		const von = dialog.get_value("von");
		const bis = dialog.get_value("bis");
		if (!von || !bis) return;
		wrapper.html(`<div class="text-muted text-center py-5">${__("Festbeträge werden geladen ...")}</div>`);
		const response = await frappe.call({
			method:
				"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen.get_mieter_festbetrag_overview",
			args: {
				customer: frm.doc.name,
				von,
				bis,
			},
		});
		render_rows(response.message || {});
	};

	dialog.show();
	await load_rows();
}

function hv_open_mieterkonto_report({ customer, from_date, to_date }) {
	const company = frappe.defaults.get_user_default("Company");
	if (!company) {
		frappe.msgprint(__("Bitte zuerst eine Standard-Firma setzen."));
		return;
	}
	if (!customer) {
		frappe.msgprint(__("Kein Mieter/Debitor vorhanden."));
		return;
	}

	frappe.set_route("query-report", "Mieterkonto", {
		company,
		customer,
		from_date: from_date || frappe.datetime.year_start(),
		to_date: to_date || frappe.datetime.get_today(),
	});
}

function auto_link_import_row(frm) {
	if (frm.is_new()) return;
	if (frm.__hv_autolink_done) return;
	frm.__hv_autolink_done = true;

	let ctx = null;
	try {
		ctx = JSON.parse(localStorage.getItem("hv_bankauszug_autolink_context") || "null");
	} catch (e) {
		localStorage.removeItem("hv_bankauszug_autolink_context");
		ctx = null;
	}
	if (!ctx) return;
	if (ctx.done) {
		localStorage.removeItem("hv_bankauszug_autolink_context");
		return;
	}
	if (ctx.expected_doctype !== "Customer") return;
	if (!ctx.import_docname || !ctx.row_name || Date.now() - (ctx.ts || 0) > 30 * 60 * 1000) {
		localStorage.removeItem("hv_bankauszug_autolink_context");
		return;
	}

	frappe.call({
		method: "hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.apply_party_to_row_and_relink",
		args: {
			docname: ctx.import_docname,
			row_name: ctx.row_name,
			party_type: "Customer",
			party: frm.doc.name,
			iban: ctx.iban || "",
		},
	}).then((r) => {
		try {
			localStorage.removeItem("hv_bankauszug_autolink_context");
		} catch (e) {
			// ignore
		}
		const msg = (r && r.message) || {};
		const ba = msg.bank_account || {};
		const more = (msg.relink_all_count || 0) + (msg.relink_bt_count || 0);
		const tail = more ? __(" Auch {0} weitere Zeile(n) aktualisiert.", [more]) : "";
		if (ba.created) {
			frappe.show_alert({
				message: __("Mieter + Bankkonto angelegt – Zeile aktualisiert.") + tail,
				indicator: "green",
			});
		} else {
			frappe.show_alert({
				message: __("Mieter zugewiesen.") + tail,
				indicator: "green",
			});
		}
		setTimeout(() => {
			frappe.set_route("Form", "Bankauszug Import", ctx.import_docname);
		}, 600);
	}).catch(() => {
		frm.__hv_autolink_done = false;
	});
}
