// Phase 5 UI-Schicht fuer Prozess Instanz:
// 5a — Payload-Form-Renderer (dynamische Controls statt JSON-Textarea)
// 5b — Per-Task-Action-Buttons (PDF, Paperless, Python-Action, ...)
// 5c — create_linked_doc Dialog-Flow
// Phase 6 — Progress-Graph (Mermaid) im progress_html-Feld

frappe.ui.form.on("Prozess Instanz", {
	async refresh(frm) {
		// payload_json wird via DocField-Property versteckt (kein DOM-Eingriff).
		// Power-User-Toggle weiter unten kann es bei Bedarf wieder einblenden.
		frm.set_df_property("payload_json", "hidden", 1);
		_add_raw_json_toggle(frm);

		if (frm.is_new() && !frm.doc.prozess_typ) {
			return;
		}
		await _render_payload_form(frm);
		_render_task_action_panel(frm);
		_wire_task_actions(frm);
		_render_progress_graph(frm);
	},
	prozess_typ(frm) {
		_render_payload_form(frm);
	},
});

frappe.ui.form.on("Prozess Aufgabe", {
	// Action-Panel + Graph zusammen aktualisieren — sonst zeigt der Graph alten Status
	// bis zum naechsten reload_doc().
	status(frm) {
		_render_task_action_panel(frm);
		_render_progress_graph(frm);
	},
	erfuellt(frm) {
		_render_task_action_panel(frm);
		_render_progress_graph(frm);
	},
});

// ==================== 5a: Payload-Form-Renderer ====================

async function _render_payload_form(frm) {
	const field = frm.get_field("payload_form_html");
	if (!field) return;
	if (!frm.doc.prozess_typ) {
		field.$wrapper.html("");
		return;
	}
	let specs = [];
	try {
		const r = await frappe.call({
			method: "hausverwaltung.hausverwaltung.processes.triggers.get_payload_field_specs",
			args: { prozess_typ: frm.doc.prozess_typ },
		});
		specs = r.message || [];
	} catch (err) {
		console.error("get_payload_field_specs failed", err);
		field.$wrapper.html(`<p class="text-danger">${__("Payload-Specs konnten nicht geladen werden.")}</p>`);
		return;
	}
	if (!specs.length) {
		field.$wrapper.html(`<p class="text-muted">${__("Keine Payload-Felder konfiguriert.")}</p>`);
		return;
	}

	let state = {};
	try {
		state = JSON.parse(frm.doc.payload_json || "{}");
		if (!state || typeof state !== "object") state = {};
	} catch (e) {
		state = {};
	}

	const $container = $('<div class="payload-dynamic-form row"></div>');
	field.$wrapper.empty().append($container);

	for (const spec of specs) {
		const $col = $('<div class="form-column col-sm-6" style="margin-bottom:8px;"></div>');
		$container.append($col);
		const df = {
			fieldname: spec.fieldname,
			label: spec.label,
			fieldtype: spec.fieldtype,
			options: spec.options || undefined,
			reqd: spec.reqd,
			description: spec.description || undefined,
		};
		const ctrl = frappe.ui.form.make_control({
			df,
			parent: $col.get(0),
			render_input: true,
		});
		const current_val = state[spec.fieldname] ?? null;
		if (current_val !== null && current_val !== undefined) {
			ctrl.set_value(current_val);
		}
		ctrl.df.onchange = () => {
			const new_state = { ...state, [spec.fieldname]: ctrl.get_value() };
			state = new_state;
			frm.set_value("payload_json", JSON.stringify(new_state));
		};
	}
}

function _add_raw_json_toggle(frm) {
	if (frm.is_new()) return;
	if (frm.__hv_raw_json_toggle_added) return;
	frm.__hv_raw_json_toggle_added = true;
	frm.add_custom_button(__("Raw JSON anzeigen"), () => {
		frm.set_df_property("payload_json", "hidden", 0);
		frm.refresh_field("payload_json");
	}, __("Power-User"));
}

// ==================== 5b: Per-Task-Action-Buttons ====================

