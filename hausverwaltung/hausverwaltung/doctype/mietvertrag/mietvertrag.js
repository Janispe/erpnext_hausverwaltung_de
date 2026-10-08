// frappe.ui.form.on("Mietvertrag", {
// 	refresh(frm) {

// 	},
// });

frappe.ui.form.on("Mietvertrag", {
	setup(frm) {
		frm.set_query("kontakt", "kontoverbindungen", () => {
			const contacts = (frm.doc.mieter || []).map((row) => row.mieter);
			if (contacts.length) {
				return { filters: { name: ["in", contacts] } };
			}
			return {};
		});
		frm.set_query("betriebskostenart", "festbetraege", () => ({
			filters: { verteilung: "Festbetrag" },
		}));
	},
	onload(frm) {
		remember_staffel_snapshot(frm);
	},
	before_save(frm) {
		frm.__hv_sollstellung_korrektur_scope = frm.is_new()
			? null
			: get_changed_staffel_scope(frm.__hv_staffel_snapshot, get_staffel_snapshot(frm));
	},
	after_save(frm) {
		// Frappe skips `before_save` for submitted documents saved via "Update".
		// In that case, compare the snapshot here, before refreshing it.
		const scope = Object.prototype.hasOwnProperty.call(
			frm,
			"__hv_sollstellung_korrektur_scope"
		)
			? frm.__hv_sollstellung_korrektur_scope
			: get_changed_staffel_scope(frm.__hv_staffel_snapshot, get_staffel_snapshot(frm));
		delete frm.__hv_sollstellung_korrektur_scope;
		remember_staffel_snapshot(frm);
		if (scope && Object.keys(scope).length) {
			prompt_for_existing_sollstellung_corrections(frm, scope);
		}
	},
	refresh(frm) {
		console.log("✅ mietvertrag.js wurde geladen");

		update_bruttomiete(frm);
		setup_monthly_rent_table(frm);
		hide_staffelmiete_art_column(frm, "kaution");
		rename_staffelmiete_miete_column(frm, "kaution", "Betrag");
		ensure_staffel_highlight_css();
		highlight_current_staffeln(frm);
		setup_festbetrag_dimension_overview(frm);

		update_cost_table_visibility(frm);

		add_paperless_button(frm);
		add_mieterkonto_button_from_mietvertrag(frm);
		frm.add_custom_button(__("Teilmonatsmiete festlegen"), () => {
			open_part_month_rent_dialog(frm);
		});

		frm.add_custom_button(__("Staffelmieten sortieren"), async () => {
			sort_betriebskostenregelungen(frm);
			sort_staffel_table_by_von(frm, "miete");
			sort_staffel_table_by_von(frm, "betriebskosten");
			sort_staffel_table_by_von(frm, "heizkosten");
			sort_staffel_table_by_von(frm, "untermietzuschlag");
			sort_staffel_table_by_von(frm, "kaution");

			frm.refresh_fields([
				"betriebskostenregelungen",
				"miete",
				"betriebskosten",
				"heizkosten",
				"untermietzuschlag",
				"kaution",
			]);
			highlight_current_staffeln(frm);
		});

		if (!frm.is_new()) {
			frm.add_custom_button(__("Sollstellungen prüfen"), () => {
				frappe.require("/assets/hausverwaltung/js/sollstellung_check.js", () => {
					frappe.call({
						method:
							"hausverwaltung.hausverwaltung.scripts.check_mietrechnungen.pruefe_mietvertrag",
						args: { mietvertrag: frm.doc.name },
						freeze: true,
						freeze_message: __("Prüfe Sollstellungen..."),
						callback: (r) => {
							if (r.exc || !r.message) return;
							window.hausverwaltung.sollstellung_check.show_mietvertrag(r.message, {
								title_suffix: frm.doc.bezeichnung || frm.doc.name,
							});
						},
					});
				});
			});
		}
	},

	staffelmiete_erzeugen(frm) {
		open_staffelmiete_generate_dialog(frm);
	},
	teilmonatsmiete_festlegen(frm) {
		open_part_month_rent_dialog(frm);
	},

	von(frm) {
		update_bruttomiete(frm);
	},
	bis(frm) {
		update_bruttomiete(frm);
	},
	miete_add(frm, cdt, cdn) {
		if (cdt && cdn) frappe.model.set_value(cdt, cdn, "art", "Monatlich");
		update_bruttomiete(frm);
	},
	miete_remove(frm) {
		setup_monthly_rent_table(frm);
		update_bruttomiete(frm);
	},
	betriebskosten_add(frm) {
		update_bruttomiete(frm);
	},
	betriebskosten_remove(frm) {
		update_bruttomiete(frm);
	},
	betriebskostenregelungen_add(frm) {
		update_bruttomiete(frm);
	},
	betriebskostenregelungen_remove(frm) {
		update_bruttomiete(frm);
	},
	heizkosten_add(frm) {
		update_bruttomiete(frm);
	},
	heizkosten_remove(frm) {
		update_bruttomiete(frm);
	},
	untermietzuschlag_add(frm) {
		update_bruttomiete(frm);
	},
	untermietzuschlag_remove(frm) {
		update_bruttomiete(frm);
	},

	wohnung(frm) {
		update_cost_table_visibility(frm);
	},
});

