frappe.ui.form.on("Purchase Invoice", {
	refresh(frm) {
		window.hv_role_field_visibility?.apply(frm);
	},
	onload_post_render(frm) {
		window.hv_role_field_visibility?.apply(frm);
	},
});