function _render_task_action_panel(frm) {
	const field = frm.get_field("task_actions_html");
	if (!field) return;
	const rows = frm.doc.aufgaben || [];
	if (!rows.length) {
		field.$wrapper.html(`<p class="text-muted">${__("Keine Aufgaben.")}</p>`);
		return;
	}
	const items = rows.map((r) => _render_task_row(frm, r)).join("");
	field.$wrapper.html(`<div class="task-action-panel" style="margin-top:8px;">${items}</div>`);
}

function _render_task_row(frm, row) {
	const locked = row.pflicht && !_is_task_unlocked_client(frm, row);
	const buttons = _buttons_for_task_type(row, locked);
	const status = row.status || "Offen";
	const status_class = status === "Erledigt" ? "green" : (locked ? "gray" : "blue");
	const status_badge = `<span class="indicator-pill ${status_class}">${frappe.utils.escape_html(status)}</span>`;
	const pflicht = row.pflicht ? `<span class="indicator-pill orange">${__("Pflicht")}</span>` : "";
	const lock_hint = locked ? `<span class="text-muted" style="margin-left:6px;">(${__("Vorgaenger offen")})</span>` : "";
	return `
		<div class="task-row" data-row-name="${row.name}" style="border:1px solid #d1d8dd; padding:8px 12px; margin-bottom:6px; border-radius:4px; ${locked ? "opacity:0.7;" : ""}">
			<div style="display:flex; justify-content:space-between; align-items:center; gap:12px;">
				<div>
					<strong>${frappe.utils.escape_html(row.aufgabe || row.step_key || "")}</strong>
					${pflicht} ${status_badge}${lock_hint}
				</div>
				<div class="task-actions" style="display:flex; gap:4px;">${buttons}</div>
			</div>
		</div>
	`;
}

function _is_task_unlocked_client(frm, row) {
	// UX-Approximation: prueft NUR direkte depends_on. Server (_is_task_unlocked
	// in engine.py) macht das TRANSITIV. Hier nur fuer den Disabled-State.
	let deps = [];
	try { deps = JSON.parse(row.depends_on_json || "[]"); } catch (e) { deps = []; }
	if (!Array.isArray(deps) || !deps.length) return true;
	const by_key = {};
	for (const r of (frm.doc.aufgaben || [])) {
		const k = (r.step_key || "").trim();
		if (k) by_key[k] = r;
	}
	for (const d of deps) {
		const parent = by_key[(d || "").trim()];
		if (parent && !parent.erfuellt) return false;
	}
	return true;
}

function _buttons_for_task_type(row, locked) {
	const rn = row.name;
	const tt = row.task_type;
	const btns = [];
	const da = locked ? "disabled" : "";
	if (row.status !== "Erledigt") {
		btns.push(`<button class="btn btn-xs btn-default" data-action="set_status" data-row="${rn}" data-status="Erledigt" ${da}>${__("Erledigt")}</button>`);
	} else {
		btns.push(`<button class="btn btn-xs btn-default" data-action="set_status" data-row="${rn}" data-status="Offen">${__("Wieder oeffnen")}</button>`);
	}
	if (tt === "print_document") {
		btns.push(`<button class="btn btn-xs btn-primary" data-action="generate_print" data-row="${rn}" ${da}>${__("PDF generieren")}</button>`);
		btns.push(`<button class="btn btn-xs btn-default" data-action="confirm_filed" data-row="${rn}" ${da}>${__("Abheften bestaetigen")}</button>`);
	}
	if (tt === "paperless_export") {
		btns.push(`<button class="btn btn-xs btn-primary" data-action="export_file" data-row="${rn}" ${da}>${__("Nach Paperless")}</button>`);
	}
	if (tt === "python_action") {
		btns.push(`<button class="btn btn-xs btn-primary" data-action="run_python" data-row="${rn}" ${da}>${__("Ausfuehren")}</button>`);
	}
	if (tt === "create_linked_doc") {
		btns.push(`<button class="btn btn-xs btn-primary" data-action="create_linked" data-row="${rn}" ${da}>${__("Neu anlegen")}</button>`);
	}
	return btns.join(" ");
}

