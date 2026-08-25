frappe.pages.problemzentrale.on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Problemzentrale"),
		single_column: true,
	});
	const center = new HausverwaltungProblemCenter(page);
	page.set_primary_action(__("Jetzt prüfen"), () => center.runChecks(), "refresh");
	center.mount();
};

class HausverwaltungProblemCenter {
	constructor(page) {
		this.page = page;
		this.$root = $(page.body);
		this.state = {
			filters: { status: "aktiv", severity: "", type_code: "", search: "" },
			rows: [],
			total: 0,
			selected: null,
			detail: null,
			loading: false,
		};
	}

	mount() {
		this.ensureStyles();
		this.$root.html(`
			<div class="hv-problem-center">
				<div class="hv-problem-metrics"></div>
				<div class="hv-filterbar hv-problem-filterbar">
					<label class="hv-filter"><span class="hv-filter-label">${__("Status")}</span>
						<select class="hv-field" data-filter="status">
							<option value="aktiv">${__("Aktiv")}</option>
							<option value="Offen">${__("Offen")}</option>
							<option value="In Bearbeitung">${__("In Bearbeitung")}</option>
							<option value="Akzeptiert">${__("Akzeptiert")}</option>
							<option value="Behoben">${__("Behoben")}</option>
							<option value="alle">${__("Alle")}</option>
						</select>
					</label>
					<label class="hv-filter"><span class="hv-filter-label">${__("Schweregrad")}</span>
						<select class="hv-field" data-filter="severity">
							<option value="">${__("Alle")}</option>
							<option value="Kritisch">${__("Kritisch")}</option>
							<option value="Warnung">${__("Warnung")}</option>
							<option value="Hinweis">${__("Hinweis")}</option>
						</select>
					</label>
					<label class="hv-filter hv-problem-type-filter"><span class="hv-filter-label">${__("Problemtyp")}</span>
						<select class="hv-field" data-filter="type_code"><option value="">${__("Alle")}</option></select>
					</label>
					<label class="hv-filter hv-problem-search"><span class="hv-filter-label">${__("Suche")}</span>
						<input class="hv-field" data-filter="search" type="search" placeholder="${__("Adresse, Ordner, Vertrag …")}">
					</label>
					<div class="hv-problem-filter-count"></div>
				</div>
				<div class="hv-problem-layout">
					<section class="hv-problem-list-panel" aria-label="${__("Probleme")}">
						<div class="hv-problem-list"></div>
						<button class="hv-btn hv-btn-ghost hv-problem-more" type="button">${__("Weitere laden")}</button>
					</section>
					<section class="hv-problem-detail" aria-live="polite"></section>
				</div>
			</div>
		`);
		this.bindEvents();
		this.load(true);
	}

