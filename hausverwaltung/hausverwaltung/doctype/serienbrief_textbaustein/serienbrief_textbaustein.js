const HV_BASE_PLACEHOLDERS = [
	{ label: __("Datum (formatiert)"), value: "{{ datum }}" },
	{ label: __("Datum (ISO)"), value: "{{ datum_iso }}" },
];

const HV_SERIENBRIEF_SNIPPETS = [
	{
		label: __("If/Else"),
		value: `{% if CONDITION %}\n\n{% else %}\n\n{% endif %}`,
	},
	{
		label: __("If mit == Vergleich"),
		value: `{% if CONDITION == "WERT" %}\n\n{% endif %}`,
	},
	{
		label: __("If mit and"),
		value: `{% if A and B %}\n\n{% endif %}`,
	},
	{
		label: __("If mit or"),
		value: `{% if A or B %}\n\n{% endif %}`,
	},
];

const hv_scrub = (value) => {
	if (!value) return "";
	if (frappe.model && typeof frappe.model.scrub === "function") {
		return frappe.model.scrub(value);
	}
	return String(value).toLowerCase().replace(/\s+/g, "_");
};

const hv_load_meta = (doctype) =>
	new Promise((resolve) => {
		if (!doctype) {
			resolve(null);
			return;
		}
		frappe.model.with_doctype(doctype, () => resolve(frappe.get_meta(doctype)));
	});

const hv_require_placeholder_picker = () =>
	new Promise((resolve) => {
		const assetPath = "/assets/hausverwaltung/js/serienbrief_placeholder_picker.js";

		const current = window.hausverwaltung?.serienbrief_placeholder_picker;
		if (current && typeof current.open_dialog === "function") {
			resolve(current);
			return;
		}

		const loadViaAsset = () =>
			new Promise((res, rej) => {
				const existing = document.querySelector(`script[data-hv-src="${assetPath}"]`);
				if (existing) {
					existing.addEventListener("load", () => res(), { once: true });
					existing.addEventListener("error", () => rej(new Error("asset load failed")), {
						once: true,
					});
					return;
				}

				const script = document.createElement("script");
				script.src = `${assetPath}?v=${Date.now()}`;
				script.async = true;
				script.dataset.hvSrc = assetPath;
				script.onload = () => res();
				script.onerror = () => rej(new Error("asset load failed"));
				document.head.appendChild(script);
			});

		const loadViaBackend = () =>
			frappe
				.call({
					method: "hausverwaltung.hausverwaltung.utils.serienbrief_placeholder_picker.get_serienbrief_placeholder_picker_js",
					quiet: true,
				})
				.then((r) => {
					const source = r.message || "";
					if (typeof source === "string" && source.trim()) {
						Function(source)();
					}
				});

		loadViaAsset()
			.catch(() => loadViaBackend())
			.finally(() => resolve(window.hausverwaltung?.serienbrief_placeholder_picker));
	});

const hv_require_quill_placeholders = () =>
	new Promise((resolve) => {
		const assetPath = "/assets/hausverwaltung/js/serienbrief_quill_placeholders.js";

		const current = window.hausverwaltung?.serienbrief_quill_placeholders;
		if (current && typeof current.insert_into_quill === "function") {
			resolve(current);
			return;
		}

		const loadViaAsset = () =>
			new Promise((res, rej) => {
				const existing = document.querySelector(`script[data-hv-src="${assetPath}"]`);
				if (existing) {
					existing.addEventListener("load", () => res(), { once: true });
					existing.addEventListener("error", () => rej(new Error("asset load failed")), {
						once: true,
					});
					return;
				}

				const script = document.createElement("script");
				script.src = `${assetPath}?v=${Date.now()}`;
				script.async = true;
				script.dataset.hvSrc = assetPath;
				script.onload = () => res();
				script.onerror = () => rej(new Error("asset load failed"));
				document.head.appendChild(script);
			});

		const loadViaBackend = () =>
			frappe
				.call({
					method: "hausverwaltung.hausverwaltung.utils.serienbrief_quill_placeholders.get_serienbrief_quill_placeholders_js",
					quiet: true,
				})
				.then((r) => {
					const source = r.message || "";
					if (typeof source === "string" && source.trim()) {
						Function(source)();
					}
				});

		loadViaAsset()
			.catch(() => loadViaBackend())
			.finally(() => resolve(window.hausverwaltung?.serienbrief_quill_placeholders));
	});

const hv_parse_mapping = (raw) => {
	if (!raw) return {};
	try {
		const data = JSON.parse(raw);
		return typeof data === "object" && data ? data : {};
	} catch (e) {
		return {};
	}
};

const hv_placeholder_to_value_path = (placeholder) => {
	const raw = (placeholder == null ? "" : String(placeholder)).trim();
	if (!raw) {
		return null;
	}

	const match = raw.match(/^\{\{\s*([^{}]+?)\s*\}\}$/);
	if (!match) {
		return null;
	}

	const expr = (match[1] || "").trim();
	if (!expr || /[%()|]/.test(expr)) {
		return null;
	}

	const normalized = expr.replace(/\[(\d+)\]/g, ".$1").trim();
	if (!normalized || normalized.startsWith(".") || normalized.endsWith(".")) {
		return null;
	}

	const listMatches = normalized.match(/\[\]/g) || [];
	if (listMatches.length > 1) {
		return null;
	}
	if (listMatches.length === 1 && !normalized.endsWith("[]")) {
		return null;
	}

	const normalizedForCheck = normalized.replace(/\[\]/g, "");
	if (!normalizedForCheck || !/^[A-Za-z0-9_.]+$/.test(normalizedForCheck)) {
		return null;
	}

	return normalized;
};

