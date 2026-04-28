frappe.ui.form.on("Zustandsschluessel", {
	refresh(frm) {
		toggle_reference_fields(frm);
		set_reference_queries(frm);
	},
	art(frm) {
		toggle_reference_fields(frm);
		set_reference_queries(frm);
	},
	referenzquelle(frm) {
		toggle_reference_fields(frm);
	},
});

function toggle_reference_fields(frm) {
	const art = frm.doc.art || "";
	const source = frm.doc.referenzquelle || "Keine";
	const supportsReference = art === "Gleitkommazahl";
	const showStateField = supportsReference && source === "Wohnungszustand-Feld";
	const showKeyField = supportsReference && source === "Zustandsschluessel";

	frm.toggle_display("referenzquelle", supportsReference);
	frm.toggle_display("wohnungszustand_feld", showStateField);
	frm.toggle_display("referenz_zustandsschluessel", showKeyField);

	if (!supportsReference) {
		frm.set_value("referenzquelle", "Keine");
		frm.set_value("wohnungszustand_feld", "");
		frm.set_value("referenz_zustandsschluessel", "");
	}
}

function set_reference_queries(frm) {
	frm.set_query("referenz_zustandsschluessel", () => ({
		filters: {
			art: ["in", ["Gleitkommazahl", "Natürliche Zahl"]],
			name: ["!=", frm.doc.name || ""],
		},
	}));
}