async function update_cost_table_visibility(frm) {
	const wohnungName = frm.doc.wohnung;
	if (!wohnungName) {
		frm.set_df_property("betriebskosten", "hidden", 1);
		frm.set_df_property("heizkosten", "hidden", 1);
		return;
	}

	frm.__hv_wohnung_cost_visibility ||= {};
	let wohnung = frm.__hv_wohnung_cost_visibility[wohnungName];
	if (!wohnung) {
		// These flags are virtual properties derived from the current Wohnungszustand.
		// get_value only queries stored fields and does not evaluate those properties.
		wohnung = await frappe.db.get_doc("Wohnung", wohnungName);
		if (!wohnung) return;
		frm.__hv_wohnung_cost_visibility[wohnungName] = wohnung;
	}

	// Ignore an outdated response if the user selected another Wohnung meanwhile.
	if (frm.doc.wohnung !== wohnungName) return;
	frm.set_df_property(
		"betriebskosten",
		"hidden",
		!wohnung.betriebskostenabrechnung_durch_vermieter
	);
	frm.set_df_property(
		"heizkosten",
		"hidden",
		!wohnung.heizkostenabrechnung_durch_vermieter
	);
}

frappe.ui.form.on("Betriebskostenregelung", {
	gueltig_von(frm) {
		update_bruttomiete(frm);
	},
	abrechnungsart(frm) {
		update_bruttomiete(frm);
	},
});

const SOLLSTELLUNG_TYP_BY_STAFFEL_FIELD = {
	miete: "Miete",
	betriebskosten: "Betriebskosten",
	heizkosten: "Heizkosten",
	untermietzuschlag: "Untermietzuschlag",
};

function canonical_staffel_rows(rows) {
	return (rows || [])
		.map((row) => ({
			von: row.von || "",
			miete: flt(row.miete),
			art: row.art || "",
		}))
		.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
}

function get_staffel_snapshot(frm) {
	const snapshot = {};
	Object.keys(SOLLSTELLUNG_TYP_BY_STAFFEL_FIELD).forEach((fieldname) => {
		snapshot[fieldname] = canonical_staffel_rows(frm.doc[fieldname]);
	});
	snapshot.betriebskostenregelungen = (frm.doc.betriebskostenregelungen || [])
		.map((row) => ({
			gueltig_von: row.gueltig_von || "",
			abrechnungsart: row.abrechnungsart || "Vorauszahlung",
		}))
		.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
	snapshot.miete_teilmonate = (frm.doc.miete_teilmonate || [])
		.map((row) => ({
			von: row.von || "",
			bis: row.bis || "",
			berechnung: row.berechnung || "Automatisch anteilig",
			betrag: row.berechnung === "Festbetrag" ? flt(row.betrag) : null,
		}))
		.sort((a, b) => JSON.stringify(a).localeCompare(JSON.stringify(b)));
	return snapshot;
}

function remember_staffel_snapshot(frm) {
	frm.__hv_staffel_snapshot = get_staffel_snapshot(frm);
}

function changed_staffel_rows(beforeRows, afterRows) {
	const counts = new Map();
	[...(beforeRows || [])].forEach((row) => {
		const key = JSON.stringify(row);
		counts.set(key, (counts.get(key) || 0) + 1);
	});
	[...(afterRows || [])].forEach((row) => {
		const key = JSON.stringify(row);
		counts.set(key, (counts.get(key) || 0) - 1);
	});
	return [...counts.entries()]
		.filter(([, count]) => count !== 0)
		.map(([key]) => JSON.parse(key));
}

function get_changed_staffel_scope(before, after) {
	if (!before) return null;
	const scope = {};
	Object.entries(SOLLSTELLUNG_TYP_BY_STAFFEL_FIELD).forEach(([fieldname, typ]) => {
		const changed = changed_staffel_rows(before[fieldname], after[fieldname]);
		if (!changed.length) return;
		const dates = changed.map((row) => row.von).filter(Boolean).sort();
		// Sollstellungen werden monatsweise erzeugt. Auch eine Änderung innerhalb
		// eines Monats betrifft deshalb den kompletten Prüfmonat.
		scope[typ] = dates.length ? `${dates[0].slice(0, 7)}-01` : "1900-01-01";
	});
	const changedRules = changed_staffel_rows(
		before.betriebskostenregelungen,
		after.betriebskostenregelungen
	);
	if (changedRules.length) {
		const dates = changedRules.map((row) => row.gueltig_von).filter(Boolean).sort();
		scope.Betriebskosten = dates.length ? `${dates[0].slice(0, 7)}-01` : "1900-01-01";
	}
	const changedPartMonths = changed_staffel_rows(before.miete_teilmonate, after.miete_teilmonate);
	if (changedPartMonths.length) {
		const dates = changedPartMonths.map((row) => row.von).filter(Boolean).sort();
		const from = dates.length ? `${dates[0].slice(0, 7)}-01` : "1900-01-01";
		scope.Miete = scope.Miete && scope.Miete < from ? scope.Miete : from;
	}
	return scope;
}

