// Buchungs-Cockpit: zentraler Einstieg für vereinfachte Buchungsvorgänge.
// Bündelt drei Flows:
//   - Eingangsrechnung (Purchase Invoice direkt erzeugt)
//   - Rechnung an Mieter (Sales Invoice direkt erzeugt)
//   - Dauerabschlag (öffnet bestehende Abschlagszahlung)
//
// API:
//   hausverwaltung.buchen_cockpit.mount($container)
//   hausverwaltung.buchen_cockpit.open_eingangsrechnung_dialog(opts?)
//   hausverwaltung.buchen_cockpit.open_mieterrechnung_dialog(opts?)

frappe.provide("hausverwaltung.buchen_cockpit");

const HV_COCKPIT_STYLE_ID = "hv-buchen-cockpit-styles";
const HV_COCKPIT_API = "hausverwaltung.hausverwaltung.page.buchen_cockpit.buchen_cockpit";
const HV_DRAFT_KEY_PI = "hv_buchen_cockpit_draft_pi_v1";
const HV_DRAFT_KEY_SI = "hv_buchen_cockpit_draft_si_v1";

const hv_cockpit_ensure_styles = () => {
	if (document.getElementById(HV_COCKPIT_STYLE_ID)) return;
	const style = document.createElement("style");
	style.id = HV_COCKPIT_STYLE_ID;
	style.textContent = `
		.hv-cockpit {
			display: flex;
			flex-direction: column;
			gap: 20px;
			padding: 8px 4px;
		}
		.hv-cockpit-tiles {
			display: grid;
			grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
			gap: 12px;
		}
		.hv-cockpit-tile {
			display: flex;
			flex-direction: column;
			gap: 6px;
			padding: 16px;
			border: 1px solid var(--border-color, #d9d9d9);
			border-radius: 10px;
			background: var(--card-bg, #fff);
			cursor: pointer;
			transition: box-shadow 0.12s ease, transform 0.12s ease;
		}
		.hv-cockpit-tile:hover {
			box-shadow: 0 2px 10px rgba(0,0,0,0.08);
			transform: translateY(-1px);
		}
		.hv-cockpit-tile .hv-cockpit-tile-title {
			font-weight: 600;
			font-size: 15px;
		}
		.hv-cockpit-tile .hv-cockpit-tile-desc {
			color: var(--text-muted, #666);
			font-size: 12px;
			line-height: 1.35;
		}
		.hv-cockpit-section {
			border: 1px solid var(--border-color, #d9d9d9);
			border-radius: 10px;
			background: var(--card-bg, #fff);
			padding: 12px 14px;
		}
		.hv-cockpit-section h4 {
			margin: 0 0 8px;
			font-size: 14px;
		}
		.hv-cockpit-list {
			display: flex;
			flex-direction: column;
			gap: 4px;
			font-size: 13px;
		}
		.hv-cockpit-list .hv-cockpit-row {
			display: flex;
			justify-content: space-between;
			gap: 8px;
			padding: 4px 0;
			border-bottom: 1px dashed var(--border-color, #eee);
		}
		.hv-cockpit-list .hv-cockpit-row:last-child { border-bottom: none; }
		.hv-cockpit-empty { color: var(--text-muted, #666); font-size: 13px; }
		.hv-cockpit-columns {
			display: grid;
			grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
			gap: 12px;
		}
		.hv-cockpit-draft-banner {
			background: var(--yellow-50, #fff8e1);
			border: 1px solid var(--yellow-200, #ffe08a);
			color: var(--text-color, #333);
			padding: 6px 10px;
			border-radius: 6px;
			font-size: 12px;
			margin-bottom: 8px;
			display: flex;
			justify-content: space-between;
			gap: 8px;
			align-items: center;
		}
	`;
	document.head.appendChild(style);
};

// ---------------------------------------------------------------------------
// LocalStorage draft helpers
// ---------------------------------------------------------------------------

const hv_draft_save = (key, data) => {
	try {
		localStorage.setItem(key, JSON.stringify({ ts: Date.now(), data }));
	} catch (e) {
		/* quota exceeded or blocked — ignore */
	}
};

