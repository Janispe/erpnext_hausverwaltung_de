frappe.ui.form.on('Wohnungszustand', {
	refresh(frm) {
		frm.fields_dict['zustand_int']?.grid?.get_field('zustandsschluessel').get_query = function() {
			return { filters: { art: 'Natürliche Zahl' } };
		};
	}
});
