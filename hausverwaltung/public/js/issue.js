frappe.ui.form.on('Issue', {
	setup(frm) {
		frm.set_query('hv_wohnung', () => ({
			filters: frm.doc.hv_immobilie ? { immobilie: frm.doc.hv_immobilie } : {},
		}));
		frm.set_query('hv_mietvertrag', () => ({
			filters: { wohnung: frm.doc.hv_wohnung || '', docstatus: ['!=', 2] },
		}));
		frm.set_query('hv_zustaendig', () => ({
			filters: { enabled: 1, user_type: 'System User' },
		}));
	},
	refresh(frm) {
		hv_damage_fields(frm);
		if (!frm.is_new() && frm.doc.hv_wohnungsschaden) {
			frm.timeline.wrapper.find('.btn-split-issue').hide();
		}
	},
	timeline_refresh(frm) {
		if (frm.doc.hv_wohnungsschaden) {
			frm.timeline.wrapper.find('.btn-split-issue').hide();
		}
	},
	hv_wohnungsschaden: hv_damage_fields,
});

function hv_damage_fields(frm) {
	const damage = Boolean(frm.doc.hv_wohnungsschaden);
	const staff = frappe.session.user === 'Administrator'
		|| frappe.user.has_role(['Hausverwalter', 'System Manager']);
	frm.set_df_property('hv_wohnungsschaden', 'hidden', !staff);
	frm.set_df_property('hv_wohnungsschaden', 'read_only', damage && !frm.is_new());
	frm.set_df_property('hv_eingang', 'read_only', Boolean(frm.doc.hv_eingangsmail));
	frm.set_df_property('customer', 'read_only', damage);
}
