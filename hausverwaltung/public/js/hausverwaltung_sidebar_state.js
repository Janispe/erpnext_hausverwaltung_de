(function () {
	const STORAGE_KEY = "hausverwaltung.sidebar.open_sections.v1";
	const HAUSVERWALTUNG_WORKSPACE = "Hausverwaltung";
	const MAIL_MERGE_MODULE = "Mail Merge";
	const SERIENBRIEF_PAGES = new Set([
		"serienbrief_browser",
		"serienbrief_editor",
		"serienbrief_durchlauf_viewer",
		"serienbrief_vorlagenbaum",
	]);
	const SERIENBRIEF_DOCTYPES = new Set([
		"Serienbrief Vorlage",
		"Serienbrief Durchlauf",
		"Serienbrief Kategorie",
		"Serienbrief Dokument",
		"Serienbrief Textbaustein",
		"Serienbrief Einstellungen",
		"Serienbrief Beispielobjekt",
		"Serienbrief Beispielwert",
	]);
	let enforcing_workspace = false;
	let router_hook_installed = false;

	function read_state() {
		try {
			return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
		} catch (e) {
			return {};
		}
	}

	function write_state(state) {
		try {
			localStorage.setItem(STORAGE_KEY, JSON.stringify(state || {}));
		} catch (e) {
			// Ignore storage failures; navigation should still work normally.
		}
	}

	function get_item_key($item) {
		return (
			$item.attr("item-name") ||
			$item.attr("item-title") ||
			$item.find("> .standard-sidebar-item .sidebar-item-label").first().text().trim()
		);
	}

	function get_parent_items() {
		return $(".body-sidebar .sidebar-item-container").filter(function () {
			const $item = $(this);
			const has_children = $item.find("> .sidebar-child-item > .sidebar-item-container").length > 0;
			const has_toggle = $item.find("> .standard-sidebar-item .drop-icon:not(.hidden)").length > 0;
			return has_children && has_toggle;
		});
	}

	function is_hausverwaltung_sidebar() {
		const labels = $(".body-sidebar .sidebar-item-label")
			.toArray()
			.map((el) => $(el).text().trim());
		return labels.includes("Serienbriefe") && labels.includes("Buchungen");
	}

	function is_open($item) {
		return !$item.find("> .sidebar-child-item").first().hasClass("hidden");
	}

	function set_open($item, open) {
		const currently_open = is_open($item);
		if (currently_open === open) return;
		const toggle = $item.find("> .standard-sidebar-item .drop-icon:not(.hidden)").first()[0];
		if (toggle) toggle.click();
	}

	function snapshot_state() {
		if (!is_hausverwaltung_sidebar()) return;

		const state = read_state();
		get_parent_items().each(function () {
			const $item = $(this);
			const key = get_item_key($item);
			if (key) state[key] = is_open($item);
		});
		write_state(state);
	}

	function restore_state() {
		if (!is_hausverwaltung_sidebar()) return;

		const state = read_state();
		get_parent_items().each(function () {
			const $item = $(this);
			const key = get_item_key($item);
			if (key && Object.prototype.hasOwnProperty.call(state, key)) {
				set_open($item, Boolean(state[key]));
			}
		});
	}

	function restore_soon() {
		setTimeout(restore_state, 0);
		setTimeout(restore_state, 100);
	}

	function get_route_from_path() {
		const parts = window.location.pathname.split("/").filter(Boolean);
		const desk_index = parts.findIndex((part) => ["app", "desk"].includes(part));
		return desk_index >= 0 ? parts[desk_index + 1] || "" : "";
	}

	function get_current_route_str() {
		return (
			window.frappe?.get_route_str?.() ||
			(window.frappe?.get_route?.() || []).join("/") ||
			get_route_from_path()
		);
	}

	function is_serienbrief_doctype(doctype) {
		return SERIENBRIEF_DOCTYPES.has(doctype) || String(doctype || "").startsWith("Serienbrief ");
	}

	function is_serienbrief_route(route) {
		route = route || window.frappe?.get_route?.() || [];
		const route_name = route[0] || get_route_from_path();
		if (SERIENBRIEF_PAGES.has(route_name)) return true;
		if (["Form", "List"].includes(route[0]) && is_serienbrief_doctype(route[1])) return true;
		if (is_serienbrief_doctype(route[0])) return true;
		if (SERIENBRIEF_PAGES.has(route[0])) return true;
		return false;
	}

	function normalize_serienbrief_breadcrumb(breadcrumb) {
		if (!breadcrumb || !is_serienbrief_route()) return breadcrumb;

		if (typeof breadcrumb === "string") {
			if (breadcrumb !== MAIL_MERGE_MODULE) return breadcrumb;
			return {
				module: HAUSVERWALTUNG_WORKSPACE,
				workspace: HAUSVERWALTUNG_WORKSPACE,
			};
		}

		const doctype = breadcrumb.doctype;
		if (
			breadcrumb.module !== MAIL_MERGE_MODULE &&
			breadcrumb.workspace !== MAIL_MERGE_MODULE &&
			!is_serienbrief_doctype(doctype)
		) {
			return breadcrumb;
		}

		return {
			...breadcrumb,
			module: HAUSVERWALTUNG_WORKSPACE,
			workspace: HAUSVERWALTUNG_WORKSPACE,
		};
	}

	function get_hausverwaltung_app() {
		return (
			window.frappe?.workspace_map?.[HAUSVERWALTUNG_WORKSPACE]?.app ||
			window.frappe?.boot?.workspace_sidebar_item?.[HAUSVERWALTUNG_WORKSPACE.toLowerCase()]?.app ||
			window.frappe?.boot?.module_app?.hausverwaltung ||
			"hausverwaltung"
		);
	}

	function force_hausverwaltung_breadcrumb() {
		if (!window.frappe?.breadcrumbs || !is_serienbrief_route()) return false;

		const route_key = get_current_route_str();
		if (!route_key) return false;

		const current = frappe.breadcrumbs.all[route_key] || {};
		const normalized = {
			...current,
			module: HAUSVERWALTUNG_WORKSPACE,
			workspace: HAUSVERWALTUNG_WORKSPACE,
		};
		const changed =
			current.module !== normalized.module || current.workspace !== normalized.workspace;

		if (changed || !frappe.breadcrumbs.all[route_key]) {
			frappe.breadcrumbs.all[route_key] = normalized;
		}
		return changed;
	}

	function force_hausverwaltung_app() {
		if (!window.frappe?.app?.sidebar || !is_serienbrief_route()) return;

		if (
			frappe.boot?.workspace_sidebar_item?.[HAUSVERWALTUNG_WORKSPACE.toLowerCase()] &&
			frappe.app.sidebar.sidebar_title !== HAUSVERWALTUNG_WORKSPACE
		) {
			frappe.app.sidebar.preferred_sidebars = [HAUSVERWALTUNG_WORKSPACE];
			frappe.app.sidebar.setup(HAUSVERWALTUNG_WORKSPACE);
			frappe.app.sidebar.set_active_workspace_item?.();
			return;
		}

		const app = get_hausverwaltung_app();
		if (frappe.boot?.app_data_map?.[app] && frappe.current_app !== app) {
			frappe.app.sidebar.apps_switcher?.set_current_app?.(app);
		}
	}

	function enforce_serienbrief_workspace() {
		if (enforcing_workspace || !is_serienbrief_route()) return;

		enforcing_workspace = true;
		try {
			const changed_breadcrumb = force_hausverwaltung_breadcrumb();
			if (changed_breadcrumb) {
				frappe.breadcrumbs.update();
			}
			force_hausverwaltung_app();
			restore_soon();
		} finally {
			enforcing_workspace = false;
		}
	}

	function enforce_serienbrief_workspace_soon() {
		setTimeout(enforce_serienbrief_workspace, 0);
		setTimeout(enforce_serienbrief_workspace, 100);
		setTimeout(enforce_serienbrief_workspace, 300);
	}

	function install_router_hook() {
		if (router_hook_installed || !window.frappe?.router?.on) return;
		frappe.router.on("change", enforce_serienbrief_workspace_soon);
		router_hook_installed = true;
	}

	function patch_breadcrumbs() {
		if (!window.frappe?.breadcrumbs || frappe.breadcrumbs.__hausverwaltung_workspace_lock) {
			return;
		}

		const original_add = frappe.breadcrumbs.add;
		frappe.breadcrumbs.add = function (module, doctype, type) {
			let result;
			if (typeof module === "object") {
				result = original_add.call(this, normalize_serienbrief_breadcrumb(module), doctype, type);
			} else {
				const normalized = normalize_serienbrief_breadcrumb({
					module,
					doctype,
					type,
				});
				result = original_add.call(this, normalized);
			}
			enforce_serienbrief_workspace_soon();
			return result;
		};

		frappe.breadcrumbs.__hausverwaltung_workspace_lock = true;
	}

	function patch_sidebar() {
		if (!window.frappe?.ui?.Sidebar || frappe.ui.Sidebar.__hausverwaltung_sidebar_state) {
			return;
		}

		const original_setup = frappe.ui.Sidebar.prototype.setup;
		if (original_setup) {
			frappe.ui.Sidebar.prototype.setup = function (workspace_title) {
				if (workspace_title === MAIL_MERGE_MODULE && is_serienbrief_route()) {
					workspace_title = HAUSVERWALTUNG_WORKSPACE;
					this.preferred_sidebars = [HAUSVERWALTUNG_WORKSPACE];
				}
				return original_setup.call(this, workspace_title);
			};
		}

		const original_make_sidebar = frappe.ui.Sidebar.prototype.make_sidebar;
		frappe.ui.Sidebar.prototype.make_sidebar = function () {
			const result = original_make_sidebar.apply(this, arguments);
			restore_soon();
			return result;
		};

		const original_set_active = frappe.ui.Sidebar.prototype.set_active_workspace_item;
		frappe.ui.Sidebar.prototype.set_active_workspace_item = function () {
			let result;
			try {
				result = original_set_active.apply(this, arguments);
			} catch (e) {
				if (!String(e && e.message).includes("isTrusted")) throw e;
			}
			enforce_serienbrief_workspace_soon();
			restore_soon();
			return result;
		};

		frappe.ui.Sidebar.__hausverwaltung_sidebar_state = true;
	}

	$(document).on("click", ".body-sidebar .drop-icon", function () {
		setTimeout(snapshot_state, 0);
	});

	$(document).on("click", ".body-sidebar .item-anchor", function () {
		snapshot_state();
	});

	function open_mahnung_workflow(event) {
		const anchor = event.target?.closest?.('.body-sidebar .item-anchor[href*="op-workflow?view=mahnwesen"], .body-sidebar .item-anchor[href*="mahnung-workflow"]');
		if (!anchor) return false;
		event.preventDefault();
		event.stopPropagation();
		if (event.stopImmediatePropagation) event.stopImmediatePropagation();
		snapshot_state();

		window.location.href = "/desk/mahnung-workflow";
		return true;
	}

	document.addEventListener("click", open_mahnung_workflow, true);
	$(document).on("click", '.body-sidebar .item-anchor[href*="op-workflow?view=mahnwesen"], .body-sidebar .item-anchor[href*="mahnung-workflow"]', open_mahnung_workflow);

	$(document).on("app_ready", function () {
		patch_breadcrumbs();
		patch_sidebar();
		install_router_hook();
		enforce_serienbrief_workspace_soon();
		restore_soon();
	});

	if (document.readyState !== "loading") {
		patch_breadcrumbs();
		patch_sidebar();
		install_router_hook();
		enforce_serienbrief_workspace_soon();
		restore_soon();
	}
})();
