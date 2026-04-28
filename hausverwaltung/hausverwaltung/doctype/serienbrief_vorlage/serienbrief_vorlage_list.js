(function () {
	if (window.__hv_serienbrief_vorlage_list_loaded) return;
	window.__hv_serienbrief_vorlage_list_loaded = true;

	const hv_render_fulltext_results = (dialog, results) => {
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

	const hv_ensure_tree_loaded = () =>
		new Promise((resolve) => {
			if (frappe?.ui?.Tree) {
				resolve();
				return;
			}
			frappe.require("assets/frappe/js/frappe/ui/tree.js", () => resolve());
		});

	const hv_open_kategorie_tree_picker = async ({ on_select }) => {
		await hv_ensure_tree_loaded();

	let selected = "";
	const picker = new frappe.ui.Dialog({
		title: __("Kategorie im Baum auswählen"),
		fields: [{ fieldtype: "HTML", fieldname: "tree_html" }],
		primary_action_label: __("Übernehmen"),
		primary_action() {
			if (!selected) {
				frappe.msgprint({ message: __("Bitte eine Kategorie auswählen."), indicator: "orange" });
				return;
			}
			on_select && on_select(selected);
			picker.hide();
		},
	});

	picker.show();
	const wrapper = $(picker.get_field("tree_html").wrapper).empty();

	// Root: parent == "" -> zeigt Wurzelknoten des Tree-Doctypes
	new frappe.ui.Tree({
		parent: wrapper,
		label: __("Kategorien"),
		root_value: "",
		args: { doctype: "Serienbrief Kategorie" },
		method: "frappe.desk.treeview.get_children",
		on_click(node) {
			if (node?.is_root) {
				selected = "";
				return;
			}
			selected = node?.label || "";
		},
	});
	};

	const hv_open_kategorie_ordner_dialog = (listview) => {
		const dialog = new frappe.ui.Dialog({
		title: __("Ordner (Kategorie)"),
		fields: [
			{
				fieldtype: "Link",
				fieldname: "kategorie",
				label: __("Kategorie"),
				options: "Serienbrief Kategorie",
			},
			{
				fieldtype: "HTML",
				fieldname: "kategorie_tree_picker",
				label: "",
				options: `<div><a class="btn btn-xs btn-secondary hv-kategorie-tree">${__("Im Baum auswählen")}</a></div>`,
			},
			{
				fieldtype: "Check",
				fieldname: "inkl_unterkategorien",
				label: __("Unterkategorien einschließen"),
				default: 1,
			},
		],
		primary_action_label: __("Anwenden"),
		primary_action(values) {
			const kategorie = (values.kategorie || "").trim();
			const includeChildren = !!values.inkl_unterkategorien;

			if (!kategorie) {
				listview.filter_area.remove("kategorie");
				listview.refresh();
				dialog.hide();
				return;
			}

			// Standard-Filter Feld leeren, damit "in"-Filter nicht verwirrt
			try {
				listview.page?.fields_dict?.kategorie?.set_value("");
			} catch (e) {
				// ignore
			}

			if (!includeChildren) {
				listview.filter_area.remove("kategorie");
				listview.filter_area.add("Serienbrief Vorlage", "kategorie", "=", kategorie);
				dialog.hide();
				return;
			}

			frappe
				.call({
					method: "hausverwaltung.hausverwaltung.doctype.serienbrief_kategorie.serienbrief_kategorie.get_kategorie_und_unterkategorien",
					args: { kategorie },
				})
				.then((r) => {
					const categories = r.message || [];
					listview.filter_area.remove("kategorie");
					if (Array.isArray(categories) && categories.length) {
						listview.filter_area.add("Serienbrief Vorlage", "kategorie", "in", categories);
					} else {
						listview.filter_area.add("Serienbrief Vorlage", "kategorie", "=", kategorie);
					}
					dialog.hide();
				});
		},
	});

	dialog.set_secondary_action_label(__("Zurücksetzen"));
	dialog.set_secondary_action(() => {
		listview.filter_area.remove("kategorie");
		listview.refresh();
		dialog.hide();
	});

	dialog.show();

	$(dialog.get_field("kategorie_tree_picker").wrapper)
		.off("click.hv_tree")
		.on("click.hv_tree", ".hv-kategorie-tree", () => {
			hv_open_kategorie_tree_picker({
				on_select: (name) => dialog.set_value("kategorie", name),
			});
		});
	};

	const hv_open_fulltext_dialog = () => {
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
			{
				fieldtype: "Int",
				fieldname: "limit",
				label: __("Max. Treffer"),
				default: 20,
			},
			{ fieldtype: "HTML", fieldname: "results_html" },
		],
		primary_action_label: __("Suchen"),
		primary_action(values) {
			const query = (values.query || "").trim();
			const limit = values.limit || 20;

			if (!query) {
				frappe.msgprint({ message: __("Bitte gib einen Suchtext ein."), indicator: "orange" });
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
					hv_render_fulltext_results(dialog, r.message || []);
				})
				.finally(() => {
					dialog.enable_primary_action();
				});
		},
	});

	dialog.show();
	};

	const hv_should_redirect_to_ordneransicht = () => {
		if (frappe?.route_options?.hv_allow_list_view) {
			delete frappe.route_options.hv_allow_list_view;
			return false;
		}
		return true;
	};

	frappe.listview_settings["Serienbrief Vorlage"] = {
		onload(listview) {
			if (hv_should_redirect_to_ordneransicht()) {
				frappe.set_route("serienbrief_vorlagenbaum");
				return;
			}

			listview.page.add_inner_button(__("Volltextsuche"), () => hv_open_fulltext_dialog());
			listview.page.add_inner_button(__("Ordner (Kategorie)"), () =>
				hv_open_kategorie_ordner_dialog(listview)
			);
			listview.page.add_inner_button(__("Ordneransicht"), () =>
				frappe.set_route("serienbrief_vorlagenbaum")
			);
		},
	};
})();
