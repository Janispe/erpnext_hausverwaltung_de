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
		const scope = frm.__hv_sollstellung_korrektur_scope;
		frm.__hv_sollstellung_korrektur_scope = null;
		remember_staffel_snapshot(frm);
		if (scope && Object.keys(scope).length) {
			prompt_for_existing_sollstellung_corrections(frm, scope);
		}
	},
	refresh(frm) {
		console.log("✅ mietvertrag.js wurde geladen");

		update_bruttomiete(frm);
		rename_staffelmiete_miete_column(frm, "miete", "Nettokaltmiete");
		hide_staffelmiete_art_column(frm, "kaution");
		rename_staffelmiete_miete_column(frm, "kaution", "Betrag");
		ensure_staffel_highlight_css();
		highlight_current_staffeln(frm);
		setup_festbetrag_dimension_overview(frm);

		// Felder ausblenden je nach Wohnung
		if (frm.doc.wohnung) {
			frappe.db.get_doc("Wohnung", frm.doc.wohnung).then(function (wohnung) {
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
			});
		} else {
			frm.set_df_property("betriebskosten", "hidden", 1);
			frm.set_df_property("heizkosten", "hidden", 1);
		}

		add_paperless_button(frm);
		add_mieterkonto_button_from_mietvertrag(frm);

		frm.add_custom_button(__("Staffelmieten sortieren"), async () => {
			sort_staffel_table_by_von(frm, "miete");
			sort_staffel_table_by_von(frm, "betriebskosten");
			sort_staffel_table_by_von(frm, "heizkosten");
			sort_staffel_table_by_von(frm, "untermietzuschlag");
			sort_staffel_table_by_von(frm, "kaution");

			frm.refresh_fields([
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
								title_suffix: frm.doc.name,
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

	von(frm) {
		update_bruttomiete(frm);
	},
	bis(frm) {
		update_bruttomiete(frm);
	},
	miete_add(frm) {
		update_bruttomiete(frm);
	},
	miete_remove(frm) {
		update_bruttomiete(frm);
	},
	betriebskosten_add(frm) {
		update_bruttomiete(frm);
	},
	betriebskosten_remove(frm) {
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
		if (frm.doc.wohnung) {
			frappe.db.get_doc("Wohnung", frm.doc.wohnung).then(function (wohnung) {
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
			});
		} else {
			frm.set_df_property("betriebskosten", "hidden", 1);
			frm.set_df_property("heizkosten", "hidden", 1);
		}
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
	return scope;
}

function prompt_for_existing_sollstellung_corrections(frm, scope) {
	frappe.call({
		method:
			"hausverwaltung.hausverwaltung.scripts.check_mietrechnungen.get_korrigierbare_sollstellungen_fuer_mietvertrag",
		args: {
			mietvertrag: frm.doc.name,
			scope: JSON.stringify(scope),
		},
		callback: (r) => {
			if (r.exc || !r.message) return;
			if (window.cur_frm && window.cur_frm !== frm) return;
			const invoices = r.message.sales_invoices || [];
			if (!invoices.length) return;

			const months = (r.message.monate || []).join(", ");
			const message = __(
				"Die Mietstaffel wurde geändert. Für {0} bereits gebuchte Sollstellung(en) in {1} weicht der Betrag nun vom Mietvertrag ab. Sollen diese jetzt korrigiert werden? Bezahlte Sollstellungen werden mit Zahlungs-Neuzuordnung verarbeitet, geschlossene Perioden per Gutschrift.",
				[invoices.length, months || __("dem betroffenen Zeitraum")]
			);
			frappe.require("/assets/hausverwaltung/js/mietrechnung_korrektur_report.js", () => {
				window.hausverwaltung?.korrektur?.run_bulk(invoices, {
					confirm_message: message,
				});
			});
		},
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
						${__("Filter anwenden")}
					</button>
				</div>
			</div>
			<div data-role="dimension-table"></div>
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
					<td>${escape(row.wohnung)}</td>
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
	load_rows();
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

function hide_staffelmiete_art_column(frm, tableFieldname) {
	const field = frm.get_field && frm.get_field(tableFieldname);
	const grid = field && field.grid;
	if (!grid) return;

	// Default-Wert "Gesamter Zeitraum" auf jeder neuen Kaution-Row erzwingen,
	// damit auch ohne sichtbares Feld konsistente Daten landen.
	if (typeof grid.update_docfield_property === "function") {
		grid.update_docfield_property("art", "hidden", 1);
		grid.update_docfield_property("art", "in_list_view", 0);
		grid.update_docfield_property("art", "default", "Gesamter Zeitraum");
	}

	// Feld komplett aus dem Grid-Model entfernen — nur dann verschwindet auch
	// die Datenzelle (nicht nur der Header). docfields/meta filtern.
	const removeArtField = function (arr) {
		if (!Array.isArray(arr)) return arr;
		return arr.filter(function (df) {
			return !(df && df.fieldname === "art");
		});
	};
	if (grid.docfields) grid.docfields = removeArtField(grid.docfields);
	if (grid.meta && grid.meta.fields) {
		grid.meta.fields = removeArtField(grid.meta.fields);
	}
	if (Array.isArray(grid.visible_columns)) {
		grid.visible_columns = grid.visible_columns.filter(function (col) {
			return !(col && col[0] && col[0].fieldname === "art");
		});
	}
	if (grid.fields_map && grid.fields_map.art) {
		delete grid.fields_map.art;
	}

	frm.refresh_field(tableFieldname);
	if (typeof grid.refresh === "function") grid.refresh();
}

function rename_staffelmiete_miete_column(frm, tableFieldname, newLabel) {
	const field = frm.get_field && frm.get_field(tableFieldname);
	const grid = field && field.grid;
	if (!grid || typeof grid.update_docfield_property !== "function") return;

	grid.update_docfield_property("miete", "label", newLabel);
	if (Array.isArray(grid.docfields)) {
		grid.docfields.forEach(function (df) {
			if (df && df.fieldname === "miete") {
				df.label = newLabel;
			}
		});
	}
	frm.refresh_field(tableFieldname);
	if (typeof grid.refresh === "function") {
		grid.refresh();
	}
}

frappe.ui.form.on("Staffelmiete", {
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

function update_bruttomiete(frm) {
	if (!frm || frm.doctype !== "Mietvertrag") return;
	if (!frm.doc) return;

	const stichtagObj = _bruttomiete_stichtag_obj(frm);
	const nettokaltmiete = _staffelbetrag_am(frm.doc.miete, stichtagObj);
	const betriebskosten = _staffelbetrag_am(frm.doc.betriebskosten, stichtagObj);
	const heizkosten = _staffelbetrag_am(frm.doc.heizkosten, stichtagObj);
	const total =
		nettokaltmiete +
		betriebskosten +
		heizkosten +
		_staffelbetrag_am(frm.doc.untermietzuschlag, stichtagObj);

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
