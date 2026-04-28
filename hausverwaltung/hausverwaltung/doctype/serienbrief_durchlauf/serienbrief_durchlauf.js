const hv_ensure_iteration_objects = (frm) => {
	if (!frm.doc.iteration_objekte || !frm.doc.iteration_objekte.length) {
		frappe.msgprint({
			message: __("Bitte fügen Sie mindestens ein Iterations-Objekt hinzu."),
			title: __("Keine Iterations-Objekte"),
			indicator: "orange",
		});
		return false;
	}
	return true;
};

const hv_get_preview_ui = (frm) => {
	if (frm._hv_preview_ui && frm._hv_preview_ui.wrapper?.length) {
		return frm._hv_preview_ui;
	}

	const section = $('<div class="form-section card-section hv-preview-section"></div>');
	const card = $('<div class="frappe-card hv-preview-card"></div>').appendTo(section);
	$('<div class="frappe-card-header"><div class="frappe-card-title">Live-Preview</div></div>').appendTo(card);

	const body = $('<div class="frappe-card-body"></div>').appendTo(card);
	const status = $('<div class="text-muted small hv-preview-status"></div>').appendTo(body);
	const frame = $(
		'<iframe class="hv-preview-frame" sandbox="allow-same-origin" style="width:100%;min-height:520px;border:1px solid var(--border-color);border-radius:6px;background:#fff;"></iframe>'
	).appendTo(body);

	// Nach Iterations-Grid einfügen, sonst ans Ende
	const grid_wrapper = frm.fields_dict?.iteration_objekte?.grid?.wrapper;
	if (grid_wrapper && grid_wrapper.length) {
		section.insertAfter(grid_wrapper.closest(".form-section"));
	} else {
		section.appendTo(frm.layout.wrapper);
	}

	frm._hv_preview_ui = { wrapper: section, body, status, frame };
	return frm._hv_preview_ui;
};

const hv_set_preview_message = (frm, message, tone = "muted") => {
	const ui = hv_get_preview_ui(frm);
	ui.status
		.removeClass("text-muted text-danger")
		.addClass(tone === "danger" ? "text-danger" : "text-muted")
		.text(message || "");
	ui.frame.attr("srcdoc", "");
};

const hv_scrub = (value) => {
	if (!value) return "";
	if (frappe.model && typeof frappe.model.scrub === "function") {
		return frappe.model.scrub(value);
	}
	return String(value).toLowerCase().replace(/\s+/g, "_");
};

const hv_parse_variable_values = (raw) => {
	if (!raw) return {};
	try {
		const data = typeof raw === "string" ? JSON.parse(raw) : raw;
		const result = {};
		if (data && typeof data === "object") {
			Object.entries(data).forEach(([key, value]) => {
				if (value && typeof value === "object") {
					result[key] = {
						value: value.value ?? "",
						path: value.path ?? "",
					};
				} else {
					result[key] = { value, path: "" };
				}
			});
		}
		return result;
	} catch (e) {
		return {};
	}
};

const hv_escape_html = (value) => {
	if (frappe?.utils && typeof frappe.utils.escape_html === "function") {
		return frappe.utils.escape_html(value);
	}
	const div = document.createElement("div");
	div.innerText = value == null ? "" : String(value);
	return div.innerHTML;
};

const hv_format_assignment_value = (value) => {
	if (!value || value.is_empty) {
		return __("nicht belegt");
	}
	const display = value.display || "";
	if (display) {
		return display;
	}
	if (value.doctype && value.name) {
		return `${value.doctype}: ${value.name}`;
	}
	if (value.count) {
		return `${value.count} ${__("Einträge")}`;
	}
	return __("nicht belegt");
};

