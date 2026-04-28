frappe.ui.form.on('ZustandsschluesselFloatRow', {
	form_render: function(frm) {
		set_filters(frm);
	}
});

function set_filters(frm) {
	['zustand_float'].forEach(childfield => {
		frm.fields_dict[childfield]?.grid?.get_field('zustandsschluessel').get_query = function() {
			return { filters: { art: 'Gleitkommazahl' } };
		};
	});
}