const hv_draft_load = (key) => {
	try {
		const raw = localStorage.getItem(key);
		if (!raw) return null;
		const parsed = JSON.parse(raw);
		if (!parsed || !parsed.data) return null;
		return parsed;
	} catch (e) {
		return null;
	}
};

const hv_draft_clear = (key) => {
	try {
		localStorage.removeItem(key);
	} catch (e) {
		/* ignore */
	}
};

// Debounced autosave: prevents get_values() from running on every keystroke,
// which interferes with Grid row editing (Link-autocompletes, partial rows).
const hv_attach_autosave = (dialog, key) => {
	let timer = null;
	const persist = () => {
		try {
			const v = dialog.get_values(true);
			hv_draft_save(key, v);
		} catch (e) {
			/* ignore transient grid-edit states */
		}
	};
	dialog.$wrapper.on("change", "input, select, textarea", () => {
		if (timer) clearTimeout(timer);
		timer = setTimeout(persist, 600);
	});
};

// Dialog Table fields don't reliably apply child field "default" values when
// the user clicks "Add Row". This hook watches the grid's add-row buttons and
// stamps defaults onto the last row. Needed so Dynamic Link fields (Kostenart)
// have a resolved target DocType (umlagefaehig) from the start.
const hv_apply_row_defaults = (dialog, fieldname, defaults) => {
	const field = dialog.fields_dict && dialog.fields_dict[fieldname];
	const grid = field && field.grid;
	if (!grid || !grid.wrapper) return;

	const selectors = [".grid-add-row", ".grid-add-multiple-rows", ".grid-insert-row-below", ".grid-insert-row"];
	grid.wrapper.on("click", selectors.join(", "), () => {
		setTimeout(() => {
			const data = grid.data || (grid.df && grid.df.data) || [];
			const last = data.length ? data[data.length - 1] : null;
			if (!last) return;
			let changed = false;
			Object.keys(defaults).forEach((k) => {
				if (last[k] === undefined || last[k] === null || last[k] === "") {
					last[k] = defaults[k];
					changed = true;
				}
			});
			if (changed) grid.refresh();
		}, 30);
	});
};

// ---------------------------------------------------------------------------
// Dialog: Eingangsrechnung (Purchase Invoice)
// ---------------------------------------------------------------------------

