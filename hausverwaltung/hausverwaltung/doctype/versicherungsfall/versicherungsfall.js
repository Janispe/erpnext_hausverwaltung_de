const VERSICHERUNGSFALL_BELEG_DOCTYPES = {
	Reparaturrechnung: ["Purchase Invoice"],
	Versicherungsforderung: ["Journal Entry"],
	Versicherungseingang: ["Journal Entry", "Bank Transaction"],
	Mietererstattungsanspruch: ["Journal Entry"],
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

async function set_insurance_account_defaults(frm) {
	if (!frm.doc.company) return;
	for (const [field, name, root] of [["versicherungsforderungskonto", "Forderungen gegen Versicherungen", "Asset"], ["versicherungsertragskonto", "Versicherungserstattungen", "Income"]]) {
		if (frm.doc[field]) continue;
		const result = await frappe.db.get_value("Account", {company: frm.doc.company, account_name: name, root_type: root, is_group: 0, disabled: 0}, "name");
		if (result?.message?.name) await frm.set_value(field, result.message.name);
	}
}

frappe.ui.form.on("Versicherungsfall", {
	onload: set_insurance_account_defaults,
	company: set_insurance_account_defaults,
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Versicherungsforderung vorbereiten"), () => {
			if (frm.is_dirty()) return frappe.msgprint(__("Bitte zuerst den Versicherungsfall speichern."));
			frappe.prompt([{fieldname: "posting_date", fieldtype: "Date", label: "Buchungsdatum der Forderung", reqd: 1, default: frappe.datetime.get_today()}], async (values) => {
				const result = await frappe.call({method: "hausverwaltung.hausverwaltung.utils.insurance_receivables.create_insurance_claim", args: {name: frm.doc.name, ...values}, freeze: true});
				await frm.reload_doc();
				frappe.set_route("Form", "Journal Entry", result.message.name);
			}, __("Versicherungsforderung als Entwurf"), __("Entwurf erstellen"));
		});
		frm.add_custom_button(__("Mieteranspruch vorbereiten"), () => {
			if (frm.is_dirty()) return frappe.msgprint(__("Bitte zuerst den Versicherungsfall speichern."));
			frappe.prompt([{fieldname: "posting_date", fieldtype: "Date", label: "Buchungsdatum des Anspruchs", reqd: 1, default: frappe.datetime.get_today()}], async (values) => {
				const result = await frappe.call({method: "hausverwaltung.hausverwaltung.doctype.versicherungsfall.versicherungsfall.create_tenant_claim", args: {name: frm.doc.name, ...values}, freeze: true});
				await frm.reload_doc();
				frappe.set_route("Form", "Journal Entry", result.message.name);
			}, __("Erstattungsbuchung als Entwurf"), __("Entwurf erstellen"));
		});
		if (frm.doc.kunde) frm.add_custom_button(__("Mieterkonto"), () => frappe.set_route("mieterkonto-workflow", {customer: frm.doc.kunde}));
		frm.add_custom_button(__("Bankimport / Zahlungen zuordnen"), () => frappe.set_route("bankimport_v2"));
	},
	setup(frm) {
		for (const [field, root] of [["versicherungsforderungskonto", "Asset"], ["versicherungsertragskonto", "Income"]]) {
			frm.set_query(field, () => ({filters: {company: frm.doc.company, root_type: root, is_group: 0, disabled: 0, account_type: ["not in", ["Receivable", "Payable", "Bank", "Cash"]]}}));
		}
		frm.set_query("erstattungskonto", () => ({filters: {company: frm.doc.company, is_group: 0, disabled: 0, root_type: ["in", frm.doc.erstattungsart === "Auslagenersatz Gebäudereparatur" ? ["Expense"] : ["Asset", "Liability"]], account_type: ["not in", ["Bank", "Cash", "Receivable", "Payable"]]}}));
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
