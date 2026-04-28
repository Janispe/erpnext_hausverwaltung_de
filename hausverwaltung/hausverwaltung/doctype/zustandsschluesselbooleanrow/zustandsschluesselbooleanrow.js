frappe.ui.form.on('Wohnungszustand', {
	refresh(frm) {
		if (!frm.doc) return;
		frm.fields_dict['zustand_bool']?.grid?.get_field('zustandsschluessel').get_query = function() {
			return { filters: { art: 'Boolean' } };
		};
	}
});