function prompt_for_existing_sollstellung_corrections(frm, scope) {
	frappe.require("/assets/hausverwaltung/js/mietrechnung_korrektur_report.js", () => {
		window.hausverwaltung?.korrektur?.run_for_mietvertrag(frm.doc.name, {
			frm,
			scope,
		});
	});
}

function setup_festbetrag_dimension_overview(frm) {
	const field = frm.get_field && frm.get_field("festbetrag_dimensionsbuchungen");
	const wrapper = field && field.$wrapper;
	if (!wrapper) return;
	if (frm.is_new() || !frm.doc.kunde) {
		wrapper.empty();
		return;
	}

	const escape = (value) => frappe.utils.escape_html(String(value || ""));
	const format_date = (value) => value ? frappe.datetime.str_to_user(value) : "–";
	const format_amount = (value) => format_currency(
		value || 0,
		frappe.defaults.get_default("currency")
	);
	const defaultVon = frappe.datetime.year_start();
	const defaultBis = frappe.datetime.year_end();

	wrapper.html(`
		<div class="mt-4">
			<h5>${__("Dimensionsbuchungen (nicht manuell änderbar)")}</h5>
			<p class="text-muted small">
				${__("Diese Beträge stammen aus Buchungsbelegen mit der Abrechnungsdimension Wohnung.")}
			</p>
			<div class="row align-items-end mb-3">
				<div class="col-sm-3">
					<label class="control-label">${__("Von")}</label>
					<input type="date" class="form-control" data-filter="von" value="${escape(defaultVon)}">
				</div>
				<div class="col-sm-3">
					<label class="control-label">${__("Bis")}</label>
					<input type="date" class="form-control" data-filter="bis" value="${escape(defaultBis)}">
				</div>
				<div class="col-sm-3">
					<button type="button" class="btn btn-default btn-sm" data-action="filter">
						${__("Dimensionsbuchungen laden")}
					</button>
				</div>
			</div>
			<div data-role="dimension-table" class="text-muted small">
				${__("Die Buchungen werden erst bei Bedarf geladen.")}
			</div>
		</div>
	`);

	const tableWrapper = wrapper.find('[data-role="dimension-table"]');
	const render_rows = (rows) => {
		let html = `<div class="table-responsive"><table class="table table-bordered">
			<thead><tr>
				<th>${__("Kostenart")}</th>
				<th>${__("Wohnung")}</th>
				<th class="text-right">${__("Betrag")}</th>
				<th>${__("Belegdatum")}</th>
				<th>${__("Belegtyp")}</th>
				<th>${__("Belegnummer")}</th>
			</tr></thead><tbody>`;

		if (!rows.length) {
			html += `<tr><td colspan="6" class="text-muted text-center">
				${__("Im gewählten Zeitraum sind keine Dimensionsbuchungen vorhanden.")}
			</td></tr>`;
		} else {
			rows.forEach((row) => {
				html += `<tr>
					<td>${escape(row.bezeichnung)}</td>
					<td>${escape(frappe.utils.get_link_title("Wohnung", row.wohnung) || row.wohnung)}</td>
					<td class="text-right">${escape(format_amount(row.betrag))}</td>
					<td>${escape(format_date(row.belegdatum))}</td>
					<td>${escape(row.belegtyp)}</td>
					<td>${escape(row.belegnummer)}</td>
				</tr>`;
			});
		}

		html += "</tbody></table></div>";
		tableWrapper.html(html);
	};

	const load_rows = async () => {
		const von = wrapper.find('[data-filter="von"]').val();
		const bis = wrapper.find('[data-filter="bis"]').val();
		if (!von || !bis) {
			frappe.msgprint(__("Bitte Von und Bis angeben."));
			return;
		}
		if (von > bis) {
			frappe.msgprint(__("Von darf nicht nach Bis liegen."));
			return;
		}

		tableWrapper.html(
			`<div class="text-muted text-center py-4">${__("Dimensionsbuchungen werden geladen ...")}</div>`
		);
		const response = await frappe.call({
			method:
				"hausverwaltung.hausverwaltung.scripts.betriebskosten.kosten_auf_wohnungen.get_mieter_festbetrag_overview",
			args: {
				customer: frm.doc.kunde,
				mietvertrag: frm.doc.name,
				von,
				bis,
			},
		});
		render_rows((response.message && response.message.dimension_rows) || []);
	};

	wrapper.find('[data-action="filter"]').on("click", load_rows);
}

frappe.ui.form.on("Betriebskosten Festbetrag", {
	betriebskostenart(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.betriebskostenart && row.bezeichnung) {
			frappe.model.set_value(cdt, cdn, "bezeichnung", "");
		}
	},
	bezeichnung(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.bezeichnung && row.betriebskostenart) {
			frappe.model.set_value(cdt, cdn, "betriebskostenart", "");
		}
	},
});

