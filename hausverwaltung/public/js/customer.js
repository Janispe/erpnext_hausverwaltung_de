frappe.ui.form.on("Customer", {
	refresh(frm) {
		window.hv_role_field_visibility?.apply(frm);
		auto_link_import_row(frm);
		if (frm.is_new()) return;

		frm.add_custom_button(__("Mietvertrag"), () => {
			frappe.db
				.get_list("Mietvertrag", {
					fields: ["name"],
					filters: { kunde: frm.doc.name },
					limit: 1,
					order_by: "modified desc",
				})
				.then((rows) => {
					const name = rows && rows.length ? rows[0].name : null;
					if (!name) {
						frappe.msgprint(__("Kein Mietvertrag für diesen Mieter gefunden."));
						return;
					}
					frappe.set_route("Form", "Mietvertrag", name);
				});
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

async function show_customer_festbetraege(frm) {
	const response = await frappe.call({
		method:
			"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen.get_mieter_festbetrag_overview",
		args: { customer: frm.doc.name },
		freeze: true,
		freeze_message: __("Festbeträge und Dimensionsbuchungen werden ermittelt ..."),
	});
	const rows = response.message || [];

	const escape = (value) => frappe.utils.escape_html(String(value || ""));
	const format_date = (value) => value ? frappe.datetime.str_to_user(value) : "–";
	const format_amount = (value) => format_currency(value || 0, frappe.defaults.get_default("currency"));
	let html = `<div class="table-responsive"><table class="table table-bordered">
		<thead><tr>
			<th>${__("Festbetrag / Zusatzposten")}</th>
			<th>${__("Wohnung")}</th>
			<th class="text-right">${__("Vertrags-Festbetrag")}</th>
			<th class="text-right">${__("Dimension Wohnung")}</th>
			<th class="text-right">${__("Gesamt")}</th>
			<th>${__("Gültig von")}</th>
			<th>${__("Gültig bis")}</th>
		</tr></thead><tbody>`;

	if (!rows.length) {
		html += `<tr><td colspan="7" class="text-muted text-center">
			${__("Für diesen Mieter sind keine Festbeträge hinterlegt.")}
		</td></tr>`;
	} else {
		rows.forEach((row) => {
			html += `<tr>
				<td><a href="/app/mietvertrag/${encodeURIComponent(row.mietvertrag)}">${escape(row.bezeichnung)}</a></td>
				<td>${escape(row.wohnung)}</td>
				<td class="text-right">${escape(format_amount(row.vertrags_festbetrag))}</td>
				<td class="text-right">${escape(format_amount(row.dimensionsbuchungen))}</td>
				<td class="text-right"><strong>${escape(format_amount(row.gesamtbetrag))}</strong></td>
				<td>${escape(format_date(row.gueltig_von))}</td>
				<td>${escape(format_date(row.gueltig_bis))}</td>
			</tr>`;
		});
	}
	html += "</tbody></table></div>";

	const dialog = new frappe.ui.Dialog({
		title: __("Festbeträge – {0}", [frm.doc.customer_name || frm.doc.name]),
		fields: [{ fieldtype: "HTML", fieldname: "festbetraege_html" }],
		primary_action_label: __("Schließen"),
		primary_action: () => dialog.hide(),
		size: "large",
	});
	dialog.fields_dict.festbetraege_html.$wrapper.html(html);
	dialog.show();
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
