// Buchungs-Inbox-Page: Master-Detail-Ansicht für Buchungs-Vorschläge.
//
// Layout:
//   ┌──────────────────────────────────────────────────────────────────┐
//   │ Filter-Bar (Status / Session / Sort)        [+ Sammel] [⟳]      │
//   ├────────────────────┬─────────────────────────────────────────────┤
//   │ Sidebar-Liste      │ Detail-Pane (split: Werte | PDF iframe)     │
//   └────────────────────┴─────────────────────────────────────────────┘

frappe.provide("hausverwaltung.buchungs_inbox");

const HV_INBOX_STYLE_ID = "hv-buchungs-inbox-styles";
const HV_INBOX_API = "hausverwaltung.hausverwaltung.services.bulk_extraction";
const HV_INBOX_COCKPIT_API = "hausverwaltung.hausverwaltung.page.buchen_cockpit.buchen_cockpit";

const _hv_inbox_ensure_styles = () => {
	if (document.getElementById(HV_INBOX_STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = HV_INBOX_STYLE_ID;
	style.textContent = `
		.hv-inbox {
			display: flex;
			flex-direction: column;
			gap: 12px;
			padding: 8px 4px;
		}
		.hv-inbox-filterbar {
			display: flex;
			gap: 12px;
			align-items: center;
			padding: 10px 12px;
			background: var(--card-bg, #fff);
			border: 1px solid var(--border-color, #e0e0e0);
			border-radius: 8px;
			flex-wrap: wrap;
		}
		.hv-inbox-filterbar .hv-filter-control {
			display: flex;
			flex-direction: column;
			gap: 2px;
			min-width: 140px;
		}
		.hv-inbox-filterbar .hv-filter-control label {
			font-size: 11px;
			color: var(--text-muted, #666);
			margin: 0;
		}
		.hv-inbox-filterbar .hv-filter-control select {
			padding: 4px 8px;
			border: 1px solid var(--border-color, #d9d9d9);
			border-radius: 4px;
			background: #fff;
			font-size: 13px;
		}
		.hv-inbox-filterbar .spacer { flex: 1 1 auto; }
		.hv-inbox-filterbar button {
			padding: 6px 12px;
			border: 1px solid var(--border-color, #d9d9d9);
			background: var(--btn-default-bg, #fff);
			border-radius: 4px;
			cursor: pointer;
			font-size: 13px;
		}
		.hv-inbox-filterbar button:hover { background: #f5f5f5; }
		.hv-inbox-filterbar button.btn-primary {
			background: var(--primary, #1976d2);
			color: #fff;
			border-color: var(--primary, #1976d2);
		}
		.hv-inbox-body {
			display: flex;
			gap: 12px;
			min-height: 70vh;
		}
		.hv-inbox-list {
			flex: 0 0 320px;
			max-height: 80vh;
			overflow-y: auto;
			background: var(--card-bg, #fff);
			border: 1px solid var(--border-color, #e0e0e0);
			border-radius: 8px;
			padding: 6px;
		}
		.hv-inbox-list-row {
			padding: 8px 10px;
			border-bottom: 1px solid var(--border-color, #f0f0f0);
			cursor: pointer;
			border-left: 3px solid transparent;
		}
		.hv-inbox-list-row:hover { background: #f9f9f9; }
		.hv-inbox-list-row.selected { background: #e3f2fd; border-left-color: #1976d2; }
		.hv-inbox-list-row .row-title { font-size: 13px; font-weight: 600; }
		.hv-inbox-list-row .row-sub { font-size: 11px; color: var(--text-muted, #666); margin-top: 2px; }
		.hv-inbox-list-empty { padding: 30px; text-align: center; color: var(--text-muted, #666); }
		.hv-inbox-detail {
			flex: 1 1 auto;
			background: var(--card-bg, #fff);
			border: 1px solid var(--border-color, #e0e0e0);
			border-radius: 8px;
			padding: 12px;
			display: flex;
			flex-direction: column;
		}
		.hv-inbox-detail-empty {
			flex: 1;
			display: flex;
			align-items: center;
			justify-content: center;
			color: var(--text-muted, #666);
		}
		.hv-inbox-detail-header {
			padding-bottom: 8px;
			margin-bottom: 12px;
			border-bottom: 1px solid var(--border-color, #f0f0f0);
			display: flex;
			justify-content: space-between;
			align-items: center;
			gap: 12px;
		}
		.hv-inbox-detail-header .title { font-weight: 600; font-size: 14px; }
		.hv-inbox-detail-header .actions { display: flex; gap: 6px; }
		.hv-inbox-detail-header .actions button {
			padding: 5px 10px;
			border: 1px solid var(--border-color, #d9d9d9);
			background: #fff;
			border-radius: 4px;
			cursor: pointer;
			font-size: 13px;
		}
		.hv-inbox-detail-header .actions button.btn-primary {
			background: var(--primary, #1976d2);
			color: #fff;
			border-color: var(--primary, #1976d2);
		}
		.hv-inbox-detail-header .actions button:disabled {
			opacity: 0.5;
			cursor: not-allowed;
		}
		.hv-inbox-split {
			display: flex;
			gap: 12px;
			flex: 1 1 auto;
			min-height: 60vh;
		}
		.hv-inbox-values {
			flex: 1 1 0;
			min-width: 360px;
			overflow-y: auto;
			padding-right: 4px;
		}
		.hv-inbox-pdf {
			flex: 1 1 0;
			min-width: 400px;
			border: 1px solid var(--border-color, #e0e0e0);
			border-radius: 4px;
			background: #f5f5f5;
			display: flex;
			flex-direction: column;
			overflow: hidden;
		}
		.hv-inbox-pdf iframe,
		.hv-inbox-pdf embed,
		.hv-inbox-pdf object {
			width: 100%;
			border: 0;
			flex: 1 1 auto;
			height: 100%;
			min-height: 60vh;
		}
		@media (max-width: 1200px) {
			.hv-inbox-split { flex-direction: column; }
			.hv-inbox-pdf { min-width: 100%; min-height: 50vh; }
		}
		.hv-status-pill {
			display: inline-block;
			padding: 1px 8px;
			border-radius: 10px;
			font-size: 11px;
			color: #fff;
		}
	`;
	document.head.appendChild(style);
};

const _STATUS_COLOR = {
	Pending: "#888",
	Processing: "#7b1fa2",
	Ready: "#1976d2",
	Booked: "#2e7d32",
	Skipped: "#9e9e9e",
	Error: "#c62828",
};
const _STATUS_LABEL = {
	Pending: __("wartet"),
	Processing: __("läuft"),
	Ready: __("bereit"),
	Booked: __("gebucht"),
	Skipped: __("übersprungen"),
	Error: __("Fehler"),
};

const _hv_status_pill = (s) => {
	const color = _STATUS_COLOR[s] || "#666";
	const label = _STATUS_LABEL[s] || s;
	return `<span class="hv-status-pill" style="background:${color};">${label}</span>`;
};

const _hv_format_currency = (value) => {
	try {
		return frappe.format(value || 0, { fieldtype: "Currency" });
	} catch (e) {
		return value;
	}
};

const _hv_conf_color = (s) => (s >= 0.85 ? "#2e7d32" : s >= 0.65 ? "#f57f17" : "#c62828");
const _hv_conf_pill = (s) => {
	if (s === undefined || s === null) return "";
	const pct = Math.round(Number(s) * 100);
	return `<span style="background:${_hv_conf_color(s)};color:#fff;padding:1px 6px;border-radius:8px;font-size:10px;margin-left:4px;">${pct}%</span>`;
};

const HV_INBOX_PREFS_KEY = "hv_buchungs_inbox_prefs";

const _hv_inbox_load_prefs = () => {
	try {
		const raw = localStorage.getItem(HV_INBOX_PREFS_KEY);
		return raw ? JSON.parse(raw) : {};
	} catch (e) {
		return {};
	}
};

const _hv_inbox_save_prefs = (prefs) => {
	try {
		localStorage.setItem(HV_INBOX_PREFS_KEY, JSON.stringify(prefs));
	} catch (e) {
		/* SafeStorage voll / Privacy-Mode → still */
	}
};

hausverwaltung.buchungs_inbox.mount = ($container, options) => {
	_hv_inbox_ensure_styles();
	options = options || {};

	// Status + Sort werden über Reloads via localStorage persistiert.
	// session_id NICHT — die kommt immer frisch aus Route-Options.
	const prefs = _hv_inbox_load_prefs();
	const state = {
		filters: {
			status: options.status || prefs.status || "open",
			session_id: options.session_id || "",
		},
		sort_by: prefs.sort_by || "creation",
		sort_order: prefs.sort_order || "desc",
		rows: [],
		sessions: [],
		selected_name: null,
		full_cache: {}, // vorschlag_name → full data
		poll_timer: null,
		poll_paused: false, // pausieren wenn modaler Buchen-Dialog offen
		current_pdf_url: null, // letzte gerenderte PDF-URL — für Re-Render-Vermeidung
		refresh_seq: 0, // monoton steigend, gegen stale-overwrite bei parallelen refresh_list
	};

	const layout = $(`
		<div class="hv-inbox">
			<div class="hv-inbox-filterbar">
				<div class="hv-filter-control">
					<label>${__("Status")}</label>
					<select data-filter="status">
						<option value="open">${__("Offen (Pending/Processing/Ready)")}</option>
						<option value="alle">${__("Alle")}</option>
						<option value="Ready">${__("Ready")}</option>
						<option value="Pending">${__("Pending")}</option>
						<option value="Processing">${__("Processing")}</option>
						<option value="Booked">${__("Booked")}</option>
						<option value="Skipped">${__("Skipped")}</option>
						<option value="Error">${__("Error")}</option>
					</select>
				</div>
				<div class="hv-filter-control">
					<label>${__("Session")}</label>
					<select data-filter="session_id">
						<option value="">${__("Alle Sessions")}</option>
					</select>
				</div>
				<div class="hv-filter-control">
					<label>${__("Sortierung")}</label>
					<select data-filter="sort">
						<option value="creation desc">${__("Neueste zuerst")}</option>
						<option value="creation asc">${__("Älteste zuerst")}</option>
						<option value="status asc">${__("Status A-Z")}</option>
						<option value="original_filename asc">${__("Dateiname A-Z")}</option>
					</select>
				</div>
				<div class="spacer"></div>
				<button class="btn-refresh" title="${__("Liste neu laden")}">⟳ ${__("Refresh")}</button>
				<button class="btn-bulk btn-primary">+ ${__("Sammel-Upload")}</button>
			</div>
			<div class="hv-inbox-body">
				<div class="hv-inbox-list">
					<div class="hv-inbox-list-empty">${__("Lade...")}</div>
				</div>
				<div class="hv-inbox-detail">
					<div class="hv-inbox-detail-empty">${__("Wähle einen Vorschlag aus der Liste links.")}</div>
				</div>
			</div>
		</div>
	`);

	$container.empty().append(layout);

	// Filter-Initialisierung — incl. wiederhergestellter Sort-Auswahl
	layout.find('select[data-filter="status"]').val(state.filters.status);
	layout
		.find('select[data-filter="sort"]')
		.val(`${state.sort_by} ${state.sort_order}`);

	// Event-Handlers
	layout.on("change", "select[data-filter]", (event) => {
		const $el = $(event.currentTarget);
		const key = $el.data("filter");
		const val = $el.val();
		if (key === "sort") {
			const [sb, so] = (val || "creation desc").split(" ");
			state.sort_by = sb;
			state.sort_order = so;
		} else {
			state.filters[key] = val;
		}
		// Status + Sort persistieren (Session bleibt bewusst route-getrieben).
		_hv_inbox_save_prefs({
			status: state.filters.status,
			sort_by: state.sort_by,
			sort_order: state.sort_order,
		});
		refresh_list();
	});

	layout.on("click", ".btn-refresh", () => refresh_list());
	layout.on("click", ".btn-bulk", () => {
		if (
			hausverwaltung.buchen_cockpit
			&& typeof hausverwaltung.buchen_cockpit.open_bulk_upload_dialog === "function"
		) {
			hausverwaltung.buchen_cockpit.open_bulk_upload_dialog();
		}
	});

	layout.on("click", ".hv-inbox-list-row", (event) => {
		const name = $(event.currentTarget).data("name");
		if (!name) return;
		state.selected_name = name;
		render_list();
		render_detail();
	});

	const refresh_list = () => {
		const my_seq = ++state.refresh_seq;
		frappe
			.call({
				method: `${HV_INBOX_API}.list_vorschlaege`,
				args: {
					status: state.filters.status,
					session_id: state.filters.session_id,
					sort_by: state.sort_by,
					sort_order: state.sort_order,
					limit: 200,
				},
			})
			.then((r) => {
				// Stale-Response verwerfen (z.B. Polling-Fetch der zurückkommt
				// nachdem der User schon den Filter gewechselt und eine neue
				// Anfrage rausgeschickt hat).
				if (my_seq !== state.refresh_seq) return;
				const data = (r && r.message) || { rows: [], sessions: [] };
				const new_rows = data.rows || [];

				// Cache-Invalidation: wenn sich der Status eines Vorschlags
				// geändert hat (z.B. Worker fertig: Processing → Ready), den
				// gecachten full-Eintrag wegwerfen, damit render_detail ihn neu
				// fetcht. Sonst zeigt das Detail-Pane ewig "Worker noch nicht fertig".
				const prev_status = {};
				for (const r0 of state.rows) prev_status[r0.name] = r0.status;
				for (const r1 of new_rows) {
					if (prev_status[r1.name] && prev_status[r1.name] !== r1.status) {
						delete state.full_cache[r1.name];
					}
				}

				state.rows = new_rows;
				state.sessions = data.sessions || [];
				_update_session_dropdown();
				if (
					!state.selected_name
					|| !state.rows.find((row) => row.name === state.selected_name)
				) {
					state.selected_name = state.rows.length ? state.rows[0].name : null;
				}
				render_list();
				render_detail();
				schedule_poll();
			});
	};

	const _update_session_dropdown = () => {
		const $sel = layout.find('select[data-filter="session_id"]');
		const current = state.filters.session_id || "";
		const options = [
			`<option value="">${__("Alle Sessions")}</option>`,
			...state.sessions.map(
				(s) =>
					`<option value="${frappe.utils.escape_html(s)}">${frappe.utils.escape_html(s)}</option>`
			),
		];
		$sel.html(options.join(""));
		$sel.val(current);
	};

	// Externer Hook: erlaubt Aufrufern (Cockpit "Analysieren starten",
	// Router-Change-Listener) die Inbox auf neue Route-Options zu rebooten,
	// ohne dass der User F5 drücken muss.
	hausverwaltung.buchungs_inbox._apply_route_options = (route_options) => {
		if (!route_options || !Object.keys(route_options).length) return;
		if (route_options.session_id !== undefined) {
			state.filters.session_id = route_options.session_id || "";
			const $sel = layout.find('select[data-filter="session_id"]');
			if (
				route_options.session_id
				&& !$sel.find(`option[value="${route_options.session_id}"]`).length
			) {
				$sel.append(
					`<option value="${frappe.utils.escape_html(route_options.session_id)}">${frappe.utils.escape_html(route_options.session_id)}</option>`
				);
			}
			$sel.val(state.filters.session_id);
		}
		if (route_options.status !== undefined) {
			state.filters.status = route_options.status;
			layout.find('select[data-filter="status"]').val(state.filters.status);
		}
		state.selected_name = null;
		refresh_list();
	};

	// Same-page-Navigation: wenn set_route("buchungs_inbox", {...}) feuert
	// während wir bereits gemounted sind, läuft on_page_load NICHT erneut.
	// Listener auf Router-Change picked die neuen route_options auf.
	if (
		!hausverwaltung.buchungs_inbox._router_bound
		&& frappe.router
		&& typeof frappe.router.on === "function"
	) {
		hausverwaltung.buchungs_inbox._router_bound = true;
		frappe.router.on("change", () => {
			const route = frappe.get_route() || [];
			if (route[0] !== "buchungs_inbox") return;
			const opts = frappe.route_options;
			if (!opts || !Object.keys(opts).length) return;
			frappe.route_options = null;
			if (typeof hausverwaltung.buchungs_inbox._apply_route_options === "function") {
				hausverwaltung.buchungs_inbox._apply_route_options(opts);
			}
		});
	}

	const render_list = () => {
		const $list = layout.find(".hv-inbox-list");
		if (!state.rows.length) {
			$list.html(`<div class="hv-inbox-list-empty">${__("Keine Vorschläge mit diesen Filtern.")}</div>`);
			return;
		}
		const html = state.rows
			.map((row) => {
				const sum = row.extracted_summary || {};
				const lf = sum.lieferant || sum.llm_lieferant || "—";
				const dt = row.creation ? frappe.datetime.str_to_user(row.creation.split(".")[0].replace(" ", "T")) : "";
				const sel = row.name === state.selected_name ? " selected" : "";
				return `
					<div class="hv-inbox-list-row${sel}" data-name="${frappe.utils.escape_html(row.name)}">
						<div class="row-title">${frappe.utils.escape_html(row.original_filename || row.name)}</div>
						<div class="row-sub">
							${_hv_status_pill(row.status)}
							· ${frappe.utils.escape_html(lf)}
							${
								sum.betrag_gesamt
									? `· <strong>${_hv_format_currency(sum.betrag_gesamt)}</strong>`
									: ""
							}
						</div>
						<div class="row-sub">${frappe.utils.escape_html(row.session_id || "")} · ${dt}</div>
					</div>
				`;
			})
			.join("");
		$list.html(html);
	};

	const render_detail = () => {
		const $detail = layout.find(".hv-inbox-detail");
		if (!state.selected_name) {
			$detail.html(`<div class="hv-inbox-detail-empty">${__("Wähle einen Vorschlag aus der Liste links.")}</div>`);
			return;
		}
		const row = state.rows.find((r) => r.name === state.selected_name);
		if (!row) {
			$detail.html(`<div class="hv-inbox-detail-empty">${__("Vorschlag nicht gefunden.")}</div>`);
			return;
		}

		// Volldaten cachen
		if (!state.full_cache[row.name]) {
			state.full_cache[row.name] = "loading";
			frappe
				.call({
					method: `${HV_INBOX_API}.get_vorschlag_full`,
					args: { name: row.name },
				})
				.then((r) => {
					state.full_cache[row.name] = (r && r.message) || null;
					if (state.selected_name === row.name) render_detail();
				})
				.catch(() => {
					delete state.full_cache[row.name];
				});
		}

		const full = state.full_cache[row.name];
		const data = full && full !== "loading" ? full.data || {} : null;

		const can_book = row.status === "Ready";
		const can_skip = ["Pending", "Processing", "Ready"].includes(row.status);
		const can_reactivate = ["Skipped", "Error"].includes(row.status);
		const can_reprocess = row.status !== "Booked";
		const can_delete = row.status !== "Booked";

		const file_url = row.file_url || (full && full.file_url) || "";

		// PDF-Container vor dem html()-Replace detachen — wenn die file_url gleich
		// bleibt (gleicher Vorschlag selektiert + Polling-Tick), recyceln wir den
		// existing <embed> statt ihn neu zu mounten. Das verhindert Browser-Hang
		// durch wiederholtes Re-Init des PDF-Plugins.
		const $existing_pdf_pane = $detail.find(".hv-inbox-pdf").detach();
		const keep_pdf = $existing_pdf_pane.length > 0 && state.current_pdf_url === file_url;

		// Wichtig: wenn wir recyceln, KEIN frisches <embed> in die neue HTML
		// einbauen — sonst startet der Browser einen neuen Download (sichtbarer
		// Reload-Flicker alle Polling-Ticks). Stattdessen leerer Placeholder
		// der gleich durch die detached Pane ersetzt wird.
		const pdf_iframe = keep_pdf
			? ""
			: file_url
				? `<embed src="${frappe.utils.escape_html(file_url)}" type="application/pdf"
					style="width:100%; height:100%; min-height:60vh; border:0;"
					title="${__("PDF-Vorschau")}" />
				   <a href="${frappe.utils.escape_html(file_url)}" target="_blank"
				      style="display:block; padding:6px 8px; font-size:11px; color:#666;
				             text-align:center; border-top:1px solid var(--border-color, #e0e0e0);">
				      ${__("Original-PDF in neuem Tab öffnen")} ↗
				   </a>`
				: `<div class="hv-inbox-detail-empty">${__("Keine PDF-Datei verknüpft.")}</div>`;

		const linked_pi_link = row.linked_purchase_invoice
			? `<a href="/app/purchase-invoice/${encodeURIComponent(row.linked_purchase_invoice)}" target="_blank">${frappe.utils.escape_html(row.linked_purchase_invoice)}</a>`
			: "";

		const detail_block = data
			? _hv_render_extraction_details(data)
			: full === "loading"
			? `<div style="padding:20px; color:#666;"><i class="fa fa-spinner fa-spin"></i> ${__("Lade Detail-Werte...")}</div>`
			: `<div style="padding:20px; color:#666;">${__("Keine extrahierten Daten — Worker hat noch nicht abgeschlossen.")}</div>`;

		$detail.html(`
			<div class="hv-inbox-detail-header">
				<div class="title">
					<i class="fa fa-file-pdf-o"></i>
					${frappe.utils.escape_html(row.original_filename || row.name)}
					${_hv_status_pill(row.status)}
					${linked_pi_link ? ` · ${linked_pi_link}` : ""}
				</div>
				<div class="actions">
					<button class="btn-book btn-primary" ${can_book ? "" : "disabled"}>${__("Buchen")}</button>
					<button class="btn-skip" ${can_skip ? "" : "disabled"}>${__("Überspringen")}</button>
					<button class="btn-reactivate" ${can_reactivate ? "" : "disabled"}>${__("Reaktivieren")}</button>
					<button class="btn-reprocess" title="${__("Komplett neu durchs LLM jagen — bisherige Felder werden überschrieben.")}" ${can_reprocess ? "" : "disabled"}>↻ ${__("Neu analysieren")}</button>
					<button class="btn-delete" style="color:#c62828; border-color:#c62828;" ${can_delete ? "" : "disabled"}>${__("Löschen")}</button>
				</div>
			</div>
			<div class="hv-inbox-split">
				<div class="hv-inbox-values">
					${detail_block}
					${
						row.error_message
							? `<div style="margin-top: 8px; padding: 8px; background: #ffebee; border-radius: 6px; font-size: 12px; color: #c62828;">${frappe.utils.escape_html(row.error_message)}</div>`
							: ""
					}
				</div>
				<div class="hv-inbox-pdf">${pdf_iframe}</div>
			</div>
		`);

		// Recycling-Trick: wenn file_url unverändert, ersetze den frisch gerenderten
		// PDF-Container durch den vor-detached existing — der <embed> bleibt damit
		// am gleichen DOM-Knoten und wird nicht neu initialisiert.
		if (keep_pdf) {
			$detail.find(".hv-inbox-pdf").replaceWith($existing_pdf_pane);
		} else {
			state.current_pdf_url = file_url || null;
		}

		$detail.find(".btn-book").off("click").on("click", () => _do_book(row));
		$detail.find(".btn-skip").off("click").on("click", () => _do_skip(row));
		$detail.find(".btn-reactivate").off("click").on("click", () => _do_reactivate(row));
		$detail.find(".btn-reprocess").off("click").on("click", () => _do_reprocess(row));
		$detail.find(".btn-delete").off("click").on("click", () => _do_delete(row));
	};

	const _do_book = (row) => {
		if (!state.full_cache[row.name] || state.full_cache[row.name] === "loading") return;
		const full = state.full_cache[row.name];
		const data = full.data || {};

		// Polling sofort pausieren, sonst kann ein 3-Sek-Tick mid-Dialog
		// den PDF-Embed unter dem Modal neu mounten (-> Browser-Tab-Hang).
		state.poll_paused = true;
		if (state.poll_timer) {
			clearTimeout(state.poll_timer);
			state.poll_timer = null;
		}
		const opts = {
			lieferant: data.fields && data.fields.lieferant,
			rechnungsdatum: data.fields && data.fields.rechnungsdatum,
			wertstellungsdatum: data.fields && data.fields.wertstellungsdatum,
			rechnungsname: data.fields && data.fields.rechnungsname,
			remarks: data.fields && data.fields.remarks,
			positionen: data.positionen || [],
			_confidence: data.confidence || {},
			_warnings: data.warnings || [],
			_attached_file: full.file_url,
			_used_vision: !!data.used_vision,
			_lieferant_neu: data.lieferant_neu || null,
			_vorschlag_name: row.name,
			_after_book: () => {
				delete state.full_cache[row.name];
				state.poll_paused = false;
				refresh_list();
			},
		};
		hausverwaltung.buchen_cockpit.open_eingangsrechnung_dialog(opts);
		// Sicherheits-Net: wenn der Dialog ohne Submit geschlossen wird, polling
		// nach 5 Sek wieder anschalten (sonst polled Inbox nie mehr).
		setTimeout(() => {
			state.poll_paused = false;
			schedule_poll();
		}, 5000);
	};

	const _do_skip = (row) => {
		frappe
			.call({
				method: `${HV_INBOX_API}.mark_vorschlag_skipped`,
				args: { name: row.name },
			})
			.then(() => {
				delete state.full_cache[row.name];
				refresh_list();
			});
	};

	const _do_reactivate = (row) => {
		frappe
			.call({
				method: `${HV_INBOX_API}.reactivate_vorschlag`,
				args: { name: row.name },
			})
			.then(() => {
				delete state.full_cache[row.name];
				refresh_list();
			});
	};

	const _do_reprocess = (row) => {
		frappe.confirm(
			__("Vorschlag <b>{0}</b> komplett neu durchs LLM jagen? Bisherige extrahierte Felder werden überschrieben.", [
				frappe.utils.escape_html(row.original_filename || row.name),
			]),
			() => {
				frappe
					.call({
						method: `${HV_INBOX_API}.reprocess_vorschlag`,
						args: { name: row.name },
						freeze: true,
						freeze_message: __("Starte Neu-Extraktion..."),
					})
					.then(() => {
						delete state.full_cache[row.name];
						refresh_list();
					});
			}
		);
	};

	const _do_delete = (row) => {
		const d = new frappe.ui.Dialog({
			title: __("Vorschlag löschen?"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p style="margin-bottom:8px;">
						${__("Soll der Vorschlag <b>{0}</b> ({1}) wirklich gelöscht werden?", [
							frappe.utils.escape_html(row.name),
							frappe.utils.escape_html(row.original_filename || ""),
						])}
					</p>
					<p style="margin-bottom:8px; color:#666; font-size:12px;">
						${__("Die extrahierten Daten und der Vorschlag-Eintrag verschwinden dauerhaft.")}
					</p>`,
				},
				{
					fieldtype: "Check",
					fieldname: "also_delete_file",
					label: __("Auch hochgeladene PDF-Datei löschen"),
					default: 0,
					description: __(
						"Datei wird nur gelöscht, wenn kein anderer Vorschlag noch darauf verweist."
					),
				},
			],
			primary_action_label: __("Löschen"),
			primary_action(values) {
				d.disable_primary_action();
				frappe
					.call({
						method: `${HV_INBOX_API}.delete_vorschlag`,
						args: {
							name: row.name,
							also_delete_file: values.also_delete_file ? 1 : 0,
						},
					})
					.then((r) => {
						const res = (r && r.message) || {};
						frappe.show_alert({
							message: res.deleted_file
								? __("Vorschlag und Datei gelöscht.")
								: __("Vorschlag gelöscht."),
							indicator: "blue",
						});
						delete state.full_cache[row.name];
						state.selected_name = null;
						d.hide();
						refresh_list();
					})
					.finally(() => d.enable_primary_action());
			},
		});
		// Roten Primary-Button ohne Custom-CSS: Frappe's Dialog stylt 'primary'
		// als Akzent-Farbe; der Hinweis im Body macht klar dass es destruktiv ist.
		d.show();
	};

	const schedule_poll = () => {
		if (state.poll_timer) {
			clearTimeout(state.poll_timer);
			state.poll_timer = null;
		}
		if (state.poll_paused) return; // kein Polling während ein modaler Dialog offen ist
		const has_pending = state.rows.some((r) =>
			["Pending", "Processing"].includes(r.status)
		);
		if (has_pending) {
			state.poll_timer = setTimeout(refresh_list, 3000);
		}
	};

	// Externer Refresh-Hook: erlaubt z.B. dem Cockpit-Bulk-Upload, die Inbox
	// neu zu laden ohne den Session-Filter zu aktivieren.
	hausverwaltung.buchungs_inbox._refresh = () => refresh_list();

	// Initial-Load
	refresh_list();
};

// _render_extraction_details Helper — Kopie aus buchen_cockpit.js,
// damit die Inbox unabhängig vom Cockpit-JS geladen werden kann.
function _hv_render_extraction_details(data) {
	const fields = data.fields || {};
	const conf = data.confidence || {};
	const positionen = data.positionen || [];
	const lieferant_neu = data.lieferant_neu || null;
	const warnings = data.warnings || [];
	const used_vision = !!data.used_vision;
	const raw_text = (data.raw_text || "").slice(0, 600);

	const header_table = `
		<table style="width:100%; font-size:12px; border-collapse:collapse;">
			<tr><td style="color:#666; padding:2px 8px 2px 0; width:30%;">${__("Lieferant (LLM)")}</td>
				<td>${frappe.utils.escape_html(data.llm_lieferant || "–")} ${_hv_conf_pill(conf.lieferant)}</td></tr>
			<tr><td style="color:#666; padding:2px 8px 2px 0;">${__("Lieferant (gemappt)")}</td>
				<td>${
					fields.lieferant
						? `<a href="/app/supplier/${encodeURIComponent(fields.lieferant)}" target="_blank">${frappe.utils.escape_html(fields.lieferant)}</a>`
						: `<span style="color:#c62828;">${__("nicht in Stammdaten")}</span>`
				}</td></tr>
			<tr><td style="color:#666; padding:2px 8px 2px 0;">${__("Rechnungsdatum")}</td>
				<td>${frappe.utils.escape_html(fields.rechnungsdatum || "–")} ${_hv_conf_pill(conf.rechnungsdatum)}</td></tr>
			<tr><td style="color:#666; padding:2px 8px 2px 0;">${__("Wertstellungsdatum")}</td>
				<td>${frappe.utils.escape_html(fields.wertstellungsdatum || "–")} ${_hv_conf_pill(conf.wertstellungsdatum)}</td></tr>
			<tr><td style="color:#666; padding:2px 8px 2px 0;">${__("Rechnungs-Nr.")}</td>
				<td>${frappe.utils.escape_html(fields.rechnungsname || "–")} ${_hv_conf_pill(conf.bill_no)}</td></tr>
			${
				fields.remarks
					? `<tr><td style="color:#666; padding:2px 8px 2px 0; vertical-align:top;">${__("Anmerkungen")}</td>
						<td style="white-space:pre-wrap;">${frappe.utils.escape_html(fields.remarks)}</td></tr>`
					: ""
			}
		</table>
	`;

	const positionen_summe = positionen.reduce(
		(acc, p) => acc + (parseFloat(p.betrag) || 0),
		0
	);
	const positionen_table = positionen.length
		? `
			<div style="margin-top:12px; font-weight:600; font-size:12px;">${__("Positionen ({0})", [positionen.length])}</div>
			<table style="width:100%; font-size:12px; border-collapse:collapse; margin-top:4px;">
				<thead>
					<tr style="border-bottom:1px solid #ddd; color:#666;">
						<th style="text-align:left; padding:3px 6px;">${__("Beschreibung")}</th>
						<th style="text-align:right; padding:3px 6px;">${__("Betrag")}</th>
						<th style="text-align:left; padding:3px 6px;">${__("Kostenart")}</th>
						<th style="text-align:left; padding:3px 6px;">${__("Kostenstelle")}</th>
					</tr>
				</thead>
				<tbody>
					${positionen
						.map(
							(p) => `
						<tr style="border-bottom:1px dashed #eee;">
							<td style="padding:3px 6px;">${frappe.utils.escape_html(p.beschreibung || "–")}</td>
							<td style="padding:3px 6px; text-align:right;">${_hv_format_currency(p.betrag || 0)}</td>
							<td style="padding:3px 6px;">${
								p.kostenart
									? frappe.utils.escape_html(p.kostenart)
									: `<span style="color:#999;">${__("manuell")}</span>`
							}</td>
							<td style="padding:3px 6px;">${frappe.utils.escape_html(p.kostenstelle || "–")}</td>
						</tr>
					`
						)
						.join("")}
				</tbody>
				<tfoot>
					<tr style="border-top:2px solid #999; font-weight:600;">
						<td style="padding:5px 6px;">${__("Summe")}</td>
						<td style="padding:5px 6px; text-align:right;">${_hv_format_currency(positionen_summe)}</td>
						<td colspan="2"></td>
					</tr>
				</tfoot>
			</table>
		`
		: `<div style="margin-top:12px; padding:8px; background:#ffebee; border-radius:6px; font-size:12px; color:#c62828;">
			<i class="fa fa-exclamation-triangle"></i> ${__("Modell hat keine Positionen erkannt.")}
		</div>`;

	const lieferant_neu_block = lieferant_neu
		? `
			<details style="margin-top:12px;" open>
				<summary style="cursor:pointer; font-weight:600; font-size:12px;">
					${__("Lieferant-Anlage-Vorschlag")} (${frappe.utils.escape_html(lieferant_neu.supplier_name || "")})
				</summary>
				<table style="width:100%; font-size:12px; border-collapse:collapse; margin-top:4px;">
					${["supplier_name", "iban", "tax_id", "strasse", "plz", "ort", "land"]
						.filter((k) => lieferant_neu[k])
						.map(
							(k) => `<tr><td style="color:#666; padding:2px 8px 2px 0;">${k}</td>
								<td>${frappe.utils.escape_html(lieferant_neu[k])}</td></tr>`
						)
						.join("")}
				</table>
			</details>
		`
		: "";

	const warnings_block = warnings.length
		? `
			<div style="margin-top:12px; padding:8px; background:#fff8e1; border-radius:6px; font-size:12px; border:1px solid #ffd54f;">
				<strong>${__("Hinweise")}</strong>
				<ul style="margin:4px 0 0 18px; padding:0;">
					${warnings.map((w) => `<li>${frappe.utils.escape_html(w)}</li>`).join("")}
				</ul>
			</div>
		`
		: "";

	const raw_block = raw_text
		? `
			<details style="margin-top:12px;">
				<summary style="cursor:pointer; font-weight:600; font-size:12px; color:#666;">
					${used_vision ? __("Vision-Modell genutzt") : __("PDF-Text-Vorschau")}
				</summary>
				<pre style="margin-top:4px; padding:6px; background:#f5f5f5; font-size:11px; max-height:120px; overflow-y:auto; white-space:pre-wrap;">${frappe.utils.escape_html(raw_text)}</pre>
			</details>
		`
		: "";

	return `
		${header_table}
		${positionen_table}
		${lieferant_neu_block}
		${warnings_block}
		${raw_block}
	`;
}
