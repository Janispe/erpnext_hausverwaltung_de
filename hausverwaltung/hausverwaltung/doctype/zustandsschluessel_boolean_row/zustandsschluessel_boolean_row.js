frappe.ui.form.on('Wohnungszustand', {
	refresh(frm) {
		if (!frm.doc) return;
		['zustand_bool','zustand_float','zustand_int'].forEach(childfield => frm.fields_dict[childfield]?.grid?.refresh());
	}
});

frappe.ui.form.on('ZustandsschluesselBooleanRow', {
	form_render: function(frm) {
		set_filters(frm);
	}
});

function set_filters(frm) {
	['zustand_bool'].forEach(childfield => {
		frm.fields_dict[childfield]?.grid?.get_field('zustandsschluessel').get_query = function() {
			return { filters: { art: 'Boolean' } };
		};
	});
}
