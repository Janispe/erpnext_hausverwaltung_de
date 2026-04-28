frappe.ui.form.on("Journal Entry", {
	refresh(frm) {
		window.hv_role_field_visibility?.apply(frm);
	},
	onload_post_render(frm) {
		window.hv_role_field_visibility?.apply(frm);
	},
});
