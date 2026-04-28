(() => {
	window.hausverwaltung = window.hausverwaltung || {};

	const api = (window.hausverwaltung.serienbrief_placeholder_picker =
		window.hausverwaltung.serienbrief_placeholder_picker || {});

	const ensure_tree_styles = () => {
		if (document.getElementById("hv-serienbrief-placeholder-picker-styles")) return;
		const style = document.createElement("style");
		style.id = "hv-serienbrief-placeholder-picker-styles";
		style.textContent = `
			.hv-tree { list-style: none; padding-left: 0; margin: 0; }
			.hv-tree li { margin: 2px 0; }
			.hv-tree-row { display: flex; align-items: center; gap: 4px; cursor: pointer; }
			.hv-tree-toggle { cursor: pointer; user-select: none; font-weight: 600; color: var(--gray-700); }
			.hv-tree-label { border: none; background: none; padding: 2px 4px; color: var(--text-color); text-align: left; }
			.hv-tree-label:hover { background: var(--gray-100); }
			.hv-tree-type { margin-left: 6px; padding: 1px 6px; border-radius: 999px; border: 1px solid var(--gray-300); background: var(--gray-50); color: var(--gray-700); font-size: 11px; line-height: 16px; white-space: nowrap; }
			.hv-tree-children { list-style: none; padding-left: 14px; margin: 4px 0 0 10px; border-left: 1px solid var(--gray-300); }
			.hv-tree-node.collapsed > .hv-tree-children { display: none; }
			.hv-tree-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--gray-500); display: inline-block; }
		`;
		document.head.appendChild(style);
	};

	const escape_html = (text) => {
		if (window.frappe?.utils && typeof frappe.utils.escape_html === "function") {
			return frappe.utils.escape_html(text);
		}
		const div = document.createElement("div");
		div.innerText = text == null ? "" : String(text);
		return div.innerHTML;
	};

	const build_tree_html = (nodes) => {
		if (!nodes || !nodes.length) return "";
		return nodes
			.map((node) => {
				const hasChildren = node.children && node.children.length;
				const placeholderAttr = node.placeholder
					? ` data-placeholder="${escape_html(node.placeholder)}"`
					: "";
				const typeBadge = node.type
					? `<span class="hv-tree-type">${escape_html(node.type)}</span>`
					: "";
				return `
					<li class="hv-tree-node${hasChildren ? " collapsed" : ""}">
						<div class="hv-tree-row"${placeholderAttr}>
							${hasChildren ? `<span class="hv-tree-toggle">▸</span>` : `<span class="hv-tree-dot"></span>`}
							<button type="button" class="hv-tree-label"${placeholderAttr}>${escape_html(node.label)}</button>
							${typeBadge}
						</div>
						${hasChildren ? `<ul class="hv-tree-children">${build_tree_html(node.children)}</ul>` : ""}
					</li>
				`;
			})
			.join("");
	};

	const render_tree = (container, group) => {
		if (!group) {
			container.html(`<div class="text-muted small">${__("Keine Platzhalter gefunden.")}</div>`);
			return;
		}
		container.html(`<ul class="hv-tree">${build_tree_html(group.tree || [])}</ul>`);
	};

	const filter_tree = (nodes, term) => {
		if (!term) return nodes;
		const lower = term.toLowerCase();
		const next = [];
		(nodes || []).forEach((node) => {
			const label = (node.label || "").toLowerCase();
			const placeholder = (node.placeholder || "").toLowerCase();
			const type = (node.type || "").toLowerCase();
			const filteredChildren = filter_tree(node.children || [], term);
			if (label.includes(lower) || placeholder.includes(lower) || type.includes(lower) || filteredChildren.length) {
				next.push({ ...node, children: filteredChildren });
			}
		});
		return next;
	};

	api.open_dialog = ({ title, load_groups, on_insert, on_setup } = {}) => {
		if (!window.frappe?.ui?.Dialog) {
			throw new Error("Frappe Dialog not available");
		}
		if (typeof load_groups !== "function") {
			throw new Error("load_groups must be a function");
		}
		if (typeof on_insert !== "function") {
			throw new Error("on_insert must be a function");
		}

		ensure_tree_styles();

		const dialog = new frappe.ui.Dialog({
			title: title || __("Platzhalter auswählen"),
			fields: [
				{
					fieldname: "group",
					fieldtype: "Select",
					label: __("Quelle"),
					options: [],
				},
				{
					fieldname: "search",
					fieldtype: "Data",
					label: __("Felder durchsuchen"),
					onchange: () => apply_tree(),
				},
				{
					fieldname: "tree",
					fieldtype: "HTML",
					label: __("Felder"),
				},
			],
			primary_action_label: __("Schließen"),
			primary_action: () => dialog.hide(),
		});

		const treeContainer = $(dialog.get_field("tree").wrapper).empty();
		let activeGroups = [];

		const apply_tree = () => {
			const selectedGroupLabel = dialog.get_value("group");
			const group =
				activeGroups.find((g) => g.label === selectedGroupLabel) || activeGroups[0];
			const term = dialog.get_value("search") || "";
			const filtered = group ? { ...group, tree: filter_tree(group.tree || [], term) } : group;
			render_tree(treeContainer, filtered);
		};

		treeContainer.on("click", ".hv-tree-toggle", (e) => {
			e.stopPropagation();
			const li = $(e.currentTarget).closest(".hv-tree-node");
			li.toggleClass("collapsed");
			const toggler = $(e.currentTarget);
			toggler.text(li.hasClass("collapsed") ? "▸" : "▾");
		});

		treeContainer.on("click", ".hv-tree-row", (e) => {
			e.preventDefault();
			if ($(e.target).closest(".hv-tree-toggle").length) {
				return;
			}
			const placeholder = $(e.currentTarget).data("placeholder");
			if (!placeholder) {
				return;
			}
			on_insert(String(placeholder));
		});

		const refresh_groups = async (preferLabel) => {
			treeContainer.html(`<div class="text-muted small">${__("Lade Platzhalter …")}</div>`);
			activeGroups = (await load_groups()) || [];
			const options = activeGroups.map((g) => g.label);
			const groupField = dialog.get_field("group");
			groupField.df.options = options.length ? options : [__("Keine Quellen verfügbar")];
			groupField.refresh_input();
			const target = preferLabel && options.includes(preferLabel) ? preferLabel : options[0];
			if (target) {
				dialog.set_value("group", target);
			}
			apply_tree();
		};

		dialog.fields_dict.group.df.onchange = apply_tree;
		dialog.show();
		refresh_groups(dialog.get_value("group"));

		const setup_api = { dialog, refresh_groups, apply_tree, treeContainer };
		if (typeof on_setup === "function") {
			on_setup(setup_api);
		}

		return setup_api;
	};
})();