const hv_is_dynamic_index_placeholder = (placeholder) =>
	typeof placeholder === "string" && placeholder.includes("[__INDEX__]");

const hv_resolve_dynamic_index_placeholder = (placeholder) =>
	new Promise((resolve) => {
		let settled = false;
		const finish = (value) => {
			if (settled) {
				return;
			}
			settled = true;
			resolve(value);
		};

		const dialog = new frappe.ui.Dialog({
			title: __("Eintrag auswählen"),
			fields: [
				{
					fieldname: "entry_number",
					fieldtype: "Int",
					label: __("Nummer"),
					reqd: 1,
					description: __("1 = erster Eintrag, 2 = zweiter Eintrag"),
				},
			],
			primary_action_label: __("Übernehmen"),
			primary_action(values) {
				const input = values.entry_number;
				const parsed = Number.parseInt(String(input), 10);
				if (!Number.isInteger(parsed) || parsed < 1 || String(parsed) !== String(input).trim()) {
					frappe.msgprint({
						message: __("Bitte eine ganze Zahl ab 1 eingeben."),
						indicator: "orange",
					});
					return;
				}

				const index = parsed - 1;
				finish(String(placeholder).replaceAll("[__INDEX__]", `[${index}]`));
				dialog.hide();
			},
		});

		const finalize = () => finish(null);
		dialog.onhide = finalize;
		dialog.on_hide = finalize;
		window.setTimeout(() => dialog.show(), 0);
	});

const hv_open_pdf_value_path_picker = async (frm, on_select) => {
	const picker = await hv_require_placeholder_picker();
	if (!picker || typeof picker.open_dialog !== "function") {
		frappe.msgprint({
			message: __(
				"Platzhalter-Dialog konnte nicht geladen werden. Falls /assets/* nicht erreichbar ist, muss der Server-Fallback verfügbar sein (get_serienbrief_placeholder_picker_js)."
			),
			indicator: "red",
		});
		return;
	}

	let pickerApi = null;
	pickerApi = picker.open_dialog({
		title: __("Wert-Pfad auswählen"),
		load_groups: () => hv_get_placeholder_groups(frm),
		on_insert: async (placeholder) => {
			const applyPlaceholder = (effectivePlaceholder) => {
				const path = hv_placeholder_to_value_path(effectivePlaceholder);
				if (!path) {
					frappe.msgprint({
						message: __("Nur direkte Feld-Platzhalter können als Wert-Pfad verwendet werden."),
						indicator: "orange",
					});
					return;
				}
				if (typeof on_select === "function") {
					on_select(path);
				}
			};

			if (hv_is_dynamic_index_placeholder(placeholder)) {
				pickerApi?.dialog?.hide();
				window.setTimeout(async () => {
					const effectivePlaceholder = await hv_resolve_dynamic_index_placeholder(placeholder);
					if (!effectivePlaceholder) {
						return;
					}
					applyPlaceholder(effectivePlaceholder);
				}, 0);
				return;
			}

			applyPlaceholder(placeholder);
			pickerApi?.dialog?.hide();
		},
		on_setup: ({ dialog, refresh_groups }) => {
			const addBtn = $(
				`<button type="button" class="btn btn-sm btn-secondary me-2">${__(
					"Referenzvariable hinzufügen"
				)}</button>`
			);
			addBtn.on("click", () => {
				hv_add_reference_doctype(frm, async (doc) => {
					await refresh_groups(doc);
					hv_render_placeholder_panels(frm);
					window.setTimeout(() => hv_attach_pdf_mapping_path_pickers(frm), 0);
				});
			});
			dialog.get_primary_btn().before(addBtn);
		},
	});
};