const hv_render_preview = frappe.utils.debounce((frm) => {
	const ui = hv_get_preview_ui(frm);

	if (!frm.doc.vorlage) {
		hv_set_preview_message(frm, __("Bitte wähle eine Vorlage."), "muted");
		return;
	}
	if (!frm.doc.iteration_objekte || !frm.doc.iteration_objekte.length) {
		hv_set_preview_message(frm, __("Bitte fügen Sie Iterations-Objekte hinzu."), "muted");
		return;
	}

	ui.status.removeClass("text-danger").addClass("text-muted").text(__("Lade Vorschau …"));

frappe
		.call({
			method: "hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf.render_preview",
			args: { doc: frm.doc },
			quiet: true,
		})
		.then((r) => {
			const html = r?.message?.html;
			if (!html) {
				hv_set_preview_message(frm, __("Kein Inhalt zum Anzeigen."), "muted");
				return;
			}
			ui.status.text("");
			// iframe nutzen, damit Styles der Vorschau isoliert bleiben
			ui.frame.attr("srcdoc", html);
		})
		.catch((err) => {
			let msg = err?.message || __("Fehler beim Laden der Vorschau.");
			try {
				const server = err?._server_messages ? JSON.parse(err._server_messages || "[]") : [];
				if (Array.isArray(server) && server.length) {
					msg = server.join("\n");
				}
			} catch (e) {
				// ignore parse errors
			}
			hv_set_preview_message(frm, msg, "danger");
		});
}, 700);

const hv_trigger_preview = (frm) => {
	hv_render_preview(frm);
};

const hv_render_variable_input = (valueType, key, rowname, currentValue) => {
	const rowAttr = rowname ? ` data-row="${frappe.utils.escape_html(rowname)}"` : "";
	const keyAttr = frappe.utils.escape_html(key);
	if (valueType === "Zahl") {
		const val = currentValue !== undefined && currentValue !== null ? String(currentValue) : "";
		return `<input type="number" step="any" class="form-control" value="${frappe.utils.escape_html(
			val
		)}" data-hv-template-var data-key="${keyAttr}"${rowAttr} data-type="Zahl" />`;
	}
	if (valueType === "Bool") {
		const selected = currentValue === true ? "Ja" : currentValue === false ? "Nein" : "";
		return `
			<select class="form-control" data-hv-template-var data-key="${keyAttr}"${rowAttr} data-type="Bool">
				<option value=""></option>
				<option value="Ja"${selected === "Ja" ? " selected" : ""}>${__("Ja")}</option>
				<option value="Nein"${selected === "Nein" ? " selected" : ""}>${__("Nein")}</option>
			</select>
		`;
	}
	if (valueType === "Datum") {
		const val = currentValue !== undefined && currentValue !== null ? String(currentValue) : "";
		return `<input type="date" class="form-control" value="${frappe.utils.escape_html(
			val
		)}" data-hv-template-var data-key="${keyAttr}"${rowAttr} data-type="Datum" />`;
	}
	const val = currentValue !== undefined && currentValue !== null ? String(currentValue) : "";
	return `<input type="text" class="form-control" value="${frappe.utils.escape_html(
		val
	)}" data-hv-template-var data-key="${keyAttr}"${rowAttr} data-type="String" />`;
};

const hv_parse_typed_value = (type, raw) => {
	const text = String(raw ?? "").trim();
	if (type === "Zahl") {
		if (text === "") return null;
		const numberVal = Number(text);
		return Number.isNaN(numberVal) ? null : numberVal;
	}
	if (type === "Bool") {
		const full = String(raw ?? "");
		if (full === "Ja") return true;
		if (full === "Nein") return false;
		return null;
	}
	return text || null;
};

