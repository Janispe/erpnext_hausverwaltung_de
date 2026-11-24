(() => {
	const settings = frappe.listview_settings.Issue || {};
	const onload = settings.onload;
	settings.onload = function (listview) {
		onload?.call(this, listview);
		const staff = frappe.session.user === 'Administrator'
			|| frappe.user.has_role(['Hausverwalter', 'System Manager']);
		if (!staff || !frappe.model.can_create('Issue')) return;

		listview.page.add_inner_button(__('Telefon-Schaden erfassen'), () => {
			const issue = frappe.model.get_new_doc('Issue');
			Object.assign(issue, { hv_wohnungsschaden: 1, hv_eingang: 'Telefon' });
			frappe.set_route('Form', 'Issue', issue.name);
		});
	};
	frappe.listview_settings.Issue = settings;
})();