const hv_sync_pdf_field_mappings = (frm, { freeze = true, showAlert = true } = {}) => {
	const contentType = (frm.doc.content_type || "").trim();
	const fileUrl = (frm.doc.pdf_file || "").trim();

	if (contentType !== "PDF Formular" || !fileUrl) {
		return Promise.resolve(false);
	}

	const syncKey = `${frm.doc.name || "__new__"}::${fileUrl}`;
	if (frm._hv_pdf_field_sync_key === syncKey && frm._hv_pdf_field_sync_promise) {
		return frm._hv_pdf_field_sync_promise;
	}

	const request = frappe
		.call({
			method: "hausverwaltung.hausverwaltung.doctype.serienbrief_textbaustein.serienbrief_textbaustein.get_pdf_form_fields",
			args: { docname: frm.doc.name, pdf_file: fileUrl },
			freeze,
			freeze_message: freeze ? __("Lese PDF-Felder …") : undefined,
		})
		.then((r) => {
			const names = Array.isArray(r.message) ? r.message.filter(Boolean) : [];
			const existingRows = Array.isArray(frm.doc.pdf_field_mappings) ? frm.doc.pdf_field_mappings : [];
			const existingByName = new Map();

			existingRows.forEach((row) => {
				const fieldName = (row.pdf_field_name || "").trim();
				if (fieldName && !existingByName.has(fieldName)) {
					existingByName.set(fieldName, row);
				}
			});

			const previousNames = existingRows
				.map((row) => (row.pdf_field_name || "").trim())
				.filter(Boolean);
			const unchanged =
				previousNames.length === names.length &&
				previousNames.every((fieldName, idx) => fieldName === names[idx]);

			if (!unchanged) {
				if (typeof frappe.model?.clear_table === "function") {
					frappe.model.clear_table(frm.doc, "pdf_field_mappings");
				} else {
					frm.doc.pdf_field_mappings = [];
				}

				names.forEach((fieldName) => {
					const existing = existingByName.get(fieldName);
					const row = frm.add_child("pdf_field_mappings");
					row.pdf_field_name = fieldName;
					row.value_path = existing?.value_path || "";
					row.fallback_value = existing?.fallback_value || "";
					row.required = existing?.required || 0;
					row.value_type = existing?.value_type || "String";
				});
				frm.refresh_field("pdf_field_mappings");
				window.setTimeout(() => hv_attach_pdf_mapping_path_pickers(frm), 0);
			}

			if (showAlert) {
				const added = names.filter((fieldName) => !previousNames.includes(fieldName)).length;
				const removed = previousNames.filter((fieldName) => !names.includes(fieldName)).length;
				if (!names.length) {
					frappe.show_alert({
						message: __("Keine Formularfelder gefunden."),
						indicator: "orange",
					});
				} else {
					frappe.show_alert({
						message: __("PDF-Felder geladen: {0}, neu: {1}, entfernt: {2}", [
							names.length,
							added,
							removed,
						]),
						indicator: "green",
					});
				}
			}

			frm._hv_pdf_field_autoloaded_for = fileUrl;
			return true;
		})
		.finally(() => {
			if (frm._hv_pdf_field_sync_key === syncKey) {
				frm._hv_pdf_field_sync_key = null;
				frm._hv_pdf_field_sync_promise = null;
			}
		});

	frm._hv_pdf_field_sync_key = syncKey;
	frm._hv_pdf_field_sync_promise = request;
	return request;
};

const hv_attach_pdf_mapping_path_picker_to_wrapper = (frm, rowDoc, wrapper) => {
	const el = wrapper instanceof HTMLElement ? wrapper : wrapper?.get?.(0);
	if (!el || el.dataset.hvPdfPathPickerAttached === "1") {
		return;
	}

	let container = el.querySelector(".hv-pdf-value-path-picker");
	if (!container) {
		container = document.createElement("div");
		container.className = "hv-pdf-value-path-picker mt-2";
		el.appendChild(container);
	}
	container.innerHTML = "";

	const btn = document.createElement("button");
	btn.type = "button";
	btn.className = "btn btn-xs btn-secondary";
	btn.textContent = __("Pfad wählen");
	btn.addEventListener("click", () => {
		hv_open_pdf_value_path_picker(frm, (path) => {
			frappe.model.set_value(rowDoc.doctype, rowDoc.name, "value_path", path);
		});
	});

	container.appendChild(btn);
	el.dataset.hvPdfPathPickerAttached = "1";
};

const hv_attach_pdf_mapping_path_pickers = (frm) => {
	if (!frm || (frm.doc.content_type || "").trim() !== "PDF Formular") {
		return;
	}

	const grid = frm.fields_dict?.pdf_field_mappings?.grid;
	if (!grid || !Array.isArray(grid.grid_rows)) {
		return;
	}

	grid.grid_rows.forEach((gridRow) => {
		const rowDoc = gridRow?.doc;
		if (!rowDoc) {
			return;
		}

		const inlineWrapper = gridRow?.columns?.value_path?.field_area;
		if (inlineWrapper) {
			hv_attach_pdf_mapping_path_picker_to_wrapper(frm, rowDoc, inlineWrapper);
		}

		const formWrapper = gridRow?.grid_form?.fields_dict?.value_path?.wrapper;
		if (formWrapper) {
			hv_attach_pdf_mapping_path_picker_to_wrapper(frm, rowDoc, formWrapper);
		}
	});
};

const hv_find_paths = async (startNodes, targetDoctype, maxDepth = 3) => {
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
	});

	return nodes;
};

const HV_SKIP_TYPES = new Set([
	"Table",
	"Table MultiSelect",
	"Section Break",
	"Column Break",
	"Fold",
	"Button",
	"HTML",
	"Attach",
	"Attach Image",
	"Image",
]);

const hv_format_field_type = (df) => {
	const ft = df?.fieldtype || "";
	if (ft === "Link") {
		return df?.options ? `Link → ${df.options}` : "Link";
	}
	if (ft === "Dynamic Link") {
		return df?.options ? `Dynamic Link → ${df.options}` : "Dynamic Link";
	}
	if (ft === "Select") {
		return "Select";
	}
	return ft;
};