const hv_render_template_variables_table = (frm, requirements) => {
	const wrapper = frm.get_field("vorlagen_variablen_html")?.wrapper;
	if (!wrapper) return;

	const variables = (requirements?.template_variables || []).filter((v) =>
		["String", "Zahl", "Bool", "Datum", "Text"].includes((v.variable_type || "String").trim())
	);
	const iterationRows = (frm.doc.iteration_objekte || []).filter((r) => r.objekt);
	const hasVariables = Boolean(variables.length);
	frm.toggle_display("vorlagen_variablen_section", hasVariables);
	frm.toggle_display("vorlagen_variablen_html", hasVariables);
	if (!hasVariables) {
		$(wrapper).empty();
		return;
	}

	if (!iterationRows.length) {
		$(wrapper).empty().append(
			`<div class="text-muted small">${__(
				"Bitte zuerst Iterations-Objekte hinzufügen, um Variablenwerte pro Objekt zu setzen."
			)}</div>`
		);
		return;
	}

	const defaults = hv_parse_variable_values(requirements?.template_variable_defaults);
	const durchlaufMapping = hv_parse_variable_values(frm.doc.variablen_werte);

	const header = variables
		.map(
			(variable) =>
				`<th>${frappe.utils.escape_html(
					variable.label || variable.variable || variable.key || ""
				)}</th>`
		)
		.join("");

	const table = $(`
		<div class="table-responsive">
			<table class="table table-bordered table-sm">
				<thead>
					<tr>
						<th>${__("Iterations-Objekt")}</th>
						${header}
					</tr>
				</thead>
				<tbody></tbody>
			</table>
		</div>
	`);
	const tbody = table.find("tbody");

	iterationRows.forEach((iterRow) => {
		const rowMapping = hv_parse_variable_values(iterRow.variablen_werte);
		const cells = variables
			.map((variable) => {
				const rawKey = variable.variable || variable.label || "";
				const key = variable.key || hv_scrub(rawKey);
				const valueType = (variable.variable_type || "String").trim() || "String";
				const rowEntry = rowMapping[key] || {};
				const fallbackEntry = durchlaufMapping[key] || defaults[key] || {};
				const rowValue = rowEntry.value;
				const hasRowValue = rowValue !== undefined && rowValue !== null && rowValue !== "";
				const input = hv_render_variable_input(valueType, key, iterRow.name, rowValue);
				const fallbackValue = fallbackEntry.value;
				const showFallback =
					!hasRowValue &&
					fallbackValue !== undefined &&
					fallbackValue !== null &&
					fallbackValue !== "";
				const hint = showFallback
					? `<div class="text-muted small">${__("Default: {0}", [
							frappe.utils.escape_html(String(fallbackValue)),
					  ])}</div>`
					: "";
				return `<td><div>${input}</div>${hint}</td>`;
			})
			.join("");

		const label = frappe.utils.escape_html(
			iterRow.objekt || iterRow.name || __("Neues Objekt")
		);
		tbody.append(`<tr><td>${label}</td>${cells}</tr>`);
	});

	$(wrapper).empty().append(table);

	$(wrapper)
		.off("change.hvTemplateVars")
		.on("change.hvTemplateVars", "[data-hv-template-var]", (event) => {
			const $el = $(event.currentTarget);
			const key = $el.data("key");
			const type = $el.data("type");
			const rowname = $el.data("row");
			if (!rowname) return;

			const iterRow = (frm.doc.iteration_objekte || []).find((r) => r.name === rowname);
			if (!iterRow) return;

			const mapping = hv_parse_variable_values(iterRow.variablen_werte);
			const parsed = hv_parse_typed_value(type, $el.val());
			if (parsed === null) {
				delete mapping[key];
			} else {
				mapping[key] = { value: parsed, path: "" };
			}

			frappe.model.set_value(
				"Serienbrief Iterationsobjekt",
				rowname,
				"variablen_werte",
				Object.keys(mapping).length ? JSON.stringify(mapping) : ""
			);
			hv_trigger_preview(frm);
		});
};

