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
const HV_BULK_API = "hausverwaltung.hausverwaltung.services.bulk_extraction";
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
		{ fieldtype: "Column Break" },
		{
			fieldtype: "Date",
			fieldname: "wertstellungsdatum",
			label: __("Wertstellungsdatum"),
			description: __("Leistungszeitraum (wird in custom_wertstellungsdatum gespeichert)."),
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

	// Attached source file (vom PDF-Analyse-Flow): an dialog hängen, submit liest's wieder ab.
	if (opts && opts._attached_file) {
		dialog._hv_attached_file = opts._attached_file;
	}
	// Lieferanten-Vorschlagsdaten aus der LLM-Extraktion (für Quick-Create-Button).
	if (opts && opts._lieferant_neu) {
		dialog._hv_lieferant_neu = opts._lieferant_neu;
	}
	// Aus dem Bulk-Wizard heraus geöffnet → Vorschlag-Name + Callback merken.
	if (opts && opts._vorschlag_name) {
		dialog._hv_vorschlag_name = opts._vorschlag_name;
	}
	if (opts && typeof opts._after_book === "function") {
		dialog._hv_after_book = opts._after_book;
	}

	dialog.show();

	if (has_explicit_defaults) {
		if (opts.lieferant) dialog.set_value("lieferant", opts.lieferant);
		if (opts.rechnungsdatum) dialog.set_value("rechnungsdatum", opts.rechnungsdatum);
		if (opts.wertstellungsdatum) dialog.set_value("wertstellungsdatum", opts.wertstellungsdatum);
		if (opts.rechnungsname) dialog.set_value("rechnungsname", opts.rechnungsname);
		if (opts.referenz) dialog.set_value("referenz", opts.referenz);
		if (opts.positionen && opts.positionen.length) {
			dialog.fields_dict.positionen.df.data = opts.positionen;
			dialog.fields_dict.positionen.grid.refresh();
		}
	} else if (stored_draft && stored_draft.data) {
		show_draft_banner(dialog, stored_draft, HV_DRAFT_KEY_PI);
	}

	if (opts && (opts._confidence || opts._warnings || opts._used_vision)) {
		apply_extraction_hints(dialog, opts);
	}

	apply_eingabemodus(dialog);

	dialog.add_custom_action(
		__("Als Entwurf speichern"),
		() => submit_eingangsrechnung(dialog, dialog.get_values(true), false),
		"btn-secondary"
	);

	return dialog;
};

function apply_extraction_hints(dialog, opts) {
	const conf = opts._confidence || {};
	const FIELD_MAP = {
		lieferant: "lieferant",
		rechnungsdatum: "rechnungsdatum",
		wertstellungsdatum: "wertstellungsdatum",
		bill_no: "rechnungsname",
	};
	Object.keys(FIELD_MAP).forEach((key) => {
		const value = conf[key];
		if (value === undefined || value === null) return;
		const target = FIELD_MAP[key];
		if (!dialog.fields_dict[target]) return;
		const score = Number(value) || 0;
		let note = "";
		if (score >= 0.9) note = `✓ ${__("Mistral sicher")} (${score.toFixed(2)})`;
		else if (score >= 0.7) note = `~ ${__("Mistral plausibel")} (${score.toFixed(2)})`;
		else note = `⚠ ${__("Mistral unsicher — bitte prüfen")} (${score.toFixed(2)})`;
		dialog.fields_dict[target].df.description = note;
		dialog.fields_dict[target].refresh();
	});

	const warnings = opts._warnings || [];
	if (warnings.length || opts._used_vision) {
		const lines = [];
		if (opts._used_vision) {
			lines.push(__("Vision-Modell genutzt (Scan ohne Text-Layer)."));
		}
		warnings.forEach((w) => lines.push(w));
		const $banner = $(
			`<div class="hv-cockpit-draft-banner" style="background: #fff8e1; border-color: #ffd54f;">
				<div><strong>${__("Hinweise zur Extraktion")}</strong></div>
				<ul style="margin: 4px 0 0 18px; padding: 0;">
					${lines.map((l) => `<li>${frappe.utils.escape_html(l)}</li>`).join("")}
				</ul>
			</div>`
		);
		dialog.$body.prepend($banner);
	}

	// Quick-Create-Button für unbekannte Lieferanten — sichtbar wenn das LLM einen
	// Vorschlag gemacht hat aber kein Match in den Stammdaten gefunden wurde.
	if (opts._lieferant_neu && opts._lieferant_neu.supplier_name) {
		const lf = dialog.fields_dict.lieferant;
		if (lf && lf.$wrapper) {
			const $btn = $(
				`<button type="button" class="btn btn-xs btn-secondary hv-quick-create-supplier" style="margin-top: 4px;">
					+ ${__("Lieferant '{0}' anlegen", [
						frappe.utils.escape_html(opts._lieferant_neu.supplier_name),
					])}
				</button>`
			);
			lf.$wrapper.find(".hv-quick-create-supplier").remove();
			lf.$wrapper.append($btn);
			$btn.on("click", () => open_supplier_quick_create(dialog, opts._lieferant_neu));
		}
	}
}

const HV_DE_COUNTRY_MAP = {
	"Deutschland": "Germany",
	"Österreich": "Austria",
	"Oesterreich": "Austria",
	"Schweiz": "Switzerland",
};