const hv_build_tree_nodes = async (baseKey, baseLabel, meta, visited, depth, maxDepth) => {
	const nodes = [];
	if (!meta || !meta.fields) {
		return nodes;
	}

	for (const df of meta.fields) {
		if (!df.fieldname) {
			continue;
		}

		const label = df.label || df.fieldname;
		const type = hv_format_field_type(df);

		if ((df.fieldtype === "Table" || df.fieldtype === "Table MultiSelect") && df.options) {
			nodes.push({
				label: `${baseLabel}: ${label} (${__("Liste")})`,
				placeholder: `{{ ${baseKey}.${df.fieldname}[] }}`,
				type: __("Tabelle"),
				children: [],
			});

			if (depth < maxDepth) {
				const childMeta = await hv_load_meta(df.options);
				if (childMeta) {
					const childVisited = new Set(visited);
					childVisited.add(df.options);
					const firstChildNodes = await hv_build_tree_nodes(
						`${baseKey}.${df.fieldname}[0]`,
						`${label} #1`,
						childMeta,
						childVisited,
						depth + 1,
						maxDepth
					);

					if (firstChildNodes.length) {
						nodes.push({
							label: `${baseLabel}: ${label} (${__("1. Eintrag")})`,
							type: __("Tabelle"),
							children: firstChildNodes,
						});
					}

					const indexedChildNodes = await hv_build_tree_nodes(
						`${baseKey}.${df.fieldname}[__INDEX__]`,
						`${label} #N`,
						childMeta,
						childVisited,
						depth + 1,
						maxDepth
					);

					if (indexedChildNodes.length) {
						nodes.push({
							label: `${baseLabel}: ${label} (${__("N-ter Eintrag...")})`,
							type: __("Tabelle"),
							children: indexedChildNodes,
						});
					}
				}
			}
			continue;
		}

		if (HV_SKIP_TYPES.has(df.fieldtype)) {
			continue;
		}

		// Immer einen Leaf für das eigentliche Feld
		nodes.push({
			label: `${baseLabel}: ${label}`,
			placeholder: `{{ ${baseKey}.${df.fieldname} }}`,
			type,
			children: [],
		});

		// Link-Felder: rekursiv verlinkten Doctype auflösen und als Unterknoten anbieten
		if (
			df.fieldtype === "Link" &&
			df.options &&
			!visited.has(df.options) &&
			depth < maxDepth
		) {
			const targetMeta = await hv_load_meta(df.options);
			if (!targetMeta) {
				continue;
			}

			const targetKey = `${baseKey}.${df.fieldname}`;
			const childVisited = new Set(visited);
			childVisited.add(df.options);

			const childNodes = await hv_build_tree_nodes(
				targetKey,
				df.options,
				targetMeta,
				childVisited,
				depth + 1,
				maxDepth
			);

			if (childNodes.length) {
				nodes.push({
					label: `${label} → ${df.options}`,
					placeholder: `{{ ${targetKey} }}`,
					type: "Link",
					children: childNodes,
				});
			}
		}
	}

	return nodes;
};

const hv_collect_reference_groups = async (frm) => {
	const refs = frm.doc.reference_doctypes || [];
	const variables = frm.doc.variables || [];
	const groups = [];

	const variableRefs = variables.filter((row) => {
		const t = (row.variable_type || "Text").trim();
		return t !== "Text" && row.reference_doctype && (row.variable || row.label);
	});

	for (const row of variableRefs) {
		const refDoctype = row.reference_doctype;
		if (!refDoctype) continue;

		const key = hv_scrub(row.variable || row.label || refDoctype);
		const isList = String(row.variable_type || "").trim() === "Doctype Liste";
		const treeKey = isList ? `${key}[0]` : key;

		const meta = await hv_load_meta(refDoctype);
		if (!meta) {
			continue;
		}

		const tree = await hv_build_tree_nodes(
			treeKey,
			refDoctype,
			meta,
			new Set([refDoctype]),
			0,
			2
		);

		if (tree.length) {
			groups.push({
				key,
				label: row.label || row.variable || refDoctype,
				tree,
			});
		}
	}

	// Fallback: alte Referenz-Doctype-Tabelle (wird auf dem DocType inzwischen verborgen).
	for (const ref of refs) {
		if (!ref.reference_doctype) continue;
		const key = hv_scrub(ref.context_variable || ref.reference_doctype || "");
		if (!key || groups.some((g) => g.key === key)) continue;

		const meta = await hv_load_meta(ref.reference_doctype);
		if (!meta) continue;

		const tree = await hv_build_tree_nodes(
			key,
			ref.reference_doctype,
			meta,
			new Set([ref.reference_doctype]),
			0,
			2
		);

		if (tree.length) {
			groups.push({
				key,
				label: ref.reference_doctype,
				tree,
			});
		}
	}

	return groups;
};

const hv_get_placeholder_groups = async (frm) => {
	const referenceGroups = await hv_collect_reference_groups(frm);
	const baseTree = HV_BASE_PLACEHOLDERS.map((ph) => ({
		label: ph.label,
		placeholder: ph.value,
		children: [],
	}));

	const variableTree = (frm.doc.variables || [])
		.filter((row) => row.variable && ((row.variable_type || "Text").trim() === "Text"))
		.map((row) => ({
			label: row.label || row.variable,
			placeholder: `{{ ${hv_scrub(row.variable)} }}`,
			children: [],
		}));

	return [
		{ key: "__base", label: __("Allgemein"), tree: baseTree },
		...(variableTree.length ? [{ key: "__variables", label: __("Block-Variablen"), tree: variableTree }] : []),
		...referenceGroups,
	].filter((g) => g.tree && g.tree.length);
};

