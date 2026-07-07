frappe.ui.form.on("Journal Entry", {
	setup(frm) {
		hv_default_journal_entry_wertstellungsdatum_from_posting_date(frm);
	},
	refresh(frm) {
		window.hv_role_field_visibility?.apply(frm);
		hv_default_journal_entry_wertstellungsdatum_from_posting_date(frm);
	},
	onload_post_render(frm) {
		window.hv_role_field_visibility?.apply(frm);
		hv_default_journal_entry_wertstellungsdatum_from_posting_date(frm);
	},
	posting_date(frm) {
		hv_default_journal_entry_wertstellungsdatum_from_posting_date(frm);
	},
	validate(frm) {
		hv_default_journal_entry_wertstellungsdatum_from_posting_date(frm);
	},
});

function hv_default_journal_entry_wertstellungsdatum_from_posting_date(frm) {
	if (!frm.doc || frm.doc.custom_wertstellungsdatum || !frm.doc.posting_date) return;
	frm.set_value("custom_wertstellungsdatum", frm.doc.posting_date);
}
