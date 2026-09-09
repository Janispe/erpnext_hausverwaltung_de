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

async function open_claim_workflow(frm) {
	if (frm.is_dirty()) return frappe.msgprint(__("Bitte zuerst den Versicherungsfall speichern."));
	const active = (role) => (frm.doc.belege || []).filter(r => r.belegart === role && r.belegstatus !== "Storniert");
	const insurance = active("Versicherungsforderung");
	const tenant = active("Mietererstattungsanspruch");
	const hasInsurance = Number(frm.doc.bewilligter_betrag) > 0 || insurance.length > 0;
	const hasTenant = Number(frm.doc.erstattungsbetrag) > 0 || tenant.length > 0;
	if (!hasInsurance && !hasTenant) return frappe.msgprint(__("Bitte zuerst den bewilligten Versicherungsbetrag beziehungsweise den anerkannten Erstattungsbetrag des Mieters erfassen."));
	const expectedModified = frm.doc.modified;
	const fields = [{fieldtype: "HTML", fieldname: "explanation", options: `<p>${__("Vorhandene Entwürfe werden verwendet. Alle erforderlichen Ansprüche werden gemeinsam gebucht. Bei einer Datumskorrektur ersetzt das System die betroffenen unbezahlten Buchungen und erhält ihre Verknüpfung mit diesem Fall.")}</p><p>${__("Wähle das tatsächliche Datum des jeweiligen Anspruchs. Bei bereits erfolgter Zahlung darf es nicht nach dem Zahlungstag liegen.")}</p>`}];
	if (hasInsurance) fields.push({fieldname: "insurance_date", fieldtype: "Date", label: "Buchungsdatum Versicherungsforderung", reqd: 1, default: insurance[0]?.belegdatum || undefined, description: `${frappe.utils.escape_html(frm.doc.versicherungsforderungskonto || "")} an ${frappe.utils.escape_html(frm.doc.versicherungsertragskonto || "")}`});
	if (hasTenant) fields.push({fieldname: "tenant_date", fieldtype: "Date", label: "Buchungsdatum Mieteranspruch", reqd: 1, default: tenant[0]?.belegdatum || undefined, description: `${frappe.utils.escape_html(frm.doc.erstattungskonto || "")} an Mieterdebitor ${frappe.utils.escape_html(frm.doc.kunde || "")}`});
	if ([...insurance, ...tenant].some(r => r.belegstatus === "Eingereicht")) fields.push({fieldname: "correction_reason", fieldtype: "Small Text", label: "Grund der Datumskorrektur", description: "Erforderlich, wenn das Datum eines bereits gebuchten Anspruchs geändert wird."});
	const dialog = new frappe.ui.Dialog({
		title: __("Ansprüche des Versicherungsfalls"), fields,
		primary_action_label: __("Ansprüche buchen / Korrektur ausführen"),
		async primary_action(values) {
			dialog.disable_primary_action();
			try {
				await frappe.call({method: "hausverwaltung.hausverwaltung.utils.insurance_workflow.book_claims", args: {name: frm.doc.name, expected_modified: expectedModified, ...values}, freeze: true, freeze_message: __("Ansprüche werden gemeinsam verarbeitet …")});
				dialog.hide();
				await frm.reload_doc();
				frappe.show_alert({message: __("Ansprüche gebucht und mit dem Versicherungsfall verknüpft."), indicator: "green"});
			} finally {
				dialog.enable_primary_action();
			}
		},
	});
	dialog.show();
}

frappe.ui.form.on("Versicherungsfall", {
	onload: set_insurance_account_defaults,
	company: set_insurance_account_defaults,
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Ansprüche buchen / Datum korrigieren"), () => open_claim_workflow(frm));
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
