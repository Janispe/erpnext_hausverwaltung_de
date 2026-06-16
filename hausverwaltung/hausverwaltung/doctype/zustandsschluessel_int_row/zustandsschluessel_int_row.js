frappe.ui.form.on('ZustandsschluesselIntRow', {
	form_render: function(frm) {
		set_filters(frm);
	}
});

function set_filters(frm) {
	['zustand_int'].forEach(childfield => {
		const zustandsschluessel = frm.fields_dict[childfield]?.grid?.get_field('zustandsschluessel');
		if (!zustandsschluessel) return;
		zustandsschluessel.get_query = function() {
			return { filters: { art: 'Natürliche Zahl' } };
		};
	});
}
