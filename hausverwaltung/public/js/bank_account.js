frappe.ui.form.on("Bank Account", {
	refresh(frm) {
		auto_link_import_row(frm);
	},
});

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
	if (!ctx || ctx.done || ctx.expected_doctype !== "Bank Account") return;
	if (!ctx.import_docname || !ctx.row_name) return;
	if (Date.now() - (ctx.ts || 0) > 30 * 60 * 1000) return;

	frappe.call({
		method: "hausverwaltung.hausverwaltung.doctype.bankauszug_import.bankauszug_import.apply_party_to_row_and_relink",
		args: {
			docname: ctx.import_docname,
			row_name: ctx.row_name,
			party_type: frm.doc.party_type || ctx.party_type || "",
			party: frm.doc.party || "",
			iban: frm.doc.iban || ctx.iban || "",
		},
	}).then((r) => {
		try {
			ctx.done = 1;
			localStorage.setItem("hv_bankauszug_autolink_context", JSON.stringify(ctx));
		} catch (e) {
			// ignore
		}
		const msg = (r && r.message) || {};
		const more = (msg.relink_all_count || 0) + (msg.relink_bt_count || 0);
		const tail = more ? __(" Auch {0} weitere Zeile(n) aktualisiert.", [more]) : "";
		frappe.show_alert({
			message: __("Bankkonto verknüpft.") + tail,
			indicator: "green",
		});
		setTimeout(() => {
			frappe.set_route("Form", "Bankauszug Import", ctx.import_docname);
		}, 600);
	}).catch(() => {
		frm.__hv_autolink_done = false;
	});
}