function open_supplier_quick_create(parent_dialog, prefill) {
	const default_group = "Services";
	const default_country = HV_DE_COUNTRY_MAP[prefill.land] || prefill.land || "Germany";
	const qc = new frappe.ui.Dialog({
		title: __("Lieferant aus Vorschlag anlegen"),
		fields: [
			{
				fieldtype: "Data",
				fieldname: "supplier_name",
				label: __("Lieferantenname"),
				reqd: 1,
				default: prefill.supplier_name || "",
			},
			{
				fieldtype: "Link",
				fieldname: "supplier_group",
				label: __("Lieferantengruppe"),
				options: "Supplier Group",
				reqd: 1,
				default: default_group,
			},
			{
				fieldtype: "Link",
				fieldname: "country",
				label: __("Land"),
				options: "Country",
				default: default_country,
			},
			{ fieldtype: "Section Break", label: __("Steuer / Zahlung") },
			{
				fieldtype: "Data",
				fieldname: "tax_id",
				label: __("USt-IdNr / Steuernummer"),
				default: prefill.tax_id || "",
			},
			{
				fieldtype: "Data",
				fieldname: "iban",
				label: __("IBAN"),
				default: prefill.iban || "",
				description: __(
					"Wird als Notiz im Lieferanten gespeichert. Bank Account legst du nachträglich auf der Lieferanten-Seite an."
				),
			},
			{ fieldtype: "Section Break", label: __("Adresse") },
			{
				fieldtype: "Data",
				fieldname: "strasse",
				label: __("Straße + Hausnummer"),
				default: prefill.strasse || "",
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Data",
				fieldname: "plz",
				label: __("PLZ"),
				default: prefill.plz || "",
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Data",
				fieldname: "ort",
				label: __("Ort"),
				default: prefill.ort || "",
			},
		],
		primary_action_label: __("Anlegen"),
		primary_action(values) {
			qc.disable_primary_action();
			frappe
				.call({
					method: `${HV_COCKPIT_API}.create_supplier_from_extraction`,
					args: values,
				})
				.then((r) => {
					const created = r && r.message;
					if (!created || !created.name) return;
					qc.hide();
					parent_dialog.set_value("lieferant", created.name);
					frappe.show_alert({
						message: __("Lieferant {0} angelegt.", [created.name]),
						indicator: "green",
					});
				})
				.finally(() => qc.enable_primary_action());
		},
	});
	qc.show();
}

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
				wertstellungsdatum: values.wertstellungsdatum,
				rechnungsname: values.rechnungsname,
				referenz: values.referenz,
				positionen: JSON.stringify(rows),
				submit_doc: submit_doc ? 1 : 0,
				attached_file_url: dialog._hv_attached_file || null,
				vorschlag_name: dialog._hv_vorschlag_name || null,
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
			// Wenn der Dialog aus dem Bulk-Wizard heraus geöffnet wurde:
			// Callback ausführen (Wizard refresht und springt zum nächsten Eintrag),
			// nicht aufs PI-Formular wegnavigieren.
			if (typeof dialog._hv_after_book === "function") {
				try {
					dialog._hv_after_book(name);
				} catch (e) {
					console.error(e);
				}
			} else {
				frappe.set_route("Form", "Purchase Invoice", name);
			}
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
		{ fieldtype: "Column Break" },
		{
			fieldtype: "Date",
			fieldname: "wertstellungsdatum",
			label: __("Wertstellungsdatum"),
			description: __("Leistungszeitraum (wird in custom_wertstellungsdatum gespeichert)."),
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
		if (opts.wertstellungsdatum) dialog.set_value("wertstellungsdatum", opts.wertstellungsdatum);
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
				wertstellungsdatum: values.wertstellungsdatum,
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
// Dialog: PDF-Analyse → vorgefüllter Eingangsrechnungs-Dialog
// ---------------------------------------------------------------------------

hausverwaltung.buchen_cockpit.open_extract_dialog = () => {
	const dialog = new frappe.ui.Dialog({
		title: __("PDF-Rechnung analysieren"),
		fields: [
			{
				fieldtype: "Attach",
				fieldname: "pdf_file",
				label: __("PDF-Datei"),
				reqd: 1,
				description: __(
					"Lade die Eingangsrechnung als PDF hoch. Mistral schlägt anschließend Lieferant, Positionen und Kostenarten vor."
				),
			},
		],
		primary_action_label: __("Analysieren"),
		primary_action(values) {
			if (!values.pdf_file) return;
			dialog.disable_primary_action();
			frappe
				.call({
					method: `${HV_COCKPIT_API}.extract_invoice_from_file`,
					args: { file_url: values.pdf_file },
					freeze: true,
					freeze_message: __("Analysiere PDF mit Mistral..."),
				})
				.then((r) => {
					const data = (r && r.message) || null;
					if (!data) return;
					dialog.hide();
					hausverwaltung.buchen_cockpit.open_eingangsrechnung_dialog({
						lieferant: data.fields && data.fields.lieferant,
						rechnungsdatum: data.fields && data.fields.rechnungsdatum,
						wertstellungsdatum: data.fields && data.fields.wertstellungsdatum,
						rechnungsname: data.fields && data.fields.rechnungsname,
						positionen: data.positionen || [],
						_confidence: data.confidence || {},
						_warnings: data.warnings || [],
						_attached_file: values.pdf_file,
						_used_vision: !!data.used_vision,
						_lieferant_neu: data.lieferant_neu || null,
					});
				})
				.catch((err) => {
					console.error("PDF-Analyse fehlgeschlagen", err);
				})
				.finally(() => dialog.enable_primary_action());
		},
	});
	dialog.show();
};

// ---------------------------------------------------------------------------
// Bulk-Upload + Wizard
// ---------------------------------------------------------------------------

hausverwaltung.buchen_cockpit.open_bulk_upload_dialog = () => {
	const dialog = new frappe.ui.Dialog({
		title: __("Sammel-PDF-Upload"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "info",
				options: `
					<p style="margin-bottom: 14px;">
						${__(
							"Lade hier mehrere Eingangsrechnungen als PDF hoch. Sie werden im Hintergrund analysiert; danach führt dich ein Wizard durch jeden Vorschlag."
						)}
					</p>
				`,
			},
			{
				fieldtype: "HTML",
				fieldname: "uploader_target",
				options: `<div class="hv-bulk-uploader-target"></div>`,
			},
			{
				fieldtype: "HTML",
				fieldname: "list",
				options: `<div class="hv-bulk-uploaded-list" style="margin-top: 10px; font-size: 13px;"></div>`,
			},
		],
		primary_action_label: __("Analysieren starten"),
		primary_action() {
			const urls = (dialog._hv_uploaded_urls || []).filter(Boolean);
			if (!urls.length) {
				frappe.msgprint({
					message: __("Bitte zuerst mindestens eine PDF hochladen."),
					indicator: "orange",
				});
				return;
			}
			dialog.disable_primary_action();
			frappe
				.call({
					method: `${HV_BULK_API}.bulk_create_vorschlaege`,
					args: { file_urls: JSON.stringify(urls) },
					freeze: true,
					freeze_message: __("Lege Vorschläge an..."),
				})
				.then((r) => {
					const res = (r && r.message) || {};
					if (!res.session_id) return;
					dialog.hide();
					hausverwaltung.buchen_cockpit.open_bulk_wizard(res.session_id);
				})
				.finally(() => dialog.enable_primary_action());
		},
	});
	dialog._hv_uploaded_urls = [];
	dialog.show();

	// Frappe FileUploader inline einhängen — Multiple aktiv.
	const $target = dialog.$body.find(".hv-bulk-uploader-target");
	const $list = dialog.$body.find(".hv-bulk-uploaded-list");
	const render_list = () => {
		const urls = dialog._hv_uploaded_urls || [];
		if (!urls.length) {
			$list.html(`<div style="color: var(--text-muted, #666);">${__("Noch keine Datei hochgeladen.")}</div>`);
			return;
		}
		$list.html(
			`<strong>${__("Bereit zur Analyse:")} ${urls.length}</strong><ul style="margin: 6px 0 0 18px; padding: 0;">${urls
				.map(
					(u) =>
						`<li>${frappe.utils.escape_html(u.split("/").pop() || u)}</li>`
				)
				.join("")}</ul>`
		);
	};
	render_list();

	new frappe.ui.FileUploader({
		wrapper: $target.get(0),
		method: `${HV_COCKPIT_API}.upload_invoice_pdf`,
		allow_multiple: 1,
		on_success(file_doc) {
			handle_uploaded_file(file_doc, dialog, render_list);
		},
	});
};

