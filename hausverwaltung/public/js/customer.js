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
		ctx = null;
	}
	if (!ctx || ctx.done || ctx.expected_doctype !== "Customer") return;
	if (!ctx.import_docname || !ctx.row_name) return;
	if (Date.now() - (ctx.ts || 0) > 30 * 60 * 1000) return;

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
			ctx.done = 1;
			localStorage.setItem("hv_bankauszug_autolink_context", JSON.stringify(ctx));
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
