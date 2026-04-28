// App-weit verfügbarer Dialog zum Anlegen eines Serienbrief Durchlaufs
// mit Multi-Select für Iterations-Objekte und dynamischen Variablen-Feldern.

frappe.provide("hausverwaltung.serienbrief");

hausverwaltung.serienbrief.open_new_durchlauf_dialog = (prefill = {}) => {
		const state = {
			names: [], // ausgewählte Iteration-Objekt-Namen
			variables: [], // [{ key, label, variable_type }]
			values: {}, // { [objectName]: { [key]: { value, path } } }
			preview_request_id: 0,
		};

	const dialog = new frappe.ui.Dialog({
		title: __("Neuen Serienbrief-Durchlauf erstellen"),
		size: "extra-large",
		fields: [
			{
				label: __("Vorlage durchsuchen …"),
				fieldname: "pick_vorlage_btn",
				fieldtype: "Button",
				click: () => hv_sbd_open_vorlage_picker(dialog),
			},
			{
				label: __("Vorlage"),
				fieldname: "vorlage",
				fieldtype: "Link",
				options: "Serienbrief Vorlage",
				reqd: 1,
				onchange: () => hv_sbd_on_vorlage_change(dialog, state),
			},
			{ label: __("Titel"), fieldname: "title", fieldtype: "Data", reqd: 1 },
			{ fieldtype: "Column Break" },
			{
				label: __("Ordner"),
				fieldname: "kategorie",
				fieldtype: "Link",
				options: "Serienbrief Kategorie",
				read_only: 1,
			},
				{
					label: __("Datum"),
					fieldname: "date",
					fieldtype: "Date",
					reqd: 1,
					default: frappe.datetime.get_today(),
				},
				{ fieldtype: "HTML", fieldname: "template_preview" },
				{ fieldtype: "Section Break" },
			{
				label: __("Iterations-Doctype"),
				fieldname: "iteration_doctype",
				fieldtype: "Link",
				options: "DocType",
				read_only: 1,
			},
			{
				label: __("Iterations-Objekte auswählen"),
				fieldname: "pick_objects_btn",
				fieldtype: "Button",
				click: () => hv_sbd_open_iteration_picker(dialog, state),
			},
			{ fieldtype: "HTML", fieldname: "iteration_objects_summary" },
			{ fieldtype: "Section Break", label: __("Vorlagen-Variablen") },
			{ fieldtype: "HTML", fieldname: "variables_table" },
		],
		primary_action_label: __("Erstellen & öffnen"),
		primary_action: (values) => hv_sbd_create(dialog, state, values),
	});

		dialog.__hv_state = state;
		hv_sbd_render_iteration_summary(dialog, state);
		hv_sbd_render_variables_table(dialog, state);
		hv_sbd_render_template_preview_shell(dialog);
		dialog.show();

	if (prefill.vorlage) dialog.set_value("vorlage", prefill.vorlage);
	if (prefill.title) dialog.set_value("title", prefill.title);
};

const hv_sbd_open_vorlage_picker = (dialog) => {
	const picker = hausverwaltung.serienbrief.open_vorlage_picker;
	if (typeof picker !== "function") {
		frappe.msgprint(
			__("Der Vorlagen-Browser ist nicht geladen. Bitte Seite neu laden.")
		);
		return;
	}
	picker({
		title: __("Serienbrief-Vorlage auswählen"),
		on_pick(row) {
			if (row?.name) dialog.set_value("vorlage", row.name);
		},
	});
};