function setup_monthly_rent_table(frm) {
	const grid = frm.get_field("miete")?.grid;
	if (!grid) return;
	const legacy = (frm.doc.miete || []).some((row) => row.art === "Gesamter Zeitraum");
	// Existing fixed staffels retain their identity until they have been migrated.
	// Never reinterpret those amounts as monthly rent just to simplify the form.
	set_staffelmiete_grid_properties(grid, {
		von: { label: __("Gültig ab") },
		miete: { label: legacy ? __("Mietbetrag") : __("Monatsmiete") },
		art: { default: "Monatlich", hidden: legacy ? 0 : 1, in_list_view: legacy ? 1 : 0, read_only: 1 },
	});
	frm.set_df_property("miete", "description", legacy
		? __("Dieser Vertrag enthält ältere Festbeträge (Gesamter Zeitraum). Diese bleiben sichtbar und werden nicht automatisch in Monatsmieten umgewandelt. Für neue Vereinbarungen bitte die Monatsmiete und Teilmonatsmiete verwenden.")
		: __("Regulärer Mietbetrag je vollem Monat. Ein- und Auszugsmonate werden automatisch anteilig berechnet; einen vereinbarten Betrag können Sie über Teilmonatsmiete festlegen eingeben. Separate Betriebs- und Heizkostenvorauszahlungen werden dadurch nicht geändert."));
	frm.refresh_field("miete");
}

function set_staffelmiete_grid_properties(grid, properties) {
	// Frappe shares a child DocType's parent-specific DocFields between every
	// table of that type. Miete, BK/HK and Kaution all use Staffelmiete. Keep
	// labels/defaults local to this grid, including after Frappe rebuilds it.
	if (!grid.__hv_staffel_properties) {
		grid.__hv_staffel_properties = {};
		const setup_fields = grid.setup_fields;
		grid.setup_fields = function () {
			setup_fields.call(this);
			this.docfields = this.docfields.map((df) => ({
				...df, ...(this.__hv_staffel_properties[df.fieldname] || {}),
			}));
			this.docfields.forEach((df) => { this.fields_map[df.fieldname] = df; });
		};
		grid.get_docfield = function (fieldname) {
			return this.docfields.find((df) => df.fieldname === fieldname);
		};
	}
	Object.entries(properties).forEach(([fieldname, values]) => {
		grid.__hv_staffel_properties[fieldname] = {
			...(grid.__hv_staffel_properties[fieldname] || {}), ...values,
		};
	});
	grid.reset_grid();
}

function part_month_end(date) {
	const [year, month] = date.split("-").map(Number);
	const day = new Date(Date.UTC(year, month, 0)).getUTCDate();
	return `${date.slice(0, 7)}-${String(day).padStart(2, "0")}`;
}

function part_month_periods(frm) {
	const periods = [];
	const add = (label, von, bis) => {
		if (von && bis && von <= bis && !periods.some((p) => p.von === von && p.bis === bis)) {
			periods.push({ label, von, bis });
		}
	};
	if (frm.doc.von) {
		const firstEnd = part_month_end(frm.doc.von);
		add(__("Erster Mietmonat"), frm.doc.von,
			frm.doc.bis && frm.doc.bis < firstEnd ? frm.doc.bis : firstEnd);
	}
	if (frm.doc.bis) {
		const lastStart = `${frm.doc.bis.slice(0, 7)}-01`;
		add(__("Letzter Mietmonat"),
			frm.doc.von && frm.doc.von > lastStart ? frm.doc.von : lastStart, frm.doc.bis);
	}
	return periods;
}

