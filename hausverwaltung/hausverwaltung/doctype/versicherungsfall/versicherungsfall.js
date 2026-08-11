const VERSICHERUNGSFALL_BELEG_DOCTYPES = {
	Reparaturrechnung: ["Purchase Invoice"],
	Versicherungsforderung: ["Journal Entry"],
	Versicherungseingang: ["Journal Entry", "Bank Transaction"],
	Mietergutschrift: ["Sales Invoice"],
	Mieterauszahlung: ["Payment Entry", "Bank Transaction"],
	"Sonstiger Buchungsbeleg": [
		"Journal Entry",
		"Sales Invoice",
		"Purchase Invoice",
		"Payment Entry",
		"Bank Transaction",
	],
};

function reset_beleg_details(cdt, cdn) {
	frappe.model.set_value(cdt, cdn, "belegdatum", null);
	frappe.model.set_value(cdt, cdn, "betrag", 0);
	frappe.model.set_value(cdt, cdn, "belegstatus", null);
}

frappe.ui.form.on("Versicherungsfall", {
	setup(frm) {
		frm.set_query("wohnung", () => ({
			filters: frm.doc.immobilie ? { immobilie: frm.doc.immobilie } : {},
		}));

		const grid = frm.fields_dict.belege?.grid;
		if (grid) {
			grid.get_field("referenz_doctype").get_query = (_doc, cdt, cdn) => {
				const row = locals[cdt][cdn];
				const allowed = VERSICHERUNGSFALL_BELEG_DOCTYPES[row.belegart] || [];
				return { filters: { name: ["in", allowed] } };
			};
		}
	},

	async mietvertrag(frm) {
		if (!frm.doc.mietvertrag) {
			await frm.set_value("kunde", null);
			return;
		}
		const result = await frappe.db.get_value("Mietvertrag", frm.doc.mietvertrag, [
			"kunde",
			"wohnung",
			"immobilie",
		]);
		const values = result?.message || {};
		await frm.set_value({
			kunde: values.kunde || null,
			wohnung: values.wohnung || null,
			immobilie: values.immobilie || null,
		});
	},

	async wohnung(frm) {
		if (frm.doc.mietvertrag || !frm.doc.wohnung) return;
		const result = await frappe.db.get_value("Wohnung", frm.doc.wohnung, "immobilie");
		await frm.set_value("immobilie", result?.message?.immobilie || null);
	},
});

frappe.ui.form.on("Versicherungsfall Beleg", {
	belegart(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		const allowed = VERSICHERUNGSFALL_BELEG_DOCTYPES[row.belegart] || [];
		if (allowed.length === 1) {
			frappe.model.set_value(cdt, cdn, "referenz_doctype", allowed[0]);
		} else if (!allowed.includes(row.referenz_doctype)) {
			frappe.model.set_value(cdt, cdn, "referenz_doctype", null);
		}
		if (row.referenz) frappe.model.set_value(cdt, cdn, "referenz", null);
		reset_beleg_details(cdt, cdn);
	},

	referenz_doctype(_frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.referenz) frappe.model.set_value(cdt, cdn, "referenz", null);
		reset_beleg_details(cdt, cdn);
	},

	referenz(_frm, cdt, cdn) {
		reset_beleg_details(cdt, cdn);
	},
});
