frappe.ui.form.on("Mieterwechsel", {
	refresh(frm) {
		apply_prozess_typ_ui(frm);
		seed_tasks_for_new_doc(frm);
		render_progress(frm);
		render_blockers(frm);
		add_action_buttons(frm);
		set_contract_queries(frm);
	},
	prozess_typ(frm) {
		apply_prozess_typ_ui(frm);
		seed_tasks_for_new_doc(frm, { force: true });
		render_progress(frm);
		render_blockers(frm);
	},
	aufgaben_add(frm) {
		render_progress(frm);
		render_blockers(frm);
	},
	aufgaben_remove(frm) {
		render_progress(frm);
		render_blockers(frm);
	},
	wohnung(frm) {
		set_contract_queries(frm);
	},
});

frappe.ui.form.on("Prozess Aufgabe", {
	status(frm) {
		render_progress(frm);
		render_blockers(frm);
	},
	pflicht(frm) {
		render_progress(frm);
		render_blockers(frm);
	},
	erfuellt(frm) {
		render_progress(frm);
		render_blockers(frm);
	},
});

function set_contract_queries(frm) {
	const wohnung = (frm.doc.wohnung || "").trim();
	frm.set_query("alter_mietvertrag", () => ({
		filters: wohnung ? { wohnung } : {},
	}));
	frm.set_query("neuer_mietvertrag", () => ({
		filters: wohnung ? { wohnung } : {},
	}));
}

function apply_prozess_typ_ui(frm) {
	const istErstvermietung = (frm.doc.prozess_typ || "").trim() === "Erstvermietung";
	frm.set_df_property("alter_mietvertrag", "reqd", istErstvermietung ? 0 : 1);
	frm.set_df_property("alter_mietvertrag", "hidden", istErstvermietung ? 1 : 0);

	// Legacy-Felder sind nicht mehr führend in der Abschlusslogik.
	frm.set_df_property("section_pruefung", "hidden", 1);
	frm.set_df_property("section_dokumente", "hidden", 1);
}

function render_progress(frm) {
	const rows = frm.doc.aufgaben || [];
	const required = rows.filter((r) => cint(r.pflicht)).length;
	const done = rows.filter((r) => cint(r.pflicht) && cint(r.erfuellt)).length;
	const pct = required ? Math.round((done / required) * 100) : 0;
	const versionLabel = (frm.doc.prozess_version_label || frm.doc.prozess_version || "").trim();
	const versionHtml = versionLabel ? `<div><strong>Prozessversion:</strong> ${frappe.utils.escape_html(versionLabel)}</div>` : "";

	const html = `
		<div style="border:1px solid #ddd;border-radius:8px;padding:10px;">
			${versionHtml}
			<div><strong>Pflichtaufgaben:</strong> ${done}/${required} fachlich erfüllt (${pct}%)</div>
			<div style="height:10px;background:#f2f2f2;border-radius:6px;margin-top:8px;overflow:hidden;">
				<div style="height:10px;width:${pct}%;background:#4b7bec;"></div>
			</div>
		</div>
	`;
	frm.get_field("progress_html").$wrapper.html(html);
}

function render_blockers(frm) {
	if (frm.is_new()) {
		frm.get_field("blocker_hinweise_html").$wrapper.html("");
		return;
	}

	frappe.call({
		method: "hausverwaltung.hausverwaltung.doctype.mieterwechsel.mieterwechsel.get_completion_blockers",
		args: { docname: frm.doc.name },
	}).then((r) => {
		const blockers = (r.message && r.message.blockers) || [];
		const warnings = (r.message && r.message.warnings) || [];

		let html = "";
		if (blockers.length) {
			html += `<div style="border:1px solid #f5c2c7;background:#fff5f5;padding:10px;border-radius:8px;margin-bottom:8px;">
				<strong>Abschluss-Blocker</strong><ul>${blockers.map((b) => `<li>${frappe.utils.escape_html(b)}</li>`).join("")}</ul></div>`;
		}
		if (warnings.length) {
			html += `<div style="border:1px solid #ffe08a;background:#fff9e6;padding:10px;border-radius:8px;">
				<strong>Hinweise</strong><ul>${warnings.map((b) => `<li>${frappe.utils.escape_html(b)}</li>`).join("")}</ul></div>`;
		}
		frm.get_field("blocker_hinweise_html").$wrapper.html(html);
	});
}

