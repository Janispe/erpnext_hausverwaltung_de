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
					fieldname: "presets_html",
					fieldtype: "HTML",
				},
				{
					fieldname: "from_date",
					fieldtype: "Date",
					label: __("Ausgezogen von"),
					default: defaultFromDate,
					reqd: 1,
				},
				{
					fieldname: "to_date",
					fieldtype: "Date",
					label: __("Ausgezogen bis"),
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
		render_ausgezogen_presets(dialog);
	});
}

function render_ausgezogen_presets(dialog) {
	const presets_api = window.hausverwaltung && window.hausverwaltung.date_presets;
	const presets_field = dialog.get_field("presets_html");
	if (!presets_api || !presets_field || !presets_field.$wrapper) return;

	const $outer = $(
		`<div style="margin:0 0 8px;"><div style="font-size:11px; color:#8d99a6; margin-bottom:4px;">${__("Schnellauswahl:")}</div><div class="hv-date-presets-target" style="display:flex; flex-wrap:wrap; gap:4px;"></div></div>`
	);
	presets_field.$wrapper.empty().append($outer);

	presets_api.render_buttons($outer.find(".hv-date-presets-target"), {
		include_gesamt: false,
		on_select(range) {
			dialog.set_value("from_date", range.from);
			dialog.set_value("to_date", range.to);
		},
	});
}
