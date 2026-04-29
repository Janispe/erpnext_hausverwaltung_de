frappe.listview_settings["Mietvertrag"] = {
	onload(listview) {
		add_ausgezogen_zeitraum_button(listview);

		if (listview._hv_status_checked) {
			return;
		}
		listview._hv_status_checked = true;
		frappe.call({
			method: "hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag.update_statuses_for_list",
			callback(res) {
				const updated = res?.message?.updated || 0;
				if (updated > 0) {
					listview.refresh();
				}
			},
		});
	},
};

function add_ausgezogen_zeitraum_button(listview) {
	if (listview._hv_ausgezogen_button_added) return;
	listview._hv_ausgezogen_button_added = true;

	listview.page.add_inner_button(__("Ausgezogen Zeitraum"), () => {
		const currentYear = new Date().getFullYear();
		const lastYear = currentYear - 1;
		const defaultFromDate = `${lastYear}-01-01`;
		const defaultToDate = `${lastYear}-12-31`;

		const dialog = new frappe.ui.Dialog({
			title: __("Ausgezogen im Zeitraum"),
			fields: [
				{
					fieldname: "from_date",
					fieldtype: "Date",
					label: __("Von"),
					default: defaultFromDate,
					reqd: 1,
				},
				{
					fieldname: "to_date",
					fieldtype: "Date",
					label: __("Bis"),
					default: defaultToDate,
					reqd: 1,
				},
				{
					fieldname: "only_past",
					fieldtype: "Check",
					label: __("Nur vergangene Mietverträge"),
					default: 1,
				},
			],
			primary_action_label: __("Filtern"),
			primary_action(values) {
				if (values.from_date > values.to_date) {
					frappe.msgprint(__("Das Von-Datum darf nicht nach dem Bis-Datum liegen."));
					return;
				}

				listview.filter_area.remove("status");
				listview.filter_area.remove("bis");

				if (values.only_past) {
					listview.filter_area.add("Mietvertrag", "status", "=", "Vergangenheit");
				}
				listview.filter_area.add("Mietvertrag", "bis", "between", [
					values.from_date,
					values.to_date,
				]);
				dialog.hide();
				listview.refresh();
			},
		});

		dialog.show();
	});
}