const hv_append_placeholder_panel = (frm, fieldname, titleText) => {
	const control = frm.get_field(fieldname);
	if (!control || !control.$wrapper) {
		return;
	}

	control.$wrapper.find(".serienbrief-placeholder-panel").remove();

	const panel = $(`
		<div class="serienbrief-placeholder-panel">
			<div class="placeholder-title">${titleText || __("Platzhalter einfügen")}</div>
			<div class="placeholder-buttons"></div>
			<div class="snippet-title">${__("Snippets einfügen")}</div>
			<div class="snippet-buttons"></div>
		</div>
	`);
	panel.css({
		border: "1px solid var(--gray-300)",
		padding: "12px",
		borderRadius: "4px",
		marginTop: "12px",
		backgroundColor: "var(--fg-color-white)",
	});
	panel.find(".placeholder-title").css({
		fontWeight: 600,
		marginBottom: "8px",
		fontSize: "var(--text-md)",
	});
	panel.find(".snippet-title").css({
		fontWeight: 600,
		marginTop: "12px",
		marginBottom: "8px",
		fontSize: "var(--text-md)",
	});
	control.$wrapper.append(panel);

	const buttonContainer = panel.find(".placeholder-buttons").empty();
	const placeholderBtn = $(`<button type="button" class="btn btn-xs btn-secondary mb-2"></button>`);
	placeholderBtn.text(__("Platzhalter auswählen"));
	placeholderBtn.on("click", () => hv_open_placeholder_dialog(frm, fieldname));
	buttonContainer.append(placeholderBtn);

	const snippetContainer = panel.find(".snippet-buttons").empty();
	HV_SERIENBRIEF_SNIPPETS.forEach((snippet) => {
		const btn = $(`<button type="button" class="btn btn-xs btn-outline-secondary me-2 mb-2"></button>`);
		btn.text(snippet.label);
		btn.on("click", () => hv_insert_placeholder(frm, fieldname, snippet.value));
		snippetContainer.append(btn);
	});
};

const hv_insert_placeholder = async (frm, fieldname, value) => {
	const control = frm.get_field(fieldname);
	if (!control) {
		return;
	}

	const hv_tokenize_condition = (condition) => {
		const raw = condition == null ? "" : String(condition);
		if (!raw) return [{ kind: "text", value: "" }];

		const re = /(\s+and\s+|\s+or\s+|\s*==\s*)/g;
		const parts = raw.split(re).filter((p) => p !== "");
		return parts.map((p) => {
			const t = p.trim();
			if (t === "and" || t === "or" || t === "==") {
				return { kind: "token", value: p };
			}
			return { kind: "text", value: p };
		});
	};

	const hv_build_jinja_snippet_sequence = (raw) => {
		const source = raw == null ? "" : String(raw);
		if (!source.includes("{%")) return null;

		const lines = source.replace(/\r\n/g, "\n").split("\n");
		const seq = [];

		lines.forEach((line, idx) => {
			const trimmed = (line || "").trim();
			if (!trimmed) {
				// Leerzeile beibehalten
			} else if (/^\{%\s*else\s*%\}$/.test(trimmed)) {
				seq.push({ kind: "token", value: "{% else %}" });
			} else if (/^\{%\s*endif\s*%\}$/.test(trimmed)) {
				seq.push({ kind: "token", value: "{% endif %}" });
			} else {
				const m = trimmed.match(/^\{%\s*if\s+(.+?)\s*%\}$/);
				if (m) {
					seq.push({ kind: "token", value: "{% if " });
					hv_tokenize_condition(m[1]).forEach((p) => seq.push(p));
					seq.push({ kind: "token", value: " %}" });
				} else {
					seq.push({ kind: "text", value: line });
				}
			}

			if (idx < lines.length - 1) {
				seq.push({ kind: "newline" });
			}
		});

		return seq;
	};

	const hv_is_simple_placeholder = (raw) => {
		const v = (raw == null ? "" : String(raw)).trim();
		if (!v) return false;
		// Snippets / Block-Statements dürfen nicht als "Token" eingefügt werden,
		// sonst kann man innerhalb nicht weiter Platzhalter setzen.
		if (v.includes("{%") || v.includes("%}")) return false;
		// Platzhalter (egal ob mit/ohne Whitespace) als Badge behandeln
		return v.includes("{{") && v.includes("}}");
	};

	const hv_read_value_from_control = () => {
		if (typeof control.get_value === "function") {
			return control.get_value();
		}
		if (control.quill && control.quill.root) {
			return control.quill.root.innerHTML;
		}
		if (control.editor && typeof control.editor.getValue === "function") {
			return control.editor.getValue();
		}
		return undefined;
	};

	const hv_fallback_sync_to_model = (beforeValue) => {
		window.setTimeout(() => {
			const modelValue = frm.doc[fieldname] || "";
			if (modelValue !== (beforeValue || "")) {
				return;
			}

			const editorValue = hv_read_value_from_control();
			if (typeof editorValue !== "string") {
				return;
			}

			if (editorValue !== modelValue) {
				frm.set_value(fieldname, editorValue);
			}
		}, 0);
	};

	const editor = control.quill || control.editor;

	// Für Quill: Nur "echte" Platzhalter als nicht-editierbares Token einfügen.
	// Snippets (z.B. `{% if ... %}`) müssen editierbarer Text bleiben.
	if (hv_is_simple_placeholder(value) && editor && typeof editor.insertEmbed === "function") {
		const beforeValue = frm.doc[fieldname] || "";
		const api = await hv_require_quill_placeholders();
		if (api && typeof api.insert_into_quill === "function") {
			api.insert_into_quill(editor, value);
			hv_fallback_sync_to_model(beforeValue);
			return;
		}
	}

	// Snippets: Jinja-Delimiter/Operatoren als nicht-editierbare Tokens, Rest editierbar lassen.
	if (String(value || "").includes("{%") && editor && typeof editor.insertEmbed === "function") {
		const beforeValue = frm.doc[fieldname] || "";
		const api = await hv_require_quill_placeholders();
		const seq = hv_build_jinja_snippet_sequence(value);
		if (seq && api && typeof api.insert_sequence === "function") {
			if (api.insert_sequence(editor, seq)) {
				hv_fallback_sync_to_model(beforeValue);
				return;
			}
		}
	}

	// Fallback für Quill ohne clipboard API
	if (editor && typeof editor.insertText === "function") {
		const beforeValue = frm.doc[fieldname] || "";
		let index = editor.getLength ? editor.getLength() : 0;
		if (typeof editor.getSelection === "function") {
			const selection = editor.getSelection();
			if (selection) {
				index = selection.index;
			}
		}
		editor.focus && editor.focus();
		if (hv_is_simple_placeholder(value)) {
			editor.insertText(
				index,
				` ${value} `,
				{
					background: '#e3f2fd',
					color: '#1565c0',
					bold: true,
				},
				"user"
			);
		} else {
			editor.insertText(index, ` ${value} `, "user");
		}
		editor.setSelection && editor.setSelection(index + value.length + 2, 0, "user");
		hv_fallback_sync_to_model(beforeValue);
		return;
	}

	// Für CodeMirror oder andere Editoren
	if (editor && typeof editor.replaceSelection === "function") {
		const beforeValue = frm.doc[fieldname] || "";
		editor.focus && editor.focus();
		editor.replaceSelection(value);
		hv_fallback_sync_to_model(beforeValue);
		return;
	}

	if (editor && typeof editor.insert === "function") {
		const beforeValue = frm.doc[fieldname] || "";
		editor.focus && editor.focus();
		editor.insert(value);
		hv_fallback_sync_to_model(beforeValue);
		return;
	}

	const current = frm.doc[fieldname] || "";
	frm.set_value(fieldname, `${current}${value}`);
};

