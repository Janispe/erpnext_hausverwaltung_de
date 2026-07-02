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
	]);

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

	function is_serienbrief_route() {
		const route = window.frappe?.get_route?.() || [];
		if (SERIENBRIEF_PAGES.has(route[0])) return true;
		if (["Form", "List"].includes(route[0]) && SERIENBRIEF_DOCTYPES.has(route[1])) return true;
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
		if (breadcrumb.module !== MAIL_MERGE_MODULE && !SERIENBRIEF_DOCTYPES.has(doctype)) {
			return breadcrumb;
		}

		return {
			...breadcrumb,
			module: HAUSVERWALTUNG_WORKSPACE,
			workspace: HAUSVERWALTUNG_WORKSPACE,
		};
	}

	function patch_breadcrumbs() {
		if (!window.frappe?.breadcrumbs || frappe.breadcrumbs.__hausverwaltung_workspace_lock) {
			return;
		}

		const original_add = frappe.breadcrumbs.add;
		frappe.breadcrumbs.add = function (module, doctype, type) {
			if (typeof module === "object") {
				return original_add.call(this, normalize_serienbrief_breadcrumb(module), doctype, type);
			}

			const normalized = normalize_serienbrief_breadcrumb({
				module,
				doctype,
				type,
			});
			return original_add.call(this, normalized);
		};

		frappe.breadcrumbs.__hausverwaltung_workspace_lock = true;
	}

	function patch_sidebar() {
		if (!window.frappe?.ui?.Sidebar || frappe.ui.Sidebar.__hausverwaltung_sidebar_state) {
			return;
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
		restore_soon();
	});

	if (document.readyState !== "loading") {
		patch_breadcrumbs();
		patch_sidebar();
		restore_soon();
	}
})();
