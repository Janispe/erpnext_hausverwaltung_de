(() => {
	const api = "hausverwaltung.hausverwaltung.doctype.heizkostenmeldung.heizkostenmeldung.";
	const definitions = frm => JSON.parse(frm.doc.vorlage_snapshot || "{}").felder || [];
	const values = row => JSON.parse(row.zusatzwerte_json || "{}");
	const df = d => ({
		fieldname: d.schluessel, label: d.bezeichnung + (d.einheit ? ` (${d.einheit})` : ""),
		fieldtype: d.feldtyp, options: d.feldtyp === "Select" ? "\n" + d.optionen : undefined,
		description: [d.hinweis, d.pflichtfeld ? __("Pflicht bei Freigabe") : ""].filter(Boolean).join(" · "),
	});
	async function saved(frm) {
		if (frm.is_new() || frm.is_dirty()) await frm.save();
		if (frm.is_new() || frm.is_dirty()) frappe.throw(__("Die Meldung konnte nicht gespeichert werden. Bitte die angezeigten Fehler korrigieren."));
	}
	async function action(frm, method) {
		await saved(frm);
		const r = await frappe.call({ method: api + method, args: { name: frm.doc.name }, freeze: true });
		if (method === "folgejahr") frappe.set_route("Form", "Heizkostenmeldung", r.message);
		else await frm.reload_doc();
	}
	function showIssues(frm, issues) {
		const $area = frm.fields_dict.pruefung_html.$wrapper.empty();
		if (!issues.length) $("<p>").text(__("Die gespeicherten Pflichtangaben sind vollständig. Bei Freigabe werden die ERP-Daten erneut verglichen.")).appendTo($area);
		else {
			$("<p>").text(__("Vor Freigabe zu erledigen: {0}", [issues.length])).appendTo($area);
			const list = $("<ul>").appendTo($area);
			issues.forEach(issue => $("<li>").text(issue).appendTo(list));
		}
	}
	function renderExtras(frm) {
		const $area = frm.fields_dict.zusatzfelder_html.$wrapper.empty();
		if (!frm.doc.vorlage_snapshot) {
			$("<p>").text(__("Vorlagenversion auswählen und speichern, um Zusatzfelder anzuzeigen.")).appendTo($area);
			return;
		}
		const current = values(frm.doc);
		let section;
		definitions(frm).filter(d => d.bereich === "Meldung").forEach(d => {
			if (d.abschnitt && d.abschnitt !== section) {
				$("<h5>").text(d.abschnitt).appendTo($area);
				section = d.abschnitt;
			}
			let loading = true, control;
			control = frappe.ui.form.make_control({
				parent: $("<div>").css("max-width", "650px").appendTo($area), render_input: true,
				df: { ...df(d), read_only: frm.doc.docstatus !== 0, change() {
					if (loading || !control || frm.doc.docstatus !== 0) return;
					const next = values(frm.doc);
					next[d.schluessel] = control.get_value() ?? null;
					frm.set_value("zusatzwerte_json", JSON.stringify(next));
				}},
			});
			Promise.resolve(control.set_value(current[d.schluessel] ?? null)).then(() => { loading = false; });
		});
	}
	function editRow(frm, cdt, cdn, scope) {
		const row = locals[cdt][cdn], fields = definitions(frm).filter(d => d.bereich === scope);
		if (!fields.length) return frappe.msgprint(__("Diese Vorlagenversion definiert hier keine Zusatzfelder."));
		const dialog = new frappe.ui.Dialog({
			title: __("Zusatzfelder: {0}", [row.mietername || row.bezeichnung || scope]),
			fields: fields.map(d => ({ ...df(d), read_only: frm.doc.docstatus !== 0 })),
			primary_action_label: __("Übernehmen"),
			primary_action(result) {
				if (frm.doc.docstatus === 0) frappe.model.set_value(cdt, cdn, "zusatzwerte_json", JSON.stringify(result));
				dialog.hide();
			},
		});
		dialog.set_values(values(row));
		dialog.show();
	}
	frappe.ui.form.on("Heizkostenmeldung", {
		setup(frm) {
			frm.set_query("vorlage", () => ({ filters: { docstatus: 1 } }));
			frm.set_query("abrechnung", () => ({ filters: {
				immobilie: frm.doc.immobilie, von: frm.doc.von, bis: frm.doc.bis, docstatus: ["<", 2],
			}}));
			frm.fields_dict.nutzer.grid.cannot_add_rows = true;
			frm.fields_dict.nutzer.grid.cannot_delete_rows = true;
		},
		refresh(frm) {
			renderExtras(frm);
			frm.set_df_property("vorlage", "read_only", !frm.is_new());
			for (const field of ["immobilie", "von", "bis"]) frm.set_df_property(field, "read_only", !!frm.doc.nutzer?.length);
			if (frm.doc.docstatus === 0) frm.add_custom_button(__("ERP-Daten laden"), () => action(frm, "daten_laden"));
			if (frm.is_new()) return;
			frm.add_custom_button(__("Excel herunterladen"), async () => {
				await saved(frm);
				window.open(`/api/method/${api}export_xlsx?name=${encodeURIComponent(frm.doc.name)}`, "_blank", "noopener");
			});
			frm.add_custom_button(__("Angaben prüfen"), async () => {
				await saved(frm);
				const r = await frappe.call({ method: api + "pruefen", args: { name: frm.doc.name } });
				showIssues(frm, r.message.hinweise);
				frm.scroll_to_field("pruefung_html", false);
			});
			if (frm.doc.docstatus !== 2) frm.add_custom_button(__("Folgejahr anlegen"), async () => {
				await saved(frm);
				frappe.prompt([{ fieldname: "vorlage", label: __("Vorlagenversion für das Folgejahr"), fieldtype: "Link",
					options: "Heizkostenmeldung Vorlage", reqd: 1, default: frm.doc.vorlage,
					get_query: () => ({ filters: { docstatus: 1 } }),
				}], async result => {
					const r = await frappe.call({ method: api + "folgejahr", args: { name: frm.doc.name, vorlage: result.vorlage }, freeze: true });
					frappe.set_route("Form", "Heizkostenmeldung", r.message);
				}, __("Folgejahr anlegen"), __("Anlegen"));
			}, __("Aktionen"));
			if (frm.doc.docstatus === 0 && !frm.is_dirty()) frm.page.set_primary_action(__("Freigeben"), () => frm.savesubmit());
			if (frm.doc.docstatus === 1 && !frm.doc.versandt_am) frm.add_custom_button(__("Versand vermerken"), () => action(frm, "versand_vermerken"), __("Aktionen"));
			if (frm.doc.docstatus === 1) frm.dashboard.set_headline_alert(__("Freigegeben. Der archivierte Excel-Stand bleibt unverändert. 'Versand vermerken' dokumentiert nur den Versand und versendet keine Nachricht."));
		},
	});
	for (const [doctype, scope] of [["Heizkostenmeldung Nutzer", "Nutzer"], ["Heizkostenmeldung Kosten", "Kosten"], ["Heizkostenmeldung Brennstoff", "Brennstoff"]]) {
		frappe.ui.form.on(doctype, { zusatzangaben: (frm, cdt, cdn) => editRow(frm, cdt, cdn, scope) });
	}
})();
