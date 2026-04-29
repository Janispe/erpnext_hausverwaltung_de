const toggle_summary_fields = (frm) => {
	const showSummary = !frm.is_new();
	[
		"section_break_mieter",
		"mieter_abrechnungen",
		"section_break_summary",
		"kosten_pro_art",
		"gesamtkosten",
		"gesamt_vorauszahlungen",
		"gesamt_differenz",
		"zaehler_summen",
		"tab_break_verteilungsdetails",
		"section_break_verteilungsdetails",
		"verteilungsbasis",
	].forEach((field) => frm.toggle_display(field, showSummary));
};

const toggle_header_fields = (frm) => {
	const readOnly = !frm.is_new();
	[
		"immobilie",
		"von",
		"bis",
		"nachzahlung_faellig_am",
		"stichtag",
	].forEach((field) => frm.set_df_property(field, "read_only", readOnly ? 1 : 0));
};

const set_default_due_date = (frm) => {
	if (!frm || !frm.is_new()) {
		return;
	}
	if (frm.doc.nachzahlung_faellig_am) {
		return;
	}
	if (!frm.doc.bis) {
		return;
	}
	const due_date = frappe.datetime.add_days(frappe.datetime.get_today(), 21);
	if (due_date) {
		frm.set_value("nachzahlung_faellig_am", due_date);
	}
};

const fmt_money = (value) => format_currency(value || 0, "EUR", 2);

const escape_html = (value) => frappe.utils.escape_html(value == null ? "" : String(value));

const fmt_qm = (value) => {
	const num = parseFloat(value || 0) || 0;
	return `${format_number(num, null, 2)} qm`;
};

const normalize_verteilungsbasis = (data) => {
	if (Array.isArray(data)) {
		return { qm_rows: data, festbetrag_rows: [] };
	}
	if (!data || typeof data !== "object") {
		return { qm_rows: [], festbetrag_rows: [] };
	}
	return {
		qm_rows: Array.isArray(data.qm_rows) ? data.qm_rows : [],
		festbetrag_rows: Array.isArray(data.festbetrag_rows) ? data.festbetrag_rows : [],
	};
};

const set_html_field_content = (frm, fieldname, html) => {
	frm.set_df_property(fieldname, "options", html);
	const field = frm.get_field(fieldname);
	if (field && field.$wrapper) {
		field.$wrapper.html(html);
	}
	frm.refresh_field(fieldname);
};

const render_verteilungsbasis = (frm, data = {}) => {
	if (!frm.get_field("verteilungsbasis")) {
		return;
	}
	const normalized = normalize_verteilungsbasis(data);
	const qmRows = normalized.qm_rows;
	const festbetragRows = normalized.festbetrag_rows;
	if (!qmRows.length && !festbetragRows.length) {
		set_html_field_content(
			frm,
			"verteilungsbasis",
			`<p class="text-muted">${__("Noch keine Verteilungsdaten vorhanden.")}</p>`
		);
		return;
	}
	const sections = [];
	if (qmRows.length) {
		const total_qm = qmRows.reduce((acc, row) => acc + (parseFloat(row.qm || 0) || 0), 0);
		sections.push(`
			<div style="margin-bottom: 18px;">
				<div style="font-weight: 600; margin-bottom: 8px;">${__("Wohnflächen")}</div>
				<table class="table table-bordered table-hover" style="font-size: 12px; margin-bottom: 0;">
					<thead>
						<tr>
							<th>${__("Wohnung")}</th>
							<th style="text-align:right;">${__("qm")}</th>
						</tr>
					</thead>
					<tbody>
						${qmRows
							.map(
								(row) => `
									<tr>
										<td>${escape_html(row.wohnung || "")}</td>
										<td style="text-align:right;">${fmt_qm(row.qm)}</td>
									</tr>
								`
							)
							.join("")}
						<tr>
							<td style="text-align:right;"><strong>${__("Summe")}</strong></td>
							<td style="text-align:right;"><strong>${fmt_qm(total_qm)}</strong></td>
						</tr>
					</tbody>
				</table>
			</div>
		`);
	}

	if (festbetragRows.length) {
		const wohnungen = qmRows.map((row) => row.wohnung).filter(Boolean);
		const grouped = {};
		festbetragRows.forEach((row) => {
			const key = row.kostenart || __("Unbekannt");
			if (!grouped[key]) {
				grouped[key] = [];
			}
			grouped[key].push(row);
		});
		const festbetragHtml = Object.keys(grouped)
			.sort((a, b) => a.localeCompare(b))
			.map((kostenart) => {
				const rowsByWohnung = new Map();
				grouped[kostenart].forEach((row) => {
					rowsByWohnung.set(row.wohnung, row);
				});
				const rows = wohnungen.length
					? wohnungen.map((wohnung) => {
							const existing = rowsByWohnung.get(wohnung);
							return existing || { wohnung, betrag: 0 };
						})
					: grouped[kostenart];
				const total = rows.reduce((acc, row) => acc + (parseFloat(row.betrag || 0) || 0), 0);
				return `
					<div style="margin-bottom: 18px;">
						<div style="font-weight: 600; margin-bottom: 8px;">${escape_html(kostenart)}</div>
						<table class="table table-bordered table-hover" style="font-size: 12px; margin-bottom: 0;">
							<thead>
								<tr>
									<th>${__("Wohnung")}</th>
									<th style="text-align:right;">${__("Betrag")}</th>
								</tr>
							</thead>
							<tbody>
								${rows
									.map(
										(row) => `
											<tr>
												<td>${escape_html(row.wohnung || "")}</td>
												<td style="text-align:right;">${fmt_money(row.betrag)}</td>
											</tr>
										`
									)
									.join("")}
								<tr>
									<td style="text-align:right;"><strong>${__("Summe")}</strong></td>
									<td style="text-align:right;"><strong>${fmt_money(total)}</strong></td>
								</tr>
							</tbody>
						</table>
					</div>
				`;
			})
			.join("");
		sections.push(`
			<div>
				<div style="font-weight: 600; margin-bottom: 8px;">${__("Festbeträge je Wohnung")}</div>
				${festbetragHtml}
			</div>
		`);
	}

	const html = `
		<div>
			${sections.join("")}
		</div>
	`;
	set_html_field_content(frm, "verteilungsbasis", html);
};