function open_part_month_rent_dialog(frm) {
	if (!frm.doc.von) {
		frappe.msgprint(__("Bitte zuerst den Beginn des Mietvertrags angeben."));
		return;
	}
	const periods = part_month_periods(frm);
	const first = periods.find((p) => p.von.slice(-2) !== "01" || p.bis !== part_month_end(p.von))
		|| periods[0];
	if (!first) return;
	const existing_rule = (von, bis) => (frm.doc.miete_teilmonate || [])
		.find((row) => row.von === von && row.bis === bis);
	const initial = existing_rule(first.von, first.bis);
	let selectedRowName = initial?.name || null;
	const currency = frappe.defaults.get_default("currency") || "EUR";
	const escape = (value) => frappe.utils.escape_html(String(value ?? ""));
	let previewSequence = 0;
	let timer;
	let changingPeriod = false;
	let previousMode = initial?.berechnung || "Automatisch anteilig";
	const d = new frappe.ui.Dialog({
		title: __("Teilmonatsmiete festlegen"),
		fields: [
			{ fieldtype: "HTML", fieldname: "explanation", options:
				`<p>${__("Der Festbetrag gilt einmalig für den angezeigten Zeitraum und ersetzt dort die anteilige Monatsmiete. Die restlichen Tage des Monats werden regulär berechnet. Separate Betriebs- und Heizkostenvorauszahlungen bleiben unverändert.")}</p>` },
			{ fieldtype: "Select", fieldname: "zeitraum", label: __("Zeitraum auswählen"),
				options: [...periods.map((p) => p.label), __("Eigener Zeitraum")].join("\n"),
				default: first.label,
				onchange: async () => {
					const period = periods.find((p) => p.label === d.get_value("zeitraum"));
					if (!period) return;
					changingPeriod = true;
					const rule = existing_rule(period.von, period.bis);
					selectedRowName = rule?.name || null;
					await d.set_value("von", period.von);
					await d.set_value("bis", period.bis);
					await d.set_value("berechnung", rule?.berechnung || "Automatisch anteilig");
					await d.set_value("betrag", rule?.berechnung === "Festbetrag" ? rule.betrag : null);
					changingPeriod = false;
					refresh_preview();
				} },
			{ fieldtype: "Date", fieldname: "von", label: __("Von (einschließlich)"),
				reqd: 1, default: first.von, onchange: date_changed },
			{ fieldtype: "Date", fieldname: "bis", label: __("Bis (einschließlich)"),
				reqd: 1, default: first.bis, onchange: date_changed },
			{ fieldtype: "Select", fieldname: "berechnung", label: __("Berechnung für diesen Zeitraum"),
				options: "Automatisch anteilig\nFestbetrag", default: initial?.berechnung || "Automatisch anteilig",
				onchange: async () => {
					const mode = d.get_value("berechnung");
					d.set_df_property("betrag", "hidden", mode !== "Festbetrag");
					if (mode === "Festbetrag" && previousMode !== "Festbetrag" && !changingPeriod) {
						await d.set_value("betrag", null);
						d.fields_dict.betrag.$input.val("");
					}
					previousMode = mode;
					refresh_preview();
				} },
			{ fieldtype: "Currency", fieldname: "betrag", label: __("Vereinbarter Mietbetrag für diesen Zeitraum"),
				default: initial?.berechnung === "Festbetrag" ? initial.betrag : null,
				hidden: initial?.berechnung !== "Festbetrag", onchange: refresh_preview,
				description: __("Ein einmaliger Betrag, keine Monatsmiete. Auch 0,00 ist möglich.") },
			{ fieldtype: "HTML", fieldname: "vorschau" },
		],
		primary_action_label: __("In Mietvertrag übernehmen"),
		async primary_action() {
			const rule = get_rule();
			if (!rule) return;
			d.get_primary_btn().prop("disabled", true);
			try {
				const preview = await calculate_preview(rule);
				if (!preview || preview.exc) return;
				let target = selectedRowName && (frm.doc.miete_teilmonate || [])
					.find((row) => row.name === selectedRowName);
				if (selectedRowName && !target) {
					frappe.msgprint(__("Die Teilmonatsregel wurde zwischenzeitlich verändert. Bitte den Dialog erneut öffnen."));
					return;
				}
				target ||= frm.add_child("miete_teilmonate");
				Object.assign(target, rule);
				frm.dirty();
				frm.refresh_field("miete_teilmonate");
				d.hide();
				frappe.show_alert({ message: __("Teilmonatsmiete übernommen. Bitte den Mietvertrag speichern."), indicator: "green" });
			} catch (_) {
				// The server shows its validation message; the form remains untouched.
			} finally {
				d.get_primary_btn().prop("disabled", false);
			}
		},
	});

	function date_changed() {
		if (changingPeriod) return;
		d.set_value("zeitraum", __("Eigener Zeitraum"));
		refresh_preview();
	}
	function get_rule() {
		const von = d.get_value("von"), bis = d.get_value("bis");
		const berechnung = d.get_value("berechnung");
		if (!von || !bis || von > bis || von.slice(0, 7) !== bis.slice(0, 7)) {
			d.fields_dict.vorschau.$wrapper.html(`<p class="text-danger">${__("Bitte einen gültigen Zeitraum innerhalb eines Kalendermonats angeben.")}</p>`);
			return null;
		}
		if (berechnung === "Festbetrag" && !String(d.fields_dict.betrag.$input.val() ?? "").trim()) {
			d.fields_dict.vorschau.$wrapper.html(`<p class="text-muted">${__("Bitte den vereinbarten Mietbetrag eingeben. Für einen mietfreien Zeitraum ausdrücklich 0 eingeben.")}</p>`);
			return null;
		}
		return { von, bis, berechnung, betrag: berechnung === "Festbetrag" ? d.get_value("betrag") : 0 };
	}
	async function calculate_preview(rule) {
		const document = JSON.parse(JSON.stringify(frm.doc));
		document.miete_teilmonate = (document.miete_teilmonate || [])
			.filter((row) => !selectedRowName || row.name !== selectedRowName);
		document.miete_teilmonate.push({ doctype: "Miete Teilmonat", ...rule });
		const response = await frappe.call({
			method: "hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag.vorschau_teilmonatsmiete",
			args: { document: JSON.stringify(document), month: `${rule.von.slice(0, 7)}-01` },
		});
		return response.exc ? null : response.message;
	}
	function refresh_preview() {
		if (changingPeriod) return;
		clearTimeout(timer);
		const sequence = ++previewSequence;
		timer = setTimeout(async () => {
			const rule = get_rule();
			if (!rule) return;
			d.fields_dict.vorschau.$wrapper.html(`<p class="text-muted">${__("Vorschau wird berechnet …")}</p>`);
			try {
				const preview = await calculate_preview(rule);
				if (sequence !== previewSequence || !preview) return;
				const rows = (preview.segments || []).map((segment) => `<tr>
					<td>${escape(frappe.datetime.str_to_user(segment.von))} – ${escape(frappe.datetime.str_to_user(segment.bis))}</td>
					<td>${escape(segment.berechnung)}</td>
					<td class="text-right">${escape(format_currency(segment.betrag, currency))}</td>
				</tr>`).join("");
				d.fields_dict.vorschau.$wrapper.html(`<div data-role="part-month-preview">
					<p><strong>${__("Mietbetrag für den gesamten Monat {0}: {1}",
						[escape(rule.von.slice(0, 7)), escape(format_currency(preview.amount, currency))])}</strong></p>
					<div class="table-responsive"><table class="table table-bordered">
						<thead><tr><th>${__("Zeitraum")}</th><th>${__("Berechnung")}</th><th class="text-right">${__("Mietbetrag")}</th></tr></thead>
						<tbody>${rows}</tbody>
					</table></div>
				</div>`);
			} catch (_) {
				if (sequence === previewSequence) d.fields_dict.vorschau.$wrapper.html(
					`<p class="text-danger">${__("Der Zeitraum konnte nicht berechnet werden. Bitte die Eingaben prüfen.")}</p>`);
			}
		}, 200);
	}
	d.onhide = () => { clearTimeout(timer); previewSequence++; };
	d.show();
	refresh_preview();
}