function handle_uploaded_file(file_doc, parent_dialog, render_list_fn) {
	if (!file_doc || !file_doc.file_url) return;
	const existing = file_doc.existing_vorschlag || null;
	if (!existing) {
		// Kein bestehender Vorschlag — direkt in die Liste packen.
		_push_url(parent_dialog, file_doc.file_url, render_list_fn);
		if (file_doc.is_new_file === false) {
			frappe.show_alert({
				message: __("Datei {0} bereits vorhanden — wird wiederverwendet.", [
					file_doc.file_name || "",
				]),
				indicator: "blue",
			});
		}
		return;
	}
	// Existing Vorschlag → User entscheiden lassen.
	open_duplicate_dialog(file_doc, parent_dialog, render_list_fn);
}

function _push_url(parent_dialog, file_url, render_list_fn) {
	if (!parent_dialog) return;
	parent_dialog._hv_uploaded_urls = parent_dialog._hv_uploaded_urls || [];
	if (!parent_dialog._hv_uploaded_urls.includes(file_url)) {
		parent_dialog._hv_uploaded_urls.push(file_url);
	}
	if (typeof render_list_fn === "function") render_list_fn();
}

function open_duplicate_dialog(file_doc, parent_dialog, render_list_fn) {
	const existing = file_doc.existing_vorschlag;
	const status = existing.status;
	const status_de = {
		Pending: __("wartet auf Verarbeitung"),
		Processing: __("wird gerade analysiert"),
		Ready: __("Vorschlag bereit, noch nicht gebucht"),
		Booked: __("bereits als Eingangsrechnung gebucht"),
		Skipped: __("zuvor übersprungen"),
		Error: __("mit Fehler abgebrochen"),
	}[status] || status;

	const filename = frappe.utils.escape_html(file_doc.file_name || existing.original_filename || "");
	const linked = existing.linked_purchase_invoice
		? `<div style="margin-top: 6px; font-size: 12px;"><i class="fa fa-link"></i> <a href="/app/purchase-invoice/${frappe.utils.escape_html(
				existing.linked_purchase_invoice
		  )}" target="_blank">${frappe.utils.escape_html(existing.linked_purchase_invoice)}</a></div>`
		: "";
	const error_msg = existing.error_message
		? `<div style="margin-top: 6px; font-size: 12px; color: #c62828;">${frappe.utils.escape_html(existing.error_message)}</div>`
		: "";

	const msg = `
		<div>
			<div><strong>${filename}</strong></div>
			<div style="margin-top: 4px; color: var(--text-muted, #666);">
				${__("Status:")} <strong>${status_de}</strong>
				<span style="font-size: 11px; color: #999;"> (${frappe.utils.escape_html(existing.name)})</span>
			</div>
			${linked}
			${error_msg}
		</div>
	`;

	const d = new frappe.ui.Dialog({
		title: __("Datei bereits vorhanden"),
		fields: [{ fieldtype: "HTML", options: msg }],
	});

	const close_and = (fn) => () => {
		d.hide();
		try {
			fn();
		} catch (e) {
			console.error(e);
		}
	};

	if (status === "Booked" && existing.linked_purchase_invoice) {
		d.add_custom_action(
			__("Eingangsrechnung öffnen"),
			close_and(() =>
				frappe.set_route("Form", "Purchase Invoice", existing.linked_purchase_invoice)
			),
			"btn-primary"
		);
	} else if (
		(status === "Ready" || status === "Pending" || status === "Processing") &&
		existing.session_id
	) {
		d.add_custom_action(
			__("Bestehenden Wizard öffnen"),
			close_and(() => hausverwaltung.buchen_cockpit.open_bulk_wizard(existing.session_id)),
			"btn-primary"
		);
	} else if (status === "Skipped" || status === "Error") {
		d.add_custom_action(
			__("Reaktivieren & analysieren"),
			close_and(() =>
				_reactivate_and_add(existing.name, file_doc.file_url, parent_dialog, render_list_fn)
			),
			"btn-primary"
		);
	} else {
		// Datei vorhanden, aber kein passender Status (Edge-Case oder neuer Vorschlag-Pfad)
		d.add_custom_action(
			__("Jetzt analysieren"),
			close_and(() => _push_url(parent_dialog, file_doc.file_url, render_list_fn)),
			"btn-primary"
		);
	}

	// Bei Booked / im Wizard offen: zusätzlich Re-Analyze als Sekundär-Option.
	if (status === "Booked" || status === "Ready" || status === "Pending" || status === "Processing") {
		d.add_custom_action(
			__("Trotzdem nochmal analysieren"),
			close_and(() =>
				_discard_and_reanalyze(existing.name, file_doc.file_url, parent_dialog, render_list_fn)
			),
			"btn-default"
		);
	}

	d.add_custom_action(__("Abbrechen"), close_and(() => {}), "btn-default");
	d.show();
}

