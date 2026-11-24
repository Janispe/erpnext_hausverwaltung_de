frappe.ui.form.on("Prozess Instanz", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.prozess_typ !== "mieterwechsel") return;
		if (!frappe.model.can_read("Wohnungsabnahme")) return;
		frappe.call({
			method: "hausverwaltung.hausverwaltung.doctype.wohnungsabnahme.process.process_contracts",
			args: { prozess: frm.doc.name },
		}).then(({ message }) => {
			for (const [richtung, mietvertrag] of Object.entries(message || {})) {
				frm.add_custom_button(__(richtung), () => {
					const query = new URLSearchParams({ mietvertrag, richtung, prozess: frm.doc.name });
					window.location.assign("/wohnungsabnahme?" + query);
				}, __("Wohnungsabnahme"));
			}
		});
	},
});