function hide_staffelmiete_art_column(frm, tableFieldname) {
	const field = frm.get_field && frm.get_field(tableFieldname);
	const grid = field && field.grid;
	if (!grid) return;

	set_staffelmiete_grid_properties(grid, {
		art: { hidden: 1, in_list_view: 0, default: "Gesamter Zeitraum" },
	});
	frm.refresh_field(tableFieldname);
}

function rename_staffelmiete_miete_column(frm, tableFieldname, newLabel) {
	const field = frm.get_field && frm.get_field(tableFieldname);
	const grid = field && field.grid;
	if (!grid) return;

	const amountField = (grid.docfields || []).find(
		(df) => df && df.fieldname === "miete"
	);
	if (amountField && amountField.label === newLabel) return;

	set_staffelmiete_grid_properties(grid, { miete: { label: newLabel } });
	frm.refresh_field(tableFieldname);
}

frappe.ui.form.on("Staffelmiete", {
	miete_add(frm, cdt, cdn) {
		if (frm.doctype !== "Mietvertrag") return;
		frappe.model.set_value(cdt, cdn, "art", "Monatlich");
		update_bruttomiete(frm);
	},
	miete_remove(frm) {
		if (frm.doctype !== "Mietvertrag") return;
		setup_monthly_rent_table(frm);
		update_bruttomiete(frm);
	},
	von(frm) {
		if (frm.doctype !== "Mietvertrag") return;
		update_bruttomiete(frm);
	},
	miete(frm) {
		if (frm.doctype !== "Mietvertrag") return;
		update_bruttomiete(frm);
	},
	art(frm) {
		if (frm.doctype !== "Mietvertrag") return;
		update_bruttomiete(frm);
	},
});

function _bruttomiete_stichtag_obj(frm) {
	const todayObj = frappe.datetime.str_to_obj(frappe.datetime.get_today());
	let stichtag = todayObj;

	if (frm.doc.von) {
		const vonObj = frappe.datetime.str_to_obj(frm.doc.von);
		if (vonObj > stichtag) stichtag = vonObj;
	}
	if (frm.doc.bis) {
		const bisObj = frappe.datetime.str_to_obj(frm.doc.bis);
		if (bisObj < stichtag) stichtag = bisObj;
	}
	return stichtag;
}

function _staffelbetrag_am(rows, stichtagObj) {
	let bestVon = null;
	let bestValue = 0.0;

	(rows || []).forEach((row) => {
		if (!row.von) return;
		const vonObj = frappe.datetime.str_to_obj(row.von);
		if (vonObj <= stichtagObj && (bestVon === null || vonObj > bestVon)) {
			bestVon = vonObj;
			bestValue = flt(row.miete);
		}
	});

	return flt(bestValue);
}

function _bk_regelung_am(rows, stichtagObj) {
	let bestVon = null;
	let result = "Vorauszahlung";
	(rows || []).forEach((row) => {
		if (!row.gueltig_von) return;
		const vonObj = frappe.datetime.str_to_obj(row.gueltig_von);
		if (vonObj <= stichtagObj && (bestVon === null || vonObj > bestVon)) {
			bestVon = vonObj;
			result = row.abrechnungsart || "Vorauszahlung";
		}
	});
	return result;
}