	ensureStyles() {
		if (document.getElementById("hv-problem-center-styles")) return;
		const style = document.createElement("style");
		style.id = "hv-problem-center-styles";
		style.textContent = `
			.hv-problem-center { display:flex; flex-direction:column; gap:14px; padding:4px 0 18px; color:var(--hv-ink); }
			.hv-problem-metrics { display:grid; grid-template-columns:repeat(4,minmax(150px,1fr)); gap:12px; }
			.hv-problem-metric { padding:14px 16px; border:1px solid var(--hv-line); border-radius:var(--hv-radius-lg); background:var(--hv-surface); box-shadow:var(--hv-shadow); }
			.hv-problem-metric strong { display:block; font-size:24px; line-height:1.1; margin-bottom:4px; font-variant-numeric:tabular-nums; }
			.hv-problem-metric span { color:var(--hv-ink-3); font-size:var(--hv-fs-sm); }
			.hv-problem-metric.is-critical { box-shadow:inset 3px 0 0 var(--hv-danger),var(--hv-shadow); }
			.hv-problem-filterbar { gap:14px; }
			.hv-problem-type-filter { min-width:260px; }
			.hv-problem-search { flex:1 1 260px; }
			.hv-problem-search input { width:100%; }
			.hv-problem-filter-count { margin-left:auto; color:var(--hv-ink-3); font-size:var(--hv-fs-sm); white-space:nowrap; }
			.hv-problem-layout { display:grid; grid-template-columns:minmax(320px,390px) minmax(0,1fr); gap:14px; min-height:65vh; }
			.hv-problem-list-panel,.hv-problem-detail { border:1px solid var(--hv-line); border-radius:var(--hv-radius-lg); background:var(--hv-surface); box-shadow:var(--hv-shadow); overflow:hidden; }
			.hv-problem-list-panel { display:flex; flex-direction:column; }
			.hv-problem-list { overflow:auto; max-height:72vh; }
			.hv-problem-row { width:100%; display:block; text-align:left; padding:13px 14px; border:0; border-bottom:1px solid var(--hv-line); border-left:3px solid transparent; background:transparent; color:var(--hv-ink); cursor:pointer; }
			.hv-problem-row:hover { background:var(--hv-surface-2); }
			.hv-problem-row.is-selected { background:var(--hv-primary-soft); border-left-color:var(--hv-primary); }
			.hv-problem-row-head { display:flex; gap:8px; align-items:flex-start; justify-content:space-between; }
			.hv-problem-row-title { font-weight:600; font-size:var(--hv-fs); line-height:1.35; overflow-wrap:anywhere; }
			.hv-problem-row-meta { margin-top:7px; display:flex; gap:6px; align-items:center; flex-wrap:wrap; color:var(--hv-ink-3); font-size:var(--hv-fs-xs); }
			.hv-problem-more { margin:10px; justify-content:center; }
			.hv-problem-detail { padding:20px; overflow:auto; max-height:72vh; }
			.hv-problem-empty { min-height:240px; display:flex; align-items:center; justify-content:center; text-align:center; color:var(--hv-ink-3); padding:30px; }
			.hv-problem-detail-head { display:flex; justify-content:space-between; align-items:flex-start; gap:18px; padding-bottom:16px; border-bottom:1px solid var(--hv-line); }
			.hv-problem-detail-head h2 { margin:5px 0 7px; font-size:20px; line-height:1.3; color:var(--hv-ink); }
			.hv-problem-kicker { color:var(--hv-ink-3); font-size:var(--hv-fs-sm); }
			.hv-problem-actions { display:flex; flex-wrap:wrap; justify-content:flex-end; gap:8px; min-width:210px; }
			.hv-problem-references { display:flex; gap:8px; flex-wrap:wrap; margin-top:12px; }
			.hv-problem-reference { border:0; padding:0; background:none; color:var(--hv-primary); cursor:pointer; font-size:var(--hv-fs-sm); }
			.hv-problem-section { margin-top:18px; }
			.hv-problem-section h3 { margin:0 0 9px; font-size:14px; color:var(--hv-ink); }
			.hv-problem-section p { white-space:pre-wrap; line-height:1.55; color:var(--hv-ink-2); }
			.hv-problem-section ul { margin:0; padding-left:20px; color:var(--hv-ink-2); }
			.hv-problem-section li { margin:5px 0; overflow-wrap:anywhere; }
			.hv-problem-section .hv-cardgrid { grid-template-columns:repeat(auto-fit,minmax(145px,1fr)); }
			.hv-problem-section .hv-table-wrap { max-height:300px; overflow:auto; }
			.hv-problem-section .hv-table td { vertical-align:top; overflow-wrap:anywhere; }
			.hv-problem-loading { opacity:.62; pointer-events:none; }
			@media (max-width:900px) {
				.hv-problem-metrics { grid-template-columns:repeat(2,1fr); }
				.hv-problem-layout { grid-template-columns:1fr; }
				.hv-problem-list { max-height:42vh; }
				.hv-problem-detail { max-height:none; }
				.hv-problem-detail-head { flex-direction:column; }
				.hv-problem-actions { justify-content:flex-start; }
			}
		`;
		document.head.appendChild(style);
	}

	bindEvents() {
		this.$root.on("change", "[data-filter]:not([data-filter='search'])", (event) => {
			this.state.filters[event.currentTarget.dataset.filter] = event.currentTarget.value;
			this.load(true);
		});
		let timer = null;
		this.$root.on("input", "[data-filter='search']", (event) => {
			clearTimeout(timer);
			timer = setTimeout(() => {
				this.state.filters.search = event.currentTarget.value;
				this.load(true);
			}, 280);
		});
		this.$root.on("click", ".hv-problem-row", (event) => this.select(event.currentTarget.dataset.name));
		this.$root.on("click", ".hv-problem-more", () => this.load(false));
		this.$root.on("click", ".hv-problem-reference", (event) => {
			frappe.set_route("Form", event.currentTarget.dataset.doctype, event.currentTarget.dataset.name);
		});
		this.$root.on("click", ".hv-problem-action", (event) => {
			const action = (this.state.detail?.ui?.actions || []).find(
				(item) => item.key === event.currentTarget.dataset.action
			);
			if (action) this.startAction(action);
		});
	}

	async call(method, args = {}) {
		const response = await frappe.call({ method, args });
		return response.message || {};
	}

