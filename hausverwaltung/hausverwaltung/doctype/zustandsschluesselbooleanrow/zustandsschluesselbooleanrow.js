frappe.ui.form.on('Wohnungszustand', {
	refresh(frm) {
		if (!frm.doc) return;
		const zustandsschluessel = frm.fields_dict['zustand_bool']?.grid?.get_field('zustandsschluessel');
		if (!zustandsschluessel) return;
		zustandsschluessel.get_query = function() {
			return { filters: { art: 'Boolean' } };
		};
	}
});