function update_bruttomiete(frm) {
	if (!frm || frm.doctype !== "Mietvertrag") return;
	if (!frm.doc) return;

	const stichtagObj = _bruttomiete_stichtag_obj(frm);
	const nettokaltmiete = _staffelbetrag_am(frm.doc.miete, stichtagObj);
	const bkRegelung = _bk_regelung_am(frm.doc.betriebskostenregelungen, stichtagObj);
	const betriebskosten = bkRegelung === "Vorauszahlung"
		? _staffelbetrag_am(frm.doc.betriebskosten, stichtagObj)
		: 0;
	const heizkosten = _staffelbetrag_am(frm.doc.heizkosten, stichtagObj);
	const total =
		nettokaltmiete +
		betriebskosten +
		heizkosten +
		_staffelbetrag_am(frm.doc.untermietzuschlag, stichtagObj);
	if (frm.doc.aktuelle_betriebskostenregelung !== bkRegelung) {
		frm.set_value("aktuelle_betriebskostenregelung", bkRegelung);
	}

	const changed = [
		["aktuelle_nettokaltmiete", nettokaltmiete],
		["aktuelle_betriebskosten", betriebskosten],
		["aktuelle_heizkosten", heizkosten],
		["bruttomiete", total],
	].filter(([fieldname, value]) => Math.abs(flt(frm.doc[fieldname]) - flt(value)) >= 0.00001);

	if (!changed.length) {
		highlight_current_staffeln(frm);
		return;
	}
	changed.forEach(([fieldname, value]) => {
		frm.set_value(fieldname, flt(value));
	});
	highlight_current_staffeln(frm);
}

function add_paperless_button(frm) {
	if (frm.is_new()) {
		return;
	}

	// Paperless-Integration ist noch nicht final — nur System Manager sehen den
	// Button. Hausverwalter (und alle anderen) bekommen ihn nicht angezeigt.
	const roles = (frappe.user_roles || []);
	if (!roles.includes('System Manager')) {
		return;
	}

	frm.add_custom_button(__('Paperless NGX'), () => {
		frappe.call({
			method: 'hausverwaltung.hausverwaltung.doctype.mietvertrag.mietvertrag.get_mietvertrag_paperless_link',
			args: { mietvertrag: frm.doc.name },
			freeze: true,
			callback: function(r) {
				const link = r.message;
				if (!link) {
					frappe.msgprint(__('Kein Paperless-Link gefunden.'));
					return;
				}
				window.open(link, '_blank');
			},
			error: function() {
				frappe.msgprint(__('Paperless-Link konnte nicht geladen werden.'));
			}
		});
	}, __('Paperless'));
}

function add_mieterkonto_button_from_mietvertrag(frm) {
	if (frm.is_new()) {
		return;
	}

	frm.add_custom_button(__("Mieterkonto"), () => {
		const company = frappe.defaults.get_user_default("Company");
		if (!company) {
			frappe.msgprint(__("Bitte zuerst eine Standard-Firma setzen."));
			return;
		}
		if (!frm.doc.kunde) {
			frappe.msgprint(__("Dieser Mietvertrag hat keinen Mieter/Debitor."));
			return;
		}

		frappe.set_route("query-report", "Mieterkonto", {
			company,
			customer: frm.doc.kunde,
			from_date: frm.doc.von || frappe.datetime.year_start(),
			to_date: frm.doc.bis || frappe.datetime.get_today(),
		});
	}, __("Accounting"));
}

function open_staffelmiete_generate_dialog(frm) {
	const existing = frm.doc.miete || [];
	const last_row = existing.length ? existing[existing.length - 1] : null;

	const default_start = last_row && last_row.von
		? frappe.datetime.add_months(last_row.von, 12)
		: (frm.doc.von || frappe.datetime.get_today());
	const default_start_amount = last_row ? flt(last_row.miete) : 0;

	const d = new frappe.ui.Dialog({
		title: __("Staffelmieten erzeugen"),
		fields: [
			{
				fieldtype: "Date",
				fieldname: "startdatum",
				label: __("Startdatum"),
				reqd: 1,
				default: default_start,
			},
			{
				fieldtype: "Currency",
				fieldname: "startbetrag",
				label: __("Startbetrag"),
				reqd: 1,
				default: default_start_amount,
			},
			{
				fieldtype: "Currency",
				fieldname: "erhoehung",
				label: __("Erhöhung pro Staffel (€)"),
				reqd: 1,
				default: 0,
			},
			{
				fieldtype: "Int",
				fieldname: "intervall_monate",
				label: __("Erhöhungszeitraum (Monate)"),
				reqd: 1,
				default: 12,
			},
			{
				fieldtype: "Int",
				fieldname: "anzahl",
				label: __("Anzahl Staffeln"),
				reqd: 1,
				default: 5,
			},
		],
		primary_action_label: __("Erzeugen"),
		primary_action(values) {
			const anzahl = cint(values.anzahl);
			const intervall = cint(values.intervall_monate);
			const start_amount = flt(values.startbetrag);
			const step = flt(values.erhoehung);

			if (anzahl < 1) {
				frappe.msgprint(__("Anzahl Staffeln muss mindestens 1 sein."));
				return;
			}
			if (intervall < 1) {
				frappe.msgprint(__("Erhöhungszeitraum muss mindestens 1 Monat sein."));
				return;
			}

			for (let i = 0; i < anzahl; i++) {
				const von = i === 0
					? values.startdatum
					: frappe.datetime.add_months(values.startdatum, intervall * i);
				const row = frm.add_child("miete");
				row.von = von;
				row.miete = start_amount + step * i;
				row.art = "Monatlich";
			}

			sort_staffel_table_by_von(frm, "miete");
			frm.refresh_field("miete");
			update_bruttomiete(frm);
			highlight_current_staffeln(frm);
			d.hide();
		},
	});
	d.show();
}

