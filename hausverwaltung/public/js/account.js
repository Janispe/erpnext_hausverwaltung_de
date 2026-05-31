function hv_open_hauptbuch_for_account(account, company) {
	frappe.route_options = {
		account: account ? [account] : undefined,
		from_date: erpnext.utils.get_fiscal_year(frappe.datetime.get_today(), true)[1],
		to_date: erpnext.utils.get_fiscal_year(frappe.datetime.get_today(), true)[2],
		company: company,
	};
	frappe.set_route("query-report", "Hauptbuch HV");
}

frappe.ui.form.on("Account", {
	refresh(frm) {
		if (frm.is_new() || cint(frm.doc.is_group) || frappe.boot.user.can_read.indexOf("GL Entry") === -1) {
			return;
		}

		frm.remove_custom_button(__("General Ledger"), __("View"));
		frm.add_custom_button(
			__("General Ledger"),
			() => hv_open_hauptbuch_for_account(frm.doc.name, frm.doc.company),
			__("View")
		);
	},
});
