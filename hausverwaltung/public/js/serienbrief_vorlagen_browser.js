// Gemeinsamer "File Explorer" für Serienbrief Vorlagen.
// Wird sowohl von der Seite `serienbrief_vorlagenbaum` als auch vom
// Durchlauf-Dialog (Picker-Modus) genutzt.
//
// API:
//   hausverwaltung.serienbrief.mount_vorlagen_browser($container, opts)
//     -> { refresh, set_kategorie, destroy }
//   hausverwaltung.serienbrief.open_vorlage_picker({ title, on_pick, initial_kategorie })
//
// opts.mode: "manage" (Default) = alle CRUD-Aktionen; "picker" = nur Auswahl.

frappe.provide("hausverwaltung.serienbrief");

const HV_BROWSER_STYLE_ID = "hv-serienbrief-vorlagen-browser-styles";

const hv_browser_ensure_styles = () => {
	if (document.getElementById(HV_BROWSER_STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = HV_BROWSER_STYLE_ID;
	style.textContent = `
		.hv-vorlagenbaum-layout {
			display: flex;
			gap: 16px;
			align-items: stretch;
		}
		.hv-vorlagenbaum-layout.hv-preview-layout {
			min-height: 500px;
		}
		.hv-vorlagenbaum-list {
			flex: 1 1 auto;
			display: flex;
			flex-direction: column;
			min-height: 0;
			overflow: hidden;
			border: 1px solid var(--border-color, #d9d9d9);
			border-radius: 8px;
			padding: 12px;
			background: var(--card-bg, #fff);
		}
		.hv-vorlagenbaum-list .hv-breadcrumb,
		.hv-vorlagenbaum-list .hv-vorlagenbaum-toolbar { flex: 0 0 auto; }
		.hv-vorlagenbaum-list .hv-template-list {
			flex: 1 1 auto;
			min-height: 0;
			overflow-y: auto;
			padding-right: 4px;
		}
		.hv-breadcrumb {
			display: flex;
			flex-wrap: wrap;
			gap: 4px;
			align-items: center;
			padding: 4px 2px 10px;
			margin-bottom: 8px;
			border-bottom: 1px solid var(--border-color, #eee);
			font-size: 14px;
		}
		.hv-breadcrumb .hv-breadcrumb-item {
			color: var(--primary, #2490ef);
			cursor: pointer;
		}
		.hv-breadcrumb .hv-breadcrumb-item:hover { text-decoration: underline; }
		.hv-breadcrumb .hv-breadcrumb-current {
			font-weight: 600;
			color: var(--text-color);
		}
		.hv-breadcrumb .hv-breadcrumb-sep { color: var(--text-muted, #666); }
		.hv-vorlagenbaum-toolbar {
			display: flex;
			gap: 12px;
			align-items: center;
			flex-wrap: wrap;
			margin-bottom: 12px;
		}
		.hv-vorlagenbaum-toolbar-actions {
			margin-left: auto;
			display: flex;
			gap: 8px;
			align-items: center;
		}
		.hv-vorlagenbaum-toolbar-actions .btn { white-space: nowrap; }
		.hv-vorlagenbaum-toolbar .form-control { max-width: 320px; }
		.hv-vorlagenbaum-list .hv-template-item {
			padding: 10px 8px;
			border-bottom: 1px solid var(--border-color, #eee);
		}
		.hv-vorlagenbaum-list .hv-template-item:last-child { border-bottom: none; }
		.hv-vorlagenbaum-list.hv-picker-mode .hv-template-item { cursor: pointer; }
		.hv-vorlagenbaum-list.hv-picker-mode .hv-template-item:hover { background: var(--bg-light-gray, #f5f7fa); }
		.hv-vorlagenbaum-list.hv-manage-mode .hv-template-item { cursor: pointer; }
		.hv-vorlagenbaum-list.hv-manage-mode .hv-template-item:hover { background: var(--bg-light-gray, #f5f7fa); }
		.hv-vorlagenbaum-list.hv-picker-mode .hv-template-item.hv-selected {
			background: var(--control-bg, #eef3ff);
			box-shadow: inset 3px 0 0 var(--primary, #2490ef);
		}
		.hv-vorlagenbaum-list.hv-manage-mode .hv-template-item.hv-selected {
			background: var(--control-bg, #eef3ff);
			box-shadow: inset 3px 0 0 var(--primary, #2490ef);
		}
		.hv-template-row {
			display: flex;
			align-items: flex-start;
			justify-content: space-between;
			gap: 12px;
		}
		.hv-template-main { min-width: 0; flex: 1 1 auto; }
		.hv-template-actions { display: flex; gap: 6px; flex: 0 0 auto; }
		.hv-template-actions .btn { white-space: nowrap; }
		.hv-vorlagenbaum-list .hv-template-title { font-weight: 600; }
		.hv-vorlagenbaum-list .hv-template-meta {
			font-size: 12px;
			color: var(--text-muted, #666);
		}
		.hv-vorlagenbaum-empty { color: var(--text-muted, #666); padding: 12px 4px; }
		.hv-folder-item {
			padding: 8px;
			border: 1px solid var(--border-color, #eee);
			border-radius: 6px;
			margin-bottom: 8px;
			background: var(--card-bg, #fff);
			display: flex;
			align-items: center;
			justify-content: space-between;
			gap: 12px;
			cursor: pointer;
		}
		.hv-vorlagenbaum-preview {
			display: flex;
			flex-direction: column;
			flex: 0 1 44%;
			min-width: 360px;
			min-height: 0;
			border: 1px solid var(--border-color, #d9d9d9);
			border-radius: 8px;
			background: var(--card-bg, #fff);
			overflow: hidden;
		}
		.hv-vorlagenbaum-preview-title,
		.hv-vorlagenbaum-preview-status { flex: 0 0 auto; }
		.hv-vorlagenbaum-preview-title {
			padding: 10px 12px;
			border-bottom: 1px solid var(--border-color, #eee);
			font-weight: 600;
		}
		.hv-vorlagenbaum-preview-status {
			padding: 8px 12px;
			border-bottom: 1px solid var(--border-color, #eee);
		}
		.hv-vorlagenbaum-preview iframe {
			width: 100%;
			flex: 1 1 auto;
			min-height: 480px;
			border: 0;
			background: #fff;
		}
		.hv-folder-title {
			font-weight: 600;
			display: flex;
			align-items: center;
			gap: 6px;
		}
		.hv-folder-actions { display: flex; gap: 6px; }
		@media (max-width: 900px) {
			.hv-vorlagenbaum-layout { flex-direction: column; }
			.hv-vorlagenbaum-layout.hv-preview-layout { height: auto; }
			.hv-vorlagenbaum-list { overflow: visible; }
			.hv-vorlagenbaum-list .hv-template-list { overflow-y: visible; }
			.hv-vorlagenbaum-preview { min-width: 0; }
		}
	`;
	document.head.appendChild(style);
};

const hv_browser_render_fulltext_results = (dialog, results) => {
	const wrapper = dialog.get_field("results_html").$wrapper;
	if (!results || !results.length) {
		wrapper.html(`<div class="text-muted">${__("Keine Treffer gefunden.")}</div>`);
		return;
	}
	const items = results
		.map((row) => {
			const title = frappe.utils.escape_html(row.title || row.name);
			const snippet = row.snippet ? frappe.utils.escape_html(row.snippet) : "";
			const blockInfo = row.matched_block ? frappe.utils.escape_html(row.matched_block) : "";
			const link = `/app/serienbrief-vorlage/${encodeURIComponent(row.name)}`;
			return `
				<div class="mb-3">
					<div><a href="${link}">${title}</a></div>
					${blockInfo ? `<div class="text-muted small">${blockInfo}</div>` : ""}
					${snippet ? `<div class="text-muted small">${snippet}</div>` : ""}
				</div>
			`;
		})
		.join("");
	wrapper.html(items);
};

const hv_browser_open_fulltext_dialog = (on_pick) => {
	const dialog = new frappe.ui.Dialog({
		title: __("Volltextsuche in Vorlagen"),
		fields: [
			{
				fieldtype: "Small Text",
				fieldname: "query",
				label: __("Suchtext"),
				reqd: 1,
				description: __("Satz oder Textausschnitt eingeben"),
			},
			{ fieldtype: "Int", fieldname: "limit", label: __("Max. Treffer"), default: 20 },
			{ fieldtype: "HTML", fieldname: "results_html" },
		],
		primary_action_label: __("Suchen"),
		primary_action(values) {
			const query = (values.query || "").trim();
			const limit = values.limit || 20;
			if (!query) {
				frappe.msgprint({
					message: __("Bitte gib einen Suchtext ein."),
					indicator: "orange",
				});
				return;
			}
			dialog.disable_primary_action();
			dialog.get_field("results_html").$wrapper.html(__("Suche läuft..."));
			frappe
				.call({
					method: "hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.search_serienbrief_vorlagen",
					args: { query, limit },
				})
				.then((r) => {
					const results = r.message || [];
					if (typeof on_pick === "function") {
						// Render als anklickbare Liste im Picker-Modus
						const wrapper = dialog.get_field("results_html").$wrapper;
						if (!results.length) {
							wrapper.html(
								`<div class="text-muted">${__("Keine Treffer gefunden.")}</div>`
							);
							return;
						}
						const items = results
							.map((row, idx) => {
								const title = frappe.utils.escape_html(row.title || row.name);
								const snippet = row.snippet
									? frappe.utils.escape_html(row.snippet)
									: "";
								return `
									<div class="mb-3 hv-fulltext-hit" data-idx="${idx}" style="cursor:pointer;padding:6px;border-radius:4px;">
										<div><b>${title}</b></div>
										${snippet ? `<div class="text-muted small">${snippet}</div>` : ""}
									</div>
								`;
							})
							.join("");
						wrapper.html(items);
						wrapper.find(".hv-fulltext-hit").on("click", (e) => {
							const idx = Number($(e.currentTarget).data("idx"));
							const row = results[idx];
							if (!row) return;
							dialog.hide();
							on_pick(row);
						});
					} else {
						hv_browser_render_fulltext_results(dialog, results);
					}
				})
				.finally(() => dialog.enable_primary_action());
		},
	});
	dialog.show();
	dialog.get_field("query").$input?.focus();
};

hausverwaltung.serienbrief.mount_vorlagen_browser = ($container, opts = {}) => {
	hv_browser_ensure_styles();

	const mode = opts.mode === "picker" ? "picker" : "manage";
	const is_picker = mode === "picker";
	const on_template_pick = typeof opts.on_template_pick === "function" ? opts.on_template_pick : null;

	const manageActionsHtml = is_picker
		? ""
		: `
			<button class="btn btn-sm btn-default hv-back-folder">${__("Zurück")}</button>
			<button class="btn btn-sm btn-secondary hv-add-folder">${__("Ordner hinzufügen")}</button>
			<button class="btn btn-sm btn-primary hv-add-template">${__("Vorlage hinzufügen")}</button>
		`;

	const backBtnPickerHtml = is_picker
		? `<button class="btn btn-sm btn-default hv-back-folder">${__("Zurück")}</button>`
		: "";

	const previewHtml = `
		<div class="hv-vorlagenbaum-preview">
			<div class="hv-vorlagenbaum-preview-title">${__("Vorschau")}</div>
			<div class="hv-vorlagenbaum-preview-status text-muted small">
				${__("Klicke links auf eine Vorlage, um die PDF-Vorschau zu laden.")}
			</div>
			<iframe title="${__("Serienbrief Vorschau")}"></iframe>
		</div>
	`;

	const layout = $(`
		<div class="hv-vorlagenbaum-layout hv-preview-layout">
			<div class="hv-vorlagenbaum-list ${is_picker ? "hv-picker-mode" : "hv-manage-mode"}">
				<nav class="hv-breadcrumb"></nav>
				<div class="hv-vorlagenbaum-toolbar">
					<input type="text" class="form-control input-sm hv-filter"
						placeholder="${__("Titel oder Notiz filtern")}">
					<button class="btn btn-sm btn-default hv-fulltext-search">${__("Volltextsuche")}</button>
					<div class="hv-vorlagenbaum-toolbar-actions">
						${backBtnPickerHtml}
						${manageActionsHtml}
					</div>
				</div>
				<div class="hv-template-list"></div>
			</div>
			${previewHtml}
		</div>
	`);

	$container.empty().append(layout);

	const listWrapper = layout.find(".hv-template-list");
	const filterInput = layout.find(".hv-filter");
	const breadcrumbWrapper = layout.find(".hv-breadcrumb");
	const backFolderBtn = layout.find(".hv-back-folder");
	const addFolderBtn = layout.find(".hv-add-folder");
	const addTemplateBtn = layout.find(".hv-add-template");
	const fulltextBtn = layout.find(".hv-fulltext-search");
	const previewTitle = layout.find(".hv-vorlagenbaum-preview-title");
	const previewStatus = layout.find(".hv-vorlagenbaum-preview-status");
	const previewFrame = layout.find(".hv-vorlagenbaum-preview iframe");

	let currentKategorie = opts.initial_kategorie || "";
	let currentTemplates = [];
	let currentFolders = [];
	let currentChain = [];
	let selectedTemplate = "";
	let previewRequestId = 0;

	const fetchChain = async (name) => {
		const chain = [];
		let current = name;
		while (current) {
			const r = await frappe.call({
				method: "frappe.client.get_value",
				args: {
					doctype: "Serienbrief Kategorie",
					filters: { name: current },
					fieldname: ["title", "parent_serienbrief_kategorie"],
				},
			});
			const data = r.message || {};
			chain.unshift({ name: current, title: data.title || current });
			current = data.parent_serienbrief_kategorie || "";
		}
		return chain;
	};

	const renderBreadcrumb = () => {
		if (!currentChain.length) {
			breadcrumbWrapper.hide().empty();
			backFolderBtn.prop("disabled", true);
			return;
		}
		const parts = [`<span class="hv-breadcrumb-item hv-breadcrumb-root" data-name="">/</span>`];
		currentChain.forEach((seg, idx) => {
			const isLast = idx === currentChain.length - 1;
			const title = frappe.utils.escape_html(seg.title);
			if (isLast) {
				parts.push(`<span class="hv-breadcrumb-current">${title}</span>`);
			} else {
				parts.push(
					`<span class="hv-breadcrumb-item" data-name="${encodeURIComponent(seg.name)}">${title}</span>`
				);
				parts.push(`<span class="hv-breadcrumb-sep">/</span>`);
			}
		});
		breadcrumbWrapper.html(parts.join(" ")).show();
		backFolderBtn.prop("disabled", false);
	};

	const setBreadcrumb = async () => {
		if (!currentKategorie) {
			currentChain = [];
		} else {
			const last = currentChain.length ? currentChain[currentChain.length - 1].name : "";
			if (last !== currentKategorie) {
				currentChain = await fetchChain(currentKategorie);
			}
		}
		renderBreadcrumb();
	};

	const buildFolderList = (folders) => {
		if (!folders || !folders.length) return "";
		const items = folders
			.map((row) => {
				const title = frappe.utils.escape_html(row.title || row.name);
				const name = encodeURIComponent(row.name || "");
				const actions = is_picker
					? `
						<div class="hv-folder-actions">
							<button class="btn btn-xs btn-secondary hv-folder-action" data-action="open" data-name="${name}" title="${__(
								"Öffnen"
							)}">
								<i class="fa fa-arrow-right"></i>
							</button>
						</div>
					`
					: `
						<div class="hv-folder-actions">
							<button class="btn btn-xs btn-secondary hv-folder-action" data-action="move" data-name="${name}" title="${__(
								"Verschieben"
							)}">
								<i class="fa fa-folder-open"></i>
							</button>
							<button class="btn btn-xs btn-secondary hv-folder-action" data-action="copy" data-name="${name}" title="${__(
								"Kopieren"
							)}">
								<i class="fa fa-copy"></i>
							</button>
							<button class="btn btn-xs btn-secondary hv-folder-action" data-action="open" data-name="${name}" title="${__(
								"Öffnen"
							)}">
								<i class="fa fa-arrow-right"></i>
							</button>
						</div>
					`;
				return `
					<div class="hv-folder-item" data-name="${name}">
						<div class="hv-folder-title">
							<i class="fa fa-folder-open text-muted"></i>
							<span>${title}</span>
						</div>
						${actions}
					</div>
				`;
			})
			.join("");
		return `<div class="hv-folder-list mb-3">${items}</div>`;
	};

	const renderTemplates = (templates) => {
		const folderHtml = buildFolderList(currentFolders);
		const hasTemplates = !!(templates && templates.length);
		if (!hasTemplates && !folderHtml) {
			listWrapper.html(`<div class="hv-vorlagenbaum-empty">${__("Keine Vorlagen gefunden.")}</div>`);
			return;
		}
		const items = (templates || [])
			.map((row) => {
				const title = frappe.utils.escape_html(row.title || row.name);
				const link = `/app/serienbrief-vorlage/${encodeURIComponent(row.name)}`;
				const category = frappe.utils.escape_html(row.kategorie || "");
				const note = row.description ? frappe.utils.escape_html(row.description) : "";
				const modified = row.modified ? frappe.datetime.str_to_user(row.modified) : "";
				const metaParts = [category, modified].filter((val) => val);
				const meta = metaParts.length ? metaParts.join(" · ") : "";
				const dataName = encodeURIComponent(row.name || "");
				const dataTitle = frappe.utils.escape_html(row.title || row.name);

				const titleHtml = is_picker ? title : `<a href="${link}">${title}</a>`;
				const actionsHtml = is_picker
					? `
						<div class="hv-template-actions">
							<button class="btn btn-xs btn-primary hv-template-action" data-action="pick" data-name="${dataName}">
								${__("Auswählen")}
							</button>
						</div>
					`
					: `
						<div class="hv-template-actions">
							<button class="btn btn-xs btn-primary hv-template-action" data-action="durchlauf" data-name="${dataName}" title="${__(
								"Durchlauf mit dieser Vorlage starten"
							)}">
								<i class="fa fa-play"></i> ${__("Durchlauf")}
							</button>
							<button class="btn btn-xs btn-secondary hv-template-action" data-action="move" data-name="${dataName}" title="${__(
								"Verschieben"
							)}">
								<i class="fa fa-folder-open"></i>
							</button>
							<button class="btn btn-xs btn-secondary hv-template-action" data-action="copy" data-name="${dataName}" data-title="${dataTitle}" title="${__(
								"Kopieren"
							)}">
								<i class="fa fa-copy"></i>
							</button>
							<button class="btn btn-xs btn-secondary hv-template-action" data-action="rename" data-name="${dataName}" data-title="${dataTitle}" title="${__(
								"Umbenennen"
							)}">
								<i class="fa fa-pencil"></i>
							</button>
							<button class="btn btn-xs btn-danger hv-template-action" data-action="delete" data-name="${dataName}" title="${__(
								"Löschen"
							)}">
								<i class="fa fa-trash"></i>
							</button>
						</div>
					`;

				return `
					<div class="hv-template-item ${selectedTemplate === row.name ? "hv-selected" : ""}" data-name="${dataName}">
						<div class="hv-template-row">
							<div class="hv-template-main">
								<div class="hv-template-title">${titleHtml}</div>
								${meta ? `<div class="hv-template-meta">${meta}</div>` : ""}
								${note ? `<div class="small text-muted">${note}</div>` : ""}
							</div>
							${actionsHtml}
						</div>
					</div>
				`;
			})
			.join("");

		const templateHtml = hasTemplates
			? items
			: folderHtml
				? ""
				: `<div class="hv-vorlagenbaum-empty">${__("Keine Vorlagen gefunden.")}</div>`;
		listWrapper.html(`${folderHtml}${templateHtml}`);
	};

	const applyFilter = () => {
		const query = (filterInput.val() || "").toString().trim().toLowerCase();
		if (!query) {
			renderTemplates(currentTemplates);
			return;
		}
		const filtered = currentTemplates.filter((row) => {
			const title = (row.title || row.name || "").toString().toLowerCase();
			const note = (row.description || "").toString().toLowerCase();
			return title.includes(query) || note.includes(query);
		});
		renderTemplates(filtered);
	};

	const clearPreview = (message) => {
		selectedTemplate = "";
		previewRequestId += 1;
		previewTitle.text(__("Vorschau"));
		previewStatus.text(message || __("Klicke links auf eine Vorlage, um die PDF-Vorschau zu laden."));
		if (previewFrame.length) previewFrame.removeAttr("src");
	};

	const renderTemplatePreview = (row) => {
		if (!row?.name) return;
		selectedTemplate = row.name;
		listWrapper.find(".hv-template-item").removeClass("hv-selected");
		listWrapper
			.find(`.hv-template-item[data-name="${encodeURIComponent(row.name)}"]`)
			.addClass("hv-selected");

		const requestId = ++previewRequestId;
		previewTitle.text(row.title || row.name);
		previewStatus.text(__("Lade Vorschau..."));
		previewFrame.removeAttr("src");

		frappe
			.call({
				method: "hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.render_template_preview_pdf",
				args: { template: row.name, split_preview: 1 },
				quiet: true,
			})
			.then((r) => {
				if (requestId !== previewRequestId) return;
				const pdfBase64 = r?.message?.pdf_base64 || r?.message?.pdf || r?.message;
				if (!pdfBase64) {
					previewStatus.text(__("Keine PDF-Vorschau verfügbar."));
					return;
				}
				previewFrame.attr("src", `data:application/pdf;base64,${pdfBase64}`);
				previewStatus.text("");
			})
			.catch((err) => {
				if (requestId !== previewRequestId) return;
				const message =
					err?._server_messages ||
					err?.message ||
					__("Vorschau konnte nicht geladen werden.");
				previewStatus.text(message);
			});
	};

	const loadTemplates = () => {
		listWrapper.html(`<div class="hv-vorlagenbaum-empty">${__("Lade Vorlagen...")}</div>`);
		clearPreview();
		const kategorie = currentKategorie || "";
		return Promise.all([
			frappe.call({
				method: "hausverwaltung.hausverwaltung.page.serienbrief_vorlagenbaum.serienbrief_vorlagenbaum.get_vorlagen_for_kategorie",
				args: { kategorie, include_children: 1 },
			}),
			frappe.call({
				method: "frappe.client.get_list",
				args: {
					doctype: "Serienbrief Kategorie",
					fields: ["name", "title", "is_group"],
					filters: { parent_serienbrief_kategorie: kategorie || "" },
					limit_page_length: 200,
				},
			}),
		]).then(([templatesRes, foldersRes]) => {
			currentTemplates = templatesRes.message || [];
			currentFolders = foldersRes.message || [];
			applyFilter();
		});
	};

	const goUpFolder = () => {
		if (!currentKategorie) return Promise.resolve();
		return frappe
			.call({
				method: "frappe.client.get_value",
				args: {
					doctype: "Serienbrief Kategorie",
					filters: { name: currentKategorie },
					fieldname: "parent_serienbrief_kategorie",
				},
			})
			.then((r) => {
				currentKategorie = r.message?.parent_serienbrief_kategorie || "";
				setBreadcrumb();
				return loadTemplates();
			});
	};

	filterInput.on("input", applyFilter);
	fulltextBtn.on("click", () => {
		if (is_picker && on_template_pick) {
			hv_browser_open_fulltext_dialog(on_template_pick);
		} else {
			hv_browser_open_fulltext_dialog();
		}
	});
	backFolderBtn.on("click", goUpFolder);

	breadcrumbWrapper.on("click", ".hv-breadcrumb-item", (event) => {
		const name = decodeURIComponent(($(event.currentTarget).data("name") || "").toString());
		if (name === currentKategorie) return;
		currentKategorie = name;
		setBreadcrumb();
		loadTemplates();
	});

	// Ordner-Klick (für beide Modi): in Ordner hineinspringen
	listWrapper.on("click", ".hv-folder-item", (event) => {
		if ($(event.target).closest(".hv-folder-action").length) return;
		const name = decodeURIComponent(($(event.currentTarget).data("name") || "").toString());
		if (!name) return;
		currentKategorie = name;
		setBreadcrumb();
		loadTemplates();
	});

	listWrapper.on("click", ".hv-folder-action", (event) => {
		event.stopPropagation();
		const target = $(event.currentTarget);
		const action = target.data("action");
		const name = decodeURIComponent((target.data("name") || "").toString());
		if (!name) return;

		if (action === "open") {
			currentKategorie = name;
			setBreadcrumb();
			loadTemplates();
			return;
		}

		if (is_picker) return; // CRUD-Aktionen nur im Manage-Modus

		if (action === "move") {
			frappe.prompt(
				[
					{
						fieldname: "parent",
						label: __("Zielordner"),
						fieldtype: "Link",
						options: "Serienbrief Kategorie",
						default: "",
						description: __("Leer = Root"),
					},
				],
				(values) => {
					const parent = (values.parent || "").toString().trim();
					frappe
						.call({
							method: "hausverwaltung.hausverwaltung.doctype.serienbrief_kategorie.serienbrief_kategorie.move_serienbrief_kategorie",
							args: { name, new_parent: parent || null },
						})
						.then(() => loadTemplates());
				},
				__("Ordner verschieben")
			);
			return;
		}

		if (action === "copy") {
			frappe.prompt(
				[
					{
						fieldname: "new_title",
						label: __("Neuer Ordnername"),
						fieldtype: "Data",
						reqd: 1,
						default: `${name} (${__("Kopie")})`,
					},
					{
						fieldname: "parent",
						label: __("Zielordner"),
						fieldtype: "Link",
						options: "Serienbrief Kategorie",
						default: "",
						description: __("Leer = Root"),
					},
				],
				(values) => {
					const newTitle = (values.new_title || "").toString().trim();
					const parent = (values.parent || "").toString().trim();
					if (!newTitle) return;
					frappe
						.call({
							method: "hausverwaltung.hausverwaltung.doctype.serienbrief_kategorie.serienbrief_kategorie.copy_serienbrief_kategorie",
							args: {
								name,
								new_title: newTitle,
								new_parent: parent || null,
								copy_children: 1,
							},
						})
						.then(() => loadTemplates());
				},
				__("Ordner kopieren")
			);
		}
	});

	// Template-Klick: rechts wird die Vorschau geladen.
	// Wichtig: zuerst auf <a>-Klicks lauschen um Frappes globalen Link-Handler
	// zuvorzukommen. Sonst kann es passieren dass Frappe das Form öffnet bevor
	// wir preventDefault aufrufen.
	listWrapper.on("click", ".hv-template-main a", (event) => {
		event.preventDefault();
		event.stopPropagation();
		const item = $(event.currentTarget).closest(".hv-template-item");
		const name = decodeURIComponent((item.data("name") || "").toString());
		if (!name) return;
		const row = currentTemplates.find((tpl) => tpl.name === name);
		if (row) renderTemplatePreview(row);
	});

	listWrapper.on("click", ".hv-template-item", (event) => {
		if ($(event.target).closest(".hv-template-action").length) return;
		if ($(event.target).closest("a").length) {
			// Bereits durch den a-Handler oben behandelt
			return;
		}
		const name = decodeURIComponent(($(event.currentTarget).data("name") || "").toString());
		if (!name) return;
		const row = currentTemplates.find((tpl) => tpl.name === name);
		if (row) renderTemplatePreview(row);
	});

	listWrapper.on("dblclick", ".hv-template-item", (event) => {
		if ($(event.target).closest(".hv-template-action").length) return;
		const name = decodeURIComponent(($(event.currentTarget).data("name") || "").toString());
		if (!name) return;
		const row = currentTemplates.find((tpl) => tpl.name === name);
		if (!row) return;
		if (is_picker) {
			if (on_template_pick) on_template_pick(row);
			return;
		}
		frappe.set_route("Form", "Serienbrief Vorlage", row.name);
	});

	listWrapper.on("dblclick", ".hv-folder-item", (event) => {
		if ($(event.target).closest(".hv-folder-action").length) return;
		const name = decodeURIComponent(($(event.currentTarget).data("name") || "").toString());
		if (!name) return;
		currentKategorie = name;
		setBreadcrumb();
		loadTemplates();
	});

	listWrapper.on("click", ".hv-template-action", (event) => {
		event.stopPropagation();
		const target = $(event.currentTarget);
		const action = target.data("action");
		const name = decodeURIComponent((target.data("name") || "").toString());
		const row = currentTemplates.find((tpl) => tpl.name === name);
		if (!row) return;

		if (is_picker) {
			if (action === "pick" && on_template_pick) on_template_pick(row);
			return;
		}

		if (action === "durchlauf") {
			frappe.new_doc("Serienbrief Durchlauf", { vorlage: name });
			return;
		}

		if (action === "move") {
			frappe.prompt(
				[
					{
						fieldname: "kategorie",
						label: __("Zielordner"),
						fieldtype: "Link",
						options: "Serienbrief Kategorie",
						reqd: 1,
						default: row.kategorie || "",
					},
				],
				(values) => {
					const kategorie = (values.kategorie || "").toString().trim();
					if (!kategorie) return;
					frappe
						.call({
							method: "frappe.client.set_value",
							args: {
								doctype: "Serienbrief Vorlage",
								name,
								fieldname: "kategorie",
								value: kategorie,
							},
						})
						.then(() => loadTemplates());
				},
				__("Vorlage verschieben")
			);
			return;
		}

		if (action === "copy") {
			frappe.prompt(
				[
					{
						fieldname: "new_title",
						label: __("Neuer Titel"),
						fieldtype: "Data",
						reqd: 1,
						default: `${row.title || row.name} (${__("Kopie")})`,
					},
					{
						fieldname: "kategorie",
						label: __("Zielordner"),
						fieldtype: "Link",
						options: "Serienbrief Kategorie",
						default: row.kategorie || "",
					},
				],
				(values) => {
					const newTitle = (values.new_title || "").toString().trim();
					const kategorie = (values.kategorie || "").toString().trim();
					if (!newTitle) return;
					frappe
						.call({
							method: "hausverwaltung.hausverwaltung.doctype.serienbrief_vorlage.serienbrief_vorlage.copy_serienbrief_vorlage",
							args: { template: name, new_title: newTitle },
						})
						.then((r) => {
							const newName = r.message?.name || newTitle;
							if (kategorie && kategorie !== row.kategorie) {
								return frappe.call({
									method: "frappe.client.set_value",
									args: {
										doctype: "Serienbrief Vorlage",
										name: newName,
										fieldname: "kategorie",
										value: kategorie,
									},
								});
							}
							return null;
						})
						.then(() => loadTemplates());
				},
				__("Vorlage kopieren")
			);
			return;
		}

		if (action === "rename") {
			frappe.prompt(
				[
					{
						fieldname: "new_title",
						label: __("Neuer Titel"),
						fieldtype: "Data",
						reqd: 1,
						default: row.title || row.name,
					},
				],
				(values) => {
					const newTitle = (values.new_title || "").toString().trim();
					if (!newTitle || newTitle === row.name) return;
					frappe
						.call({
							method: "frappe.client.rename_doc",
							args: {
								doctype: "Serienbrief Vorlage",
								old_name: name,
								new_name: newTitle,
							},
						})
						.then(() =>
							frappe.call({
								method: "frappe.client.set_value",
								args: {
									doctype: "Serienbrief Vorlage",
									name: newTitle,
									fieldname: "title",
									value: newTitle,
								},
							})
						)
						.then(() => loadTemplates());
				},
				__("Vorlage umbenennen")
			);
			return;
		}

		if (action === "delete") {
			frappe.confirm(
				__("Vorlage wirklich löschen?"),
				() => {
					frappe
						.call({
							method: "frappe.client.delete",
							args: { doctype: "Serienbrief Vorlage", name },
						})
						.then(() => loadTemplates());
				},
				() => null
			);
		}
	});

	addFolderBtn.on("click", () => {
		frappe.prompt(
			[
				{ fieldname: "title", label: __("Ordnername"), fieldtype: "Data", reqd: 1 },
				{
					fieldname: "parent",
					label: __("Zielordner"),
					fieldtype: "Link",
					options: "Serienbrief Kategorie",
					default: currentKategorie || "",
					description: __("Leer = Root"),
				},
			],
			(values) => {
				const title = (values.title || "").toString().trim();
				const parent = (values.parent || "").toString().trim();
				if (!title) return;
				frappe
					.call({
						method: "frappe.client.insert",
						args: {
							doc: {
								doctype: "Serienbrief Kategorie",
								title,
								parent_serienbrief_kategorie: parent || null,
								is_group: 1,
							},
						},
					})
					.then(() => {
						currentKategorie = parent || "";
						setBreadcrumb();
						loadTemplates();
					});
			},
			__("Ordner hinzufügen")
		);
	});

	addTemplateBtn.on("click", () => {
		const routeDefaults = currentKategorie ? { kategorie: currentKategorie } : {};
		frappe.new_doc("Serienbrief Vorlage", routeDefaults);
	});

	const adjustLayoutHeight = () => {
		const el = layout.get(0);
		if (!el || !el.isConnected) return;
		const top = el.getBoundingClientRect().top;
		const available = window.innerHeight - top - 16;
		if (available > 300) {
			layout.css("height", available + "px");
		} else {
			layout.css("height", "");
		}
	};
	const resizeHandler = () => adjustLayoutHeight();
	$(window).on("resize.hv-vorlagenbaum", resizeHandler);
	setTimeout(adjustLayoutHeight, 0);

	setBreadcrumb();
	loadTemplates();

	return {
		refresh: loadTemplates,
		set_kategorie(name) {
			currentKategorie = name || "";
			setBreadcrumb();
			return loadTemplates();
		},
		destroy() {
			$(window).off("resize.hv-vorlagenbaum", resizeHandler);
			$container.empty();
		},
	};
};

hausverwaltung.serienbrief.open_vorlage_picker = (opts = {}) => {
	const dialog = new frappe.ui.Dialog({
		title: opts.title || __("Vorlage auswählen"),
		size: "extra-large",
		fields: [{ fieldtype: "HTML", fieldname: "browser_host" }],
	});
	dialog.show();
	const $host = dialog.get_field("browser_host").$wrapper;
	$host.css({ "min-height": "560px" });

	const controller = hausverwaltung.serienbrief.mount_vorlagen_browser($host, {
		mode: "picker",
		initial_kategorie: opts.initial_kategorie || "",
		on_template_pick(row) {
			dialog.hide();
			opts.on_pick?.(row);
		},
	});

	dialog.$wrapper.on("hidden.bs.modal", () => controller.destroy?.());
	return dialog;
};