const load_verteilungsbasis = (frm) => {
	if (!frm.get_field("verteilungsbasis")) {
		return Promise.resolve();
	}
	if (frm.is_new()) {
		render_verteilungsbasis(frm, []);
		return Promise.resolve();
	}
	return frappe
		.call({
			method: "hausverwaltung.hausverwaltung.doctype.betriebskostenabrechnung_immobilie.betriebskostenabrechnung_immobilie.get_verteilungsbasis",
			args: { name: frm.doc.name },
		})
		.then((r) => {
			render_verteilungsbasis(frm, (r && r.message) || {});
		})
		.catch((err) => {
			console.error("Verteilungsbasis laden fehlgeschlagen", err);
			render_verteilungsbasis(frm, {});
		});
};

const DISPATCH_BUTTON_LABEL = __("Abrechnungen versenden");

const ensure_dispatch_button = (frm) => {
	if (!frm || frm.is_new() || frm.doc.docstatus !== 1) {
		return;
	}
	try {
		if (frm.remove_custom_button) {
			frm.remove_custom_button(DISPATCH_BUTTON_LABEL);
		}
	} catch {
		// ignore
	}
	frm.add_custom_button(DISPATCH_BUTTON_LABEL, () => open_dispatch_dialog(frm));
};

const load_mieter_abrechnungen = (frm, attempt = 1) => {
	const control = frm.fields_dict.mieter_abrechnungen;
	if (!control) {
		return;
	}
	// Status vor Änderungen merken, damit wir echte Nutzer-Änderungen nicht überschreiben.
	const was_dirty = frm.is_dirty();
	frm.set_df_property("mieter_abrechnungen", "cannot_add_rows", true);
	frm.set_df_property("mieter_abrechnungen", "cannot_delete_rows", true);
	frm.set_df_property("mieter_abrechnungen", "read_only", true);
	if (frm.is_new()) {
		frm.clear_table("mieter_abrechnungen");
		frm.refresh_field("mieter_abrechnungen");
		render_verteilungsbasis(frm, []);
		return;
	}
	frappe.call({
		method: "hausverwaltung.hausverwaltung.doctype.betriebskostenabrechnung_immobilie.betriebskostenabrechnung_immobilie.get_mieter_abrechnungen",
		args: { name: frm.doc.name },
	}).then((r) => {
		const rows = (r && r.message) || [];
		let sum_voraus = 0;
		let sum_anteil = 0;
		let sum_diff = 0;
		frm.clear_table("mieter_abrechnungen");
		rows.forEach((row) => {
			const child = frm.add_child("mieter_abrechnungen");
			child.mieter_abrechnung = row.name;
			child.wohnung = row.wohnung;
			child.status = row.status_label || row.status || "";
			child.vorauszahlung = row.vorauszahlung;
			child.anteil = row.anteil;
			child.guthaben_nachzahlung = row.guthaben_nachzahlung;
			sum_voraus += parseFloat(row.vorauszahlung || 0) || 0;
			sum_anteil += parseFloat(row.anteil || 0) || 0;
			sum_diff += parseFloat(row.guthaben_nachzahlung || 0) || 0;
		});
		if (rows.length) {
			const sum_row = frm.add_child("mieter_abrechnungen");
			sum_row.status = __("Summe");
			sum_row.vorauszahlung = sum_voraus;
			sum_row.anteil = sum_anteil;
			sum_row.guthaben_nachzahlung = sum_diff;

			let total_kosten = parseFloat(frm.doc.gesamtkosten || 0) || 0;
			if (!total_kosten && Array.isArray(frm.doc.kosten_pro_art)) {
				total_kosten = frm.doc.kosten_pro_art.reduce((acc, r) => {
					return acc + (parseFloat(r.betrag || 0) || 0);
				}, 0);
			}
			let vermieter_anteil = Math.round((total_kosten - sum_anteil) * 100) / 100;
			if (vermieter_anteil > -0.01 && vermieter_anteil < 0.01) {
				vermieter_anteil = 0;
			}
			const owner_row = frm.add_child("mieter_abrechnungen");
			owner_row.status = __("Vermieter (Leerstand)");
			owner_row.anteil = vermieter_anteil;
		}
		frm.refresh_field("mieter_abrechnungen");
		load_verteilungsbasis(frm);
		// Das Befüllen eines virtuellen Child-Tables markiert das Formular sonst als "unsaved".
		if (frm.doc && frm.toolbar) {
			frm.doc.__unsaved = was_dirty ? 1 : 0;
			frm.toolbar.refresh();
			// toolbar.refresh kann Custom Buttons entfernen → danach wieder setzen (auch nach DOM-Update).
			ensure_dispatch_button(frm);
			setTimeout(() => ensure_dispatch_button(frm), 0);
		}
	}).catch((err) => {
		// Erster Versuch schlug fehl? Einmal nach kurzer Pause erneut probieren, bevor wir einen Fehler zeigen.
		if (attempt < 2) {
			setTimeout(() => load_mieter_abrechnungen(frm, attempt + 1), 400);
			return;
		}
		console.error("Mieterabrechnungen laden fehlgeschlagen", err);
		let detail = "";
		try {
			const rawServer = err?._server_messages || err?.__server_messages;
			if (rawServer) {
				const msgs = JSON.parse(rawServer);
				const cleaned = (Array.isArray(msgs) ? msgs : [msgs])
					.map((m) => {
						try {
							const parsed = JSON.parse(m);
							return parsed?.message || m;
						} catch {
							return m;
						}
					})
					.join("\n");
				detail = cleaned || detail;
			}
			if (!detail && err?.message) {
				detail = err.message;
			}
			if (!detail && err?.exc) {
				detail = err.exc;
			}
			if (!detail && typeof err === "string") {
				detail = err;
			}
		} catch {
			// ignore
		}
		frappe.msgprint({
			title: __("Fehler"),
			message:
				__("Mieterabrechnungen konnten nicht geladen werden.") +
				(detail
					? "<br><small>" + frappe.utils.escape_html(detail) + "</small>"
					: "<br><small>Details siehe Browser-Konsole.</small>"),
			indicator: "red",
		});
	});
};

