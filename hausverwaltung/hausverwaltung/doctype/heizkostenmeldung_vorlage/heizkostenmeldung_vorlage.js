frappe.ui.form.on("Heizkostenmeldung Vorlage", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Neue Version"), async () => {
				if (frm.is_dirty()) await frm.save();
				const r = await frappe.call({
					method: "hausverwaltung.hausverwaltung.doctype.heizkostenmeldung_vorlage.heizkostenmeldung_vorlage.neue_version",
					args: { name: frm.doc.name }, freeze: true,
				});
				frappe.set_route("Form", "Heizkostenmeldung Vorlage", r.message);
			});
		}
		if (frm.doc.docstatus === 1) {
			frm.dashboard.set_headline_alert(__("Freigegeben: Änderungen erfolgen über eine neue Version."));
		}
		if (!frm.is_new() && !frm.is_dirty() && frm.doc.docstatus === 0) {
			frm.page.set_primary_action(__("Vorlage freigeben"), () => frm.savesubmit());
		}
	},
});
