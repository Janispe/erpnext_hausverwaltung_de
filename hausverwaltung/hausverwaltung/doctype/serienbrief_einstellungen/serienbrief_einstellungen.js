const hv_parse_mapping = (raw) => {
	if (!raw) return {};
	try {
		const data = JSON.parse(raw);
		return typeof data === "object" && data ? data : {};
	} catch (e) {
		return {};
	}
};

const hv_load_meta = (doctype) =>
	new Promise((resolve) => {
		if (!doctype) {
			resolve(null);
			return;
		}
		frappe.model.with_doctype(doctype, () => resolve(frappe.get_meta(doctype)));
	});

const hv_get_start_nodes_for_startobjekt = async (startobjekt) => {
	if (!startobjekt) {
		return [];
	}

	const nodes = [
		{
			fieldname: "iteration_doc",
			doctype: startobjekt,
			label: startobjekt,
			path: ["iteration_doc"],
		},
	];

	const meta = await hv_load_meta(startobjekt);
	(meta?.fields || []).forEach((df) => {
		if (df.fieldtype === "Link" && df.options) {
			nodes.push({
				fieldname: df.fieldname,
				doctype: df.options,
				label: df.label || df.fieldname,
				path: [df.fieldname],
			});
		}
		if (df.fieldtype === "Table" && df.options) {
			nodes.push({
				fieldname: df.fieldname,
				doctype: df.options,
				label: df.label || df.fieldname,
				path: [df.fieldname],
			});
		}
	});

	return nodes;
};

const hv_find_paths = async (startNodes, targetDoctype, maxDepth = 4) => {
	if (!startNodes || !startNodes.length || !targetDoctype) {
		return [];
	}

	const queue = startNodes.map((node) => ({ path: node.path, doctype: node.doctype }));
	const results = [];
	const visitedKey = (doctype, path) => `${doctype}::${(path || []).join(".")}`;
	const seen = new Set();

	while (queue.length) {
		const current = queue.shift();
		const key = visitedKey(current.doctype, current.path);
		if (seen.has(key)) {
			continue;
		}
		seen.add(key);

		if (current.doctype === targetDoctype) {
			results.push(current.path.join("."));
			continue;
		}

		if ((current.path || []).length >= maxDepth) {
			continue;
		}

		const meta = await hv_load_meta(current.doctype);
		if (!meta || !meta.fields) {
			continue;
		}

		meta.fields.forEach((df) => {
			if (df.fieldtype === "Link" && df.options) {
				const nextPath = [...current.path, df.fieldname];
				queue.push({ path: nextPath, doctype: df.options });
				return;
			}
			if (df.fieldtype === "Table" && df.options) {
				const nextPath = [...current.path, df.fieldname];
				queue.push({ path: nextPath, doctype: df.options });
			}
		});
	}

	return results;
};

const hv_update_global_standardpfade_labels = (frm) => {
	let touched = false;
	(frm.doc.standardpfade || []).forEach((row) => {
		const mapping = hv_parse_mapping(row.pfad_zuordnung);
		const labels = Object.entries(mapping || {})
			.map(([key, path]) => `${key}: ${path}`)
			.join(", ");
		if (row.anforderungen !== labels) {
			frappe.model.set_value(row.doctype, row.name, "anforderungen", labels);
			touched = true;
		}
	});

	if (touched) {
		frm.refresh_field("standardpfade");
	}
};