const hv_sbd_on_vorlage_change = (dialog, state) => {
	const v = dialog.get_value("vorlage");
	if (!v) {
		dialog.set_value("title", "");
		dialog.set_value("kategorie", "");
		dialog.set_value("iteration_doctype", "");
		hv_sbd_set_iteration_objects(dialog, state, []);
			state.variables = [];
			state.values = {};
			hv_sbd_render_variables_table(dialog, state);
			hv_sbd_clear_template_preview(dialog, state);
			return;
		}
		hv_sbd_load_template_preview(dialog, state, v);
		frappe.db
		.get_value("Serienbrief Vorlage", v, ["title", "kategorie", "haupt_verteil_objekt"])
		.then((r) => {
			const d = (r && r.message) || {};
			if (!dialog.get_value("title") && d.title) {
				dialog.set_value("title", d.title);
			}
			dialog.set_value("kategorie", d.kategorie || "");
			dialog.set_value("iteration_doctype", d.haupt_verteil_objekt || "");
			hv_sbd_set_iteration_objects(dialog, state, []);
			hv_sbd_load_template_variables(dialog, state);
		});
	};

	const hv_sbd_render_template_preview_shell = (dialog) => {
		const field = dialog.get_field("template_preview");
		if (!field) return;
		field.$wrapper.html(`
			<div class="hv-sbd-preview" style="border:1px solid var(--border-color,#d9d9d9);border-radius:8px;overflow:hidden;background:#fff;">
				<div class="hv-sbd-preview-title" style="padding:10px 12px;border-bottom:1px solid var(--border-color,#eee);font-weight:600;">
					${__("Vorschau")}
				</div>
				<div class="hv-sbd-preview-status text-muted small" style="padding:8px 12px;border-bottom:1px solid var(--border-color,#eee);">
					${__("Wähle eine Vorlage, um die PDF-Vorschau zu laden.")}
				</div>
				<iframe class="hv-sbd-preview-frame" title="${__("Serienbrief Vorschau")}" style="width:100%;min-height:520px;border:0;background:#fff;"></iframe>
			</div>
		`);
	};

	const hv_sbd_clear_template_preview = (dialog, state, message) => {
		state.preview_request_id += 1;
		const field = dialog.get_field("template_preview");
		if (!field) return;
		field.$wrapper.find(".hv-sbd-preview-title").text(__("Vorschau"));
		field.$wrapper
			.find(".hv-sbd-preview-status")
			.text(message || __("Wähle eine Vorlage, um die PDF-Vorschau zu laden."));
		field.$wrapper.find(".hv-sbd-preview-frame").removeAttr("src");
	};

	const hv_sbd_load_template_preview = (dialog, state, template) => {
		const field = dialog.get_field("template_preview");
		if (!field || !template) return;
		const requestId = ++state.preview_request_id;
		field.$wrapper.find(".hv-sbd-preview-title").text(template);
		field.$wrapper.find(".hv-sbd-preview-status").text(__("Lade Vorschau..."));
		field.$wrapper.find(".hv-sbd-preview-frame").removeAttr("src");

		frappe
			.call({
				method: "hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.render_template_preview_pdf",
				args: { template, split_preview: 1 },
				quiet: true,
			})
			.then((r) => {
				if (requestId !== state.preview_request_id) return;
				const pdfBase64 = r?.message?.pdf_base64 || r?.message?.pdf || r?.message;
				if (!pdfBase64) {
					field.$wrapper.find(".hv-sbd-preview-status").text(__("Keine PDF-Vorschau verfügbar."));
					return;
				}
				field.$wrapper
					.find(".hv-sbd-preview-frame")
					.attr("src", `data:application/pdf;base64,${pdfBase64}`);
				field.$wrapper.find(".hv-sbd-preview-status").text("");
			})
			.catch((err) => {
				if (requestId !== state.preview_request_id) return;
				const message =
					err?._server_messages ||
					err?.message ||
					__("Vorschau konnte nicht geladen werden.");
				field.$wrapper.find(".hv-sbd-preview-status").text(message);
			});
	};

	const hv_sbd_load_template_variables = (dialog, state) => {
	const v = dialog.get_value("vorlage");
	if (!v) {
		state.variables = [];
		state.values = {};
		hv_sbd_render_variables_table(dialog, state);
		return;
	}
	frappe.call({
		method: "hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf.get_template_requirements",
		args: { template: v },
		callback(r) {
			const reqs = (r && r.message) || {};
			const defs = (reqs.template_variables || []).filter((def) =>
				["String", "Zahl", "Bool", "Datum", "Text"].includes(
					(def.variable_type || "String").trim()
				)
			);
			state.variables = defs.map((def) => ({
				key: def.key || hv_sbd_scrub(def.variable || def.label || ""),
				label: def.label || def.variable || def.key,
				variable_type: (def.variable_type || "String").trim() || "String",
			}));
			hv_sbd_render_variables_table(dialog, state);
		},
	});
};