const trigger_serienbrief_pdf = (frm) => {
	if (!hv_ensure_iteration_objects(frm)) {
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("PDF erzeugen"),
		fields: [
			{
				fieldname: "print_format",
				fieldtype: "Link",
				label: __("Print Format"),
				options: "Print Format",
				reqd: 1,
				default: "Serienbrief Dokument",
				description: __("Jedes Serienbrief Dokument wird mit diesem Print Format gedruckt und danach gemergt."),
				get_query: () => ({
					filters: {
						doc_type: "Serienbrief Dokument",
						disabled: 0,
					},
				}),
			},
		],
		primary_action_label: __("PDF erzeugen"),
		primary_action(values) {
			const printFormat = (values.print_format || "").trim();
			if (!printFormat) {
				return;
			}
			dialog.hide();
			frappe.call({
				method: "hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf.generate_pdf",
				args: { docname: frm.doc.name, print_format: printFormat },
				freeze: true,
				freeze_message: __("PDF wird erzeugt …"),
			}).then((r) => {
				if (r.message) {
					window.open(r.message);
				}
			});
		},
	});

	dialog.show();
};

const hv_open_assignments_overview = async (frm) => {
	if (!frm.doc.vorlage) {
		frappe.msgprint({
			message: __("Bitte wähle zuerst eine Vorlage."),
			indicator: "orange",
		});
		return;
	}
	if (!frm.doc.iteration_objekte || !frm.doc.iteration_objekte.length) {
		frappe.msgprint({
			message: __("Bitte fügen Sie Iterations-Objekte hinzu."),
			indicator: "orange",
		});
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Belegungen"),
		size: "large",
		fields: [{ fieldname: "overview", fieldtype: "HTML" }],
		primary_action_label: __("Schließen"),
		primary_action: () => dialog.hide(),
	});
	const wrapper = $(dialog.get_field("overview").wrapper).empty();
	wrapper.html(`<div class="text-muted small">${__("Lade Belegungen …")}</div>`);
	dialog.show();

	let data = {};
	try {
		const r = await frappe.call({
			method: "hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf.get_serienbrief_assignments",
			args: { doc: frm.doc },
			quiet: true,
		});
		data = r.message || {};
	} catch (e) {
		wrapper.html(`<div class="text-danger small">${__("Fehler beim Laden der Belegungen.")}</div>`);
		return;
	}

	const rows = data.rows || [];
	if (!rows.length) {
		wrapper.html(`<div class="text-muted small">${__("Keine Belegungen gefunden.")}</div>`);
		return;
	}

	const render_requirements = (items) => {
		if (!items || !items.length) {
			return `<div class="text-muted small mb-2">${__("Keine Felder.")}</div>`;
		}
		return `<ul class="list-unstyled mb-2">${items
			.map((item) => {
				const label = hv_escape_html(item.label || item.fieldname || "");
				const valueText = hv_escape_html(hv_format_assignment_value(item.value));
				const meta = [];
				if (item.path) meta.push(`${__("Pfad")}: ${item.path}`);
				if (item.source) meta.push(item.source);
				if (item.resolved_via_default) meta.push(__("Standardpfad"));
				const metaHtml = meta.length
					? `<div class="text-muted small">${meta.map(hv_escape_html).join(" · ")}</div>`
					: "";
				return `<li class="mb-1"><div><strong>${label}</strong>: ${valueText}</div>${metaHtml}</li>`;
			})
			.join("")}</ul>`;
	};

	const render_variables = (items) => {
		if (!items || !items.length) {
			return `<div class="text-muted small mb-2">${__("Keine Variablen.")}</div>`;
		}
		return `<ul class="list-unstyled mb-2">${items
			.map((item) => {
				const label = hv_escape_html(item.label || item.key || "");
				const valueText = hv_escape_html(hv_format_assignment_value(item.value));
				return `<li class="mb-1"><div><strong>${label}</strong>: ${valueText}</div></li>`;
			})
			.join("")}</ul>`;
	};

	const sections = rows.map((row) => {
		const iterationLabel = row?.iteration?.doctype && row?.iteration?.name
			? `${row.iteration.doctype}: ${row.iteration.name}`
			: "";
		const header = `${__("Empfänger")} ${row.index || ""}`.trim();
		const label = row.label ? ` — ${hv_escape_html(row.label)}` : "";
		const iterationMeta = iterationLabel
			? `<div class="text-muted small">${hv_escape_html(iterationLabel)}</div>`
			: "";

		const blockSections = (row.blocks || [])
			.map((block) => {
				const title = block.block_title || block.block || block.rowname || __("Textbaustein");
				return `
					<div class="mt-3 fw-semibold">${__("Textbaustein")}: ${hv_escape_html(title)}</div>
					${render_requirements(block.requirements || [])}
					${render_variables(block.variables || [])}
				`;
			})
			.join("");

		return `
			<div class="mb-4">
				<div class="fw-semibold">${hv_escape_html(header)}${label}</div>
				${iterationMeta}
				<div class="mt-2 fw-semibold">${__("Vorlage")}</div>
				${render_requirements(row.template_fields || [])}
				${render_variables(row.template_variables || [])}
				${blockSections}
			</div>
		`;
	});

	wrapper.html(sections.join(""));
};

