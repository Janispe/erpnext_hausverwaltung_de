frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		window.hv_role_field_visibility?.apply(frm);
		if (!can_write_off(frm.doc)) return;

		frm.add_custom_button(__("Abschreiben"), () => {
			window.hv_sales_invoice_writeoff.open_dialog([frm.doc.name], { frm });
		});
	},
	onload_post_render(frm) {
		window.hv_role_field_visibility?.apply(frm);
	},
});

function can_write_off(doc) {
	return (
		doc.docstatus === 1 &&
		!doc.is_return &&
		flt(doc.outstanding_amount) > 0.01 &&
		!["Abgeschrieben", "Teilweise bezahlt und abgeschrieben"].includes(doc.status)
	);
}
