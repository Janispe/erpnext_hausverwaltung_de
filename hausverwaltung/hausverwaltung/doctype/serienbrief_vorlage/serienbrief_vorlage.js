const SERIENBRIEF_PLACEHOLDERS = [
];

const HV_VORLAGE_BASE_PLACEHOLDERS = [
	{ label: __("Datum (formatiert)"), value: "{{ datum }}" },
	{ label: __("Datum (ISO)"), value: "{{ datum_iso }}" },
];

const hv_vorlage_require_placeholder_picker = () =>
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

const hv_vorlage_require_quill_placeholders = () =>
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

const HV_PLACEHOLDER_CACHE_PREFIX = "hv_serienbrief_placeholder_cache:";

const hv_get_cache_token = () => {
	const buildVersion =
		frappe?.boot?.build_version || frappe?.boot?.versions?.frappe || frappe?.boot?.version || "";
	const bust = frappe?.boot?.hv_placeholder_cache_bust || "";
	return `${buildVersion}::${bust}`;
};

const hv_get_cache_namespace = () => `${HV_PLACEHOLDER_CACHE_PREFIX}${hv_get_cache_token()}:`;

const hv_clear_placeholder_cache_if_needed = () => {
	if (!window.localStorage) return;
	const current = hv_get_cache_token();
	const markerKey = `${HV_PLACEHOLDER_CACHE_PREFIX}version`;
	const previous = localStorage.getItem(markerKey) || "";
	if (previous === current) return;

	Object.keys(localStorage).forEach((key) => {
		if (key.startsWith(HV_PLACEHOLDER_CACHE_PREFIX)) {
			localStorage.removeItem(key);
		}
	});
	localStorage.setItem(markerKey, current);
};

const hv_get_cached_placeholder_groups = (cacheKey) => {
	if (!window.localStorage) return null;
	try {
		const raw = localStorage.getItem(hv_get_cache_namespace() + cacheKey);
		if (!raw) return null;
		const parsed = JSON.parse(raw);
		return Array.isArray(parsed) ? parsed : null;
	} catch (e) {
		return null;
	}
};

const hv_set_cached_placeholder_groups = (cacheKey, groups) => {
	if (!window.localStorage) return;
	try {
		localStorage.setItem(hv_get_cache_namespace() + cacheKey, JSON.stringify(groups || []));
	} catch (e) {
		// ignore quota or serialization errors
	}
};