const hv_sbd_open_iteration_picker = (dialog, state) => {
	const iter_dt = dialog.get_value("iteration_doctype");
	if (!iter_dt) {
		frappe.msgprint(__("Bitte zuerst eine Vorlage wählen."));
		return;
	}
	const current = (state.names || []).slice();

	new frappe.ui.form.MultiSelectDialog({
		doctype: iter_dt,
		target: dialog,
		setters: {},
		add_filters_group: 1,
		action(selections) {
			const unique = Array.from(new Set([...current, ...selections]));
			hv_sbd_set_iteration_objects(dialog, state, unique);
		},
	});
};

const hv_sbd_set_iteration_objects = (dialog, state, names) => {
	state.names = names.slice();
	Object.keys(state.values).forEach((name) => {
		if (!names.includes(name)) delete state.values[name];
	});
	hv_sbd_render_iteration_summary(dialog, state);
	hv_sbd_render_variables_table(dialog, state);
};

const hv_sbd_render_iteration_summary = (dialog, state) => {
	const field = dialog.get_field("iteration_objects_summary");
	if (!field) return;
	const names = (state && state.names) || [];
	if (!names.length) {
		field.$wrapper.html(
			`<div class="text-muted small">${__("Noch keine Objekte ausgewählt.")}</div>`
		);
		return;
	}
	const items = names
		.map((name, idx) => {
			const safe = frappe.utils.escape_html(name);
			return `
				<li class="d-flex align-items-center justify-content-between py-1">
					<span>${safe}</span>
					<button class="btn btn-xs btn-link text-danger" data-hv-remove-idx="${idx}">
						${__("Entfernen")}
					</button>
				</li>
			`;
		})
		.join("");
	field.$wrapper.html(`
		<div class="small text-muted mb-1">
			${__("{0} Objekt(e) ausgewählt", [names.length])}
		</div>
		<ul class="list-unstyled mb-0" style="max-height: 240px; overflow:auto;">
			${items}
		</ul>
	`);
	field.$wrapper.find("[data-hv-remove-idx]").on("click", (e) => {
		const idx = Number($(e.currentTarget).data("hv-remove-idx"));
		const current = (state.names || []).slice();
		const removed = current.splice(idx, 1)[0];
		if (removed) delete state.values[removed];
		hv_sbd_set_iteration_objects(dialog, state, current);
	});
};

const hv_sbd_render_variables_table = (dialog, state) => {
	dialog.__hv_state = state;
	const field = dialog.get_field("variables_table");
	if (!field) return;

	const names = state.names || [];
	const variables = state.variables || [];

	if (!variables.length) {
		field.$wrapper.html(
			`<div class="text-muted small">${__(
				"Die gewählte Vorlage enthält keine Variablen."
			)}</div>`
		);
		return;
	}
	if (!names.length) {
		field.$wrapper.html(
			`<div class="text-muted small">${__(
				"Bitte zuerst Iterations-Objekte auswählen, um Variablenwerte zu setzen."
			)}</div>`
		);
		return;
	}

	const header = variables
		.map((v) => `<th>${frappe.utils.escape_html(v.label)}</th>`)
		.join("");

	const rows = names
		.map((name) => {
			const rowValues = state.values[name] || {};
			const cells = variables
				.map((v) => {
					const entry = rowValues[v.key] || {};
					return `<td>${hv_sbd_input(v, entry.value, name)}</td>`;
				})
				.join("");
			return `<tr><td>${frappe.utils.escape_html(name)}</td>${cells}</tr>`;
		})
		.join("");

	field.$wrapper.html(`
		<div class="table-responsive">
			<table class="table table-bordered table-sm">
				<thead>
					<tr>
						<th>${__("Iterations-Objekt")}</th>
						${header}
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		</div>
	`);

	field.$wrapper.find("[data-hv-var-input]").on("change", (e) => {
		const $el = $(e.currentTarget);
		const objectName = $el.data("object");
		const varKey = $el.data("var-key");
		const varType = $el.data("var-type");
		const parsed = hv_sbd_parse(varType, $el.val());
		if (!state.values[objectName]) state.values[objectName] = {};
		if (parsed === null) {
			delete state.values[objectName][varKey];
		} else {
			state.values[objectName][varKey] = { value: parsed, path: "" };
		}
	});
};

