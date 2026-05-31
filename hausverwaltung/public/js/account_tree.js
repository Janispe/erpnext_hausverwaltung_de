(function () {
	function get_fiscal_year_dates() {
		const fiscal_year = erpnext.utils.get_fiscal_year(frappe.datetime.get_today(), true);
		return {
			from_date: fiscal_year[1],
			to_date: fiscal_year[2],
		};
	}

	function open_hauptbuch_hv(options) {
		frappe.route_options = Object.assign(get_fiscal_year_dates(), options || {});
		frappe.set_route("query-report", "Hauptbuch HV");
	}

	const settings = frappe.treeview_settings["Account"];
	if (!settings) return;

	const original_onload = settings.onload;
	settings.onload = function (treeview) {
		original_onload && original_onload.call(this, treeview);

		function get_company() {
			return treeview.page.fields_dict.company.get_value();
		}

		treeview.page.remove_inner_button(__("General Ledger"), __("View"));
		treeview.page.add_inner_button(
			__("General Ledger"),
			() => open_hauptbuch_hv({ company: get_company() }),
			__("View")
		);
	};

	(settings.toolbar || []).forEach((item) => {
		if (item.label !== __("View Ledger")) return;

		item.click = function (node) {
			open_hauptbuch_hv({
				account: node.label ? [node.label] : undefined,
				company: settings.treeview.page.fields_dict.company.get_value(),
			});
		};
	});
})();