function _reactivate_and_add(vorschlag_name, file_url, parent_dialog, render_list_fn) {
	frappe
		.call({
			method: "hausverwaltung.hausverwaltung.services.bulk_extraction.reactivate_vorschlag",
			args: { name: vorschlag_name },
		})
		.then(() => {
			frappe.show_alert({
				message: __("Vorschlag {0} reaktiviert.", [vorschlag_name]),
				indicator: "blue",
			});
			_push_url(parent_dialog, file_url, render_list_fn);
		})
		.catch((err) => console.error(err));
}

function _discard_and_reanalyze(vorschlag_name, file_url, parent_dialog, render_list_fn) {
	// Status auf Skipped setzen — historie bleibt sichtbar via DocType-List.
	frappe
		.call({
			method: `hausverwaltung.hausverwaltung.services.bulk_extraction.mark_vorschlag_skipped`,
			args: { name: vorschlag_name },
		})
		.then(() => {
			frappe.show_alert({
				message: __("Alter Vorschlag verworfen — neue Analyse wird vorbereitet."),
				indicator: "orange",
			});
			_push_url(parent_dialog, file_url, render_list_fn);
		})
		.catch((err) => console.error(err));
}

hausverwaltung.buchen_cockpit.open_bulk_wizard = (session_id) => {
	const wizard = new frappe.ui.Dialog({
		title: __("Buchungs-Wizard"),
		size: "large",
		fields: [
			{
				fieldtype: "HTML",
				fieldname: "wizard_body",
				options: `<div class="hv-wizard-body"></div>`,
			},
		],
		primary_action_label: __("Buchen"),
		primary_action() {
			const cur = wizard._hv_current_vorschlag;
			if (!cur) return;
			open_pi_dialog_from_vorschlag(cur, () => {
				// Nach erfolgreicher PI-Erstellung: Liste neu laden, nächsten Eintrag anzeigen.
				wizard._hv_force_refresh = true;
				render();
			});
		},
		secondary_action_label: __("Überspringen"),
		secondary_action() {
			const cur = wizard._hv_current_vorschlag;
			if (!cur) return;
			frappe
				.call({
					method: `${HV_BULK_API}.mark_vorschlag_skipped`,
					args: { name: cur.name },
				})
				.then(() => {
					wizard._hv_force_refresh = true;
					render();
				});
		},
	});
	wizard._hv_session_id = session_id;
	wizard._hv_state = null;
	wizard._hv_current_vorschlag = null;
	wizard._hv_force_refresh = false;
	wizard._hv_poll_timer = null;
	wizard._hv_full_cache = {}; // vorschlag_name → full extracted data

	const fetch_status = () => {
		return frappe
			.call({
				method: `${HV_BULK_API}.get_session_status`,
				args: { session_id },
			})
			.then((r) => (r && r.message) || null);
	};

	const render = () => {
		fetch_status().then((state) => {
			wizard._hv_state = state;
			if (!state) return;
			const vs = state.vorschlaege || [];
			// Aktueller Eintrag = erster mit Status "Ready". Wenn keiner, zeige Übersicht.
			const next_ready = vs.find((v) => v.status === "Ready");
			wizard._hv_current_vorschlag = next_ready || null;

			// Volldaten für Detail-Block laden (cache pro vorschlag_name).
			if (next_ready && !wizard._hv_full_cache[next_ready.name]) {
				wizard._hv_full_cache[next_ready.name] = "loading";
				frappe
					.call({
						method: `${HV_BULK_API}.get_vorschlag_full`,
						args: { name: next_ready.name },
					})
					.then((r) => {
						const full = (r && r.message) || null;
						wizard._hv_full_cache[next_ready.name] = full;
						// Re-render damit Detail-Block jetzt gefüllt ist.
						const $body = wizard.$body.find(".hv-wizard-body");
						$body.html(render_html(state, next_ready));
					})
					.catch(() => {
						delete wizard._hv_full_cache[next_ready.name];
					});
			}

			const $body = wizard.$body.find(".hv-wizard-body");
			$body.html(render_html(state, next_ready));
			wizard.set_primary_action(__("Buchen"));
			if (next_ready) {
				wizard.enable_primary_action();
			} else {
				wizard.disable_primary_action();
			}
			schedule_next_poll(state);
		});
	};

	const schedule_next_poll = (state) => {
		if (wizard._hv_poll_timer) {
			clearTimeout(wizard._hv_poll_timer);
			wizard._hv_poll_timer = null;
		}
		const stats = state.stats || {};
		const has_pending = (stats.pending || 0) + (stats.processing || 0) > 0;
		if (has_pending && wizard.is_visible !== false) {
			wizard._hv_poll_timer = setTimeout(render, 2500);
		}
	};

	const render_html = (state, current) => {
		const vs = state.vorschlaege || [];
		const stats = state.stats || {};
		const total = stats.total || 0;
		const open = (stats.pending || 0) + (stats.processing || 0);
		const ready = stats.ready || 0;
		const booked = stats.booked || 0;
		const skipped = stats.skipped || 0;
		const errored = stats.error || 0;
		const done_index = vs.findIndex((v) => v.name === (current && current.name));
		const position_text = current
			? __("Vorschlag {0} von {1}", [done_index + 1, total])
			: __("Übersicht");

		const status_pill = (s) => {
			const map = {
				Pending: ["#888", __("wartend")],
				Processing: ["#1976d2", __("läuft")],
				Ready: ["#2e7d32", __("bereit")],
				Booked: ["#558b2f", __("gebucht")],
				Skipped: ["#9e9e9e", __("übersprungen")],
				Error: ["#c62828", __("Fehler")],
			};
			const [color, label] = map[s] || ["#666", s];
			return `<span style="background: ${color}; color: #fff; padding: 1px 7px; border-radius: 9px; font-size: 11px;">${label}</span>`;
		};

		const summary_block = (() => {
			if (!current) {
				if (open > 0) {
					return `
						<div style="text-align: center; padding: 30px; color: var(--text-muted, #666);">
							<i class="fa fa-spinner fa-spin"></i>
							${__("Analyse läuft im Hintergrund...")} (${open} ${__("offen")})
						</div>
					`;
				}
				return `
					<div style="text-align: center; padding: 30px; color: var(--text-muted, #2e7d32);">
						<i class="fa fa-check-circle"></i> ${__("Alle Vorschläge bearbeitet.")}
						<div style="margin-top: 10px; font-size: 12px;">
							${booked} ${__("gebucht")}, ${skipped} ${__("übersprungen")}, ${errored} ${__("mit Fehler")}.
						</div>
					</div>
				`;
			}
			const sum = current.extracted_summary || {};
			const conf_avg = sum.confidence_avg
				? `<span style="color: ${
						sum.confidence_avg >= 0.85 ? "#2e7d32" : sum.confidence_avg >= 0.65 ? "#f57f17" : "#c62828"
				  };">${(sum.confidence_avg * 100).toFixed(0)}%</span>`
				: "–";
			return `
				<div style="border: 1px solid var(--border-color, #e0e0e0); padding: 14px; border-radius: 8px;">
					<div style="font-weight: 600; font-size: 14px; margin-bottom: 8px;">
						<i class="fa fa-file-pdf-o"></i> ${frappe.utils.escape_html(current.original_filename || "")}
					</div>
					<table style="width: 100%; font-size: 13px; border-collapse: collapse;">
						<tr>
							<td style="padding: 3px 8px 3px 0; color: var(--text-muted, #666); width: 30%;">${__("Lieferant")}:</td>
							<td>
								${frappe.utils.escape_html(sum.lieferant || sum.llm_lieferant || "–")}
								${
									!sum.lieferant && sum.llm_lieferant
										? `<span style="font-size: 11px; color: #c62828;"> (${__("nicht in Stammdaten")})</span>`
										: ""
								}
							</td>
						</tr>
						<tr>
							<td style="padding: 3px 8px 3px 0; color: var(--text-muted, #666);">${__("Datum")}:</td>
							<td>${frappe.utils.escape_html(sum.datum || "–")}</td>
						</tr>
						<tr>
							<td style="padding: 3px 8px 3px 0; color: var(--text-muted, #666);">${__("Positionen")}:</td>
							<td>${sum.position_count || 0} (${__("Summe")}: ${format_currency(sum.betrag_gesamt || 0, "EUR", 2)})</td>
						</tr>
						<tr>
							<td style="padding: 3px 8px 3px 0; color: var(--text-muted, #666);">${__("Confidence Ø")}:</td>
							<td>${conf_avg}</td>
						</tr>
						${
							sum.warning_count
								? `<tr><td style="padding: 3px 8px 3px 0; color: #f57f17;">${__("Hinweise")}:</td><td>${sum.warning_count}</td></tr>`
								: ""
						}
					</table>
				</div>
			`;
		})();

		const overview_rows = vs
			.map((v) => {
				const s = (v.extracted_summary || {});
				const lf = s.lieferant || s.llm_lieferant || "–";
				const is_current = current && v.name === current.name;
				const is_reactivatable = v.status === "Skipped" || v.status === "Error";
				const row_style = [
					is_current ? "background: #e3f2fd;" : "",
					is_reactivatable ? "cursor: pointer;" : "",
				].join(" ");
				const title = is_reactivatable
					? __("Klicken zum Reaktivieren")
					: "";
				return `
					<tr style="${row_style}" data-name="${frappe.utils.escape_html(v.name)}" data-reactivatable="${
					is_reactivatable ? 1 : 0
				}" title="${title}">
						<td style="padding: 4px 6px;">${frappe.utils.escape_html(v.original_filename || "")}</td>
						<td style="padding: 4px 6px;">${frappe.utils.escape_html(lf)}</td>
						<td style="padding: 4px 6px; text-align: right;">${
							s.betrag_gesamt ? format_currency(s.betrag_gesamt, "EUR", 2) : "–"
						}</td>
						<td style="padding: 4px 6px;">${status_pill(v.status)}</td>
					</tr>
				`;
			})
			.join("");

		// Detail-Block (nur wenn Volldaten geladen sind).
		const full_data =
			current && wizard._hv_full_cache[current.name] !== "loading"
				? wizard._hv_full_cache[current.name]
				: null;
		const detail_block =
			current && full_data && full_data.data
				? _render_extraction_details(full_data.data)
				: current
				? `<div style="margin-top: 10px; color: var(--text-muted, #666); font-size: 12px;"><i class="fa fa-spinner fa-spin"></i> ${__("Lade Detail-Werte...")}</div>`
				: "";

		return `
			<div style="display: flex; gap: 16px;">
				<div style="flex: 1.4; max-height: 480px; overflow-y: auto;">
					<div style="font-size: 13px; color: var(--text-muted, #666); margin-bottom: 8px;">${position_text}</div>
					${summary_block}
					${
						current && current.error_message
							? `<div style="margin-top: 8px; padding: 8px; background: #ffebee; border-radius: 6px; font-size: 12px; color: #c62828;">${frappe.utils.escape_html(
									current.error_message
							  )}</div>`
							: ""
					}
					${detail_block}
				</div>
				<div style="flex: 1; max-height: 480px; overflow-y: auto; border: 1px solid var(--border-color, #e0e0e0); border-radius: 8px; padding: 6px;">
					<div style="font-size: 11px; color: var(--text-muted, #666); margin-bottom: 4px; padding: 2px 4px;">
						${total} ${__("gesamt")} · ${ready} ${__("bereit")} · ${open} ${__("offen")} · ${booked} ${__("gebucht")} · ${skipped} ${__("skipped")} · ${errored} ${__("Fehler")}
					</div>
					<table style="width: 100%; font-size: 12px; border-collapse: collapse;">
						<thead>
							<tr style="border-bottom: 1px solid var(--border-color, #e0e0e0); color: var(--text-muted, #666);">
								<th style="text-align: left; padding: 3px 6px;">${__("Datei")}</th>
								<th style="text-align: left; padding: 3px 6px;">${__("Lieferant")}</th>
								<th style="text-align: right; padding: 3px 6px;">${__("Betrag")}</th>
								<th style="text-align: left; padding: 3px 6px;">${__("Status")}</th>
							</tr>
						</thead>
						<tbody>${overview_rows}</tbody>
					</table>
				</div>
			</div>
		`;
	};

	wizard.show();
	render();

	// Klick auf Skipped/Error-Zeile in der rechten Liste → reaktivieren.
	wizard.$body.on("click", "tr[data-reactivatable='1']", (event) => {
		const name = $(event.currentTarget).data("name");
		if (!name) return;
		frappe
			.call({
				method: `${HV_BULK_API}.reactivate_vorschlag`,
				args: { name },
			})
			.then(() => {
				frappe.show_alert({
					message: __("Vorschlag {0} reaktiviert.", [name]),
					indicator: "blue",
				});
				render();
			});
	});

	wizard.$wrapper.on("hidden.bs.modal", () => {
		if (wizard._hv_poll_timer) {
			clearTimeout(wizard._hv_poll_timer);
			wizard._hv_poll_timer = null;
		}
	});
};