function add_action_buttons(frm) {
	if (frm.is_new()) {
		frm.add_custom_button(__("Speichern"), () => frm.save(), __("Workflow"));
		return;
	}

	frm.add_custom_button(__("Status-Aktion"), () => open_status_action_dialog(frm), __("Workflow"));
	frm.add_custom_button(__("Aufgaben-Aktion"), () => open_task_action_dialog(frm), __("Workflow"));

	frm.add_custom_button(
		__("Neuen Mietvertrag anlegen"),
		() => {
			frappe.new_doc("Mietvertrag", {
				wohnung: frm.doc.wohnung || undefined,
				von: frm.doc.einzugsdatum || undefined,
				mieterwechsel: frm.doc.name,
			});
		},
		__("Workflow")
	);

	const canBypass =
		(frappe.user_roles || []).includes("System Manager") || (frappe.user_roles || []).includes("Hausverwalter");
	if (!canBypass) {
		return;
	}

	frm.add_custom_button(
		__("Bypass freigeben"),
		() => {
			frappe.prompt(
				[
					{
						fieldname: "reason",
						label: __("Begruendung"),
						fieldtype: "Small Text",
						reqd: 1,
					},
				],
				(values) => {
					frappe
						.call({
							method: "hausverwaltung.hausverwaltung.doctype.mieterwechsel.mieterwechsel.approve_bypass",
							args: {
								docname: frm.doc.name,
								reason: values.reason,
							},
							freeze: true,
						})
						.then(() => frm.reload_doc());
				},
				__("Bypass freigeben"),
				__("Speichern")
			);
		},
		__("Workflow")
	);
}

function open_status_action_dialog(frm) {
	const status = (frm.doc.status || "").trim();
	const options = [];
	if (status === "Entwurf") options.push({ label: "Starten", action: "start" });
	if (status === "In Bearbeitung") {
		options.push({ label: "Auf Unterlagen warten", action: "wait_for_documents" });
		options.push({ label: "Zur Pruefung", action: "to_review" });
	}
	if (status === "Wartet auf Unterlagen") options.push({ label: "Zur Pruefung", action: "to_review" });
	if (status === "Abschlusspruefung") {
		options.push({ label: "Abschliessen", action: "complete" });
		options.push({ label: "Bypass Abschliessen", action: "bypass_complete" });
	}

	if (!options.length) {
		frappe.msgprint(__("Keine Status-Aktionen verfuegbar."));
		return;
	}

	frappe.prompt(
		[
			{
				fieldname: "action_label",
				label: __("Aktion"),
				fieldtype: "Select",
				reqd: 1,
				options: options.map((o) => o.label).join("\n"),
			},
		],
		(values) => {
			const selected = options.find((o) => o.label === values.action_label);
			if (!selected) return;

			const run = (payload = {}) =>
				frappe
					.call({
						method: "hausverwaltung.hausverwaltung.doctype.mieterwechsel.mieterwechsel.dispatch_workflow_action",
						args: {
							docname: frm.doc.name,
							action: selected.action,
							payload_json: JSON.stringify(payload || {}),
						},
						freeze: true,
					})
					.then(() => frm.reload_doc());

			if (selected.action === "bypass_complete") {
				frappe.prompt(
					[
						{
							fieldname: "reason",
							label: __("Bypass Begruendung"),
							fieldtype: "Small Text",
							reqd: 1,
						},
					],
					(v) => run({ reason: v.reason }),
					__("Bypass Abschliessen"),
					__("Ausfuehren")
				);
				return;
			}

			run({});
		},
		__("Status-Aktion"),
		__("Ausfuehren")
	);
}

function seed_tasks_for_new_doc(frm, opts = {}) {
	if (!frm.is_new()) return;
	if (frm.__seeding_tasks) return;
	const hasRows = (frm.doc.aufgaben || []).length > 0;
	if (hasRows && !opts.force) return;

	frm.__seeding_tasks = true;
	frappe
		.call({
			method: "hausverwaltung.hausverwaltung.doctype.mieterwechsel.mieterwechsel.get_seed_tasks_preview",
			args: { prozess_typ: frm.doc.prozess_typ || "Mieterwechsel" },
		})
		.then((r) => {
			const msg = r.message || {};
			const tasks = Array.isArray(msg.tasks) ? msg.tasks : [];
			if (!tasks.length) return;

			frm.clear_table("aufgaben");
			tasks.forEach((row) => frm.add_child("aufgaben", row));
			if (!frm.doc.prozess_version && msg.prozess_version) frm.set_value("prozess_version", msg.prozess_version);
			if (!frm.doc.prozess_version_label && msg.prozess_version_label) {
				frm.set_value("prozess_version_label", msg.prozess_version_label);
			}
			frm.refresh_field("aufgaben");
			render_progress(frm);
			render_blockers(frm);
		})
		.finally(() => {
			frm.__seeding_tasks = false;
		});
}

function open_task_action_dialog(frm) {
	const rows = (frm.doc.aufgaben || []).filter((r) => !!(r.name || "").trim());
	if (!rows.length) {
		frappe.msgprint(__("Keine Aufgaben vorhanden."));
		return;
	}

	const options = rows.map((r) => ({
		label: `${r.aufgabe} [${r.task_type || "manual_check"}]`,
		value: r.name,
	}));

	frappe.prompt(
		[
			{
				fieldname: "row_name",
				label: __("Aufgabe"),
				fieldtype: "Select",
				reqd: 1,
				options: options.map((o) => o.label).join("\n"),
			},
		],
		(values) => {
			const selected = options.find((o) => o.label === values.row_name);
			if (!selected) {
				return;
			}
			const row = rows.find((r) => r.name === selected.value);
			if (!row) {
				return;
			}
			run_task_action(frm, row);
		},
		__("Aufgabe waehlen"),
		__("Weiter")
	);
}

