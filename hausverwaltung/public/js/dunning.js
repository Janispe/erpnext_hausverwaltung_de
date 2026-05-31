frappe.ui.form.on("Dunning", {
	setup(frm) {
		frm.set_query("hv_serienbrief_vorlage", () => ({
			filters: {
				haupt_verteil_objekt: ["in", ["", "Dunning"]],
			},
		}));
	},

	onload(frm) {
		remember_auto_template(frm);
	},

	refresh(frm) {
		apply_hv_dunning_labels(frm);
		remember_auto_template(frm);
		toggle_standard_letter_fields(frm);
		add_template_actions(frm);
	},

	dunning_type(frm) {
		set_template_from_dunning_type(frm);
	},

	hv_serienbrief_vorlage(frm) {
		toggle_standard_letter_fields(frm);
	},
});

function apply_hv_dunning_labels(frm) {
	frm.set_df_property("dunning_type", "label", __("Mahnstufe / Regel"));
	frm.set_df_property(
		"dunning_type",
		"description",
		__(
			"Optionale Regel für Mahngebühr, Verzugszins, Variablenwerte und Default-Vorlage."
		)
	);
	frm.set_df_property("hv_serienbrief_vorlage", "label", __("Serienbrief Vorlage"));
	frm.set_df_property(
		"hv_serienbrief_vorlage",
		"description",
		__(
			"Briefvorlage, die beim Drucken dieser Mahnung gerendert wird. Diese Auswahl überschreibt den Default der Mahnstufe."
		)
	);
	frm.set_df_property("hv_serienbrief_werte", "label", __("Serienbrief-Werte für diese Mahnung"));
	frm.set_df_property(
		"hv_serienbrief_werte",
		"description",
		__(
			"Optionale Variablenwerte nur für diese konkrete Mahnung. Gleichnamige Werte überschreiben die Defaults aus der Mahnstufe."
		)
	);
}

function toggle_standard_letter_fields(frm) {
	const use_serienbrief = Boolean(frm.doc.hv_serienbrief_vorlage);
	frm.toggle_display(["body_text", "closing_text"], !use_serienbrief);
}

function add_template_actions(frm) {
	if (!frm.doc.hv_serienbrief_vorlage) return;

	frm.add_custom_button(__("Serienbrief Vorlage öffnen"), () => {
		frappe.set_route("Form", "Serienbrief Vorlage", frm.doc.hv_serienbrief_vorlage);
	});
}

function remember_auto_template(frm) {
	if (!frm.doc.dunning_type || !frm.doc.hv_serienbrief_vorlage) {
		frm.__hv_last_auto_template = null;
		return;
	}

	frappe.db
		.get_value("Dunning Type", frm.doc.dunning_type, "hv_serienbrief_vorlage")
		.then((r) => {
			const template = r?.message?.hv_serienbrief_vorlage || "";
			frm.__hv_last_auto_template =
				template && template === frm.doc.hv_serienbrief_vorlage ? template : null;
		});
}

function set_template_from_dunning_type(frm) {
	if (!frm.doc.dunning_type) return;

	const current = frm.doc.hv_serienbrief_vorlage || "";
	const may_replace = !current || current === frm.__hv_last_auto_template;
	if (!may_replace) return;

	frappe.db
		.get_value("Dunning Type", frm.doc.dunning_type, "hv_serienbrief_vorlage")
		.then((r) => {
			const template = r?.message?.hv_serienbrief_vorlage || "";
			if (!template) return;

			frm.__hv_last_auto_template = template;
			frm.set_value("hv_serienbrief_vorlage", template);
		});
}
