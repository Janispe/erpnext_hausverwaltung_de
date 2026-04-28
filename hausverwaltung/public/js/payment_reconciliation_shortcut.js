window.hv_open_payment_reconciliation = function (values) {
	const company = values.company || frappe.defaults.get_user_default("Company");
	if (!company) {
		frappe.msgprint(__("Bitte zuerst eine Firma wählen oder als Benutzer-Standard setzen."));
		return;
	}

	const party_type = values.party_type;
	const party = values.party;
	if (!party_type || !party) {
		frappe.msgprint(__("Keine Partei für den Zahlungsabgleich gefunden."));
		return;
	}

	const go = (account) => {
		frappe.route_options = {
			company,
			party_type,
			party,
		};
		if (account) {
			frappe.route_options.receivable_payable_account = account;
		}
		frappe.set_route("Form", "Payment Reconciliation");
	};

	if (values.receivable_payable_account) {
		go(values.receivable_payable_account);
		return;
	}

	frappe.call({
		method: "erpnext.accounts.party.get_party_account",
		args: { party_type, party, company },
	}).then((response) => {
		go(response.message);
	});
};

frappe.ui.form.on("Payment Reconciliation", {
	onload(frm) {
		const opts = frappe.route_options;
		if (!opts || !opts.party_type || !opts.party) return;
		frappe.route_options = null;

		const apply = async () => {
			if (opts.company) await frm.set_value("company", opts.company);
			await frm.set_value("party_type", opts.party_type);
			await frm.set_value("party", opts.party);
			if (opts.receivable_payable_account) {
				await frm.set_value("receivable_payable_account", opts.receivable_payable_account);
			}
			if (frm.doc.receivable_payable_account) {
				frm.trigger("get_unreconciled_entries");
			}
		};
		apply();
	},
});