function run_task_action(frm, row) {
	const typ = (row.task_type || "manual_check").trim();
	if (typ === "paperless_export") {
		return choose_paperless_action(frm, row);
	}
	if (typ === "print_document") {
		return choose_print_action(frm, row);
	}
	if (typ === "python_action") {
		return choose_python_action(frm, row);
	}
	return choose_check_action(frm, row);
}

function choose_check_action(frm, row) {
	frappe.prompt(
		[
			{
				fieldname: "action",
				label: __("Aktion"),
				fieldtype: "Select",
				reqd: 1,
				options: "Als erledigt markieren\nAls offen markieren",
			},
		],
		(values) => {
			const status = values.action === "Als erledigt markieren" ? "Erledigt" : "Offen";
			frappe
				.call({
					method: "hausverwaltung.hausverwaltung.doctype.mieterwechsel.mieterwechsel.dispatch_workflow_action",
					args: {
						docname: frm.doc.name,
						action: "set_task_status",
						payload_json: JSON.stringify({ row_name: row.name, status }),
					},
					freeze: true,
				})
				.then(() => frm.reload_doc());
		},
		__("Check-Aufgabe"),
		__("Ausfuehren")
	);
}

function choose_paperless_action(frm, row) {
	frappe.prompt(
		[
			{
				fieldname: "action",
				label: __("Aktion"),
				fieldtype: "Select",
				reqd: 1,
				options: "Detail oeffnen (Datei hochladen)\nNach Paperless exportieren",
			},
		],
		(values) => {
			if (values.action === "Detail oeffnen (Datei hochladen)") {
				open_task_detail(frm, row);
				return;
			}
			frappe
				.call({
					method: "hausverwaltung.hausverwaltung.doctype.mieterwechsel.mieterwechsel.export_file_task_to_paperless",
					args: { docname: frm.doc.name, aufgabe_row_name: row.name },
					freeze: true,
				})
				.then(() => frm.reload_doc());
		},
		__("Datei-Aufgabe"),
		__("Ausfuehren")
	);
}

function choose_print_action(frm, row) {
	frappe.prompt(
		[
			{
				fieldname: "action",
				label: __("Aktion"),
				fieldtype: "Select",
				reqd: 1,
				options: "Detail oeffnen\nPDF erzeugen\nAbheftung bestaetigen\nAbheftung zuruecknehmen",
			},
		],
		(values) => {
			if (values.action === "Detail oeffnen") {
				open_task_detail(frm, row);
				return;
			}
			if (values.action === "PDF erzeugen") {
				frappe
					.call({
						method: "hausverwaltung.hausverwaltung.doctype.mieterwechsel.mieterwechsel.generate_print_task_pdf",
						args: { docname: frm.doc.name, aufgabe_row_name: row.name },
						freeze: true,
					})
					.then(() => frm.reload_doc());
				return;
			}
			const confirmed = values.action === "Abheftung bestaetigen" ? 1 : 0;
			frappe
				.call({
					method: "hausverwaltung.hausverwaltung.doctype.mieterwechsel.mieterwechsel.confirm_print_task_filed",
					args: { docname: frm.doc.name, aufgabe_row_name: row.name, confirmed },
					freeze: true,
				})
				.then(() => frm.reload_doc());
		},
		__("Druck-Aufgabe"),
		__("Ausfuehren")
	);
}

function choose_python_action(frm, row) {
	frappe.prompt(
		[
			{
				fieldname: "action",
				label: __("Aktion"),
				fieldtype: "Select",
				reqd: 1,
				options: "Python-Aktion ausfuehren\nAls offen markieren",
			},
		],
		(values) => {
			if (values.action === "Als offen markieren") {
				frappe
					.call({
						method: "hausverwaltung.hausverwaltung.doctype.mieterwechsel.mieterwechsel.dispatch_workflow_action",
						args: {
							docname: frm.doc.name,
							action: "set_task_status",
							payload_json: JSON.stringify({ row_name: row.name, status: "Offen" }),
						},
						freeze: true,
					})
					.then(() => frm.reload_doc());
				return;
			}
			frappe
				.call({
					method: "hausverwaltung.hausverwaltung.doctype.mieterwechsel.mieterwechsel.dispatch_workflow_action",
					args: {
						docname: frm.doc.name,
						action: "run_python_task",
						payload_json: JSON.stringify({ row_name: row.name }),
					},
					freeze: true,
				})
				.then(() => frm.reload_doc());
		},
		__("Python-Aufgabe"),
		__("Ausfuehren")
	);
}

function open_task_detail(frm, row) {
	frappe
		.call({
			method: "hausverwaltung.hausverwaltung.doctype.mieterwechsel.mieterwechsel.get_task_detail",
			args: { docname: frm.doc.name, aufgabe_row_name: row.name },
		})
		.then((r) => {
			if (!r.message || !r.message.doctype || !r.message.name) {
				frappe.msgprint(__("Kein Detailobjekt vorhanden."));
				return;
			}
			frappe.set_route("Form", r.message.doctype, r.message.name);
		});
}
