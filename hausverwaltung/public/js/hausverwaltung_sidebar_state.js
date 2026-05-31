(function () {
	const STORAGE_KEY = "hausverwaltung.sidebar.open_sections.v1";

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
		$item.find("> .standard-sidebar-item .drop-icon:not(.hidden)").first().trigger("click");
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
			const result = original_set_active.apply(this, arguments);
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

	$(document).on("app_ready", function () {
		patch_sidebar();
		restore_soon();
	});

	if (document.readyState !== "loading") {
		patch_sidebar();
		restore_soon();
	}
})();