frappe.ui.form.on("Betriebskostenabrechnung Immobilie", {
	refresh(frm) {
		// Erstellung erfolgt automatisch bei Anlage; Submit triggert Abschluss
		toggle_header_fields(frm);
		toggle_summary_fields(frm);
		set_default_due_date(frm);
		load_verteilungsbasis(frm);
		load_mieter_abrechnungen(frm);
		ensure_dispatch_button(frm);
		// Frappe kann nach refresh noch Toolbar/Header neu rendern (Buttons verschwinden sonst).
		setTimeout(() => ensure_dispatch_button(frm), 0);

		if (frm.is_new()) {
			frappe.require("/assets/hausverwaltung/js/date_range_presets.js", () => {
				const presets = window.hausverwaltung && window.hausverwaltung.date_presets;
				if (presets) {
					presets.attach_to_form(frm, {
						from_field: "von",
						to_field: "bis",
						include_gesamt: false,
					});
				}
			});
		}
	},
	bis(frm) {
		set_default_due_date(frm);
	},
});

const open_dispatch_dialog = (frm) => {
	const default_subject = __("Betriebskostenabrechnung {0} bis {1} – {2}", [
		frm.doc.von || "?",
		frm.doc.bis || "?",
		frm.doc.immobilie || "",
	]);
	const default_message = __("Guten Tag,\n\nanbei erhalten Sie Ihre Betriebskostenabrechnung als PDF.\n\nMit freundlichen Grüßen");

	const dialog = new frappe.ui.Dialog({
		title: __("Betriebskostenabrechnungen versenden"),
		fields: [
			{
				fieldname: "mode",
				fieldtype: "Select",
				label: __("Aktion"),
				options: [
					{ label: __("Versenden nach Versandweg (E-Mail/Post)"), value: "auto" },
					{ label: __("Alle drucken"), value: "print_all" },
				],
				default: "auto",
				reqd: 1,
			},
			{
				fieldname: "also_print_emailed",
				fieldtype: "Check",
				label: __("E-Mails auch drucken"),
				default: 0,
				depends_on: "eval:doc.mode==='auto'",
			},
			{
				fieldname: "serienbrief_vorlage",
				fieldtype: "Link",
				label: __("Serienbrief Vorlage"),
				options: "Serienbrief Vorlage",
				description: __("Optional: Ausgabe als Serienbrief (Adresse/Briefkopf) statt Standard-Print."),
			},
			{ fieldtype: "Section Break", label: __("E-Mail") },
			{
				fieldname: "email_subject",
				fieldtype: "Data",
				label: __("Betreff"),
				default: default_subject,
				depends_on: "eval:doc.mode==='auto'",
			},
			{
				fieldname: "email_message",
				fieldtype: "Small Text",
				label: __("Nachricht"),
				default: default_message,
				depends_on: "eval:doc.mode==='auto'",
			},
		],
		primary_action_label: __("Ausführen"),
		primary_action(values) {
			dialog.disable_primary_action();
			frappe.call({
				method: "hausverwaltung.hausverwaltung.doctype.betriebskostenabrechnung_immobilie.betriebskostenabrechnung_immobilie.dispatch_mieter_abrechnungen",
				args: {
					name: frm.doc.name,
					mode: values.mode,
					serienbrief_vorlage: values.serienbrief_vorlage || null,
					email_subject: values.email_subject || null,
					email_message: values.email_message || null,
					also_print_emailed: values.also_print_emailed ? 1 : 0,
				},
			})
				.then((r) => {
					const res = (r && r.message) || {};
					const queued = res.queued || [];
					const print_names = res.print_names || [];
					const warnings = res.warnings || [];
					const errors = res.errors || [];
					const effective_print_format = res.print_format || null;

					const lines = [];
					if (queued.length) lines.push(__("E-Mail-Entwürfe: {0}", [queued.length]));
					if (print_names.length) lines.push(__("Druck: {0}", [print_names.length]));
					if (warnings.length) lines.push(__("Hinweise: {0}", [warnings.length]));
					if (errors.length) lines.push(__("Fehler: {0}", [errors.length]));

					frappe.msgprint({
						title: __("Versand"),
						indicator: errors.length ? "red" : warnings.length ? "orange" : "green",
						message:
							(lines.join("<br>") || __("Fertig.")) +
							(warnings.length
								? "<br><br><b>" +
								  __("Hinweise") +
								  "</b><br>" +
								  warnings.map((w) => frappe.utils.escape_html(w)).join("<br>")
								: "") +
							(errors.length
								? "<br><br><b>" +
								  __("Fehler") +
								  "</b><br>" +
								  errors.map((e) => frappe.utils.escape_html(e)).join("<br>")
								: ""),
					});

					if (print_names.length) {
						const params = {
							doctype: "Betriebskostenabrechnung Mieter",
							names: JSON.stringify(print_names),
							trigger_print: 1,
							no_letterhead: 0,
						};
						if (values.serienbrief_vorlage) params.serienbrief_vorlage = values.serienbrief_vorlage;
						if (effective_print_format) params.print_format = effective_print_format;
						const url =
							"/api/method/hausverwaltung.hausverwaltung.doctype.betriebskostenabrechnung_immobilie.betriebskostenabrechnung_immobilie.download_batch_print_html?" +
							$.param(params);
						window.open(frappe.urllib.get_full_url(url));
					}

					dialog.hide();
					frm.reload_doc();
				})
				.catch((err) => {
					console.error("Dispatch fehlgeschlagen", err);
				})
				.finally(() => {
					dialog.enable_primary_action();
				});
		},
	});

	dialog.show();
};