function _wire_task_actions(frm) {
	const field = frm.get_field("task_actions_html");
	if (!field) return;
	// off() entfernt frueher gebundene Handler beim Refresh
	field.$wrapper.off("click.hv_task_actions").on("click.hv_task_actions", "button[data-action]", async (e) => {
		const $btn = $(e.currentTarget);
		const action = $btn.data("action");
		const row_name = $btn.data("row");
		const status = $btn.data("status");
		await _dispatch_task_action(frm, action, row_name, status);
	});
}

async function _dispatch_task_action(frm, action, row_name, status) {
	if (action === "create_linked") {
		return _open_create_linked_dialog(frm, row_name);
	}
	const action_map = {
		set_status: { action: "set_task_status", payload: { row_name, status } },
		generate_print: { action: "generate_print_task", payload: { row_name } },
		confirm_filed: { action: "confirm_print_task", payload: { row_name, confirmed: 1 } },
		export_file: { action: "export_file_task", payload: { row_name } },
		run_python: { action: "run_python_task", payload: { row_name } },
	};
	const mapped = action_map[action];
	if (!mapped) return;
	try {
		await frappe.call({
			method: "hausverwaltung.hausverwaltung.doctype.prozess_instanz.prozess_instanz.dispatch_workflow_action",
			args: {
				docname: frm.doc.name,
				action: mapped.action,
				payload_json: JSON.stringify(mapped.payload),
			},
			freeze: true,
		});
		await frm.reload_doc();
	} catch (err) {
		// Server-Fehler (z.B. "Vorgaenger noch nicht freigegeben") sauber anzeigen.
		const msg = (err && err.message) || (frappe.last_response && frappe.last_response._server_messages) || String(err);
		frappe.msgprint({
			title: __("Aktion fehlgeschlagen"),
			message: msg,
			indicator: "red",
		});
	}
}

// ==================== 5c: create_linked_doc Dialog ====================

async function _open_create_linked_dialog(frm, row_name) {
	let dialog_fields = [];
	try {
		const r = await frappe.call({
			method: "hausverwaltung.hausverwaltung.doctype.prozess_instanz.prozess_instanz.get_create_linked_dialog_fields",
			args: { docname: frm.doc.name, row_name },
		});
		dialog_fields = r.message || [];
	} catch (err) {
		frappe.msgprint({
			title: __("Dialog konnte nicht geoeffnet werden"),
			message: (err && err.message) || String(err),
			indicator: "red",
		});
		return;
	}
	if (!dialog_fields.length) {
		frappe.show_alert({ message: __("Keine Dialog-Felder in Task-Config."), indicator: "orange" });
		return;
	}

	const row = (frm.doc.aufgaben || []).find((r) => r.name === row_name);
	let target_doctype = "";
	try {
		const cfg = JSON.parse((row && row.config_json) || "{}");
		target_doctype = cfg.target_doctype || "";
	} catch (e) {}

	const dialog = new frappe.ui.Dialog({
		title: target_doctype ? __("Neu anlegen: {0}", [target_doctype]) : __("Neu anlegen"),
		fields: dialog_fields,
		primary_action_label: __("Anlegen"),
		primary_action: async (values) => {
			try {
				const r = await frappe.call({
					method: "hausverwaltung.hausverwaltung.doctype.prozess_instanz.prozess_instanz.dispatch_workflow_action",
					args: {
						docname: frm.doc.name,
						action: "create_linked_doc",
						payload_json: JSON.stringify({ row_name, user_values: values }),
					},
					freeze: true,
				});
				dialog.hide();
				// dispatch_local wickelt das Handler-Result in {ok, status, ..., meta: {...}}.
				const meta = (r.message && r.message.meta) || {};
				const created = meta.created_name || "(unbekannt)";
				frappe.show_alert({
					message: __("Angelegt: {0}", [created]),
					indicator: "green",
				});
				await frm.reload_doc();
			} catch (err) {
				const msg = (err && err.message) || (frappe.last_response && frappe.last_response._server_messages) || String(err);
				frappe.msgprint({
					title: __("Anlegen fehlgeschlagen"),
					message: msg,
					indicator: "red",
				});
			}
		},
	});
	dialog.show();
}