const trigger_serienbrief_html = (frm) => {
	if (!hv_ensure_iteration_objects(frm)) {
		return;
	}

	frappe.call({
		method: "hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf.generate_html",
		args: { docname: frm.doc.name },
		freeze: true,
		freeze_message: __("HTML wird erzeugt …"),
	}).then((r) => {
		if (r.message) {
			window.open(r.message);
		}
	});
};

const hv_format_requirement = (req) => {
	const label = req.label || req.fieldname;
	const parts = [];
	if (req.source) {
		parts.push(req.source);
	}
	if (req.path) {
		parts.push(req.path);
	}
	if (req.resolved_via_default) {
		parts.push(__("Standardpfad"));
	}
	if (!parts.length) {
		return label;
	}
	return `${label} (${parts.join(" · ")})`;
};

const hv_set_iteration_options = (frm) => {
	const grid = frm.get_field("iteration_objekte")?.grid;
	if (!grid) return;
	const iterationDoctype = frm.doc.iteration_doctype || "";

	// vorhandene Zeilen mitziehen, damit Dynamic Link ein Doctype hat
	if (Array.isArray(frm.doc.iteration_objekte)) {
		let touched = false;
		frm.doc.iteration_objekte.forEach((row) => {
			if (iterationDoctype && row.iteration_doctype !== iterationDoctype) {
				row.iteration_doctype = iterationDoctype;
				touched = true;
			}
		});
		if (touched) {
			frm.refresh_field("iteration_objekte");
		}
	}

	grid.refresh();
};

const hv_add_iteration_rows = (frm, names) => {
	if (!frm.doc.iteration_doctype) {
		frappe.msgprint({
			message: __("Bitte wählen Sie zuerst einen Iterations-Doctype."),
			indicator: "orange",
		});
		return;
	}
	if (!Array.isArray(names) || !names.length) return;
	const existing = new Set((frm.doc.iteration_objekte || []).map((r) => r.objekt));
	let changed = false;
	names.forEach((name) => {
		if (existing.has(name)) return;
		const row = frm.add_child("iteration_objekte");
		row.iteration_doctype = frm.doc.iteration_doctype;
		row.objekt = name;
		existing.add(name);
		changed = true;
	});
	if (changed) {
		frm.refresh_field("iteration_objekte");
		hv_trigger_preview(frm);
	}
};

