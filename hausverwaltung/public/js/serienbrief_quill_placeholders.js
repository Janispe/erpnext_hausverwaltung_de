(() => {
	window.hausverwaltung = window.hausverwaltung || {};

	const api = (window.hausverwaltung.serienbrief_quill_placeholders =
		window.hausverwaltung.serienbrief_quill_placeholders || {});

	const STYLE_ID = "hv-serienbrief-quill-placeholder-styles";
	const HV_LAST_SELECTION_KEY = "__hv_last_selection";

	const ensure_styles = () => {
		if (document.getElementById(STYLE_ID)) return;
		const style = document.createElement("style");
		style.id = STYLE_ID;
		style.textContent = `
			.ql-editor .hv-placeholder-badge {
				display: inline-block;
				padding: 2px 6px;
				margin: 0 2px;
				border-radius: 3px;
				background: #e3f2fd;
				color: #1565c0;
				font-weight: 700;
				cursor: default;
				user-select: none;
				white-space: nowrap;
			}
			.ql-editor .hv-jinja-badge {
				display: inline-block;
				padding: 2px 6px;
				margin: 0 2px;
				border-radius: 3px;
				background: #fff3e0;
				color: #e65100;
				font-weight: 700;
				cursor: default;
				user-select: none;
				white-space: nowrap;
			}
		`;
		document.head.appendChild(style);
	};

	const get_quill_namespace = (quill) => {
		if (window.Quill) return window.Quill;
		if (quill && quill.constructor && typeof quill.constructor.register === "function") {
			return quill.constructor;
		}
		return null;
	};

	const register_placeholder_blot = (quill) => {
		const Quill = get_quill_namespace(quill);
		if (!Quill || api._hv_placeholder_registered) return Boolean(api._hv_placeholder_registered);

		let Embed;
		try {
			Embed = Quill.import("blots/embed");
		} catch (e) {
			return false;
		}

		class HvPlaceholderBlot extends Embed {
			static create(value) {
				const node = super.create();
				const text = value == null ? "" : String(value);
				node.setAttribute("data-hv-placeholder", text);
				node.setAttribute("contenteditable", "false");
				node.setAttribute("draggable", "false");
				node.textContent = text;
				return node;
			}

			static value(node) {
				return node?.getAttribute?.("data-hv-placeholder") || node?.textContent || "";
			}
		}

		HvPlaceholderBlot.blotName = "hv_placeholder";
		HvPlaceholderBlot.tagName = "span";
		HvPlaceholderBlot.className = "hv-placeholder-badge";

		try {
			Quill.register(HvPlaceholderBlot, true);
			api._hv_placeholder_registered = true;
			return true;
		} catch (e) {
			return false;
		}
	};

	const register_jinja_token_blot = (quill) => {
		const Quill = get_quill_namespace(quill);
		if (!Quill || api._hv_jinja_token_registered) {
			return Boolean(api._hv_jinja_token_registered);
		}

		let Embed;
		try {
			Embed = Quill.import("blots/embed");
		} catch (e) {
			return false;
		}

		class HvJinjaTokenBlot extends Embed {
			static create(value) {
				const node = super.create();
				const text = value == null ? "" : String(value);
				node.setAttribute("data-hv-jinja-token", text);
				node.setAttribute("contenteditable", "false");
				node.setAttribute("draggable", "false");
				node.textContent = text;
				return node;
			}

			static value(node) {
				return node?.getAttribute?.("data-hv-jinja-token") || node?.textContent || "";
			}
		}

		HvJinjaTokenBlot.blotName = "hv_jinja_token";
		HvJinjaTokenBlot.tagName = "span";
		HvJinjaTokenBlot.className = "hv-jinja-badge";

		try {
			Quill.register(HvJinjaTokenBlot, true);
			api._hv_jinja_token_registered = true;
			return true;
		} catch (e) {
			return false;
		}
	};

	const upgrade_existing_badges = (quill) => {
		if (!quill || !quill.root || quill.__hv_placeholder_upgraded) return;
		if (!quill.root.querySelector) return;
		if (
			!quill.root.querySelector(".hv-placeholder-badge") &&
			!quill.root.querySelector(".hv-jinja-badge")
		) {
			return;
		}
		if (!quill.clipboard || typeof quill.clipboard.dangerouslyPasteHTML !== "function") return;

		const html = quill.root.innerHTML;
		let selection = null;
		try {
			selection = typeof quill.getSelection === "function" ? quill.getSelection() : null;
		} catch (e) {
			selection = null;
		}

		try {
			quill.clipboard.dangerouslyPasteHTML(html, "silent");
			if (selection && typeof quill.setSelection === "function") {
				quill.setSelection(selection.index, selection.length || 0, "silent");
			}
			quill.__hv_placeholder_upgraded = true;
		} catch (e) {
			// ignore
		}
	};

	const ensure_selection_tracking = (quill) => {
		if (!quill || typeof quill.on !== "function") return;
		if (quill.__hv_selection_tracking_installed) return;
		quill.__hv_selection_tracking_installed = true;

		const remember_selection = () => {
			let range = null;
			try {
				range =
					typeof quill.getSelection === "function"
						? quill.getSelection(true)
						: null;
			} catch (e) {
				range = null;
			}
			if (!range || typeof range.index !== "number") return;
			quill[HV_LAST_SELECTION_KEY] = {
				index: range.index,
				length: range.length || 0,
			};
		};

		quill.on("selection-change", (range) => {
			if (!range) return;
			quill[HV_LAST_SELECTION_KEY] = {
				index: range.index,
				length: range.length || 0,
			};
		});

		const root = quill.root;
		if (root && typeof root.addEventListener === "function") {
			["mouseup", "keyup", "touchend"].forEach((eventName) => {
				root.addEventListener(eventName, () => {
					window.setTimeout(remember_selection, 0);
				});
			});
		}
	};

	const get_cached_selection = (quill) => {
		if (!quill) return null;
		const cached = quill[HV_LAST_SELECTION_KEY];
		if (!cached || typeof cached !== "object") return null;
		if (typeof cached.index !== "number") return null;
		return { index: cached.index, length: cached.length || 0 };
	};

	const get_insertion_index = (quill) => {
		let selection = null;
		if (typeof quill?.getSelection === "function") {
			try {
				selection = quill.getSelection(true);
			} catch (e) {
				selection = null;
			}
		}
		if (!selection) {
			selection = get_cached_selection(quill);
		}
		if (selection) return selection.index;
		return typeof quill?.getLength === "function" ? quill.getLength() : 0;
	};

	const is_atomic_placeholder_leaf = (leaf) => {
		if (!leaf) return false;
		const blotName = leaf?.statics?.blotName || "";
		if (blotName === "hv_placeholder" || blotName === "hv_jinja_token") {
			return true;
		}
		const domNode = leaf?.domNode;
		if (!domNode || !domNode.classList) return false;
		return domNode.classList.contains("hv-placeholder-badge") || domNode.classList.contains("hv-jinja-badge");
	};

	const get_atomic_leaf_at = (quill, index) => {
		if (!quill || typeof quill.getLeaf !== "function") return null;
		if (typeof index !== "number" || index < 0) return null;
		try {
			const [leaf] = quill.getLeaf(index) || [];
			return is_atomic_placeholder_leaf(leaf) ? leaf : null;
		} catch (e) {
			return null;
		}
	};

	const delete_atomic_leaf = (quill, leaf) => {
		if (!quill || !leaf || typeof quill.getIndex !== "function" || typeof quill.deleteText !== "function") {
			return false;
		}
		try {
			const index = quill.getIndex(leaf);
			if (typeof index !== "number" || index < 0) return false;
			quill.deleteText(index, 1, "user");
			quill.setSelection && quill.setSelection(index, 0, "silent");
			return true;
		} catch (e) {
			return false;
		}
	};

	const install_atomic_delete_bindings = (quill) => {
		if (!quill || !quill.keyboard || typeof quill.keyboard.addBinding !== "function") return;
		if (quill.__hv_atomic_delete_bindings_installed) return;
		quill.__hv_atomic_delete_bindings_installed = true;

		quill.keyboard.addBinding({ key: "Backspace" }, { collapsed: true }, (range) => {
			if (!range || typeof range.index !== "number" || range.index <= 0) return true;
			const leaf = get_atomic_leaf_at(quill, range.index - 1);
			if (!leaf) return true;
			return !delete_atomic_leaf(quill, leaf);
		});

		quill.keyboard.addBinding({ key: "Delete" }, { collapsed: true }, (range) => {
			if (!range || typeof range.index !== "number") return true;
			const leaf = get_atomic_leaf_at(quill, range.index);
			if (!leaf) return true;
			return !delete_atomic_leaf(quill, leaf);
		});
	};

	api.ensure_for_quill = (quill) => {
		if (!quill || !quill.root) return false;
		ensure_styles();
		ensure_selection_tracking(quill);
		install_atomic_delete_bindings(quill);
		const ok = register_placeholder_blot(quill) && register_jinja_token_blot(quill);
		if (ok) {
			upgrade_existing_badges(quill);
		}
		return ok;
	};

	api.ensure_for_control = (control) => {
		const quill = control?.quill || control?.editor;
		return api.ensure_for_quill(quill);
	};

	api.insert_into_quill = (quill, value) => {
		if (!quill || typeof quill.insertEmbed !== "function") return false;
		api.ensure_for_quill(quill);

		let index = get_insertion_index(quill);

		quill.focus && quill.focus();
		quill.insertEmbed(index, "hv_placeholder", value, "user");
		quill.insertText(index + 1, " ", "user");
		quill.setSelection && quill.setSelection(index + 2, 0, "user");
		return true;
	};

	api.insert_sequence = (quill, parts) => {
		if (!quill || typeof quill.insertEmbed !== "function") return false;
		if (!Array.isArray(parts) || !parts.length) return false;
		api.ensure_for_quill(quill);

		let index = get_insertion_index(quill);

		quill.focus && quill.focus();

		parts.forEach((part) => {
			const kind = part?.kind || "";
			const value = part?.value == null ? "" : String(part.value);
			if (kind === "token") {
				quill.insertEmbed(index, "hv_jinja_token", value, "user");
				index += 1;
				return;
			}
			if (kind === "newline") {
				quill.insertText(index, "\n", "user");
				index += 1;
				return;
			}
			quill.insertText(index, value, "user");
			index += value.length;
		});

		quill.setSelection && quill.setSelection(index, 0, "user");
		return true;
	};
})();