	async load(reset) {
		if (this.state.loading) return;
		this.state.loading = true;
		this.$root.find(".hv-problem-center").addClass("hv-problem-loading");
		try {
			const start = reset ? 0 : this.state.rows.length;
			const data = await this.call(
				"hausverwaltung.hausverwaltung.page.problemzentrale.problemzentrale.get_overview",
				{ filters: this.state.filters, start, page_length: 100 }
			);
			this.state.rows = reset ? data.rows || [] : this.state.rows.concat(data.rows || []);
			this.state.total = data.total || 0;
			this.renderMetrics(data.metrics || {});
			this.renderTypes(data.types || []);
			this.renderList();
			if (reset) {
				const next = this.state.rows.some((row) => row.name === this.state.selected)
					? this.state.selected
					: this.state.rows[0]?.name;
				if (next) await this.select(next);
				else this.renderEmptyDetail();
			}
		} catch (error) {
			frappe.msgprint({ title: __("Problemzentrale konnte nicht geladen werden"), message: error.message, indicator: "red" });
		} finally {
			this.state.loading = false;
			this.$root.find(".hv-problem-center").removeClass("hv-problem-loading");
		}
	}

	renderMetrics(metrics) {
		const cards = [
			[metrics.active || 0, __("Aktive Probleme"), ""],
			[metrics.critical || 0, __("Kritisch"), "is-critical"],
			[metrics.in_progress || 0, __("In Bearbeitung"), ""],
			[metrics.accepted || 0, __("Akzeptiert"), ""],
		];
		this.$root.find(".hv-problem-metrics").html(
			cards.map(([value, label, cls]) => `<div class="hv-problem-metric ${cls}"><strong>${value}</strong><span>${this.esc(label)}</span></div>`).join("")
		);
	}

	renderTypes(types) {
		const $select = this.$root.find("[data-filter='type_code']");
		const selected = this.state.filters.type_code;
		$select.html(`<option value="">${__("Alle")}</option>${types.map((type) => `<option value="${this.esc(type.code)}">${this.esc(type.label)} (${type.count})</option>`).join("")}`);
		$select.val(selected);
	}

	renderList() {
		const $list = this.$root.find(".hv-problem-list");
		if (!this.state.rows.length) {
			$list.html(`<div class="hv-problem-empty">${__("Keine Probleme für diese Filter gefunden.")}</div>`);
		} else {
			$list.html(this.state.rows.map((row) => this.rowHtml(row)).join(""));
		}
		this.$root.find(".hv-problem-filter-count").text(
			__("{0} von {1}", [this.state.rows.length, this.state.total])
		);
		this.$root.find(".hv-problem-more").toggle(this.state.rows.length < this.state.total);
	}

	rowHtml(row) {
		const severityClass = row.severity === "Kritisch" ? "hv-pill-danger" : row.severity === "Warnung" ? "hv-pill-warning" : "hv-pill-info";
		return `<button type="button" class="hv-problem-row ${row.name === this.state.selected ? "is-selected" : ""}" data-name="${this.esc(row.name)}">
			<div class="hv-problem-row-head"><div class="hv-problem-row-title">${this.esc(row.title)}</div></div>
			<div class="hv-problem-row-meta"><span class="hv-pill ${severityClass}">${this.esc(row.severity)}</span><span>${this.esc(row.type)}</span>${row.secondary_name ? `<span>· ${this.esc(row.secondary_name)}</span>` : ""}</div>
		</button>`;
	}

	async select(name) {
		if (!name) return;
		this.state.selected = name;
		this.renderList();
		this.$root.find(".hv-problem-detail").html(`<div class="hv-problem-empty">${__("Details werden geladen …")}</div>`);
		try {
			this.state.detail = await this.call(
				"hausverwaltung.hausverwaltung.page.problemzentrale.problemzentrale.get_problem_detail",
				{ name }
			);
			if (this.state.selected === name) this.renderDetail();
		} catch (error) {
			this.$root.find(".hv-problem-detail").html(`<div class="hv-problem-empty">${this.esc(error.message)}</div>`);
		}
	}

	renderEmptyDetail() {
		this.state.selected = null;
		this.state.detail = null;
		this.$root.find(".hv-problem-detail").html(`<div class="hv-problem-empty">${__("Wähle links ein Problem aus.")}</div>`);
	}

