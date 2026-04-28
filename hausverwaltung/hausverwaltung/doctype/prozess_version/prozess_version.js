frappe.ui.form.on("Prozess Version", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		frm.add_custom_button(__("Version duplizieren"), () => {
			frappe.prompt(
				[
					{ fieldname: "new_version_key", fieldtype: "Data", label: __("Version Key"), reqd: 1 },
					{ fieldname: "new_titel", fieldtype: "Data", label: __("Titel"), reqd: 1 },
				],
				(values) => {
					frappe.call({
						method: "hausverwaltung.hausverwaltung.doctype.prozess_version.prozess_version.duplicate_version",
						args: {
							name: frm.doc.name,
							new_version_key: values.new_version_key,
							new_titel: values.new_titel,
						},
					}).then((r) => {
						if (r.message) {
							frappe.set_route("Form", "Prozess Version", r.message);
						}
					});
				},
				__("Version duplizieren"),
				__("Duplizieren")
			);
		});

		frm.add_custom_button(__("Aktivieren"), () => {
			frappe.call({
				method: "hausverwaltung.hausverwaltung.doctype.prozess_version.prozess_version.activate_version",
				args: { name: frm.doc.name },
				freeze: true,
			}).then(() => frm.reload_doc());
		});
	},
});