const hv_add_reference_doctype = (frm, on_added) => {
	const dialog = new frappe.ui.Dialog({
		title: __("Referenzvariable hinzufügen"),
		fields: [
			{
				fieldname: "reference_doctype",
				fieldtype: "Link",
				label: __("Doctype"),
				options: "DocType",
				reqd: 1,
				description: __("Wird als Quelle für Platzhalter genutzt."),
			},
			{
				fieldname: "variable_type",
				fieldtype: "Select",
				label: __("Typ"),
				options: ["Doctype", "Doctype Liste"],
				default: "Doctype",
				reqd: 1,
			},
			{
				fieldname: "variable",
				fieldtype: "Data",
				label: __("Variablenname im Template"),
				description: __("Z.B. immobilie oder mieter_liste. Wird im Template als `{{ variable }}` genutzt."),
			},
		],
		primary_action_label: __("Hinzufügen"),
		primary_action(values) {
			const doc = values.reference_doctype;
			if (!doc) return;

			const rawVar = (values.variable || "").trim() || hv_scrub(doc);
			const exists = (frm.doc.variables || []).some((row) => {
				const t = (row.variable_type || "Text").trim();
				return t !== "Text" && row.reference_doctype === doc && hv_scrub(row.variable || "") === hv_scrub(rawVar);
			});
			if (exists) {
				frappe.msgprint({
					message: __("Diese Referenzvariable ist bereits hinterlegt."),
					indicator: "orange",
				});
				return;
			}

			const row = frm.add_child("variables");
			row.variable = rawVar;
			row.label = doc;
			row.variable_type = values.variable_type || "Doctype";
			row.reference_doctype = doc;
			frm.refresh_field("variables");
			dialog.hide();
			on_added && on_added(doc);
		},
	});

	dialog.on_page_show = () => {
		const doc = dialog.get_value("reference_doctype");
		if (doc && !dialog.get_value("variable")) {
			dialog.set_value("variable", hv_scrub(doc));
		}
	};

	dialog.fields_dict.reference_doctype.$input.on("change", () => {
		const doc = dialog.get_value("reference_doctype");
		if (doc && !dialog.get_value("variable")) {
			dialog.set_value("variable", hv_scrub(doc));
		}
	});

	dialog.show();
};

const hv_open_placeholder_dialog = async (frm, fieldname) => {
	const picker = await hv_require_placeholder_picker();
	if (!picker || typeof picker.open_dialog !== "function") {
		frappe.msgprint({
			message: __(
				"Platzhalter-Dialog konnte nicht geladen werden. Falls /assets/* nicht erreichbar ist, muss der Server-Fallback verfügbar sein (get_serienbrief_placeholder_picker_js)."
			),
			indicator: "red",
		});
		return;
	}

	picker.open_dialog({
		title: __("Platzhalter auswählen"),
		load_groups: () => hv_get_placeholder_groups(frm),
		on_insert: (placeholder) => hv_insert_placeholder(frm, fieldname, placeholder),
		on_setup: ({ dialog, refresh_groups }) => {
			const addBtn = $(
				`<button type="button" class="btn btn-sm btn-secondary me-2">${__(
					"Referenzvariable hinzufügen"
				)}</button>`
			);
			addBtn.on("click", () => {
				hv_add_reference_doctype(frm, async (doc) => {
					await refresh_groups(doc);
					hv_render_placeholder_panels(frm);
				});
			});
			dialog.get_primary_btn().before(addBtn);
		},
	});
};

