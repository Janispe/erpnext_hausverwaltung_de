frappe.ui.form.on("Technische Anlage", {
	setup(frm) {
		frm.set_query("wohnung", () => ({
			filters: frm.doc.immobilie ? { immobilie: frm.doc.immobilie } : {},
		}));
		frm.set_query("anlagenart", () => ({ filters: { deaktiviert: 0 } }));
		frm.set_query("vorgaengeranlage", () => ({
			filters: {
				immobilie: frm.doc.immobilie,
				name: ["!=", frm.doc.name || ""],
			},
		}));
	},

	refresh(frm) {
		frm.toggle_reqd("wohnung", frm.doc.zuordnungstyp === "Wohnung");
		if (!frm.is_new()) {
			frm.add_custom_button(__("Dokument hinzufügen"), () => {
				frappe.new_doc("Anlagendokument", {
					bezugsdoctype: "Technische Anlage",
					bezug: frm.doc.name,
					dokumentart: "Technische Unterlage",
				});
			});
			frm.add_custom_button(__("Wartungspläne aus Vorlagen"), () => {
				frm.call("wartungsplaene_aus_vorlagen_anlegen").then((r) => {
					const anzahl = ((r.message || {}).erstellt || []).length;
					frappe.show_alert({ message: __("{0} Wartungspläne angelegt", [anzahl]), indicator: "green" });
				});
			});
		}
	},

	zuordnungstyp(frm) {
		frm.toggle_reqd("wohnung", frm.doc.zuordnungstyp === "Wohnung");
		if (frm.doc.zuordnungstyp !== "Wohnung" && frm.doc.wohnung) {
			frm.set_value("wohnung", null);
		}
	},

	anlagenart(frm) {
		if (!frm.doc.anlagenart) return;
		frappe.db.get_value("Anlagenart", frm.doc.anlagenart, "standard_zuordnung").then((r) => {
			const standard = (r.message || {}).standard_zuordnung;
			if (standard === "Wohnung") frm.set_value("zuordnungstyp", "Wohnung");
			if (standard === "Immobilie") frm.set_value("zuordnungstyp", "Immobilie");
		});
	},

	immobilie(frm) {
		if (frm.doc.wohnung) {
			frm.set_value("wohnung", null);
		}
	},
});