const hv_escape_attr = (value) =>
	String(value ?? "")
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;")
		.replace(/'/g, "&#39;");

const hv_vorlage_is_simple_inline_placeholder = (raw) => {
	const source = (raw == null ? "" : String(raw)).trim();
	if (!source.startsWith("{{") || !source.endsWith("}}")) return false;
	// Multi-line Jinja blocks stay editable as raw text.
	if (source.includes("\n")) return false;
	const inner = source.slice(2, -2).trim();
	if (!inner) return false;
	return true;
};

const hv_vorlage_upgrade_inline_placeholders = (frm) => {
	const control = frm.get_field("content");
	if (!control || typeof control.get_input_value !== "function") return;
	const quill = control.quill || control.editor;
	if (!quill || typeof control.set_formatted_input !== "function") return;

	const original = control.get_input_value() || "";
	if (!original.includes("{{")) return;

	const tokenRe = /\{\{[\s\S]*?\}\}/g;
	let changed = false;
	const updated = original.replace(tokenRe, (match, offset, fullText) => {
		const before = fullText.slice(Math.max(0, offset - 160), offset);
		if (before.includes('class="hv-placeholder-badge"') || before.includes("class='hv-placeholder-badge'")) {
			return match;
		}
		if (!hv_vorlage_is_simple_inline_placeholder(match)) {
			return match;
		}
		changed = true;
		const attr = hv_escape_attr(match);
		return `<span class="hv-placeholder-badge" data-hv-placeholder="${attr}" contenteditable="false" draggable="false">${match}</span>`;
	});

	if (!changed || updated === original) return;

	const was_dirty = frm.is_dirty();
	control.set_formatted_input(updated);
	const normalized = control.get_input_value();
	if (normalized && normalized !== frm.doc.content) {
		frm.set_value("content", normalized, null, true);
	}
	if (!was_dirty) {
		frm.doc.__unsaved = 0;
		frm.toolbar?.refresh?.();
	}
};

const HV_CONTENT_EDITOR_MIN_HEIGHT = 600;

const hv_vorlage_enlarge_content_editor = (frm, retries = 12) => {
	// Frappe's Text Editor default is ~180px high, which is cramped for full
	// letter templates. Expand the Quill root unless we're in split-preview
	// mode (that mode manages its own sizing).
	if (frm._hv_split_preview) return;
	const control = frm.get_field("content");
	const quill = control?.quill || control?.editor;
	if (!quill?.root) {
		if (retries > 0) {
			setTimeout(() => hv_vorlage_enlarge_content_editor(frm, retries - 1), 150);
		}
		return;
	}
	quill.root.style.minHeight = `${HV_CONTENT_EDITOR_MIN_HEIGHT}px`;
};

const hv_ensure_placeholder_editor_ready = (frm, retries = 12) => {
	hv_vorlage_require_quill_placeholders().then((api) => {
		if (!api || typeof api.ensure_for_control !== "function") return;

		const control = frm.get_field("content");
		const quill = control?.quill || control?.editor;
		if (!quill) {
			if (retries > 0) {
				setTimeout(() => hv_ensure_placeholder_editor_ready(frm, retries - 1), 150);
			}
			return;
		}

		api.ensure_for_control(control);
		hv_vorlage_upgrade_inline_placeholders(frm);
		hv_bind_live_preview_to_quill(frm);
	});
};

const SERIENBRIEF_SNIPPETS = [
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

const hv_vorlage_uses_inline_blocks = (frm) => {
	const content = hv_get_live_template_source(frm);
	return content.includes("baustein(") || content.includes("textbaustein(");
};

const hv_is_restricted_hausverwalter = () => {
	const roles = Array.isArray(frappe.user_roles) ? frappe.user_roles : [];
	const isSystemManager = roles.includes("System Manager");
	const isHausverwalter = roles.includes("Hausverwalter");
	return isHausverwalter && !isSystemManager;
};

const hv_apply_editor_access_mode = (frm) => {
	const restricted = hv_is_restricted_hausverwalter();
	const contentType = hv_get_template_content_type(frm);

	frm.set_df_property("content_type", "read_only", restricted ? 1 : 0);

	if (restricted && contentType === "HTML + Jinja") {
		frm.set_df_property("content", "hidden", 0);
		frm.set_df_property("html_content", "hidden", 0);
		frm.set_df_property("jinja_content", "hidden", 0);
		if (!frm._hv_html_mode_notice_shown) {
			frm._hv_html_mode_notice_shown = true;
			frappe.show_alert({
				message: __(
					"Diese Vorlage nutzt HTML + Jinja (Expertenmodus). Bearbeitung ist möglich, aber bitte vorsichtig vorgehen."
				),
				indicator: "blue",
			});
		}
		return;
	}

	// Keep default DocType depends_on behavior when editing is allowed.
	frm.set_df_property("content", "hidden", 0);
	frm.set_df_property("html_content", "hidden", 0);
	frm.set_df_property("jinja_content", "hidden", 0);
};

const hv_vorlage_extract_inline_blocks = (content) => {
	const source = content == null ? "" : String(content);
	// Matches: {{ baustein("NAME") }}, {{ textbaustein('NAME') }}
	const re = /\{\{\s*(?:baustein|textbaustein)\(\s*(['"])(.*?)\1\s*\)\s*\}\}/g;
	const ordered = [];
	const seen = new Set();
	let m;
	while ((m = re.exec(source))) {
		const name = (m[2] || "").trim();
		if (!name || seen.has(name)) continue;
		seen.add(name);
		ordered.push(name);
	}
	return ordered;
};

const hv_vorlage_sync_textbausteine_from_content = (frm) => {
	const content = hv_get_live_template_source(frm);
	const blockNames = hv_vorlage_extract_inline_blocks(content);
	const keep = new Set(blockNames);
	const currentRows = Array.isArray(frm.doc.textbausteine) ? frm.doc.textbausteine : [];

	let changed = false;

	// Remove rows that are not referenced in the template text anymore.
	const grid = frm.get_field("textbausteine")?.grid;
	if (grid && grid.grid_rows_by_docname) {
		(currentRows || []).slice().forEach((row) => {
			const block = (row?.baustein || "").trim();
			if (!block) return;
			if (keep.has(block)) return;
			const gridRow = grid.grid_rows_by_docname[row.name];
			if (gridRow && typeof gridRow.remove === "function") {
				gridRow.remove();
				changed = true;
			}
		});
	} else {
		// Fallback: filter client-side (less ideal, but avoids crashes if grid is unavailable).
		const next = (currentRows || []).filter((row) => {
			const block = (row?.baustein || "").trim();
			return !block || keep.has(block);
		});
		if (next.length !== (currentRows || []).length) {
			frm.doc.textbausteine = next;
			changed = true;
		}
	}

	// Add missing rows for blocks that were typed/added inline.
	const existing = new Set(
		(Array.isArray(frm.doc.textbausteine) ? frm.doc.textbausteine : [])
			.map((r) => (r?.baustein || "").trim())
			.filter(Boolean)
	);
	blockNames.forEach((name) => {
		if (existing.has(name)) return;
		const row = frm.add_child("textbausteine");
		row.baustein = name;
		changed = true;
	});

	if (changed) {
		frm.refresh_field("textbausteine");
		hv_update_block_requirements(frm);
	}
};

const hv_vorlage_toggle_block_position_ui = (frm) => {
	const inlineMode = hv_vorlage_uses_inline_blocks(frm);
	frm.set_df_property("content_position", "hidden", inlineMode);
};

const hv_vorlage_toggle_textbausteine_table = (frm) => {
	const show = Boolean(frm?._hv_show_textbausteine_table);
	frm.set_df_property("textbausteine", "hidden", !show);
};

const hv_vorlage_open_block_picker = (frm) => {
	frappe.prompt(
		[
			{
				fieldname: "baustein",
				fieldtype: "Link",
				label: __("Textbaustein"),
				options: "Serienbrief Textbaustein",
				reqd: 1,
			},
		],
		(values) => {
			const blockName = (values?.baustein || "").trim();
			if (!blockName) return;

			const existing = new Set((frm.doc.textbausteine || []).map((r) => r.baustein).filter(Boolean));
			if (!existing.has(blockName)) {
				const row = frm.add_child("textbausteine");
				row.baustein = blockName;
				frm.refresh_field("textbausteine");
			}

			insert_placeholder(frm, `{{ baustein("${blockName}") }}`);
			hv_vorlage_toggle_block_position_ui(frm);
		},
		__("Textbaustein einfügen"),
		__("Einfügen")
	);
};

const append_placeholder_panel = (frm) => {
	const control = frm.get_field("content");
	if (!control || !control.$wrapper) {
		return;
	}

	let panel = control.$wrapper.find(".serienbrief-placeholder-panel");
	if (!panel.length) {
		panel = $(`
			<div class="serienbrief-placeholder-panel">
				<div class="placeholder-title">${__("Platzhalter einfügen")}</div>
				<div class="placeholder-buttons"></div>
				<div class="snippet-title">${__("Snippets einfügen")}</div>
				<div class="snippet-buttons"></div>
				<div class="mapping-title">${__("Feldpfade")}</div>
				<div class="mapping-buttons"></div>
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
		panel.find(".mapping-title").css({
			fontWeight: 600,
			marginTop: "12px",
			marginBottom: "8px",
			fontSize: "var(--text-md)",
		});
		control.$wrapper.append(panel);
	}

	const buttonContainer = panel.find(".placeholder-buttons").empty();
	const placeholderBtn = $(`<button type="button" class="btn btn-xs btn-secondary mb-2"></button>`);
	placeholderBtn.text(__("Platzhalter auswählen"));
	placeholderBtn.on("click", async () => hv_vorlage_open_placeholder_dialog(frm));
	buttonContainer.append(placeholderBtn);

	const blockBtn = $(`<button type="button" class="btn btn-xs btn-secondary ms-2 mb-2"></button>`);
	blockBtn.text(__("Textbaustein einfügen"));
	blockBtn.on("click", async () => hv_vorlage_open_block_picker(frm));
	buttonContainer.append(blockBtn);

	const templateVarBtn = $(`<button type="button" class="btn btn-xs btn-secondary ms-2 mb-2"></button>`);
	templateVarBtn.text(__("Vorlagen-Variablen"));
	templateVarBtn.on("click", async () => hv_vorlage_open_template_variable_dialog(frm));
	buttonContainer.append(templateVarBtn);

	const snippetContainer = panel.find(".snippet-buttons").empty();
	SERIENBRIEF_SNIPPETS.forEach((snippet) => {
		const btn = $(`<button type="button" class="btn btn-xs btn-outline-secondary me-2 mb-2"></button>`);
		btn.text(snippet.label);
		btn.on("click", () => insert_placeholder(frm, snippet.value));
		snippetContainer.append(btn);
	});

	const mappingContainer = panel.find(".mapping-buttons").empty();
	const mappingBtn = $(`<button type="button" class="btn btn-xs btn-secondary mb-2"></button>`);
	mappingBtn.text(__("Feldpfade definieren"));
	mappingBtn.on("click", () => hv_update_block_requirements(frm, { open_mapping: true }));
	mappingContainer.append(mappingBtn);
};

const insert_placeholder = async (frm, value) => {
	const control = frm.get_field("content");
	if (!control) {
		return;
	}

	const hv_get_quill_selection_fallback = (quill) => {
		let selection = null;
		if (quill && typeof quill.getSelection === "function") {
			try {
				selection = quill.getSelection();
			} catch (e) {
				selection = null;
			}
		}
		if (!selection && quill && quill.__hv_last_selection) {
			selection = quill.__hv_last_selection;
		}
		if (!selection && frm?._hv_last_quill_selection) {
			selection = frm._hv_last_quill_selection;
		}
		if (!selection || typeof selection.index !== "number") return null;
		return { index: selection.index, length: selection.length || 0 };
	};

	const hv_restore_quill_selection = (quill) => {
		if (!quill || typeof quill.setSelection !== "function") return;
		const selection = hv_get_quill_selection_fallback(quill);
		if (!selection) return;
		try {
			const current = typeof quill.getSelection === "function" ? quill.getSelection() : null;
			if (!current) {
				quill.setSelection(selection.index, selection.length || 0, "silent");
			}
		} catch (e) {
			// ignore
		}
	};

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
		if (v.includes("{%") || v.includes("%}")) return false;
		return v.includes("{{") && v.includes("}}");
	};

	const quill = control.quill || control.editor;

	// Für Quill: Nur Platzhalter als Token, Snippets müssen editierbarer Text bleiben.
	if (hv_is_simple_placeholder(value) && quill && typeof quill.insertEmbed === "function") {
		hv_restore_quill_selection(quill);
		const api = await hv_vorlage_require_quill_placeholders();
		if (api && typeof api.insert_into_quill === "function") {
			api.insert_into_quill(quill, value);
			return;
		}
	}

	// Snippets: Jinja-Delimiter/Operatoren als nicht-editierbare Tokens, Rest editierbar lassen.
	if (String(value || "").includes("{%") && quill && typeof quill.insertEmbed === "function") {
		hv_restore_quill_selection(quill);
		const api = await hv_vorlage_require_quill_placeholders();
		const seq = hv_build_jinja_snippet_sequence(value);
		if (seq && api && typeof api.insert_sequence === "function") {
			if (api.insert_sequence(quill, seq)) {
				return;
			}
		}
	}

	if (quill && quill.insertText) {
		// Text einfügen (editierbar)
		const selection = hv_get_quill_selection_fallback(quill);
		let index = selection ? selection.index : quill.getLength ? quill.getLength() : 0;
		quill.focus && quill.focus();
		if (hv_is_simple_placeholder(value)) {
			quill.insertText(index, ` ${value} `, {
				background: '#e3f2fd',
				color: '#1565c0',
				bold: true,
			});
		} else {
			quill.insertText(index, ` ${value} `, "user");
		}
		quill.setSelection && quill.setSelection(index + value.length + 2, 0);
	} else {
		const content = frm.doc.content || "";
		frm.set_value("content", `${content}${value}`);
	}
};

const HV_VORLAGE_SKIP_TYPES = new Set([
	"Table",
	"Table MultiSelect",
	"Section Break",
	"Column Break",
	"Tab Break",
	"Fold",
	"Button",
	"HTML",
	"Image",
	"Attach",
	"Attach Image",
]);

const hv_scrub = (value) => {
	if (!value) return "";
	if (frappe.model && typeof frappe.model.scrub === "function") {
		return frappe.model.scrub(value);
	}
	return String(value).toLowerCase().replace(/\s+/g, "_");
};

const hv_vorlage_format_field_type = (df) => {
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

const hv_vorlage_is_template_value_type = (valueType) =>
	["String", "Zahl", "Bool", "Datum"].includes((valueType || "String").trim());

const hv_vorlage_doctype_exists = async (doctype) => {
	if (!doctype) return false;
	try {
		// `frappe.db.exists` returns truthy on exists; avoids 404 "DocType ... not found"
		// that `with_doctype` would trigger.
		const exists = await frappe.db.exists("DocType", doctype);
		return Boolean(exists);
	} catch (e) {
		return false;
	}
};

const hv_vorlage_load_meta = (doctype) =>
	new Promise((resolve) => {
		if (!doctype) {
			resolve(null);
			return;
		}
		hv_vorlage_doctype_exists(doctype)
			.then((ok) => {
				if (!ok) {
					resolve(null);
					return;
				}
				frappe.model.with_doctype(doctype, () => resolve(frappe.get_meta(doctype)));
			})
			.catch(() => resolve(null));
	});

const hv_vorlage_build_tree_nodes = async (
	baseKey,
	baseLabel,
	meta,
	visited,
	depth,
	maxDepth
) => {
	const nodes = [];
	if (!meta || !meta.fields) {
		return nodes;
	}

	for (const df of meta.fields) {
		if (!df.fieldname || HV_VORLAGE_SKIP_TYPES.has(df.fieldtype)) {
			continue;
		}

		const label = df.label || df.fieldname;
		const type = hv_vorlage_format_field_type(df);

		// Leaf für das Feld selbst
		nodes.push({
			label: `${baseLabel}: ${label}`,
			placeholder: `{{ ${baseKey}.${df.fieldname} }}`,
			type,
			children: [],
		});

		// Link-Felder: wie im Textbaustein-Editor als Tree in den Ziel-Doctype verzweigen
		if (
			df.fieldtype === "Link" &&
			df.options &&
			visited &&
			!visited.has(df.options) &&
			depth < maxDepth
		) {
			const targetMeta = await hv_vorlage_load_meta(df.options);
			if (!targetMeta) {
				continue;
			}

			const targetKey = hv_scrub(df.options);
			const childVisited = new Set(visited);
			childVisited.add(df.options);

			const childNodes = await hv_vorlage_build_tree_nodes(
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
					placeholder: `{{ ${targetKey}.name }}`,
					type: "Link",
					children: childNodes,
				});
			}
		}
	}

	return nodes;
};

const hv_vorlage_get_requirements = async (frm) => {
	const cached = frm?._hv_requirements_data;
	if (cached && typeof cached === "object") {
		return cached;
	}

	try {
		const r = await frappe.call({
			method: "hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf.get_template_requirements",
			args: { template_doc: hv_get_live_template_doc(frm) },
			quiet: true,
		});
		frm._hv_requirements_data = r.message || {};
		return frm._hv_requirements_data;
	} catch (e) {
		return {};
	}
};

const hv_vorlage_get_mieter_doctype = async (iterationDoctype) => {
	if (!iterationDoctype) {
		return "Contact";
	}
	try {
		const meta = await hv_vorlage_load_meta(iterationDoctype);
		const df = meta?.get_field ? meta.get_field("mieter") : null;
		return (df?.options || "").trim() || "Contact";
	} catch (e) {
		return "Contact";
	}
};

const hv_vorlage_build_iteration_tree = async (iterationDoctype) => {
	const meta = await hv_vorlage_load_meta(iterationDoctype);
	if (!meta || !meta.fields) {
		return [];
	}

	const nodes = [
		{
			label: __("Name"),
			placeholder: "{{ iteration_doc.name }}",
			type: "Name",
			children: [],
		},
	];

	for (const df of meta.fields) {
		if (!df.fieldname || HV_VORLAGE_SKIP_TYPES.has(df.fieldtype)) {
			continue;
		}

		const label = df.label || df.fieldname;
		const type = hv_vorlage_format_field_type(df);

		if (df.fieldtype === "Table" && df.options) {
			const childMeta = await hv_vorlage_load_meta(df.options);
			const children = [];
			(childMeta?.fields || []).forEach((cdf) => {
				if (!cdf.fieldname || HV_VORLAGE_SKIP_TYPES.has(cdf.fieldtype)) {
					return;
				}
				const childLabel = cdf.label || cdf.fieldname;
				const childType = hv_vorlage_format_field_type(cdf);
				children.push({
					label: `${childLabel} [0]`,
					placeholder: `{{ iteration_doc.${df.fieldname}[0].${cdf.fieldname} }}`,
					type: childType,
					children: [],
				});
			});

			nodes.push({
				label: `${label} (${__("Tabelle")})`,
				placeholder: `{{ iteration_doc.${df.fieldname} }}`,
				type: df.options ? `Table → ${df.options}` : "Table",
				children,
			});
			continue;
		}

		if (df.fieldtype === "Link" && df.options) {
			const targetMeta = await hv_vorlage_load_meta(df.options);
			if (targetMeta) {
				const childNodes = await hv_vorlage_build_tree_nodes(
					df.fieldname,
					df.options,
					targetMeta,
					new Set([df.options]),
					0,
					2
				);
				if (childNodes.length) {
					nodes.push({
						label: `${label} → ${df.options}`,
						placeholder: `{{ ${df.fieldname}.name }}`,
						type: "Link",
						children: childNodes,
					});
				}
			}
		}

		nodes.push({
			label,
			placeholder: `{{ iteration_doc.${df.fieldname} }}`,
			type,
			children: [],
		});
	}

	return nodes;
};

const hv_vorlage_get_placeholder_groups = async (frm) => {
	hv_clear_placeholder_cache_if_needed();
	const cacheKey = (() => {
		const iterationDoctype = (frm.doc.haupt_verteil_objekt || "").trim();
		const variables = (frm.doc.variables || []).map((row) => [
			row.variable || "",
			row.variable_type || "",
			row.label || "",
			row.name || "",
		]);
		const requirements = frm._hv_requirements_data || {};
		return JSON.stringify({
			iterationDoctype,
			variables,
			required_fields: requirements.required_fields || [],
			auto_fields: requirements.auto_fields || [],
			template_requirements: requirements.template_requirements || [],
			template_variables: requirements.template_variables || [],
		});
	})();
	frm._hv_placeholder_groups_cache = frm._hv_placeholder_groups_cache || {};
	if (frm._hv_placeholder_groups_cache[cacheKey]) {
		return frm._hv_placeholder_groups_cache[cacheKey];
	}
	const cached = hv_get_cached_placeholder_groups(cacheKey);
	if (cached) {
		frm._hv_placeholder_groups_cache[cacheKey] = cached;
		return cached;
	}

	const groups = [
		{
			label: __("Allgemein"),
			tree: (HV_VORLAGE_BASE_PLACEHOLDERS || []).map((ph) => ({
				label: ph.label,
				placeholder: ph.value,
				children: [],
			})),
		},
	];

	const templateVariableTree = (frm.doc.variables || [])
		.filter((row) => row.variable && hv_vorlage_is_template_value_type(row.variable_type))
		.map((row) => ({
			label: row.label || row.variable,
			placeholder: `{{ ${hv_scrub(row.variable)} }}`,
			children: [],
		}));
	if (templateVariableTree.length) {
		groups.push({
			key: "__template_variables",
			label: __("Vorlagen-Variablen"),
			tree: templateVariableTree,
		});
	}

	const iterationDoctype = (frm.doc.haupt_verteil_objekt || "").trim();
	if (iterationDoctype) {
		const tree = await hv_vorlage_build_iteration_tree(iterationDoctype);
		if (tree.length) {
			groups.push({
				key: "__iteration",
				label: `${__("Iterationsobjekt")}: ${iterationDoctype}`,
				tree,
			});
		}
	}

	// Kontext-Doctypes (typisch im Serienbrief-Kontext vorhanden)
	if (iterationDoctype) {
		const mieterDoctype = await hv_vorlage_get_mieter_doctype(iterationDoctype);
		const ctx = [
			{ key: "wohnung", label: __("Wohnung"), doctype: "Wohnung" },
			{ key: "immobilie", label: __("Immobilie"), doctype: "Immobilie" },
			{ key: "mieter", label: __("Mieter"), doctype: mieterDoctype },
		];

		for (const entry of ctx) {
			if (!(await hv_vorlage_doctype_exists(entry.doctype))) {
				continue;
			}
			const meta = await hv_vorlage_load_meta(entry.doctype);
			if (!meta) continue;
			const tree = await hv_vorlage_build_tree_nodes(
				entry.key,
				entry.doctype,
				meta,
				new Set([entry.doctype]),
				0,
				2
			);
			if (tree.length) {
				groups.push({
					key: `__ctx_${entry.key}`,
					label: `${__("Kontext")}: ${entry.label} (${entry.doctype})`,
					tree,
				});
			}
		}
	}

	// Referenz-Felder aus Anforderungen (Bausteine/Vorlage)
	const requirements = await hv_vorlage_get_requirements(frm);
	const refs = [
		...(requirements?.required_fields || []),
		...(requirements?.auto_fields || []),
	];
	const seen = new Set();
	for (const ref of refs) {
		const refDoctype = String(ref?.doctype || "").trim();
		const fieldname = String(ref?.fieldname || "").trim();
		if (!refDoctype || !fieldname) continue;
		const isList = Boolean(ref?.is_list);
		const signature = `${fieldname}::${refDoctype}::${isList ? "list" : "single"}`;
		if (seen.has(signature)) continue;
		seen.add(signature);

		if (!(await hv_vorlage_doctype_exists(refDoctype))) {
			continue;
		}
		const meta = await hv_vorlage_load_meta(refDoctype);
		if (!meta) continue;

		const treeKey = isList ? `${fieldname}[0]` : fieldname;
		const tree = await hv_vorlage_build_tree_nodes(
			treeKey,
			refDoctype,
			meta,
			new Set([refDoctype]),
			0,
			2
		);
		if (!tree.length) continue;

		groups.push({
			key: `__ref_${signature}`,
			label: `${__("Referenz")}: ${(ref?.label || fieldname)} (${refDoctype})`,
			tree,
		});
	}

	const result = groups.filter((g) => g.tree && g.tree.length);
	frm._hv_placeholder_groups_cache[cacheKey] = result;
	hv_set_cached_placeholder_groups(cacheKey, result);
	return result;
};

const hv_vorlage_open_placeholder_dialog = async (frm) => {
	const picker = await hv_vorlage_require_placeholder_picker();
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
		load_groups: () => hv_vorlage_get_placeholder_groups(frm),
		on_insert: (value) => insert_placeholder(frm, value),
	});
};

const hv_vorlage_open_template_variable_dialog = (frm) => {
	const variables = (frm.doc.variables || [])
		.filter((row) => row.variable && hv_vorlage_is_template_value_type(row.variable_type))
		.map((row) => ({
			label: row.label || row.variable,
			placeholder: `{{ ${hv_scrub(row.variable)} }}`,
		}));

	const dialog = new frappe.ui.Dialog({
		title: __("Vorlagen-Variablen"),
		fields: [
			{
				fieldname: "search",
				fieldtype: "Data",
				label: __("Suche"),
			},
			{
				fieldname: "list",
				fieldtype: "HTML",
			},
			{
				fieldname: "new_section",
				fieldtype: "Section Break",
				label: __("Neue Variable"),
			},
			{
				fieldname: "new_variable",
				fieldtype: "Data",
				label: __("Variablenname"),
				reqd: 1,
			},
			{
				fieldname: "new_type",
				fieldtype: "Select",
				label: __("Typ"),
				options: ["String", "Zahl", "Bool", "Datum"].join("\n"),
				default: "String",
			},
			{
				fieldname: "new_default_string",
				fieldtype: "Data",
				label: __("Default"),
			},
			{
				fieldname: "new_default_number",
				fieldtype: "Float",
				label: __("Default"),
			},
			{
				fieldname: "new_default_bool",
				fieldtype: "Select",
				label: __("Default"),
				options: "\nJa\nNein",
			},
			{
				fieldname: "new_default_date",
				fieldtype: "Date",
				label: __("Default"),
			},
		],
		primary_action_label: __("Anlegen"),
		primary_action: () => {
			const rawName = (dialog.get_value("new_variable") || "").trim();
			if (!rawName) {
				frappe.msgprint({ message: __("Bitte Variablennamen angeben."), indicator: "orange" });
				return;
			}
			const scrubbed = hv_scrub(rawName);
			const exists = (frm.doc.variables || []).some(
				(row) => hv_scrub(row.variable || "") === scrubbed
			);
			if (exists) {
				frappe.msgprint({
					message: __("Variable existiert bereits."),
					indicator: "orange",
				});
				return;
			}
			const row = frm.add_child("variables");
			row.variable = rawName;
			row.label = rawName;
			row.variable_type = (dialog.get_value("new_type") || "String").trim();
			frm.refresh_field("variables");

			const defaultType = (dialog.get_value("new_type") || "String").trim();
			let defaultValue = null;
			if (defaultType === "Zahl") {
				const numberVal = dialog.get_value("new_default_number");
				if (numberVal !== null && numberVal !== undefined && numberVal !== "") {
					defaultValue = numberVal;
				}
			} else if (defaultType === "Datum") {
				const dateVal = dialog.get_value("new_default_date");
				if (dateVal) {
					defaultValue = dateVal;
				}
			} else if (defaultType === "Bool") {
				const boolVal = dialog.get_value("new_default_bool");
				if (boolVal === "Ja") {
					defaultValue = true;
				} else if (boolVal === "Nein") {
					defaultValue = false;
				}
			} else {
				const stringVal = (dialog.get_value("new_default_string") || "").trim();
				if (stringVal) {
					defaultValue = stringVal;
				}
			}

			if (defaultValue !== null) {
				const mapping = hv_parse_variable_values(frm.doc.variablen_werte);
				const key = hv_scrub(rawName);
				mapping[key] = { value: defaultValue, path: "" };
				frappe.model.set_value(
					"Serienbrief Vorlage",
					frm.doc.name,
					"variablen_werte",
					JSON.stringify(mapping)
				);
			}

			hv_update_block_requirements(frm);
			dialog.set_value("new_variable", "");
			dialog.set_value("new_type", "String");
			dialog.set_value("new_default_string", "");
			dialog.set_value("new_default_number", "");
			dialog.set_value("new_default_bool", "");
			dialog.set_value("new_default_date", "");
			renderButtons();
		},
	});

	const listWrapper = $(dialog.get_field("list").wrapper).empty();
	const searchField = dialog.get_field("search");
	const defaultStringField = dialog.get_field("new_default_string");
	const defaultNumberField = dialog.get_field("new_default_number");
	const defaultBoolField = dialog.get_field("new_default_bool");
	const defaultDateField = dialog.get_field("new_default_date");

	const updateDefaultInputs = () => {
		const valueType = (dialog.get_value("new_type") || "String").trim();
		if (defaultStringField?.wrapper) {
			$(defaultStringField.wrapper).toggle(valueType === "String");
		}
		if (defaultNumberField?.wrapper) {
			$(defaultNumberField.wrapper).toggle(valueType === "Zahl");
		}
		if (defaultBoolField?.wrapper) {
			$(defaultBoolField.wrapper).toggle(valueType === "Bool");
		}
		if (defaultDateField?.wrapper) {
			$(defaultDateField.wrapper).toggle(valueType === "Datum");
		}
	};

	const renderButtons = () => {
		const term = (dialog.get_value("search") || "").toLowerCase();
		listWrapper.empty();
		const current = (frm.doc.variables || [])
			.filter((row) => row.variable && hv_vorlage_is_template_value_type(row.variable_type))
			.map((row) => ({
				label: row.label || row.variable,
				placeholder: `{{ ${hv_scrub(row.variable)} }}`,
			}));
		const filtered = current.filter((v) =>
			`${v.label} ${v.placeholder}`.toLowerCase().includes(term)
		);
		if (!filtered.length) {
			listWrapper.html(`<div class="text-muted small">${__("Keine Variablen gefunden.")}</div>`);
			return;
		}
		filtered.forEach((v) => {
			const btn = $(
				`<button type="button" class="btn btn-xs btn-outline-secondary me-2 mb-2"></button>`
			);
			btn.text(v.label);
			btn.on("click", () => insert_placeholder(frm, v.placeholder));
			listWrapper.append(btn);
		});
	};

	searchField?.$input?.on("input", renderButtons);
	dialog.fields_dict.new_type?.$input?.on("change", updateDefaultInputs);
	dialog.show();
	updateDefaultInputs();
	renderButtons();
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

const hv_parse_mapping = (raw) => {
	if (!raw) return {};
	try {
		const data = JSON.parse(raw);
		return typeof data === "object" && data ? data : {};
	} catch (e) {
		return {};
	}
};

const hv_parse_variable_values = (raw) => {
	const data = hv_parse_mapping(raw);
	const result = {};
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
	return result;
};

const hv_clear_intro = (frm) => {
	if (typeof frm?.clear_intro === "function") {
		frm.clear_intro();
		return;
	}
	if (typeof frm?.set_intro === "function") {
		frm.set_intro("");
	}
};

const hv_extract_call_error_message = (err) => {
	const serverMessagesRaw = err?._server_messages || err?.responseJSON?._server_messages;
	if (serverMessagesRaw) {
		try {
			const messages = JSON.parse(serverMessagesRaw);
			if (Array.isArray(messages) && messages.length) {
				return messages
					.map((raw) => {
						if (!raw) return "";
						try {
							const parsed = JSON.parse(raw);
							return parsed?.message || parsed?.exc || raw;
						} catch (e) {
							return raw;
						}
					})
					.filter(Boolean)
					.join("<br>");
			}
		} catch (e) {
			// ignore
		}
	}

	const exc = err?.responseJSON?.exception || err?.exception || err?.message;
	if (exc) {
		return String(exc);
	}

	return __("Fehler beim Laden der Vorlagen-Anforderungen.");
};

const hv_attach_finally = (request, callback) => {
	if (!request) {
		callback();
		return request;
	}
	if (typeof request.finally === "function") {
		return request.finally(callback);
	}
	if (typeof request.always === "function") {
		request.always(callback);
		return request;
	}
	if (typeof request.then === "function") {
		request.then(callback, callback);
		return request;
	}
	callback();
	return request;
};

const hv_handle_requirements_error = (frm, err, { open_mapping } = {}) => {
	const message = hv_extract_call_error_message(err);

	// Persistente Anzeige direkt im Formular (nicht als Toast, der verschwindet).
	if (frm?.set_intro) {
		frm.set_intro(message, "red");
	}

	// Bei expliziter User-Aktion zusätzlich als Dialog, damit es garantiert sichtbar bleibt.
	if (open_mapping) {
		frappe.msgprint({
			title: __("Vorlage unvollständig"),
			indicator: "red",
			message,
		});
	}
};

const hv_update_block_requirements = (frm, { open_mapping } = {}) => {
	frm._hv_placeholder_groups_cache = {};
	if (!frm.doc.textbausteine || !frm.doc.textbausteine.length) {
		return;
	}

	frappe
		.call({
			method: "hausverwaltung.hausverwaltung.doctype.serienbrief_durchlauf.serienbrief_durchlauf.get_template_requirements",
			args: { template_doc: hv_get_live_template_doc(frm) },
			quiet: true,
		})
		.then((r) => {
			hv_clear_intro(frm);
			hv_apply_block_requirements(frm, r.message || {}, { open_mapping });
		})
		.catch((err) => hv_handle_requirements_error(frm, err, { open_mapping }));
};

const hv_apply_block_requirements = (frm, data, { open_mapping } = {}) => {
	frm._hv_requirements_data = data || {};
	const blocks = data.block_requirements || [];
	const byRowname = new Map();

	blocks.forEach((block) => {
		if (block.rowname) {
			byRowname.set(block.rowname, block);
		}
	});

	let touched = false;
	(frm.doc.textbausteine || []).forEach((row) => {
		const block = byRowname.get(row.name);
		const requirements = block?.requirements || [];
		const mapping = hv_parse_mapping(row.pfad_zuordnung);
		const labels = requirements.map((req) => hv_format_requirement(req, mapping)).join(", ");

		if (row.anforderungen !== labels) {
			frappe.model.set_value(row.doctype, row.name, "anforderungen", labels);
			touched = true;
		}
	});

	if (touched) {
		frm.refresh_field("textbausteine");
	}

	if (open_mapping) {
		hv_open_mapping_wizard(frm);
	}
};

const hv_open_preview_dialog = (html) => {
	const win = window.open("", "_blank");
	if (win && win.document) {
		win.document.open();
		win.document.write(html);
		win.document.close();
		return;
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Vorlagen-Preview"),
		size: "large",
		fields: [{ fieldname: "preview", fieldtype: "HTML" }],
	});
	const wrapper = dialog.get_field("preview").$wrapper;
	const iframe = document.createElement("iframe");
	iframe.style.width = "100%";
	iframe.style.height = "70vh";
	iframe.style.border = "1px solid var(--gray-300)";
	iframe.srcdoc = html;
	wrapper.empty().append(iframe);
	dialog.show();
};

const HV_SPLIT_PREVIEW_STYLE_ID = "hv-serienbrief-split-preview-styles";

const hv_ensure_split_preview_styles = () => {
	if (document.getElementById(HV_SPLIT_PREVIEW_STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = HV_SPLIT_PREVIEW_STYLE_ID;
	style.textContent = `
		.hv-split-row {
			display: flex;
			gap: 16px;
			align-items: stretch;
			width: 100%;
		}
		.hv-split-editor {
			flex: 1 1 0;
			min-width: 320px;
			overflow: auto;
		}
		.hv-split-preview {
			flex: 1 1 0;
			min-width: 360px;
			border: 1px solid var(--gray-300);
			border-radius: 4px;
			background: #fff;
			display: flex;
			flex-direction: column;
			overflow: hidden;
		}
		.hv-split-preview .hv-split-status {
			flex: 0 0 auto;
		}
		.hv-split-preview iframe {
			width: 100%;
			border: 0;
			flex: 1 1 auto;
			height: 100%;
		}
		.hv-split-status {
			padding: 8px 10px;
			font-size: 12px;
			color: #666;
			border-bottom: 1px solid var(--gray-200);
		}
		@media (max-width: 1200px) {
			.hv-split-row {
				flex-direction: column;
			}
			.hv-split-preview {
				min-width: 100%;
				min-height: 50vh;
			}
		}
	`;
	document.head.appendChild(style);
};

const hv_init_split_preview = (frm) => {
	if (frm._hv_split_preview) return;
	const layoutWrapper = frm.layout?.wrapper;
	if (!layoutWrapper || !layoutWrapper.length) return;
	const control = frm.get_field("content");

	hv_ensure_split_preview_styles();

	const split = $('<div class="hv-split-row"></div>');
	const editorHost = $('<div class="hv-split-editor"></div>');
	const previewHost = $('<div class="hv-split-preview"></div>');
	const status = $('<div class="hv-split-status text-muted small"></div>').text(__("Lade Vorschau …"));
	const iframe = $('<iframe title="Serienbrief Vorschau"></iframe>');

	layoutWrapper.before(split);
	split.append(editorHost, previewHost);
	editorHost.append(layoutWrapper);
	previewHost.append(status, iframe);

	const syncHeight = () => {
		const rect = split.get(0)?.getBoundingClientRect?.();
		const top = rect ? rect.top : 0;
		const available = Math.max(window.innerHeight - top - 24, 520);
		split.css("min-height", `${available}px`);
		editorHost.css("max-height", `${available}px`);
		editorHost.css("min-height", `${available}px`);
		previewHost.css("max-height", `${available}px`);
		previewHost.css("min-height", `${available}px`);
		const statusHeight = status.outerHeight() || 0;
		iframe.css("min-height", `${Math.max(available - statusHeight, 320)}px`);
		const quill = control?.quill || control?.editor;
		if (quill?.root) {
			// Let the Quill root track the available split-preview height so
			// the editor matches the preview column instead of staying small.
			const toolbar = quill.getModule?.("toolbar")?.container;
			const toolbarHeight = toolbar ? toolbar.getBoundingClientRect().height : 0;
			const editorHeight = Math.max(available - toolbarHeight - 40, 400);
			quill.root.style.minHeight = `${editorHeight}px`;
		}
	};

	let observer = null;
	if (typeof ResizeObserver !== "undefined") {
		observer = new ResizeObserver(syncHeight);
		observer.observe(editorHost.get(0));
	} else {
		setTimeout(syncHeight, 0);
	}
	window.addEventListener("resize", syncHeight);

	frm._hv_split_preview = {
		split,
		editorHost,
		previewHost,
		status,
		iframe,
		observer,
	};
	syncHeight();
};

const hv_set_split_preview_status = (frm, message) => {
	const status = frm._hv_split_preview?.status;
	if (!status) return;
	status.text(message || "");
};

const hv_update_split_preview = (frm, { immediate } = {}) => {
	if (!frm._hv_split_preview_enabled) return;
	if (!frm._hv_split_preview) {
		hv_init_split_preview(frm);
		if (!frm._hv_split_preview) return;
	}
	if (!immediate && frm._hv_split_preview_loading) return;
	const signature = hv_get_split_preview_signature(frm);
	if (!immediate && signature && signature === frm._hv_split_preview_sig) {
		return;
	}
	frm._hv_split_preview_sig = signature;

	frm._hv_split_preview_loading = true;
	hv_set_split_preview_status(frm, __("Lade Vorschau …"));

	const templateDoc = hv_get_live_template_doc(frm);

	const request = frappe
		.call({
			method: "hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.render_template_preview_pdf",
			args: { template_doc: templateDoc, split_preview: 1 },
			quiet: true,
		})
		.then((r) => {
			const pdfBase64 = r?.message?.pdf_base64 || r?.message?.pdf || r?.message;
			if (!pdfBase64) {
				hv_set_split_preview_status(frm, __("Keine PDF-Vorschau verfügbar."));
				return;
			}
			const dataUrl = `data:application/pdf;base64,${pdfBase64}`;
			const frame = frm._hv_split_preview?.iframe;
			if (frame?.length) {
				frame.attr("src", dataUrl);
			}
			hv_set_split_preview_status(frm, "");
		})
		.catch((err) => {
			const message = hv_extract_call_error_message(err) || __("Vorschau konnte nicht geladen werden.");
			hv_set_split_preview_status(frm, message);
		});
	hv_attach_finally(request, () => {
		frm._hv_split_preview_loading = false;
	});
};

const hv_schedule_split_preview = (frm) => {
	if (!frm._hv_split_preview_enabled) return;
	if (frm._hv_split_preview_timeout) {
		clearTimeout(frm._hv_split_preview_timeout);
	}
	frm._hv_split_preview_timeout = setTimeout(() => hv_update_split_preview(frm), 600);
};

const hv_start_split_preview_polling = (frm) => {
	if (!frm._hv_split_preview_enabled) return;
	if (frm._hv_split_preview_interval) return;
	frm._hv_split_preview_interval = setInterval(() => {
		hv_update_split_preview(frm);
	}, 1200);
};

const hv_get_split_preview_signature = (frm) => {
	try {
		return JSON.stringify({
			content_type: (frm.doc.content_type || "").trim() || "Textbaustein (Rich Text)",
			content: hv_get_live_content(frm),
			html_content: hv_get_live_field_value(frm, "html_content"),
			jinja_content: hv_get_live_field_value(frm, "jinja_content"),
			content_position: frm.doc.content_position || "",
			haupt_verteil_objekt: frm.doc.haupt_verteil_objekt || "",
			textbausteine: (frm.doc.textbausteine || []).map((r) => r.baustein || ""),
			variables: (frm.doc.variables || []).map((r) => [r.variable, r.variable_type, r.label]),
		});
	} catch (e) {
		return "";
	}
};

const hv_get_live_content = (frm) => {
	return hv_get_live_field_value(frm, "content");
};

const hv_get_template_content_type = (frm) =>
	(frm?.doc?.content_type || "").trim() || "Textbaustein (Rich Text)";

const hv_get_live_field_value = (frm, fieldname) => {
	const control = frm.get_field(fieldname);
	if (control && typeof control.get_input_value === "function") {
		return control.get_input_value() || "";
	}
	if (control && typeof control.get_value === "function") {
		return control.get_value() || "";
	}
	return frm?.doc?.[fieldname] || "";
};

const hv_get_live_template_source = (frm) => {
	if (hv_get_template_content_type(frm) === "HTML + Jinja") {
		const parts = [hv_get_live_field_value(frm, "jinja_content"), hv_get_live_field_value(frm, "html_content")];
		return parts.filter((p) => String(p || "").trim()).join("\n");
	}
	return hv_get_live_content(frm);
};

const hv_get_live_template_doc = (frm) => ({
	...frm.doc,
	content: hv_get_live_content(frm),
	html_content: hv_get_live_field_value(frm, "html_content"),
	jinja_content: hv_get_live_field_value(frm, "jinja_content"),
});

const hv_set_split_preview_enabled = (frm, enabled, { immediate } = {}) => {
	frm._hv_split_preview_enabled = Boolean(enabled);
	hv_init_split_preview(frm);
	const previewHost = frm._hv_split_preview?.previewHost;
	if (previewHost?.length) {
		previewHost.toggle(Boolean(frm._hv_split_preview_enabled));
	}
	if (frm._hv_split_preview_enabled) {
		hv_update_split_preview(frm, { immediate });
		hv_start_split_preview_polling(frm);
	}
};

const hv_toggle_split_preview = (frm) => {
	hv_set_split_preview_enabled(frm, !frm._hv_split_preview_enabled, { immediate: true });
};

const hv_open_live_preview_tab = (frm) => {
	if (frm._hv_live_preview && !frm._hv_live_preview.closed) {
		frm._hv_live_preview.focus();
		return;
	}

	const win = window.open("", "hv_live_preview");
	if (!win) {
		frappe.msgprint({
			title: __("Popup blockiert"),
			message: __("Bitte erlaube Popups, um die Live-Vorschau zu öffnen."),
			indicator: "orange",
		});
		return;
	}

	frm._hv_live_preview = win;

	const shell = `<!DOCTYPE html>
<html>
<head>
	<meta charset="utf-8">
	<title>Serienbrief Vorschau (PDF)</title>
	<style>
		body { margin: 0; font-family: "Arial", "Helvetica", sans-serif; background: #f8f9fa; }
		#hv-preview-status { padding: 8px 12px; font-size: 12px; color: #555; }
		#hv-preview-frame { width: 100%; height: calc(100vh - 28px); border: 0; background: #fff; }
	</style>
</head>
<body>
	<div id="hv-preview-status">Lade Vorschau …</div>
	<iframe id="hv-preview-frame"></iframe>
	<script>
		const status = document.getElementById("hv-preview-status");
		const frame = document.getElementById("hv-preview-frame");
		const channel = "BroadcastChannel" in window ? new BroadcastChannel("hv_live_preview") : null;
		window.__hv_live_preview_initialized = true;
		let lastTs = null;
		const readStorage = () => {
			try {
				const ts = localStorage.getItem("hv_live_preview_ts");
				if (!ts || ts === lastTs) return;
				lastTs = ts;
				const storedStatus = localStorage.getItem("hv_live_preview_status");
				const storedPdf = localStorage.getItem("hv_live_preview_pdf");
				if (storedStatus !== null) {
					status.textContent = storedStatus;
				}
				if (storedPdf) {
					frame.src = storedPdf;
				}
			} catch (e) {
				// ignore storage errors
			}
		};
		if (channel) {
			channel.onmessage = (event) => {
				const data = event.data || {};
				if (typeof data.status === "string") {
					status.textContent = data.status;
				}
				if (typeof data.pdf === "string") {
					frame.src = data.pdf;
				}
			};
		}
		setInterval(readStorage, 1000);
		readStorage();
		window.addEventListener("message", (event) => {
			const data = event.data || {};
			if (data.source !== "hv_live_preview") return;
			if (typeof data.status === "string") {
				status.textContent = data.status;
			}
			if (typeof data.pdf === "string") {
				frame.src = data.pdf;
			}
		});
	</script>
</body>
</html>`;

	try {
		if (!win.__hv_live_preview_initialized) {
			win.document.open();
			win.document.write(shell);
			win.document.close();
		}
	} catch (e) {
		// ignore cross-window access issues
	}

	hv_send_live_preview(frm, { immediate: true });

	if (frm._hv_live_preview_interval) {
		clearInterval(frm._hv_live_preview_interval);
	}
	frm._hv_live_preview_interval = setInterval(() => {
		hv_send_live_preview(frm);
	}, 1500);
};

const hv_try_update_live_preview_window = (win, payload) => {
	try {
		const doc = win.document;
		const status = doc?.getElementById?.("hv-preview-status");
		const frame = doc?.getElementById?.("hv-preview-frame");
		if (!status || !frame) return false;
		if (typeof payload.status === "string") {
			status.textContent = payload.status;
		}
		if (typeof payload.pdf === "string") {
			frame.src = payload.pdf;
		}
		return true;
	} catch (e) {
		return false;
	}
};

const hv_store_live_preview_payload = (payload) => {
	try {
		if (typeof payload.status === "string") {
			localStorage.setItem("hv_live_preview_status", payload.status);
		}
		if (typeof payload.pdf === "string") {
			localStorage.setItem("hv_live_preview_pdf", payload.pdf);
		}
		localStorage.setItem("hv_live_preview_ts", String(Date.now()));
	} catch (e) {
		// ignore storage errors
	}
};

const hv_post_live_preview = (frm, payload) => {
	hv_store_live_preview_payload(payload);
	if (!frm._hv_live_preview_channel && "BroadcastChannel" in window) {
		frm._hv_live_preview_channel = new BroadcastChannel("hv_live_preview");
	}
	if (frm._hv_live_preview_channel) {
		frm._hv_live_preview_channel.postMessage(payload);
	}
	const win = frm._hv_live_preview;
	if (!win || win.closed) return;
	if (hv_try_update_live_preview_window(win, payload)) return;
	win.postMessage({ source: "hv_live_preview", ...payload }, "*");
};

const hv_send_live_preview = (frm, { immediate } = {}) => {
	if (!frm._hv_live_preview || frm._hv_live_preview.closed) return;
	if (!immediate && frm._hv_live_preview_loading) return;

	const signature = hv_get_preview_signature(frm);
	if (!immediate && signature && signature === frm._hv_preview_last_sig) {
		return;
	}
	frm._hv_preview_last_sig = signature;

	frm._hv_live_preview_loading = true;
	hv_post_live_preview(frm, { status: __("Lade Vorschau …") });

	const request = frappe
		.call({
			method: "hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.render_template_preview_pdf",
			args: { template_doc: hv_get_live_template_doc(frm) },
			quiet: true,
		})
		.then((r) => {
			const pdfBase64 = r?.message?.pdf_base64 || r?.message?.pdf || r?.message;
			if (!pdfBase64) {
				hv_post_live_preview(frm, { status: __("Keine PDF-Vorschau verfügbar.") });
				return;
			}
			const dataUrl = `data:application/pdf;base64,${pdfBase64}`;
			hv_post_live_preview(frm, { pdf: dataUrl, status: "" });
		})
		.catch((err) => {
			const message = hv_extract_call_error_message(err) || __("Vorschau konnte nicht geladen werden.");
			hv_post_live_preview(frm, { status: message });
		});
	hv_attach_finally(request, () => {
		frm._hv_live_preview_loading = false;
	});
};

const hv_schedule_live_preview = (frm) => {
	if (!frm._hv_live_preview || frm._hv_live_preview.closed) return;
	if (frm._hv_live_preview_timeout) {
		clearTimeout(frm._hv_live_preview_timeout);
	}
	frm._hv_live_preview_timeout = setTimeout(() => hv_send_live_preview(frm), 600);
};

const hv_get_preview_signature = (frm) => {
	try {
		return JSON.stringify({
			content_type: (frm.doc.content_type || "").trim() || "Textbaustein (Rich Text)",
			content: hv_get_live_content(frm),
			html_content: hv_get_live_field_value(frm, "html_content"),
			jinja_content: hv_get_live_field_value(frm, "jinja_content"),
			content_position: frm.doc.content_position || "",
			haupt_verteil_objekt: frm.doc.haupt_verteil_objekt || "",
			textbausteine: (frm.doc.textbausteine || []).map((r) => r.baustein || ""),
			variables: (frm.doc.variables || []).map((r) => [r.variable, r.variable_type, r.label]),
		});
	} catch (e) {
		return "";
	}
};

const hv_bind_live_preview_to_quill = (frm) => {
	if (frm._hv_live_preview_quill_bound) return;
	const control = frm.get_field("content");
	const quill = control?.quill || control?.editor;
	if (!quill || typeof quill.on !== "function") return;
	frm._hv_live_preview_quill_bound = true;
	quill.on("text-change", (_delta, _old, source) => {
		if (source === "api") return;
		hv_schedule_live_preview(frm);
		hv_schedule_split_preview(frm);
	});
	// Upgrade {{ … }} tokens to atomic badges only when the editor loses focus,
	// so the DOM rebuild doesn't reset the caret while the user is still typing.
	quill.on("selection-change", (range, oldRange) => {
		if (range === null && oldRange !== null) {
			hv_vorlage_upgrade_inline_placeholders(frm);
		}
	});
	hv_start_split_preview_polling(frm);
};

const hv_render_template_preview = (frm) => {
	const hasBlocks = Array.isArray(frm.doc.textbausteine) && frm.doc.textbausteine.length > 0;
	const standardText = hv_get_live_template_source(frm).trim();
	const hasStandardText = Boolean(standardText);
	if (!hasBlocks && !hasStandardText) {
		frappe.msgprint({
			message: __("Bitte fügen Sie zunächst Standardtext oder Textbausteine hinzu."),
			title: __("Keine Inhalte"),
			indicator: "orange",
		});
		return;
	}

	frappe
		.call({
			method: "hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.render_template_preview_pdf",
			args: { template_doc: hv_get_live_template_doc(frm) },
			freeze: true,
			freeze_message: __("PDF wird erzeugt …"),
		})
		.then((r) => {
			const pdfBase64 = r.message?.pdf_base64 || r.message?.pdf || r.message;
			if (!pdfBase64) {
				frappe.msgprint({
					message: __("Es konnte kein PDF erzeugt werden."),
					title: __("Keine Vorschau"),
					indicator: "orange",
				});
				return;
			}
			const filename = r.message?.filename || "vorlage-preview.pdf";
			const dataUrl = `data:application/pdf;base64,${pdfBase64}`;
			const win = window.open(dataUrl, "_blank");
			if (!win) {
				// Fallback: Download-Link triggern, falls Popup blockiert ist
				const link = document.createElement("a");
				link.href = dataUrl;
				link.download = filename;
				link.style.display = "none";
				document.body.appendChild(link);
				link.click();
				document.body.removeChild(link);
			}
		});
};

const hv_get_start_nodes = (frm) => {
	const base = frm._hv_requirements_data?.haupt_verteil_objekt;
	const links = frm._hv_requirements_data?.empfaenger_links || [];
	const nodes = [];

	if (base) {
		// Start direkt beim Iterations-Doctype, damit auch eigene Felder/Child-Tabellen erreicht werden.
		nodes.push({
			fieldname: "iteration_doc",
			doctype: base,
			label: base,
			path: ["iteration_doc"],
		});
	}

	links.forEach((link) => {
		nodes.push({
			fieldname: link.fieldname,
			doctype: link.doctype,
			label: link.label || link.fieldname,
			path: [link.fieldname],
		});
	});

	return nodes;
};

const hv_load_meta = (doctype) =>
	new Promise((resolve) => {
		if (!doctype) {
			resolve(null);
			return;
		}
		frappe.model.with_doctype(doctype, () => resolve(frappe.get_meta(doctype)));
	});

const hv_find_paths = async (startNodes, targetDoctype, maxDepth = 3) => {
	if (!startNodes || !startNodes.length || !targetDoctype) {
		return [];
	}

	const queue = [];
	startNodes.forEach((node) => {
		if (node.doctype === targetDoctype) {
			queue.push({ path: node.path, doctype: node.doctype });
		} else {
			queue.push({ path: node.path, doctype: node.doctype });
		}
	});

	const results = [];
	const visitedKey = (doctype, path) => `${doctype}::${path.join(".")}`;
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

		if (current.path.length >= maxDepth) {
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
				// Child-Tabellen erlauben Pfade in den Child-DocType hinein
				const nextPath = [...current.path, df.fieldname];
				queue.push({ path: nextPath, doctype: df.options });
			}
		});
	}

	return results;
};

const hv_collect_reachable_doctypes = async (startNodes, maxDepth = 3) => {
	if (!startNodes || !startNodes.length) {
		return [];
	}

	const queue = startNodes.map((node) => ({
		path: node.path || [],
		doctype: node.doctype,
	}));
	const seen = new Set();
	const found = new Set();

	while (queue.length) {
		const current = queue.shift();
		const key = `${current.doctype}::${current.path.join(".")}`;
		if (seen.has(key)) {
			continue;
		}
		seen.add(key);

		if (current.doctype) {
			found.add(current.doctype);
		}

		if (current.path.length >= maxDepth) {
			continue;
		}

		const meta = await hv_load_meta(current.doctype);
		if (!meta || !meta.fields) {
			continue;
		}

		meta.fields.forEach((df) => {
			if ((df.fieldtype === "Link" || df.fieldtype === "Table") && df.options) {
				found.add(df.options);
				const nextPath = [...current.path, df.fieldname];
				queue.push({ path: nextPath, doctype: df.options });
			}
		});
	}

	return Array.from(found);
};

const hv_render_path_picker = (frm, requirement, field, existingValue) => {
	const wrapper = $(field.wrapper).empty();
	const input = $(`<input type="text" class="form-control" />`);
	input.val(existingValue || "");
	wrapper.append(input);

	const helper = $(`<div class="mt-2"></div>`);
	const btn = $(`<button type="button" class="btn btn-xs btn-secondary">${__("Pfad wählen")}</button>`);
	helper.append(btn);
	wrapper.append(helper);

	btn.on("click", async () => {
		btn.prop("disabled", true);
		btn.text(__("Lade Pfade ..."));
		const startNodes = hv_get_start_nodes(frm);
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

const hv_open_mapping_wizard = (frm) => {
	const data = frm._hv_requirements_data || {};
	const blockMap = new Map();

	(frm.doc.textbausteine || []).forEach((row) => {
		if (!row.name) return;
		blockMap.set(row.name, {
			rowname: row.name,
			block: row.baustein,
			block_title: row.baustein || row.name,
			requirements: [],
		});
	});

	(data.block_requirements || []).forEach((entry) => {
		const existing = blockMap.get(entry.rowname) || {};
		blockMap.set(entry.rowname, { ...existing, ...entry, requirements: entry.requirements || [] });
	});

	(data.block_variables || []).forEach((entry) => {
		const existing = blockMap.get(entry.rowname) || {};
		blockMap.set(entry.rowname, { ...existing, ...entry, requirements: entry.requirements || existing.requirements || [] });
	});

	const templateRequirements = data.template_requirements || [];
	const templateVariables = (frm.doc.variables || []).filter(
		(row) => row.variable && hv_vorlage_is_template_value_type(row.variable_type)
	);
	const blocks = Array.from(blockMap.values());
	if (templateRequirements.length || templateVariables.length) {
		blocks.unshift({
			rowname: "__template__",
			block: "__template__",
			block_title: __("Vorlage"),
			requirements: templateRequirements,
			variables: templateVariables,
			is_template: true,
		});
	}
	if (!blocks.length) {
		frappe.msgprint({
			message: __("Keine Anforderungen gefunden."),
			title: __("Hinweis"),
			indicator: "blue",
		});
		return;
	}

	const requiredDoctypes = new Set();
	blocks.forEach((block) => {
		(block?.requirements || []).forEach((req) => {
			if (req?.doctype) requiredDoctypes.add(req.doctype);
		});
	});

	const blockOptions = blocks.map((b) => ({
		label: b.is_template ? __("Vorlage") : `${b.block_title || b.block || __("Baustein")} (${b.rowname})`,
		rowname: b.rowname,
	}));

	let currentBlock = blockOptions[0]?.rowname;
	const dialog = new frappe.ui.Dialog({
		title: __("Feldpfade & Variablen"),
		fields: [
			{
				fieldname: "block",
				fieldtype: "Select",
				label: __("Baustein"),
				options: blockOptions.map((o) => o.label),
				default: blockOptions[0]?.label,
			},
			{
				fieldname: "requirements",
				fieldtype: "HTML",
				label: __("Zuordnungen"),
			},
		],
		primary_action_label: __("Speichern"),
		primary_action() {},
	});

	const reqContainer = $(dialog.get_field("requirements").wrapper).empty();

	const renderRequirements = () => {
		const selectedLabel = dialog.get_value("block") || blockOptions[0]?.label;
		const selected = blockOptions.find((o) => o.label === selectedLabel) || blockOptions[0];
		const block = blocks.find((b) => b.rowname === selected?.rowname);
		if (!block) {
			reqContainer.html(`<div class="text-muted small">${__("Keine Anforderungen.")}</div>`);
			return;
		}

		currentBlock = block.rowname;
		const isTemplate = block.rowname === "__template__";
		const row = (frm.doc.textbausteine || []).find((r) => r.name === block.rowname);
		const mapping = hv_parse_mapping(isTemplate ? frm.doc.pfad_zuordnung : row?.pfad_zuordnung);
		const variableMapping = hv_parse_variable_values(
			isTemplate ? frm.doc.variablen_werte : row?.variablen_werte
		);

		reqContainer.empty();
		const rows = [];
		const variableRows = [];

		(block.requirements || []).forEach((req) => {
			const rowDiv = $(`
				<div class="form-group">
					<label class="control-label">${frappe.utils.escape_html(req.label || req.fieldname)} <span class="text-muted">(${frappe.utils.escape_html(req.doctype)})</span></label>
					<div class="control-input"></div>
				</div>
			`);
			reqContainer.append(rowDiv);
			const field = { wrapper: rowDiv.find(".control-input")[0] };
			const existing = hv_pick_mapping_value(mapping, req) || req.path;
			const getValue = hv_render_path_picker(frm, req, field, existing);
			rows.push({ req, getValue });
		});

		if ((block.variables || []).length) {
			reqContainer.append(
				`<div class="fw-semibold mt-3 mb-1">${__("Block-Variablen")}</div>`
			);
		}

		(block.variables || []).forEach((variable) => {
			const key = variable.key || hv_scrub(variable.variable || variable.label);
			const existing = variableMapping[key] || {};
			const rowDiv = $(`
				<div class="form-group">
					<label class="control-label">${frappe.utils.escape_html(variable.label || variable.variable || key)}</label>
					<div class="row gx-2 align-items-start">
						<div class="col-sm-6 mb-2"><input type="text" class="form-control" placeholder="${__("Fester Wert")}" /></div>
						<div class="col-sm-6 mb-2 d-flex gap-1">
							<input type="text" class="form-control" placeholder="${__("Pfad (optional)")}" />
							<button type="button" class="btn btn-xs btn-secondary hv-path-picker-btn">${__("Pfad wählen")}</button>
						</div>
					</div>
					<div class="help-box small text-muted">${__("Pfad überschreibt den festen Wert. Hänge [] an, um eine Child-Tabelle als Liste zu übernehmen.")}${variable.description || variable.beschreibung ? ` — ${frappe.utils.escape_html(variable.description || variable.beschreibung)}` : ""}</div>
				</div>
			`);
			reqContainer.append(rowDiv);
			const valueInput = rowDiv.find("input").eq(0);
			const pathInput = rowDiv.find("input").eq(1);
			const pathBtn = rowDiv.find(".hv-path-picker-btn");
			valueInput.val(existing.value || "");
			pathInput.val(existing.path || "");

			pathBtn.on("click", async () => {
				const startNodes = hv_get_start_nodes(frm);
				if (!startNodes.length) {
					frappe.msgprint({
						message: __("Keine Start-Pfade gefunden. Bitte Iterations-Doctype wählen und speichern."),
						title: __("Pfad wählen"),
						indicator: "orange",
					});
					return;
				}

				const doctypeOptionsRaw = await hv_collect_reachable_doctypes(startNodes, 4);
				const doctypeOptionsFiltered = doctypeOptionsRaw.filter((d) => requiredDoctypes.has(d));
				const doctypeOptions = doctypeOptionsFiltered.length ? doctypeOptionsFiltered : doctypeOptionsRaw;
				if (!doctypeOptions.length) {
					frappe.msgprint({
						message: __("Keine verknüpften Doctypes gefunden."),
						title: __("Pfad wählen"),
						indicator: "orange",
					});
					return;
				}

				const picker = new frappe.ui.Dialog({
					title: __("Pfad auswählen"),
					fields: [
						{
							fieldname: "target",
							fieldtype: "Select",
							label: __("Ziel-Doctype"),
							options: doctypeOptions,
							default: doctypeOptions[0],
						},
						{
							fieldname: "path",
							fieldtype: "Select",
							label: __("Pfad"),
							options: [],
						},
						{
							fieldname: "return_list",
							fieldtype: "Check",
							label: __("Als Liste übernehmen"),
							default: 0,
						},
					],
					primary_action_label: __("Übernehmen"),
					async primary_action(values) {
						let chosenPath = values.path || "";
						if (values.return_list && chosenPath && !chosenPath.endsWith("[]")) {
							chosenPath = `${chosenPath}[]`;
						}
						if (chosenPath) {
							pathInput.val(chosenPath);
						}
						picker.hide();
					},
				});

				const updatePaths = async () => {
					const pathField = picker.get_field("path");
					const target = picker.get_value("target");
					if (!target) {
						if (pathField) {
							pathField.df.options = [];
							pathField.refresh_input();
						}
						picker.set_value("path", "");
						return;
					}
					picker.get_primary_btn().prop("disabled", true);
					if (pathField) {
						pathField.df.options = [__("Lade…")];
						pathField.refresh_input();
					}
					const paths = await hv_find_paths(startNodes, target, 4);
					if (pathField) {
						pathField.df.options = paths;
						pathField.refresh_input();
					}
					if (paths.length) {
						picker.set_value("path", paths[0]);
					} else {
						picker.set_value("path", "");
						frappe.msgprint({
							message: __("Keine Pfade gefunden."),
							title: __("Hinweis"),
							indicator: "orange",
						});
					}
					picker.get_primary_btn().prop("disabled", false);
				};

				picker.fields_dict.target.$input.on("change", updatePaths);
				picker.show();
				updatePaths();
			});

			variableRows.push({
				key,
				getValue: () => (valueInput.val() || "").trim(),
				getPath: () => (pathInput.val() || "").trim(),
			});
		});

		if (!rows.length && !variableRows.length) {
			reqContainer.html(`<div class="text-muted small">${__("Keine Anforderungen.")}</div>`);
		}

		const saveBtn = dialog.get_primary_btn();
		saveBtn.off("click");
		saveBtn.on("click", () => {
			const newMapping = {};
			rows.forEach(({ req, getValue }) => {
				const val = (getValue() || "").trim();
				if (val) {
					newMapping[req.req_key] = val;
				}
			});

			const newVariableMapping = {};
			variableRows.forEach(({ key, getValue, getPath }) => {
				const value = getValue();
				const path = getPath();
				if (value || path) {
					newVariableMapping[key] = { value, path };
				}
			});

			if (currentBlock === "__template__") {
				frappe.model.set_value(
					"Serienbrief Vorlage",
					frm.doc.name,
					"pfad_zuordnung",
					Object.keys(newMapping).length ? JSON.stringify(newMapping) : ""
				);
				frappe.model.set_value(
					"Serienbrief Vorlage",
					frm.doc.name,
					"variablen_werte",
					Object.keys(newVariableMapping).length ? JSON.stringify(newVariableMapping) : ""
				);
			} else {
				frappe.model.set_value(
					"Serienbrief Vorlagenbaustein",
					currentBlock,
					"pfad_zuordnung",
					Object.keys(newMapping).length ? JSON.stringify(newMapping) : ""
				);
				frappe.model.set_value(
					"Serienbrief Vorlagenbaustein",
					currentBlock,
					"variablen_werte",
					Object.keys(newVariableMapping).length ? JSON.stringify(newVariableMapping) : ""
				);
			}
			dialog.hide();
			hv_update_block_requirements(frm);
		});
	};

	dialog.fields_dict.block.df.onchange = renderRequirements;
	dialog.get_field("block").refresh_input();
	renderRequirements();
	dialog.show();
};

const hv_open_copy_dialog = (frm) => {
	if (frm.is_new()) {
		frappe.msgprint({
			message: __("Bitte speichere die Vorlage zuerst, bevor du sie kopierst."),
			indicator: "orange",
		});
		return;
	}

	const baseTitle = frm.doc.title || frm.doc.name || "";
	const defaultTitle = baseTitle ? __("Kopie von {0}", [baseTitle]) : "";

	const dialog = new frappe.ui.Dialog({
		title: __("Vorlage kopieren"),
		fields: [
			{
				fieldname: "new_title",
				fieldtype: "Data",
				label: __("Neuer Titel"),
				reqd: 1,
				default: defaultTitle,
				description: __("Erstellt eine neue Vorlage mit allen Bausteinen und Einstellungen."),
			},
		],
		primary_action_label: __("Kopieren"),
		primary_action(values) {
			const newTitle = (values.new_title || "").trim();
			if (!newTitle) {
				frappe.msgprint({ message: __("Bitte gib einen Titel ein."), indicator: "orange" });
				return;
			}

			dialog.disable_primary_action();
			const request = frappe
				.call({
					method: "hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.copy_serienbrief_vorlage",
					args: { template: frm.doc.name, new_title: newTitle },
					freeze: true,
					freeze_message: __("Vorlage wird kopiert …"),
				})
				.then((r) => {
					const newName = r.message?.name || r.message;
					dialog.hide();
					if (newName) {
						frappe.show_alert({
							message: __("Neue Vorlage angelegt: {0}", [newName]),
							indicator: "green",
						});
						frappe.set_route("Form", "Serienbrief Vorlage", newName);
					}
				});
			hv_attach_finally(request, () => {
				dialog.enable_primary_action();
			});
		},
	});

	dialog.show();
};

frappe.ui.form.on("Serienbrief Vorlage", {
refresh(frm) {
	frm._hv_placeholder_groups_cache = {};
	hv_clear_placeholder_cache_if_needed();
	frm.set_df_property("variables", "hidden", 1);
	(frm.doc.variables || []).forEach((row) => {
		const valueType = (row.variable_type || "").trim();
		if (!valueType || !hv_vorlage_is_template_value_type(valueType)) {
			frappe.model.set_value(row.doctype, row.name, "variable_type", "String");
		}
	});
	hv_ensure_placeholder_editor_ready(frm);
	hv_vorlage_enlarge_content_editor(frm);
	frm.set_df_property(
		"textbausteine",
		"description",
		__(
			"Optional: Ergänze hier Standardbausteine wie Anrede/Unterschrift; pro Zeile kannst du über das Feld 'Position' festlegen, ob der Baustein vor oder nach dem Standardtext steht. Ohne Angabe gilt die Einstellung 'Standardtext-Position'."
		)
	);
	append_placeholder_panel(frm);
	hv_vorlage_sync_textbausteine_from_content(frm);
	hv_vorlage_toggle_block_position_ui(frm);
	hv_vorlage_toggle_textbausteine_table(frm);
	hv_apply_editor_access_mode(frm);
	hv_update_block_requirements(frm);
	if (!frm._hv_textbausteine_toggle_added) {
		frm._hv_textbausteine_toggle_added = true;
		frm.add_custom_button(__("Textbausteine anzeigen/ausblenden"), () => {
			frm._hv_show_textbausteine_table = !frm._hv_show_textbausteine_table;
			hv_vorlage_toggle_textbausteine_table(frm);
		});
	}
	frm.add_custom_button(__("In Serienbrief laden"), () => {
		if (frm.is_new()) {
			frappe.msgprint({
				message: __("Bitte speichere die Vorlage zuerst."),
				indicator: "orange",
			});
			return;
		}

		const prefill = {
			vorlage: frm.doc.name,
			title: frm.doc.title,
		};

		const open_dialog = hausverwaltung?.serienbrief?.open_new_durchlauf_dialog;
		if (typeof open_dialog === "function") {
			open_dialog(prefill);
			return;
		}

		// Fallback, falls das List-Bundle noch nicht geladen ist.
		frappe.require(
			"/assets/hausverwaltung/js/serienbrief_durchlauf_list.js",
			() => {
				hausverwaltung.serienbrief.open_new_durchlauf_dialog(prefill);
			}
		);
	});
	if (!frm.is_new()) {
		frm.add_custom_button(__("Vorlage kopieren"), () => hv_open_copy_dialog(frm));
	}
	frm.add_custom_button(__("Vorlage anzeigen (ohne Felder)"), () => hv_render_template_preview(frm));
	frm.add_custom_button(__("Live-Vorschau (Tab)"), () => hv_open_live_preview_tab(frm));
	frm.add_custom_button(__("Split-Vorschau"), () => hv_toggle_split_preview(frm));
	hv_set_split_preview_enabled(frm, true, { immediate: true });
},
	after_save(frm) {
		hv_ensure_placeholder_editor_ready(frm);
		hv_update_block_requirements(frm);
		hv_send_live_preview(frm);
		hv_update_split_preview(frm, { immediate: true });
	},
content(frm) {
	// Sync inline block references -> child table, so requirements/mapping stay consistent.
	// The placeholder badge upgrade runs on editor blur instead, to keep the caret stable
	// while typing.
	if (frm._hv_sync_textbausteine_timeout) {
		clearTimeout(frm._hv_sync_textbausteine_timeout);
	}
	frm._hv_sync_textbausteine_timeout = setTimeout(() => {
		hv_vorlage_sync_textbausteine_from_content(frm);
	}, 250);
	hv_vorlage_toggle_block_position_ui(frm);
	hv_schedule_live_preview(frm);
	hv_schedule_split_preview(frm);
},
content_type(frm) {
	hv_vorlage_toggle_block_position_ui(frm);
	hv_vorlage_sync_textbausteine_from_content(frm);
	hv_apply_editor_access_mode(frm);
	hv_schedule_live_preview(frm);
	hv_schedule_split_preview(frm);
},
html_content(frm) {
	hv_vorlage_sync_textbausteine_from_content(frm);
	hv_schedule_live_preview(frm);
	hv_schedule_split_preview(frm);
},
jinja_content(frm) {
	hv_vorlage_sync_textbausteine_from_content(frm);
	hv_schedule_live_preview(frm);
	hv_schedule_split_preview(frm);
},
	textbausteine_on_form_rendered(frm) {
		hv_update_block_requirements(frm);
		hv_vorlage_toggle_block_position_ui(frm);
		hv_vorlage_toggle_textbausteine_table(frm);
		hv_schedule_live_preview(frm);
		hv_schedule_split_preview(frm);
},
haupt_verteil_objekt(frm) {
	frm._hv_placeholder_groups_cache = {};
	hv_schedule_live_preview(frm);
	hv_schedule_split_preview(frm);
},
});

frappe.ui.form.on("Serienbrief Vorlagenbaustein", {
	baustein(frm) {
		hv_update_block_requirements(frm);
		hv_schedule_live_preview(frm);
		hv_schedule_split_preview(frm);
	},
});

frappe.ui.form.on("Serienbrief Vorlage Variable", {
	variable(frm) {
		frm._hv_placeholder_groups_cache = {};
		hv_schedule_live_preview(frm);
		hv_schedule_split_preview(frm);
	},
	variable_type(frm) {
		frm._hv_placeholder_groups_cache = {};
		hv_schedule_live_preview(frm);
		hv_schedule_split_preview(frm);
	},
	label(frm) {
		frm._hv_placeholder_groups_cache = {};
		hv_schedule_live_preview(frm);
		hv_schedule_split_preview(frm);
	},
});
