frappe.ui.form.on('Wohnungszustand', {
	refresh(frm) {
		const zustandsschluessel = frm.fields_dict['zustand_float']?.grid?.get_field('zustandsschluessel');
		if (!zustandsschluessel) return;
		zustandsschluessel.get_query = function() {
			return { filters: { art: 'Gleitkommazahl' } };
		};
	}
});