function _conf_color(score) {
	if (score >= 0.85) return "#2e7d32";
	if (score >= 0.65) return "#f57f17";
	return "#c62828";
}

function _conf_pill(score) {
	if (score === undefined || score === null) return "";
	const pct = Math.round(Number(score) * 100);
	return `<span style="background: ${_conf_color(score)}; color: #fff; padding: 1px 6px; border-radius: 8px; font-size: 10px; margin-left: 4px;">${pct}%</span>`;
}

function _render_extraction_details(data) {
	const fields = data.fields || {};
	const conf = data.confidence || {};
	const positionen = data.positionen || [];
	const lieferant_neu = data.lieferant_neu || null;
	const warnings = data.warnings || [];
	const used_vision = !!data.used_vision;
	const raw_text = (data.raw_text || "").slice(0, 600);

	const header_table = `
		<table style="width: 100%; font-size: 12px; border-collapse: collapse; margin-top: 10px;">
			<tr><td style="color: #666; padding: 2px 8px 2px 0;">${__("Lieferant (LLM)")}</td>
				<td>${frappe.utils.escape_html(data.llm_lieferant || "–")} ${_conf_pill(conf.lieferant)}</td></tr>
			<tr><td style="color: #666; padding: 2px 8px 2px 0;">${__("Lieferant (gemappt)")}</td>
				<td>${
					fields.lieferant
						? `<a href="/app/supplier/${encodeURIComponent(fields.lieferant)}" target="_blank">${frappe.utils.escape_html(fields.lieferant)}</a>`
						: `<span style="color: #c62828;">${__("nicht in Stammdaten")}</span>`
				}</td></tr>
			<tr><td style="color: #666; padding: 2px 8px 2px 0;">${__("Rechnungsdatum")}</td>
				<td>${frappe.utils.escape_html(fields.rechnungsdatum || "–")} ${_conf_pill(conf.rechnungsdatum)}</td></tr>
			<tr><td style="color: #666; padding: 2px 8px 2px 0;">${__("Wertstellungsdatum")}</td>
				<td>${frappe.utils.escape_html(fields.wertstellungsdatum || "–")} ${_conf_pill(conf.wertstellungsdatum)}</td></tr>
			<tr><td style="color: #666; padding: 2px 8px 2px 0;">${__("Rechnungs-Nr.")}</td>
				<td>${frappe.utils.escape_html(fields.rechnungsname || "–")} ${_conf_pill(conf.bill_no)}</td></tr>
		</table>
	`;

	const positionen_table = positionen.length
		? `
			<div style="margin-top: 12px; font-weight: 600; font-size: 12px;">${__("Positionen ({0})", [positionen.length])}</div>
			<table style="width: 100%; font-size: 12px; border-collapse: collapse; margin-top: 4px;">
				<thead>
					<tr style="border-bottom: 1px solid #ddd; color: #666;">
						<th style="text-align: left; padding: 3px 6px;">${__("Beschreibung")}</th>
						<th style="text-align: right; padding: 3px 6px;">${__("Betrag")}</th>
						<th style="text-align: left; padding: 3px 6px;">${__("Kostenart")}</th>
						<th style="text-align: left; padding: 3px 6px;">${__("Kostenstelle")}</th>
						<th style="text-align: right; padding: 3px 6px;">${__("Conf.")}</th>
					</tr>
				</thead>
				<tbody>
					${positionen
						.map(
							(p) => `
						<tr style="border-bottom: 1px dashed #eee;">
							<td style="padding: 3px 6px;">${frappe.utils.escape_html(p.beschreibung || "–")}</td>
							<td style="padding: 3px 6px; text-align: right;">${format_currency(p.betrag || 0, "EUR", 2)}</td>
							<td style="padding: 3px 6px;">${
								p.kostenart
									? frappe.utils.escape_html(p.kostenart)
									: `<span style="color: #c62828;">${__("leer")}</span>`
							}</td>
							<td style="padding: 3px 6px;">${frappe.utils.escape_html(p.kostenstelle || "–")}</td>
							<td style="padding: 3px 6px; text-align: right; color: ${_conf_color(p._confidence || 0)};">
								${p._confidence !== undefined ? Math.round(p._confidence * 100) + "%" : "–"}
							</td>
						</tr>
					`
						)
						.join("")}
				</tbody>
			</table>
		`
		: `<div style="margin-top: 12px; padding: 8px; background: #ffebee; border-radius: 6px; font-size: 12px; color: #c62828;">
			<i class="fa fa-exclamation-triangle"></i> ${__("Modell hat keine Positionen erkannt — manuelle Eingabe nötig.")}
		</div>`;

	const lieferant_neu_block = lieferant_neu
		? `
			<details style="margin-top: 12px;">
				<summary style="cursor: pointer; font-weight: 600; font-size: 12px;">
					${__("Lieferant-Anlage-Vorschlag")} (${frappe.utils.escape_html(lieferant_neu.supplier_name || "")})
				</summary>
				<table style="width: 100%; font-size: 12px; border-collapse: collapse; margin-top: 4px;">
					${["supplier_name", "iban", "tax_id", "strasse", "plz", "ort", "land"]
						.filter((k) => lieferant_neu[k])
						.map(
							(k) => `<tr><td style="color: #666; padding: 2px 8px 2px 0;">${k}</td>
								<td>${frappe.utils.escape_html(lieferant_neu[k])}</td></tr>`
						)
						.join("")}
				</table>
			</details>
		`
		: "";

	const warnings_block = warnings.length
		? `
			<div style="margin-top: 12px; padding: 8px; background: #fff8e1; border-radius: 6px; font-size: 12px; border: 1px solid #ffd54f;">
				<strong>${__("Hinweise")}</strong>
				<ul style="margin: 4px 0 0 18px; padding: 0;">
					${warnings.map((w) => `<li>${frappe.utils.escape_html(w)}</li>`).join("")}
				</ul>
			</div>
		`
		: "";

	const raw_block = raw_text
		? `
			<details style="margin-top: 12px;">
				<summary style="cursor: pointer; font-weight: 600; font-size: 12px; color: #666;">
					${used_vision ? __("Vision-Modell genutzt") : __("PDF-Text-Vorschau")}
				</summary>
				<pre style="margin-top: 4px; padding: 6px; background: #f5f5f5; font-size: 11px; max-height: 120px; overflow-y: auto; white-space: pre-wrap;">${frappe.utils.escape_html(raw_text)}</pre>
			</details>
		`
		: used_vision
		? `<div style="margin-top: 12px; font-size: 11px; color: #666;"><i class="fa fa-image"></i> ${__("Vision-Modell genutzt (kein Text aus pypdf)")}</div>`
		: "";

	return `
		<div style="margin-top: 14px; padding: 12px; border: 1px solid #e0e0e0; border-radius: 8px; background: #fafafa;">
			<div style="font-weight: 600; font-size: 13px; margin-bottom: 4px;">${__("Modell-Werte")}</div>
			${header_table}
			${positionen_table}
			${lieferant_neu_block}
			${warnings_block}
			${raw_block}
		</div>
	`;
}