const hv_open_global_path_dialog = (frm) => {
	let rows = [];
	let startNodes = [];

	const existingStart = (frm.doc.standardpfade || [])[0]?.startobjekt || "";
	const dialog = new frappe.ui.Dialog({
		title: __("Globale Standardpfade"),
		fields: [
			{
				fieldname: "startobjekt",
				fieldtype: "Link",
				label: __("Startobjekt (Iterations-Doctype)"),
				options: "DocType",
				reqd: 1,
				default: existingStart,
			},
			{
				fieldname: "paths",
				fieldtype: "HTML",
				label: __("Pfad Zuordnungen"),
			},
		],
		primary_action_label: __("Speichern"),
		async primary_action(values) {
			const startobjekt = values.startobjekt;
			if (!startobjekt) {
				frappe.msgprint({
					message: __("Bitte ein Startobjekt auswählen."),
					indicator: "orange",
				});
				return;
			}

			const newMapping = {};
			rows.forEach(({ getTarget, getPath }) => {
				const target = (getTarget() || "").trim();
				const path = (getPath() || "").trim();
				if (target && path) {
					newMapping[target] = path;
				}
			});

			let targetRow = (frm.doc.standardpfade || []).find((r) => r.startobjekt === startobjekt);
			if (!targetRow) {
				targetRow = frm.add_child("standardpfade");
				targetRow.startobjekt = startobjekt;
			}

			frappe.model.set_value(
				targetRow.doctype,
				targetRow.name,
				"pfad_zuordnung",
				Object.keys(newMapping).length ? JSON.stringify(newMapping) : ""
			);

			hv_update_global_standardpfade_labels(frm);
			frm.refresh_field("standardpfade");
			dialog.hide();
		},
	});

	const container = $(dialog.get_field("paths").wrapper).empty();

	const renderRows = async () => {
		const startobjekt = dialog.get_value("startobjekt");
		container.empty();
		rows = [];

		if (!startobjekt) {
			container.html(`<div class="text-muted small">${__("Bitte ein Startobjekt wählen.")}</div>`);
			return;
		}

		startNodes = await hv_get_start_nodes_for_startobjekt(startobjekt);
		const targetRow = (frm.doc.standardpfade || []).find((r) => r.startobjekt === startobjekt);
		const mapping = hv_parse_mapping(targetRow?.pfad_zuordnung);

		const addRow = (target = "", path = "") => {
			const rowDiv = $(`
				<div class="form-group mb-3">
					<div class="row gx-2 align-items-start">
						<div class="col-sm-4 mb-2 hv-target-holder"></div>
						<div class="col-sm-6 mb-2 d-flex gap-1">
							<input type="text" class="form-control hv-path" placeholder="${__("Pfad")}">
							<button type="button" class="btn btn-xs btn-secondary hv-pick">${__("Pfad wählen")}</button>
							<button type="button" class="btn btn-xs btn-default hv-remove">&times;</button>
						</div>
					</div>
				</div>
			`);

			container.append(rowDiv);
			const targetHolder = rowDiv.find(".hv-target-holder");
			const pathInput = rowDiv.find(".hv-path");
			const pickBtn = rowDiv.find(".hv-pick");
			const removeBtn = rowDiv.find(".hv-remove");

			const targetControl = frappe.ui.form.make_control({
				df: {
					fieldtype: "Link",
					options: "DocType",
					placeholder: __("Ziel-Doctype"),
				},
				parent: targetHolder.get(0),
				render_input: true,
			});
			targetControl.refresh_input && targetControl.refresh_input();
			targetControl.set_value && targetControl.set_value(target || "");

			pathInput.val(path || "");

			pickBtn.on("click", async () => {
				if (!startNodes.length) {
					frappe.msgprint({
						message: __("Keine Start-Pfade gefunden. Bitte Startobjekt prüfen."),
						indicator: "orange",
					});
					return;
				}

				const targetDoctype = (targetControl.get_value ? targetControl.get_value() : targetControl.value || "").trim();
				if (!targetDoctype) {
					frappe.msgprint({
						message: __("Bitte zuerst einen Ziel-Doctype eintragen."),
						indicator: "orange",
					});
					return;
				}

				pickBtn.prop("disabled", true).text(__("Lade Pfade ..."));
				const paths = await hv_find_paths(startNodes, targetDoctype, 4);
				pickBtn.prop("disabled", false).text(__("Pfad wählen"));

				if (!paths.length) {
					frappe.msgprint({
						message: __("Keine Pfade gefunden. Bitte manuell eintragen."),
						title: __("Keine Vorschläge"),
						indicator: "orange",
					});
					return;
				}

				const chooser = new frappe.ui.Dialog({
					title: __("Pfad auswählen"),
					fields: [
						{
							fieldname: "path",
							fieldtype: "Select",
							label: __("Pfad"),
							options: paths,
							default: pathInput.val() || paths[0],
						},
					],
					primary_action_label: __("Übernehmen"),
					primary_action(values) {
						pathInput.val(values.path || "");
						chooser.hide();
					},
				});
				chooser.show();
			});

			removeBtn.on("click", () => {
				rowDiv.remove();
				rows = rows.filter((r) => r !== rowObj);
			});

			const getPath = () => pathInput.val();
			const getTarget = () => (targetControl.get_value ? targetControl.get_value() : targetControl.value || "");
			const rowObj = { getTarget, getPath };
			rows.push(rowObj);
		};

		Object.entries(mapping || {}).forEach(([key, path]) => addRow(key, path));
		if (!Object.keys(mapping || {}).length) {
			addRow();
		}

		const addBtn = $(`
			<button type="button" class="btn btn-xs btn-outline-secondary mt-1">${__("Neue Zeile")}</button>
		`);
		container.append(addBtn);
		addBtn.on("click", () => addRow());
	};

	dialog.fields_dict.startobjekt.$input.on("change", () => renderRows());
	dialog.show();
	renderRows();
};

frappe.ui.form.on("Serienbrief Einstellungen", {
	refresh(frm) {
		hv_update_global_standardpfade_labels(frm);
		frm.add_custom_button(__("Globale Standardpfade bearbeiten"), () => hv_open_global_path_dialog(frm));
	},
	standardpfade_on_form_rendered(frm) {
		hv_update_global_standardpfade_labels(frm);
	},
});
