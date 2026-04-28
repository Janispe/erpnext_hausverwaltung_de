frappe.ui.form.on('Wohnungszustand', {
	refresh(frm) {
		frm.fields_dict['zustand_float']?.grid?.get_field('zustandsschluessel').get_query = function() {
			return { filters: { art: 'Gleitkommazahl' } };
		};
	}
});