function sort_staffel_table_by_von(frm, tableFieldname) {
	if (!frm || !frm.doc) return;
	const rows = frm.doc[tableFieldname] || [];
	if (rows.length < 2) return;

	rows.sort((a, b) => {
		if (!a.von && !b.von) return 0;
		if (!a.von) return 1;
		if (!b.von) return -1;
		const av = frappe.datetime.str_to_obj(a.von);
		const bv = frappe.datetime.str_to_obj(b.von);
		return av - bv;
	});

	rows.forEach((row, idx) => {
		row.idx = idx + 1;
	});
}

function sort_betriebskostenregelungen(frm) {
	const rows = (frm && frm.doc && frm.doc.betriebskostenregelungen) || [];
	rows.sort((a, b) => {
		if (!a.gueltig_von && !b.gueltig_von) return 0;
		if (!a.gueltig_von) return 1;
		if (!b.gueltig_von) return -1;
		return frappe.datetime.str_to_obj(a.gueltig_von) - frappe.datetime.str_to_obj(b.gueltig_von);
	});
	rows.forEach((row, idx) => {
		row.idx = idx + 1;
	});
}

function ensure_staffel_highlight_css() {
	if (window.__hv_staffel_highlight_css_loaded) return;
	window.__hv_staffel_highlight_css_loaded = true;

	const style = document.createElement("style");
	style.type = "text/css";
	style.textContent = `
		.hv-current-staffel-row {
			background: rgba(255, 193, 7, 0.12) !important;
		}
		.hv-current-staffel-row .grid-static-col,
		.hv-current-staffel-row .grid-row-check {
			background: transparent !important;
		}
		.hv-current-staffel-row .static-area .form-control,
		.hv-current-staffel-row .grid-static-col .static-area {
			font-weight: 600;
		}
	`;
	document.head.appendChild(style);
}

function highlight_current_staffeln(frm) {
	if (!frm || frm.doctype !== "Mietvertrag" || !frm.doc) return;

	// Delay until grids are rendered (especially on first load)
	setTimeout(() => {
		highlight_current_staffel_row(frm, "miete");
		highlight_current_staffel_row(frm, "betriebskosten");
		highlight_current_staffel_row(frm, "heizkosten");
		highlight_current_staffel_row(frm, "untermietzuschlag");
		highlight_current_staffel_row(frm, "kaution");
	}, 0);
}

function highlight_current_staffel_row(frm, tableFieldname) {
	const field = frm.get_field && frm.get_field(tableFieldname);
	const grid = field && field.grid;
	if (!grid) return;

	const rows = frm.doc[tableFieldname] || [];
	if (!rows.length) return;

	const stichtagObj = _bruttomiete_stichtag_obj(frm);

	let currentRow = null;
	let bestVon = null;
	rows.forEach((row) => {
		if (!row.von) return;
		const vonObj = frappe.datetime.str_to_obj(row.von);
		if (vonObj <= stichtagObj && (bestVon === null || vonObj > bestVon)) {
			bestVon = vonObj;
			currentRow = row;
		}
	});

	(grid.grid_rows || []).forEach((gridRow) => {
		const wrapper = gridRow && gridRow.wrapper;
		if (!wrapper) return;
		if (typeof wrapper.removeClass === "function") wrapper.removeClass("hv-current-staffel-row");
		else if (wrapper.classList) wrapper.classList.remove("hv-current-staffel-row");
	});

	if (!currentRow) return;

	(grid.grid_rows || []).forEach((gridRow) => {
		if (!gridRow || !gridRow.doc || !gridRow.wrapper) return;
		if (gridRow.doc.name === currentRow.name) {
			const wrapper = gridRow.wrapper;
			if (typeof wrapper.addClass === "function") wrapper.addClass("hv-current-staffel-row");
			else if (wrapper.classList) wrapper.classList.add("hv-current-staffel-row");
		}
	});
}