// ==================== Phase 6: Progress-Graph (Mermaid) ====================

function _render_progress_graph(frm) {
	const field = frm.get_field("progress_html");
	if (!field) return;
	const rows = frm.doc.aufgaben || [];
	if (!rows.length) {
		field.$wrapper.html(`<p class="text-muted">${__("Keine Aufgaben.")}</p>`);
		return;
	}
	const nodes = rows
		.map((r) => ({
			step_key: (r.step_key || "").trim(),
			titel: r.aufgabe || r.step_key,
			pflicht: !!r.pflicht,
		}))
		.filter((n) => n.step_key);
	const edges = [];
	for (const r of rows) {
		const sk = (r.step_key || "").trim();
		let deps = [];
		try {
			deps = JSON.parse(r.depends_on_json || "[]");
		} catch (e) {
			deps = [];
		}
		for (const d of deps || []) {
			const dep = (d || "").trim();
			if (sk && dep) edges.push({ from: dep, to: sk });
		}
	}
	const status_by_step = {};
	for (const r of rows) {
		const sk = (r.step_key || "").trim();
		if (!sk) continue;
		const status = (r.status || "").trim();
		if (status === "Erledigt") status_by_step[sk] = "done";
		else if (r.pflicht && !_is_task_unlocked_client(frm, r)) status_by_step[sk] = "locked";
		else if (status === "In Arbeit") status_by_step[sk] = "wip";
		else status_by_step[sk] = "open";
	}

	const legend = `<div class="text-muted" style="margin-top:6px; font-size:0.85em;">
		<span style="display:inline-block;width:10px;height:10px;background:#17a2b8;margin-right:4px;vertical-align:middle;"></span>${__("Offen")}
		<span style="display:inline-block;width:10px;height:10px;background:#ffc107;margin:0 4px 0 12px;vertical-align:middle;"></span>${__("In Arbeit")}
		<span style="display:inline-block;width:10px;height:10px;background:#28a745;margin:0 4px 0 12px;vertical-align:middle;"></span>${__("Erledigt")}
		<span style="display:inline-block;width:10px;height:10px;background:#adb5bd;margin:0 4px 0 12px;vertical-align:middle;"></span>${__("Vorgaenger offen")}
	</div>`;

	field.$wrapper.html(
		`<div class="progress-graph-container" style="margin-top:8px;"></div>${legend}`
	);

	frappe.require("/assets/hausverwaltung/js/dag_mermaid.js", () => {
		const container = field.$wrapper.find(".progress-graph-container").get(0);
		if (!container) return;
		window.hausverwaltung.dag.renderDag({
			container,
			nodes,
			edges,
			status_by_step,
			on_click: (stepKey) => _on_graph_node_click(frm, stepKey),
		});
	});
}

function _on_graph_node_click(frm, step_key) {
	// Bei create_linked_doc-Tasks (offen + freigegeben) direkt den Anlege-Dialog.
	// Sonst nur scroll zur Row in der Aufgaben-Tabelle.
	const row = (frm.doc.aufgaben || []).find(
		(r) => (r.step_key || "").trim() === step_key
	);
	if (!row) return;
	const status = (row.status || "").trim();
	const locked = row.pflicht && !_is_task_unlocked_client(frm, row);
	if ((row.task_type || "") === "create_linked_doc" && status !== "Erledigt" && !locked) {
		_open_create_linked_dialog(frm, row.name);
		return;
	}
	_scroll_to_task_row(frm, step_key);
}

function _scroll_to_task_row(frm, step_key) {
	const fld = frm.get_field("aufgaben");
	if (!fld || !fld.grid) return;
	const grid = fld.grid;
	const row = (frm.doc.aufgaben || []).find((r) => (r.step_key || "").trim() === step_key);
	if (!row) return;
	try {
		grid.toggle_view(row.name, true);
	} catch (e) {
		// Falls Grid noch nicht initialisiert: Scroll-only-Fallback
	}
	const $row = grid.$wrapper.find(`[data-name="${row.name}"]`);
	if ($row.length) {
		$row[0].scrollIntoView({ behavior: "smooth", block: "center" });
	}
}