const hv_render_placeholder_panels = async (frm) => {
	const groups = await hv_get_placeholder_groups(frm);
	if (!groups || !groups.length) {
		return;
	}
	const contentType = frm.doc.content_type || "Textbaustein (Rich Text)";
	if (contentType === "PDF Formular") {
		["text_content", "html_content", "jinja_content"].forEach((field) => {
			const control = frm.get_field(field);
			if (control && control.$wrapper) {
				control.$wrapper.find(".serienbrief-placeholder-panel").remove();
			}
		});
		return;
	}
	const targets =
		contentType === "HTML + Jinja"
			? [
					{ fieldname: "html_content", title: __("Platzhalter in HTML einfügen") },
					{ fieldname: "jinja_content", title: __("Platzhalter in Jinja einfügen") },
			  ]
			: [{ fieldname: "text_content", title: __("Platzhalter einfügen") }];

	["text_content", "html_content", "jinja_content"].forEach((field) => {
		const control = frm.get_field(field);
		if (control && control.$wrapper) {
			control.$wrapper.find(".serienbrief-placeholder-panel").remove();
		}
	});

	targets.forEach((cfg) => hv_append_placeholder_panel(frm, cfg.fieldname, cfg.title));
};

const hv_pick_mapping_value = (mapping, req) => {
	if (!mapping || typeof mapping !== "object") {
		return "";
	}
	const keys = [req.req_key, req.doctype, req.fieldname].filter(Boolean);
	for (const key of keys) {
		const val = mapping[key];
		if (val || val === 0) {
			return val;
		}
	}
	return "";
};

const hv_format_requirement = (req, pathMap) => {
	const label = req.label || req.fieldname;
	const parts = [];
	const hasOverride = pathMap && Object.prototype.hasOwnProperty.call(pathMap, req.req_key);
	if (req.source) {
		parts.push(req.source);
	}
	const path = hv_pick_mapping_value(pathMap, req) || req.path;
	if (path) {
		parts.push(path);
	}
	if (!hasOverride && req.resolved_via_default) {
		parts.push(__("Standardpfad"));
	}
	if (!parts.length) {
		return label;
	}
	return `${label} (${parts.join(" · ")})`;
};

const hv_get_reference_requirements = (frm) => {
	const source = frm.doc.title || frm.doc.name || __("Textbaustein");
	const requirements = [];

	(frm.doc.variables || [])
		.filter((row) => row.reference_doctype && (row.variable || row.label) && (row.variable_type || "Text").trim() !== "Text")
		.forEach((row) => {
			const fieldname = hv_scrub(row.variable || row.label || row.reference_doctype || "");
			const useName = row.name && !String(row.name).startsWith("new");
			const req_key = useName ? row.name : row.reference_doctype || fieldname;
			requirements.push({
				fieldname,
				doctype: row.reference_doctype,
				label: row.label || row.reference_doctype,
				source,
				req_key,
			});
		});

	// Fallback: legacy reference_doctypes
	(frm.doc.reference_doctypes || [])
		.filter((row) => row.reference_doctype)
		.forEach((row) => {
			const fieldname = hv_scrub(row.context_variable || row.reference_doctype || "");
			if (!fieldname || requirements.some((req) => req.fieldname === fieldname)) return;
			const useName = row.name && !String(row.name).startsWith("new");
			const req_key = useName ? row.name : row.reference_doctype || fieldname;
			requirements.push({
				fieldname,
				doctype: row.reference_doctype,
				label: row.reference_doctype,
				source,
				req_key,
			});
		});

	return requirements;
};

const hv_update_standardpfade_labels = (frm) => {
	const requirements = hv_get_reference_requirements(frm);
	let touched = false;

	(frm.doc.standardpfade || []).forEach((row) => {
		const mapping = hv_parse_mapping(row.pfad_zuordnung);
		const labels = requirements.length
			? requirements.map((req) => hv_format_requirement(req, mapping)).join(", ")
			: "";
		if (row.anforderungen !== labels) {
			frappe.model.set_value(row.doctype, row.name, "anforderungen", labels);
			touched = true;
		}
	});

	if (touched) {
		frm.refresh_field("standardpfade");
	}
};

const hv_render_default_path_picker = (frm, requirement, field, existingValue, startNodes) => {
	const wrapper = $(field.wrapper).empty();
	const input = $(`<input type="text" class="form-control" />`);
	input.val(existingValue || "");
	wrapper.append(input);

	const helper = $(`<div class="mt-2"></div>`);
	const btn = $(`<button type="button" class="btn btn-xs btn-secondary">${__("Pfad wählen")}</button>`);
	helper.append(btn);
	wrapper.append(helper);

	btn.on("click", async () => {
		if (!startNodes || !startNodes.length) {
			frappe.msgprint({
				message: __("Bitte zuerst ein Startobjekt wählen."),
				indicator: "orange",
			});
			return;
		}

		btn.prop("disabled", true);
		btn.text(__("Lade Pfade ..."));
		const paths = await hv_find_paths(startNodes, requirement.doctype, 4);
		btn.prop("disabled", false);
		btn.text(__("Pfad wählen"));

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
					default: input.val() || paths[0],
				},
			],
			primary_action_label: __("Übernehmen"),
			primary_action(values) {
				input.val(values.path || "");
				chooser.hide();
			},
		});
		chooser.show();
	});

	return () => input.val();
};