const hv_open_iteration_picker = (frm) => {
	if (!frm.doc.iteration_doctype) {
		frappe.msgprint({
			message: __("Bitte wählen Sie zuerst einen Iterations-Doctype."),
			indicator: "orange",
		});
		return;
	}

	hv_set_iteration_options(frm);

	let dialog;
	const handleSelection = (selected) => {
		const names = (selected || []).map((r) => r.name || r);
		if ((frm.doc.iteration_objekte || []).length) {
			frm.clear_table("iteration_objekte");
			frm.refresh_field("iteration_objekte");
		}
		hv_add_iteration_rows(frm, names);
		dialog?.dialog.hide();
	};

	dialog = new frappe.ui.form.MultiSelectDialog({
		doctype: frm.doc.iteration_doctype,
		setters: {},
		add_filters_group: 1,
		get_query() {
			return {};
		},
		primary_action_label: __("Übernehmen"),
		primary_action: handleSelection,
		action: handleSelection,
	});

	// Rückfall für ältere Frappe-Versionen: dialog.dialog existiert nicht immer
	if (dialog.dialog) {
		dialog.dialog.set_secondary_action_label(__("Abbrechen"));
		dialog.dialog.set_secondary_action(() => dialog.dialog.hide());
	} else if (dialog.set_secondary_action_label) {
		dialog.set_secondary_action_label(__("Abbrechen"));
		dialog.set_secondary_action(() => dialog.hide());
	}
};

const hv_apply_template_requirements = (frm, requirements) => {
	frm.set_intro("");

	const missing = requirements?.missing_fields || [];
	if (!missing.length) {
		frm._hv_missing_warned_for = null;
		return;
	}

	if (frm._hv_missing_warned_for === frm.doc.vorlage) {
		return;
	}

	frm._hv_missing_warned_for = frm.doc.vorlage;
	const missingLabels = missing.map((item) => item.label || item.fieldname).join(", ");
	frappe.msgprint({
		message: __("Es fehlen benötigte Felder: {0}", [missingLabels]),
		title: __("Benötigte Felder fehlen"),
		indicator: "orange",
	});
};

const hv_load_template_requirements = (frm) => {
	if (!frm.doc.vorlage) {
		const empty = { required_fields: [], missing_fields: [] };
		hv_apply_template_requirements(frm, empty);
		hv_render_template_variables_table(frm, empty);
		return;
	}

	frappe
		.call({
			method: "hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf.get_template_requirements",
			args: { template: frm.doc.vorlage },
		})
		.then((r) => {
			const requirements = r.message || {};
			hv_apply_template_requirements(frm, requirements);
			hv_render_template_variables_table(frm, requirements);
		})
		.catch(() => {
			const empty = { required_fields: [], missing_fields: [] };
			hv_apply_template_requirements(frm, empty);
			hv_render_template_variables_table(frm, empty);
		});
};

const hv_apply_template_defaults = (frm) => {
	if (!frm.doc.vorlage) {
		return Promise.resolve();
	}

	return frappe.db
		.get_value("Serienbrief Vorlage", frm.doc.vorlage, ["haupt_verteil_objekt", "kategorie"])
		.then((r) => {
			const data = r?.message || {};
			const tasks = [];
			if (data.haupt_verteil_objekt && !frm.doc.iteration_doctype) {
				tasks.push(frm.set_value("iteration_doctype", data.haupt_verteil_objekt));
			}
			if (data.kategorie && !frm.doc.kategorie) {
				tasks.push(frm.set_value("kategorie", data.kategorie));
			}
			return Promise.all(tasks);
		});
};

