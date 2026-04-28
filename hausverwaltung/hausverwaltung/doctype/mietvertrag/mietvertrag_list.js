frappe.listview_settings["Mietvertrag"] = {
	onload(listview) {
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