const hv_open_default_path_dialog = (frm) => {
	const requirements = hv_get_reference_requirements(frm);
	if (!requirements.length) {
		frappe.msgprint({
			message: __("Bitte hinterlege zuerst Referenz-Doctypes im Textbaustein."),
			indicator: "orange",
		});
		return;
	}

	const existingStart = (frm.doc.standardpfade || [])[0]?.startobjekt || "";
	let rows = [];
	let startNodes = [];

	const dialog = new frappe.ui.Dialog({
		title: __("Standardpfade je Startobjekt"),
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
				label: __("Pfad Zuordnung"),
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
			rows.forEach(({ req, getValue }) => {
				const val = (getValue() || "").trim();
				if (val) {
					newMapping[req.req_key] = val;
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

			hv_update_standardpfade_labels(frm);
			frm.refresh_field("standardpfade");
			dialog.hide();
		},
	});

	const container = $(dialog.get_field("paths").wrapper).empty();

	const renderPaths = async () => {
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

		if (!requirements.length) {
			container.html(`<div class="text-muted small">${__("Keine Referenzen definiert.")}</div>`);
			return;
		}

		requirements.forEach((req) => {
			const rowDiv = $(`
				<div class="form-group">
					<label class="control-label">${frappe.utils.escape_html(req.label || req.fieldname)}</label>
					<div class="control-input"></div>
				</div>
			`);
			container.append(rowDiv);
			const field = { wrapper: rowDiv.find(".control-input")[0] };
			const existing = hv_pick_mapping_value(mapping, req) || req.path;
			const getValue = hv_render_default_path_picker(frm, req, field, existing, startNodes);
			rows.push({ req, getValue });
		});

		if (!rows.length) {
			container.html(`<div class="text-muted small">${__("Keine Referenzen definiert.")}</div>`);
		}
	};

	dialog.fields_dict.startobjekt.$input.on("change", () => renderPaths());
	dialog.show();
	renderPaths();
};

frappe.ui.form.on("Serienbrief Textbaustein", {
	refresh(frm) {
		hv_require_quill_placeholders().then((api) => {
			if (api && typeof api.ensure_for_control === "function") {
				api.ensure_for_control(frm.get_field("text_content"));
			}
		});
		window.setTimeout(() => hv_attach_pdf_mapping_path_pickers(frm), 0);
		hv_render_placeholder_panels(frm);
		hv_update_standardpfade_labels(frm);
		frm.add_custom_button(__("Standardpfade je Startobjekt"), () => hv_open_default_path_dialog(frm));
		if ((frm.doc.content_type || "") === "PDF Formular") {
			const fileUrl = (frm.doc.pdf_file || "").trim();
			const hasMappings = Array.isArray(frm.doc.pdf_field_mappings) && frm.doc.pdf_field_mappings.length > 0;
			if (fileUrl && !hasMappings && frm._hv_pdf_field_autoloaded_for !== fileUrl) {
				hv_sync_pdf_field_mappings(frm, { freeze: false, showAlert: false });
			}
			frm.add_custom_button(__("PDF-Felder einlesen"), () => {
				const currentFileUrl = (frm.doc.pdf_file || "").trim();
				if (!currentFileUrl) {
					frappe.msgprint({
						message: __("Bitte zuerst eine PDF-Datei hochladen."),
						indicator: "orange",
					});
					return;
				}
				hv_sync_pdf_field_mappings(frm, { freeze: true, showAlert: true });
			});
		}
	},
	content_type(frm) {
		hv_render_placeholder_panels(frm);
		if ((frm.doc.content_type || "").trim() === "PDF Formular" && (frm.doc.pdf_file || "").trim()) {
			hv_sync_pdf_field_mappings(frm, { freeze: false, showAlert: false }).finally(() =>
				window.setTimeout(() => hv_attach_pdf_mapping_path_pickers(frm), 0)
			);
		}
	},
	pdf_file(frm) {
		if ((frm.doc.content_type || "").trim() !== "PDF Formular") {
			return;
		}
		frm._hv_pdf_field_autoloaded_for = null;
		hv_sync_pdf_field_mappings(frm, { freeze: true, showAlert: true }).finally(() =>
			window.setTimeout(() => hv_attach_pdf_mapping_path_pickers(frm), 0)
		);
	},
	reference_doctypes_on_form_rendered(frm) {
		hv_render_placeholder_panels(frm);
		hv_update_standardpfade_labels(frm);
	},
	variables_on_form_rendered(frm) {
		hv_render_placeholder_panels(frm);
	},
	standardpfade_on_form_rendered(frm) {
		hv_update_standardpfade_labels(frm);
	},
	pdf_field_mappings_on_form_rendered(frm) {
		window.setTimeout(() => hv_attach_pdf_mapping_path_pickers(frm), 0);
	},
});

frappe.ui.form.on("Serienbrief Textbaustein Referenz", {
	reference_doctype(frm) {
		hv_render_placeholder_panels(frm);
	},
});

frappe.ui.form.on("Serienbrief Textbaustein Standardpfad", {
	startobjekt(frm) {
		hv_update_standardpfade_labels(frm);
	},
});

frappe.ui.form.on("Serienbrief Textbaustein Variable", {
	variable(frm) {
		hv_render_placeholder_panels(frm);
	},
	label(frm) {
		hv_render_placeholder_panels(frm);
	},
	variable_type(frm) {
		hv_render_placeholder_panels(frm);
		hv_update_standardpfade_labels(frm);
	},
	reference_doctype(frm) {
		hv_render_placeholder_panels(frm);
		hv_update_standardpfade_labels(frm);
	},
});

frappe.ui.form.on("Serienbrief PDF Feld Mapping", {
	form_render(frm) {
		window.setTimeout(() => hv_attach_pdf_mapping_path_pickers(frm), 0);
	},
	value_path(frm) {
		window.setTimeout(() => hv_attach_pdf_mapping_path_pickers(frm), 0);
	},
});