hausverwaltung.buchen_cockpit.open_eingangsrechnung_dialog = (opts = {}) => {
	const fields = [
		{
			fieldtype: "Link",
			fieldname: "lieferant",
			label: __("Lieferant"),
			options: "Supplier",
			reqd: 1,
		},
		{ fieldtype: "Column Break" },
		{
			fieldtype: "Date",
			fieldname: "rechnungsdatum",
			label: __("Rechnungsdatum"),
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{ fieldtype: "Section Break" },
		{
			fieldtype: "Data",
			fieldname: "rechnungsname",
			label: __("Rechnungsname / Bill No."),
		},
		{ fieldtype: "Column Break" },
		{
			fieldtype: "Data",
			fieldname: "referenz",
			label: __("Referenz"),
		},
		{ fieldtype: "Section Break", label: __("Positionen") },
		{
			fieldtype: "Select",
			fieldname: "eingabemodus",
			label: __("Eingabemodus"),
			options: ["Kostenart", "Konto"].join("\n"),
			default: "Kostenart",
			reqd: 1,
			description: __(
				"Kostenart: Picker zeigt die Stammdaten der gewählten Position-Typ. Konto: direkt das Konto wählen — Kostenart wird automatisch zugeordnet. Pro Zeile wird zusätzlich ausgewählt, ob umlegbar oder nicht."
			),
			onchange() {
				apply_eingabemodus(dialog);
			},
		},
		{
			fieldtype: "Table",
			fieldname: "positionen",
			label: __("Positionen"),
			cannot_add_rows: false,
			in_place_edit: true,
			data: [],
			fields: [
				{
					fieldtype: "Currency",
					fieldname: "betrag",
					label: __("Betrag"),
					in_list_view: 1,
					columns: 1,
				},
				{
					fieldtype: "Select",
					fieldname: "typ",
					label: __("Typ"),
					options: ["umlegbar", "nicht umlegbar"].join("\n"),
					default: "umlegbar",
					in_list_view: 1,
					columns: 2,
					description: __("Bestimmt, welche Stammdaten/Konten im Picker angezeigt werden."),
					onchange() {
						// Nach Typ-Wechsel ist der bisherige Picker-Wert evtl. ungültig → leeren.
						const grid_row = this.grid_row;
						if (!grid_row || !grid_row.doc) return;
						grid_row.doc.kostenart = "";
						grid_row.refresh();
					},
				},
				{
					fieldtype: "Autocomplete",
					fieldname: "kostenart",
					label: __("Kostenart"),
					options: [],
					in_list_view: 1,
					columns: 3,
					description: __(
						"Picker filtert dynamisch nach Eingabemodus (Kostenart/Konto) und Zeilen-Typ (umlegbar/nicht)."
					),
					get_query: function (doc) {
						const mode =
							(dialog && dialog.get_value && dialog.get_value("eingabemodus")) ||
							"Kostenart";
						const typ_param =
							doc && doc.typ === "nicht umlegbar" ? "nicht_umlegbar" : "umlegbar";
						const method =
							mode === "Konto"
								? `${HV_COCKPIT_API}.autocomplete_konten`
								: `${HV_COCKPIT_API}.autocomplete_kostenarten`;
						return {
							query: method,
							params: { typ: typ_param },
						};
					},
				},
				{
					fieldtype: "Link",
					fieldname: "betriebskostenart",
					label: __("Kostenart (umlegbar) – Legacy"),
					options: "Betriebskostenart",
					hidden: 1,
				},
				{
					fieldtype: "Link",
					fieldname: "kostenart_nicht_ul",
					label: __("Kostenart (nicht umlegbar) – Legacy"),
					options: "Kostenart nicht umlagefaehig",
					hidden: 1,
				},
				{
					fieldtype: "Link",
					fieldname: "kostenstelle",
					label: __("Kostenstelle"),
					options: "Cost Center",
					in_list_view: 1,
					columns: 2,
				},
				{
					fieldtype: "Link",
					fieldname: "konto",
					label: __("Konto (Legacy)"),
					options: "Account",
					hidden: 1,
				},
				{
					fieldtype: "Link",
					fieldname: "wohnung",
					label: __("Wohnung"),
					options: "Wohnung",
					in_list_view: 1,
					columns: 2,
					description: __(
						"Nur nötig bei Betriebskostenart mit Verteilung 'Einzeln'."
					),
				},
				{
					fieldtype: "Date",
					fieldname: "zahldatum",
					label: __("Zahldatum"),
				},
				{
					fieldtype: "Date",
					fieldname: "wertstellungsdatum",
					label: __("Wertstellungsdatum"),
				},
			],
		},
	];

	const dialog = new frappe.ui.Dialog({
		title: __("Eingangsrechnung buchen"),
		size: "extra-large",
		fields,
		primary_action_label: __("Buchen"),
		primary_action(values) {
			submit_eingangsrechnung(dialog, values);
		},
		secondary_action_label: __("Entwurf verwerfen"),
		secondary_action() {
			hv_draft_clear(HV_DRAFT_KEY_PI);
			dialog.clear();
			frappe.show_alert({ message: __("Entwurf gelöscht."), indicator: "blue" });
		},
	});

	hv_attach_autosave(dialog, HV_DRAFT_KEY_PI);

	// Restore defaults from opts (explicit wins over draft)
	const stored_draft = hv_draft_load(HV_DRAFT_KEY_PI);
	const has_explicit_defaults = !!(opts && (opts.lieferant || opts.positionen));

	dialog.show();

	if (has_explicit_defaults) {
		if (opts.lieferant) dialog.set_value("lieferant", opts.lieferant);
		if (opts.rechnungsdatum) dialog.set_value("rechnungsdatum", opts.rechnungsdatum);
		if (opts.rechnungsname) dialog.set_value("rechnungsname", opts.rechnungsname);
		if (opts.referenz) dialog.set_value("referenz", opts.referenz);
		if (opts.positionen && opts.positionen.length) {
			dialog.fields_dict.positionen.df.data = opts.positionen;
			dialog.fields_dict.positionen.grid.refresh();
		}
	} else if (stored_draft && stored_draft.data) {
		show_draft_banner(dialog, stored_draft, HV_DRAFT_KEY_PI);
	}

	apply_eingabemodus(dialog);

	dialog.add_custom_action(
		__("Als Entwurf speichern"),
		() => submit_eingangsrechnung(dialog, dialog.get_values(true), false),
		"btn-secondary"
	);

	return dialog;
};

function apply_eingabemodus(dialog) {
	const grid = dialog.fields_dict.positionen && dialog.fields_dict.positionen.grid;
	if (!grid) return;
	const mode = dialog.get_value("eingabemodus") || "Kostenart";
	const is_konto = mode === "Konto";
	grid.update_docfield_property(
		"kostenart",
		"label",
		is_konto ? __("Konto") : __("Kostenart")
	);
	grid.update_docfield_property(
		"kostenart",
		"description",
		is_konto
			? __("Konto direkt wählen — Kostenart wird automatisch zugeordnet.")
			: __("Kostenart-Stammdatum wählen.")
	);
	// Bereits eingetragene Werte sind nach Mode-Wechsel nicht mehr passend → Spalte leeren.
	const data = (grid.df && grid.df.data) || [];
	data.forEach((row) => {
		if (row) row.kostenart = "";
	});
	grid.refresh();
}

function show_draft_banner(dialog, stored_draft, draft_key) {
	const ts = new Date(stored_draft.ts);
	const ts_str = frappe.datetime.str_to_user(ts.toISOString().split(".")[0].replace("T", " "));
	const $banner = $(
		`<div class="hv-cockpit-draft-banner">
			<span>${__("Entwurf von")} ${ts_str} ${__("gefunden.")}</span>
			<span>
				<button class="btn btn-xs btn-primary hv-draft-restore">${__("Wiederherstellen")}</button>
				<button class="btn btn-xs btn-default hv-draft-ignore">${__("Ignorieren")}</button>
			</span>
		</div>`
	);
	dialog.$body.prepend($banner);
	$banner.find(".hv-draft-restore").on("click", () => {
		restore_draft(dialog, stored_draft.data);
		$banner.remove();
	});
	$banner.find(".hv-draft-ignore").on("click", () => {
		hv_draft_clear(draft_key);
		$banner.remove();
	});
}

function restore_draft(dialog, data) {
	Object.keys(data || {}).forEach((key) => {
		const field = dialog.fields_dict[key];
		if (!field) return;
		if (field.df.fieldtype === "Table") {
			field.df.data = Array.isArray(data[key]) ? data[key] : [];
			field.grid.refresh();
		} else {
			dialog.set_value(key, data[key]);
		}
	});
}

function submit_eingangsrechnung(dialog, values, submit_doc = true) {
	const rows = (values.positionen || []).filter(
		(r) =>
			r &&
			(r.betrag ||
				r.kostenstelle ||
				r.konto ||
				r.kostenart ||
				r.betriebskostenart ||
				r.kostenart_nicht_ul)
	);
	if (!rows.length) {
		frappe.msgprint({ message: __("Bitte mindestens eine Position erfassen."), indicator: "orange" });
		return;
	}

	for (let i = 0; i < rows.length; i++) {
		const r = rows[i];
		if (r.betriebskostenart && r.kostenart_nicht_ul) {
			frappe.msgprint({
				message: __(
					"Zeile {0}: Bitte nur eine Kostenart wählen (umlegbar oder nicht umlegbar), nicht beide.",
					[i + 1]
				),
				indicator: "orange",
			});
			return;
		}
	}

	dialog.disable_primary_action();
	frappe
		.call({
			method: `${HV_COCKPIT_API}.create_purchase_invoice`,
			args: {
				lieferant: values.lieferant,
				rechnungsdatum: values.rechnungsdatum,
				rechnungsname: values.rechnungsname,
				referenz: values.referenz,
				positionen: JSON.stringify(rows),
				submit_doc: submit_doc ? 1 : 0,
			},
		})
		.then((r) => {
			const name = r && r.message && r.message.name;
			if (!name) return;
			hv_draft_clear(HV_DRAFT_KEY_PI);
			dialog.hide();
			frappe.show_alert({
				message: submit_doc
					? __("Eingangsrechnung {0} erstellt und gebucht.", [name])
					: __("Eingangsrechnung {0} als Entwurf gespeichert.", [name]),
				indicator: "green",
			});
			frappe.set_route("Form", "Purchase Invoice", name);
		})
		.finally(() => dialog.enable_primary_action());
}

// ---------------------------------------------------------------------------
// Dialog: Rechnung an Mieter (Sales Invoice)
// ---------------------------------------------------------------------------

hausverwaltung.buchen_cockpit.open_mieterrechnung_dialog = (opts = {}) => {
	const fields = [
		{
			fieldtype: "Link",
			fieldname: "mietvertrag",
			label: __("Mietvertrag"),
			options: "Mietvertrag",
			reqd: 1,
			onchange() {
				const mv = dialog.get_value("mietvertrag");
				if (!mv) return;
				frappe
					.call({
						method: `${HV_COCKPIT_API}.get_defaults_from_mietvertrag`,
						args: { mietvertrag: mv },
					})
					.then((r) => {
						const data = (r && r.message) || {};
						if (data.kunde) dialog.set_value("kunde", data.kunde);
						if (data.wohnung) dialog.set_value("wohnung", data.wohnung);
					});
			},
		},
		{ fieldtype: "Column Break" },
		{
			fieldtype: "Link",
			fieldname: "kunde",
			label: __("Mieter"),
			options: "Customer",
			read_only: 1,
		},
		{
			fieldtype: "Link",
			fieldname: "wohnung",
			label: __("Wohnung"),
			options: "Wohnung",
			read_only: 1,
		},
		{ fieldtype: "Section Break" },
		{
			fieldtype: "Date",
			fieldname: "rechnungsdatum",
			label: __("Rechnungsdatum"),
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{ fieldtype: "Column Break" },
		{
			fieldtype: "Date",
			fieldname: "faellig_am",
			label: __("Fällig am"),
			default: frappe.datetime.add_days(frappe.datetime.get_today(), 21),
		},
		{ fieldtype: "Section Break" },
		{
			fieldtype: "Data",
			fieldname: "rechnungsname",
			label: __("Rechnungsname"),
		},
		{ fieldtype: "Column Break" },
		{
			fieldtype: "Data",
			fieldname: "referenz",
			label: __("Referenz"),
		},
		{ fieldtype: "Section Break", label: __("Positionen") },
		{
			fieldtype: "Table",
			fieldname: "positionen",
			label: __("Positionen"),
			cannot_add_rows: false,
			in_place_edit: true,
			data: [],
			fields: [
				{
					fieldtype: "Data",
					fieldname: "beschreibung",
					label: __("Beschreibung"),
					in_list_view: 1,
					columns: 4,
				},
				{
					fieldtype: "Currency",
					fieldname: "betrag",
					label: __("Betrag"),
					in_list_view: 1,
					columns: 2,
				},
				{
					fieldtype: "Link",
					fieldname: "artikel",
					label: __("Artikel"),
					options: "Item",
					in_list_view: 1,
					columns: 2,
				},
				{
					fieldtype: "Link",
					fieldname: "erloeskonto",
					label: __("Erlöskonto"),
					options: "Account",
					in_list_view: 1,
					columns: 3,
				},
			],
		},
	];

	const dialog = new frappe.ui.Dialog({
		title: __("Rechnung an Mieter"),
		size: "extra-large",
		fields,
		primary_action_label: __("Buchen"),
		primary_action(values) {
			submit_mieterrechnung(dialog, values);
		},
		secondary_action_label: __("Entwurf verwerfen"),
		secondary_action() {
			hv_draft_clear(HV_DRAFT_KEY_SI);
			dialog.clear();
			frappe.show_alert({ message: __("Entwurf gelöscht."), indicator: "blue" });
		},
	});

	hv_attach_autosave(dialog, HV_DRAFT_KEY_SI);

	const stored_draft = hv_draft_load(HV_DRAFT_KEY_SI);
	const has_explicit_defaults = !!(opts && (opts.mietvertrag || opts.positionen));

	dialog.show();

	if (has_explicit_defaults) {
		if (opts.mietvertrag) dialog.set_value("mietvertrag", opts.mietvertrag);
		if (opts.rechnungsdatum) dialog.set_value("rechnungsdatum", opts.rechnungsdatum);
		if (opts.faellig_am) dialog.set_value("faellig_am", opts.faellig_am);
		if (opts.rechnungsname) dialog.set_value("rechnungsname", opts.rechnungsname);
		if (opts.referenz) dialog.set_value("referenz", opts.referenz);
		if (opts.positionen && opts.positionen.length) {
			dialog.fields_dict.positionen.df.data = opts.positionen;
			dialog.fields_dict.positionen.grid.refresh();
		}
	} else if (stored_draft && stored_draft.data) {
		show_draft_banner(dialog, stored_draft, HV_DRAFT_KEY_SI);
	}

	dialog.add_custom_action(
		__("Als Entwurf speichern"),
		() => submit_mieterrechnung(dialog, dialog.get_values(true), false),
		"btn-secondary"
	);

	return dialog;
};

function submit_mieterrechnung(dialog, values, submit_doc = true) {
	const rows = (values.positionen || []).filter(
		(r) => r && (r.betrag || r.beschreibung || r.artikel || r.erloeskonto)
	);
	if (!rows.length) {
		frappe.msgprint({ message: __("Bitte mindestens eine Position erfassen."), indicator: "orange" });
		return;
	}

	dialog.disable_primary_action();
	frappe
		.call({
			method: `${HV_COCKPIT_API}.create_sales_invoice`,
			args: {
				mietvertrag: values.mietvertrag,
				rechnungsdatum: values.rechnungsdatum,
				faellig_am: values.faellig_am,
				rechnungsname: values.rechnungsname,
				referenz: values.referenz,
				positionen: JSON.stringify(rows),
				submit_doc: submit_doc ? 1 : 0,
			},
		})
		.then((r) => {
			const name = r && r.message && r.message.name;
			if (!name) return;
			hv_draft_clear(HV_DRAFT_KEY_SI);
			dialog.hide();
			frappe.show_alert({
				message: submit_doc
					? __("Rechnung {0} erstellt und gebucht.", [name])
					: __("Rechnung {0} als Entwurf gespeichert.", [name]),
				indicator: "green",
			});
			frappe.set_route("Form", "Sales Invoice", name);
		})
		.finally(() => dialog.enable_primary_action());
}

// ---------------------------------------------------------------------------
// Cockpit page mount
// ---------------------------------------------------------------------------

hausverwaltung.buchen_cockpit.mount = ($container) => {
	hv_cockpit_ensure_styles();

	const layout = $(`
		<div class="hv-cockpit">
			<div class="hv-cockpit-tiles">
				<div class="hv-cockpit-tile" data-action="eingang">
					<div class="hv-cockpit-tile-title">
						<i class="fa fa-sign-in"></i> ${__("Eingangsrechnung buchen")}
					</div>
					<div class="hv-cockpit-tile-desc">
						${__(
							"Handwerker, Versorger, Einzelbeleg — erzeugt eine Eingangsrechnung direkt."
						)}
					</div>
				</div>
				<div class="hv-cockpit-tile" data-action="ausgang">
					<div class="hv-cockpit-tile-title">
						<i class="fa fa-sign-out"></i> ${__("Rechnung an Mieter")}
					</div>
					<div class="hv-cockpit-tile-desc">
						${__("Einzelleistung, Nebenkosten-Nachberechnung — erzeugt eine Rechnung direkt.")}
					</div>
				</div>
				<div class="hv-cockpit-tile" data-action="abschlag">
					<div class="hv-cockpit-tile-title">
						<i class="fa fa-repeat"></i> ${__("Dauerabschlag")}
					</div>
					<div class="hv-cockpit-tile-desc">
						${__("Strom, Gas, Wasser — einmal einrichten, läuft automatisch.")}
					</div>
				</div>
			</div>
			<div class="hv-cockpit-columns">
				<div class="hv-cockpit-section" data-section="pi">
					<h4>${__("Zuletzt erfasste Eingangsrechnungen")}</h4>
					<div class="hv-cockpit-list" data-list="pi">
						<div class="hv-cockpit-empty">${__("Lade...")}</div>
					</div>
				</div>
				<div class="hv-cockpit-section" data-section="si">
					<h4>${__("Zuletzt erfasste Mieterrechnungen")}</h4>
					<div class="hv-cockpit-list" data-list="si">
						<div class="hv-cockpit-empty">${__("Lade...")}</div>
					</div>
				</div>
				<div class="hv-cockpit-section" data-section="abs">
					<h4>${__("Aktive Dauerabschläge")}</h4>
					<div class="hv-cockpit-list" data-list="abs">
						<div class="hv-cockpit-empty">${__("Lade...")}</div>
					</div>
				</div>
			</div>
		</div>
	`);

	$container.empty().append(layout);

	layout.on("click", ".hv-cockpit-tile", (event) => {
		const action = $(event.currentTarget).data("action");
		if (action === "eingang") hausverwaltung.buchen_cockpit.open_eingangsrechnung_dialog();
		else if (action === "ausgang") hausverwaltung.buchen_cockpit.open_mieterrechnung_dialog();
		else if (action === "abschlag") frappe.new_doc("Abschlagszahlung");
	});

	const format_currency = (value) => {
		try {
			return frappe.format(value || 0, { fieldtype: "Currency" });
		} catch (e) {
			return value;
		}
	};

	const render_list = (selector, rows, render_fn, empty_label) => {
		const $list = layout.find(`[data-list="${selector}"]`);
		if (!rows || !rows.length) {
			$list.html(`<div class="hv-cockpit-empty">${empty_label}</div>`);
			return;
		}
		$list.html(rows.map(render_fn).join(""));
	};

	const refresh_overview = () => {
		frappe
			.call({ method: `${HV_COCKPIT_API}.get_cockpit_overview`, args: { limit: 8 } })
			.then((r) => {
				const data = (r && r.message) || {};
				render_list(
					"pi",
					data.recent_purchase_invoices,
					(row) => {
						const link = `/app/purchase-invoice/${encodeURIComponent(row.name)}`;
						const date = row.posting_date
							? frappe.datetime.str_to_user(row.posting_date)
							: "";
						return `
							<div class="hv-cockpit-row">
								<span>
									<a href="${link}">${frappe.utils.escape_html(row.name)}</a>
									<span class="text-muted"> · ${frappe.utils.escape_html(row.supplier || "")}</span>
								</span>
								<span>${format_currency(row.grand_total)} · ${date}</span>
							</div>
						`;
					},
					__("Noch keine Eingangsrechnungen über das Cockpit erfasst.")
				);

				render_list(
					"si",
					data.recent_sales_invoices,
					(row) => {
						const link = `/app/sales-invoice/${encodeURIComponent(row.name)}`;
						const date = row.posting_date
							? frappe.datetime.str_to_user(row.posting_date)
							: "";
						return `
							<div class="hv-cockpit-row">
								<span>
									<a href="${link}">${frappe.utils.escape_html(row.name)}</a>
									<span class="text-muted"> · ${frappe.utils.escape_html(row.customer || "")}</span>
								</span>
								<span>${format_currency(row.grand_total)} · ${date}</span>
							</div>
						`;
					},
					__("Noch keine Mieterrechnungen über das Cockpit erfasst.")
				);

				render_list(
					"abs",
					data.active_abschlagszahlungen,
					(row) => {
						const link = `/app/abschlagszahlung/${encodeURIComponent(row.name)}`;
						return `
							<div class="hv-cockpit-row">
								<span>
									<a href="${link}">${frappe.utils.escape_html(row.bezeichnung || row.name)}</a>
									<span class="text-muted"> · ${frappe.utils.escape_html(row.lieferant || "")}</span>
								</span>
								<span>${format_currency(row.betrag)}</span>
							</div>
						`;
					},
					__("Keine aktiven Dauerabschläge.")
				);
			});
	};

	refresh_overview();

	return { refresh: refresh_overview };
};