function open_pi_dialog_from_vorschlag(vorschlag, on_done) {
	frappe
		.call({
			method: `${HV_BULK_API}.get_vorschlag_full`,
			args: { name: vorschlag.name },
		})
		.then((r) => {
			const full = (r && r.message) || null;
			if (!full || !full.data) return;
			const data = full.data;
			const opts = {
				lieferant: data.fields && data.fields.lieferant,
				rechnungsdatum: data.fields && data.fields.rechnungsdatum,
				wertstellungsdatum: data.fields && data.fields.wertstellungsdatum,
				rechnungsname: data.fields && data.fields.rechnungsname,
				positionen: data.positionen || [],
				_confidence: data.confidence || {},
				_warnings: data.warnings || [],
				_attached_file: full.file_url,
				_used_vision: !!data.used_vision,
				_lieferant_neu: data.lieferant_neu || null,
				_vorschlag_name: vorschlag.name,
				_after_book: on_done,
			};
			hausverwaltung.buchen_cockpit.open_eingangsrechnung_dialog(opts);
		});
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
				<div class="hv-cockpit-tile" data-action="extract">
					<div class="hv-cockpit-tile-title">
						<i class="fa fa-file-pdf-o"></i> ${__("PDF analysieren")}
					</div>
					<div class="hv-cockpit-tile-desc">
						${__(
							"PDF hochladen — Mistral schlägt Lieferant, Positionen und Kostenarten vor."
						)}
					</div>
				</div>
				<div class="hv-cockpit-tile" data-action="bulk">
					<div class="hv-cockpit-tile-title">
						<i class="fa fa-files-o"></i> ${__("Sammel-Upload")}
					</div>
					<div class="hv-cockpit-tile-desc">
						${__(
							"Mehrere PDFs auf einmal — Wizard führt dich Schritt für Schritt durch alle Vorschläge."
						)}
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
				<div class="hv-cockpit-section" data-section="open-sessions">
					<h4>${__("Offene Sammel-Sessions")}</h4>
					<div class="hv-cockpit-list" data-list="open-sessions">
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
		else if (action === "abschlag") frappe.new_doc("Zahlungsplan");
		else if (action === "extract") hausverwaltung.buchen_cockpit.open_extract_dialog();
		else if (action === "bulk") hausverwaltung.buchen_cockpit.open_bulk_upload_dialog();
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
						const link = `/app/zahlungsplan/${encodeURIComponent(row.name)}`;
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
		// Offene Sammel-Sessions separat laden (anderer Endpoint)
		frappe
			.call({ method: `${HV_BULK_API}.get_open_sessions`, args: { limit: 8 } })
			.then((r) => {
				const sessions = (r && r.message) || [];
				render_list(
					"open-sessions",
					sessions,
					(row) => {
						const ts = row.started_at
							? frappe.datetime.str_to_user(row.started_at)
							: "";
						const sample = row.sample_filename || "";
						const escaped_session = frappe.utils.escape_html(row.session_id || "");
						return `
							<div class="hv-cockpit-row hv-cockpit-resume-row" data-session="${escaped_session}" style="cursor: pointer;">
								<span>
									<i class="fa fa-files-o"></i>
									<a href="javascript:void(0)" data-resume-session="${escaped_session}">
										${row.open_count}/${row.total} ${__("offen")}
									</a>
									<span class="text-muted"> · ${frappe.utils.escape_html(sample)}</span>
								</span>
								<span class="text-muted">${ts}</span>
							</div>
						`;
					},
					__("Keine offenen Sammel-Sessions.")
				);
			});
	};

	layout.on("click", "[data-resume-session]", (event) => {
		event.preventDefault();
		const session_id = $(event.currentTarget).data("resume-session");
		if (session_id) hausverwaltung.buchen_cockpit.open_bulk_wizard(session_id);
	});

	refresh_overview();

	return { refresh: refresh_overview };
};
