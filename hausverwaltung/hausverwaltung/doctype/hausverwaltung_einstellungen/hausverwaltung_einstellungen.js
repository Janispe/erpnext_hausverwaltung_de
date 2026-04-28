frappe.ui.form.on("Hausverwaltung Einstellungen", {
	setup(frm) {
		const set_account_query = (fieldname) => {
			frm.set_query(fieldname, "income_accounts", function (doc, cdt, cdn) {
				const row = locals[cdt] && locals[cdt][cdn];
				const filters = {
					root_type: "Income",
					is_group: 0,
				};
				if (row && row.company) {
					filters.company = row.company;
				}
				return { filters };
			});
		};

		["miete_income_account", "bk_income_account", "hk_income_account"].forEach(set_account_query);
	},
});