const hv_apply_incoming_route_options = (frm) => {
	const opts = frappe.route_options || {};
	const template = opts.hv_serienbrief_template;
	if (!template) {
		return;
	}

	const incoming = {
		vorlage: template,
		title: opts.hv_serienbrief_title,
		kategorie: opts.hv_serienbrief_kategorie,
		iteration_doctype: opts.hv_serienbrief_iteration_doctype,
	};

	delete frappe.route_options.hv_serienbrief_template;
	delete frappe.route_options.hv_serienbrief_title;
	delete frappe.route_options.hv_serienbrief_kategorie;
	delete frappe.route_options.hv_serienbrief_iteration_doctype;

	const apply = () => {
		const hasIterationObjects = (frm.doc.iteration_objekte || []).some((r) => r.objekt);
		if (hasIterationObjects) {
			frm.clear_table("iteration_objekte");
			frm.refresh_field("iteration_objekte");
		}
		if (incoming.vorlage) frm.set_value("vorlage", incoming.vorlage);
		if (incoming.title && !frm.doc.title) frm.set_value("title", incoming.title);
		if (incoming.kategorie && !frm.doc.kategorie) frm.set_value("kategorie", incoming.kategorie);
		if (incoming.iteration_doctype && !frm.doc.iteration_doctype) {
			frm.set_value("iteration_doctype", incoming.iteration_doctype);
		}
	};

	apply();
};

frappe.ui.form.on("Serienbrief Durchlauf", {
	refresh(frm) {
		hv_apply_incoming_route_options(frm);

		if (!frm.is_new()) {
			frm.add_custom_button(__("PDF erzeugen"), () => trigger_serienbrief_pdf(frm));
			frm.add_custom_button(__("HTML exportieren"), () => trigger_serienbrief_html(frm));
			frm.add_custom_button(__("Dokumente öffnen"), () => {
				frappe.route_options = { durchlauf: frm.doc.name };
				frappe.set_route("List", "Serienbrief Dokument");
			});
			if (cint(frm.doc.docstatus) === 0) {
				frm.add_custom_button(__("Dokumente neu erzeugen"), async () => {
					const confirmed = await new Promise((resolve) => {
						frappe.confirm(
							__(
								"Alle bestehenden Serienbrief Dokumente für diesen Durchlauf werden gelöscht und neu erzeugt. Fortfahren?"
							),
							() => resolve(true),
							() => resolve(false)
						);
					});
					if (!confirmed) return;
					await frappe.call({
						method: "hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf.regenerate_dokumente",
						args: { docname: frm.doc.name, submit_documents: 0 },
						freeze: true,
						freeze_message: __("Erzeuge Dokumente …"),
					});
					frappe.show_alert({ message: __("Dokumente wurden neu erzeugt."), indicator: "green" });
				});
			}
		}
		frm.add_custom_button(__("Belegungen anzeigen"), () => hv_open_assignments_overview(frm));

		frm.set_df_property("variablen_werte", "hidden", 1);
		frm.set_df_property("iteration_objekte", "cannot_add_rows", true);
		frm.set_df_property("iteration_objekte", "cannot_delete_rows", true);

		hv_apply_template_defaults(frm);

		hv_set_iteration_options(frm);

		frm.add_custom_button(__("Objekte auswählen"), () => hv_open_iteration_picker(frm), __("Iteration"));

		hv_load_template_requirements(frm);

		hv_trigger_preview(frm);
	},
	vorlage(frm) {
		hv_load_template_requirements(frm);
		hv_apply_template_defaults(frm).then(() => {
			if (!frm.doc.vorlage || !frm.doc.iteration_doctype) return;
			const hasRows = (frm.doc.iteration_objekte || []).some((r) => r.objekt);
			if (!hasRows) {
				hv_open_iteration_picker(frm);
			}
		});
		hv_trigger_preview(frm);
	},
	iteration_doctype(frm) {
		hv_set_iteration_options(frm);
		hv_trigger_preview(frm);
	},
	date(frm) {
		hv_trigger_preview(frm);
	},
	iteration_objekte_add(frm) {
		hv_load_template_requirements(frm);
		hv_trigger_preview(frm);
	},
	iteration_objekte_remove(frm) {
		hv_load_template_requirements(frm);
		hv_trigger_preview(frm);
	},
});

frappe.ui.form.on("Serienbrief Iterationsobjekt", {
	objekt(frm) {
		hv_load_template_requirements(frm);
		hv_trigger_preview(frm);
	},
});