const hv_sbd_input = (variable, currentValue, objectName) => {
	const key = frappe.utils.escape_html(variable.key);
	const obj = frappe.utils.escape_html(objectName);
	const type = variable.variable_type || "String";
	const val = currentValue !== undefined && currentValue !== null ? String(currentValue) : "";
	const common = `data-hv-var-input data-object="${obj}" data-var-key="${key}" data-var-type="${frappe.utils.escape_html(
		type
	)}"`;

	if (type === "Zahl") {
		return `<input type="number" step="any" class="form-control" value="${frappe.utils.escape_html(
			val
		)}" ${common} />`;
	}
	if (type === "Bool") {
		const selYes = currentValue === true ? "selected" : "";
		const selNo = currentValue === false ? "selected" : "";
		return `
			<select class="form-control" ${common}>
				<option value=""></option>
				<option value="Ja" ${selYes}>${__("Ja")}</option>
				<option value="Nein" ${selNo}>${__("Nein")}</option>
			</select>
		`;
	}
	if (type === "Datum") {
		return `<input type="date" class="form-control" value="${frappe.utils.escape_html(
			val
		)}" ${common} />`;
	}
	return `<input type="text" class="form-control" value="${frappe.utils.escape_html(
		val
	)}" ${common} />`;
};

const hv_sbd_parse = (type, raw) => {
	const text = String(raw ?? "").trim();
	if (type === "Zahl") {
		if (text === "") return null;
		const n = Number(text);
		return Number.isNaN(n) ? null : n;
	}
	if (type === "Bool") {
		if (raw === "Ja") return true;
		if (raw === "Nein") return false;
		return null;
	}
	return text || null;
};

const hv_sbd_scrub = (value) => {
	if (!value) return "";
	if (frappe.model && typeof frappe.model.scrub === "function") {
		return frappe.model.scrub(value);
	}
	return String(value).toLowerCase().replace(/\s+/g, "_");
};

const hv_sbd_create = (dialog, state, values) => {
	const names = state.names || [];
	if (!names.length) {
		frappe.msgprint(__("Bitte mindestens ein Iterations-Objekt auswählen."));
		return;
	}
	if (!values.iteration_doctype) {
		frappe.msgprint(__("Iterations-Doctype fehlt – bitte Vorlage neu wählen."));
		return;
	}

	const iteration_objekte = names.map((name) => {
		const rowVals = state.values[name] || {};
		const variablen_werte = Object.keys(rowVals).length ? JSON.stringify(rowVals) : null;
		return {
			doctype: "Serienbrief Iterationsobjekt",
			iteration_doctype: values.iteration_doctype,
			objekt: name,
			variablen_werte,
		};
	});

	const doc = {
		doctype: "Serienbrief Durchlauf",
		vorlage: values.vorlage,
		title: values.title,
		kategorie: values.kategorie,
		iteration_doctype: values.iteration_doctype,
		date: values.date,
		iteration_objekte,
	};

	dialog.disable_primary_action();
	frappe.call({
		method: "frappe.client.insert",
		args: { doc },
		callback(r) {
			const created = r && r.message;
			dialog.hide();
			if (created && created.name) {
				frappe.set_route("Form", "Serienbrief Durchlauf", created.name);
			}
		},
		error() {
			dialog.enable_primary_action();
		},
	});
};