	renderDetail() {
		const detail = this.state.detail;
		const problem = detail.problem;
		const definition = detail.type_definition || {};
		const actions = detail.ui?.actions || [];
		const references = [
			[problem.reference_doctype, problem.reference_name],
			[problem.secondary_doctype, problem.secondary_name],
		].filter(([doctype, name]) => doctype && name);
		const actionHtml = actions.map((action) => `<button type="button" class="hv-btn ${action.variant === "primary" ? "hv-btn-primary" : "hv-btn-ghost"} hv-problem-action" data-action="${this.esc(action.key)}">${this.esc(action.label)}</button>`).join("");
		const referenceHtml = references.map(([doctype, name]) => `<button type="button" class="hv-problem-reference" data-doctype="${this.esc(doctype)}" data-name="${this.esc(name)}">${this.esc(doctype)}: ${this.esc(name)}</button>`).join("");
		this.$root.find(".hv-problem-detail").html(`
			<div class="hv-problem-detail-head">
				<div>
					<div class="hv-problem-kicker">${this.esc(definition.category || problem.source)} · ${this.esc(problem.status)}</div>
					<h2>${this.esc(problem.title)}</h2>
					<span class="hv-pill ${problem.severity === "Kritisch" ? "hv-pill-danger" : problem.severity === "Warnung" ? "hv-pill-warning" : "hv-pill-info"}">${this.esc(problem.severity)}</span>
					<div class="hv-problem-references">${referenceHtml}</div>
				</div>
				<div class="hv-problem-actions">${actionHtml}</div>
			</div>
			<div class="hv-problem-sections">${(detail.ui?.sections || []).map((section) => this.sectionHtml(section)).join("")}</div>
		`);
	}

	sectionHtml(section) {
		const title = section.title ? `<h3>${this.esc(section.title)}</h3>` : "";
		if (section.type === "metrics") {
			return `<section class="hv-problem-section">${title}<div class="hv-cardgrid">${(section.items || []).map((item) => `<div class="hv-card"><span class="hv-stat-label">${this.esc(item.label)}</span><strong class="hv-stat-value">${this.esc(item.value)}</strong></div>`).join("")}</div></section>`;
		}
		if (section.type === "list") {
			return `<section class="hv-problem-section">${title}<ul>${(section.items || []).map((item) => `<li>${this.esc(item)}</li>`).join("")}</ul></section>`;
		}
		if (section.type === "table") {
			const columns = section.columns || [];
			return `<section class="hv-problem-section">${title}<div class="hv-table-wrap"><table class="hv-table"><thead><tr>${columns.map((column) => `<th>${this.esc(column.label)}</th>`).join("")}</tr></thead><tbody>${(section.rows || []).map((row) => `<tr>${columns.map((column) => `<td>${this.esc(row[column.key])}</td>`).join("")}</tr>`).join("")}</tbody></table></div></section>`;
		}
		return `<section class="hv-problem-section">${title}<p>${this.esc(section.value || "")}</p></section>`;
	}

	startAction(action) {
		const fields = (action.fields || []).map((field) => ({ ...field }));
		if (!fields.length) {
			if (action.confirm) frappe.confirm(action.confirm, () => this.executeAction(action.key, {}));
			else this.executeAction(action.key, {});
			return;
		}
		const dialog = new frappe.ui.Dialog({
			title: action.dialog_title || action.label,
			fields,
			primary_action_label: action.label,
			primary_action: (values) => {
				dialog.hide();
				this.executeAction(action.key, values);
			},
		});
		for (const field of action.fields || []) {
			if (field.filters && dialog.fields_dict[field.fieldname]) {
				dialog.fields_dict[field.fieldname].get_query = () => ({ filters: field.filters });
			}
		}
		dialog.show();
	}

	async executeAction(action, values) {
		try {
			const result = await frappe.call({
				method: "hausverwaltung.hausverwaltung.page.problemzentrale.problemzentrale.run_problem_action",
				args: { name: this.state.selected, action, values },
				freeze: true,
				freeze_message: __("Problem wird bearbeitet …"),
			});
			frappe.show_alert({ message: result.message?.message || __("Aktion ausgeführt"), indicator: "green" });
			await this.load(true);
		} catch (error) {
			frappe.msgprint({ title: __("Aktion fehlgeschlagen"), message: error.message, indicator: "red" });
		}
	}

	async runChecks() {
		try {
			await frappe.call({
				method: "hausverwaltung.hausverwaltung.page.problemzentrale.problemzentrale.run_checks",
				freeze: true,
				freeze_message: __("Probleme werden geprüft …"),
			});
			frappe.show_alert({ message: __("Prüfung abgeschlossen"), indicator: "green" });
			await this.load(true);
		} catch (error) {
			frappe.msgprint({ title: __("Prüfung fehlgeschlagen"), message: error.message, indicator: "red" });
		}
	}

	esc(value) {
		return $("<div>").text(value === null || value === undefined ? "" : String(value)).html();
	}
}
